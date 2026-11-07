"""Speech output (TTS) and input (STT) for JARVIS.

* TTS: Microsoft neural voices via edge-tts (online) with full-length
  playback, falling back to the offline Windows SAPI voice (pyttsx3).
* STT: Google Web Speech via SpeechRecognition for commands.
* Wake word: offline with Vosk when a model is configured (no network
  polling), otherwise Google; always matched as a whole word (UC 4.2).
"""
import json
import os
import re
import tempfile
import threading
import time

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.voice")

try:
    import speech_recognition as sr
    _SR_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    sr = None
    _SR_AVAILABLE = False

try:
    import pyttsx3
except Exception:  # pragma: no cover - optional dependency
    pyttsx3 = None

try:
    import edge_tts as _edge_tts
    _EDGE_TTS_AVAILABLE = True
except Exception:
    _EDGE_TTS_AVAILABLE = False

try:
    from playsound import playsound as _playsound
    _PLAYSOUND_AVAILABLE = True
except Exception:
    _PLAYSOUND_AVAILABLE = False

EDGE_TTS_VOICE = "en-GB-RyanNeural"

_MD = re.compile(r"(\*\*|__|`{1,3}|^#{1,6}\s*|^\s*[-*•]\s+|^\s*\d+\.\s+)", re.M)
_URL = re.compile(r"https?://\S+|www\.\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def make_speakable(text: str, max_sentences: int = 3, max_chars: int = 420) -> str:
    """Turn a screen reply into something pleasant to hear (UC 9.3).

    Strips markdown, URLs and emoji, keeps the first few sentences, and says
    where the rest is instead of reading raw scraped text aloud.
    """
    if not text:
        return ""
    clean = _URL.sub("", str(text))
    clean = _MD.sub("", clean)
    clean = _EMOJI.sub("", clean)
    clean = re.sub(r"[ \t]+", " ", clean)
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    flat = " ".join(lines)
    sentences = re.split(r"(?<=[.!?])\s+", flat)
    spoken = " ".join(sentences[:max_sentences]).strip()
    truncated = len(sentences) > max_sentences or len(spoken) > max_chars
    if len(spoken) > max_chars:
        spoken = spoken[:max_chars].rsplit(" ", 1)[0] + "…"
    if truncated:
        spoken += " The full details are on screen."
    return spoken


def _play_mp3_blocking(path: str, stop_event: "threading.Event" = None) -> bool:
    """Play an MP3 to completion (or until ``stop_event`` is set). Returns True if playback ran."""
    if os.name == "nt":
        try:
            import ctypes
            winmm = ctypes.windll.winmm
            alias = f"jarvis{threading.get_ident()}"
            buf = ctypes.create_unicode_buffer(128)
            if winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', buf, 127, 0) == 0:
                try:
                    # Poll instead of "play … wait" so stop_speaking() can interrupt the clip.
                    if winmm.mciSendStringW(f"play {alias}", buf, 127, 0) == 0:
                        give_up = time.monotonic() + 600
                        while not (stop_event is not None and stop_event.is_set()) and time.monotonic() < give_up:
                            if winmm.mciSendStringW(f"status {alias} mode", buf, 127, 0) != 0 or \
                                    buf.value.strip().lower() == "stopped":
                                break
                            time.sleep(0.05)
                        return True
                finally:
                    winmm.mciSendStringW(f"close {alias}", buf, 127, 0)
        except Exception as exc:
            log.debug("MCI playback failed: %s", exc)
    if _PLAYSOUND_AVAILABLE:
        try:
            _playsound(path)
            return True
        except Exception as exc:
            log.debug("playsound failed: %s", exc)
    if os.name == "nt":
        import subprocess
        ps_path = str(path).replace("'", "''")   # e.g. C:\\Users\\O'Brien\\… inside a '…' literal
        # Wait for the real clip duration instead of a fixed 5 seconds (UC 4.1).
        script = (
            "Add-Type -AssemblyName presentationCore;"
            "$p=New-Object System.Windows.Media.MediaPlayer;"
            f"$p.Open([uri]'{ps_path}');"
            "$t=0; while(-not $p.NaturalDuration.HasTimeSpan -and $t -lt 50){Start-Sleep -m 100;$t++};"
            "$p.Play();"
            "if($p.NaturalDuration.HasTimeSpan){Start-Sleep -m ([int]$p.NaturalDuration.TimeSpan.TotalMilliseconds+300)}"
            "else{Start-Sleep -s 8};$p.Close()"
        )
        try:
            done = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                                  timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return done.returncode == 0
        except Exception as exc:
            log.debug("PowerShell playback failed: %s", exc)
    return False


class VoiceEngine:
    def __init__(self):
        self.tts_engine = None
        self._tts_lock = threading.Lock()
        self._stop_speaking = threading.Event()
        try:
            if pyttsx3 is not None:
                self.tts_engine = pyttsx3.init()
                self.setup_tts()
        except Exception as exc:
            log.warning("Offline TTS unavailable: %s", exc)

        self.sr_available = sr is not None
        self.recognizer = sr.Recognizer() if self.sr_available else None
        self.microphone = None
        self.selected_mic_index = None
        self._microphone_lock = threading.RLock()
        self._vosk = None
        self.is_speaking = False
        self.speaking_text = ""
        self.is_listening = False

    # ── TTS ──────────────────────────────────────────────────────────────────

    def setup_tts(self):
        if not self.tts_engine:
            return
        try:
            voices = self.tts_engine.getProperty("voices") or []
            preferred = ["george", "ryan", "david", "mark", "hazel", "zira"]
            chosen = next((v for p in preferred for v in voices if p in v.name.lower()), None)
            if chosen:
                self.tts_engine.setProperty("voice", chosen.id)
            self.tts_engine.setProperty("rate", Config.VOICE_RATE)
            self.tts_engine.setProperty("volume", Config.VOICE_VOLUME)
        except Exception as exc:
            log.warning("TTS setup failed: %s", exc)

    def speak(self, text, summarize: bool = False):
        """Speak text to completion. Thread-safe; one utterance at a time."""
        if text is None:
            return
        text = make_speakable(text) if summarize else re.sub(r"\s+", " ", _EMOJI.sub("", str(text))).strip()
        if not text or not Config.VOICE_SETTINGS.get("enabled", True):
            return
        with self._tts_lock:
            self.speaking_text = text          # conversation mode tells its own echo from the user by this
            self.is_speaking = True
            self._stop_speaking.clear()
            try:
                if Config.TTS_ENGINE == "kokoro" and self._speak_kokoro(text):
                    return
                if Config.TTS_ENGINE == "edge" and _EDGE_TTS_AVAILABLE and not Config.LOCAL_ONLY \
                        and self._speak_edge_tts(text):           # edge-tts is an online service
                    return
                if self.tts_engine:
                    self.tts_engine.say(text)
                    self.tts_engine.runAndWait()
            except Exception as exc:
                log.warning("TTS error: %s", exc)
            finally:
                self.is_speaking = False

    def stop_speaking(self):
        self._stop_speaking.set()
        try:
            if self.tts_engine:
                self.tts_engine.stop()
        except Exception:
            pass

    def _speak_kokoro(self, text: str) -> bool:
        """Local neural voice. False (→ offline SAPI voice) until the model has downloaded."""
        try:
            from core import local_speech
            voice = local_speech.voice()
            if not voice.files_ready():
                local_speech.warm_up()           # download in the background; SAPI speaks meanwhile
                return False
            return voice.speak(text, self._stop_speaking)
        except Exception as exc:
            log.info("Kokoro unavailable, using the offline Windows voice: %s", exc)
            return False

    def _speak_edge_tts(self, text: str) -> bool:
        tmp_path = None
        try:
            import asyncio
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tmp_path = tmp.name
            tmp.close()

            async def _save(t, path):
                await _edge_tts.Communicate(t, Config.EDGE_TTS_VOICE or EDGE_TTS_VOICE).save(path)

            asyncio.run(_save(text, tmp_path))
            if os.path.getsize(tmp_path) == 0:
                return False
            return _play_mp3_blocking(tmp_path, self._stop_speaking)
        except Exception as exc:
            log.info("edge-tts unavailable, using offline voice: %s", exc)
            return False
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def test_voice(self):
        self.speak("Voice systems online. All systems nominal.")

    def test_current_voice(self):
        self.speak("Good day. All systems are operational and ready for your commands.")

    def list_available_voices(self):
        if not self.tts_engine:
            return []
        voices = self.tts_engine.getProperty("voices")
        for i, voice in enumerate(voices):
            print(f"  {i}: {voice.name}")
        return voices

    def change_voice(self, voice_index_or_name):
        if not self.tts_engine:
            return False
        voices = self.tts_engine.getProperty("voices")
        if isinstance(voice_index_or_name, int):
            if 0 <= voice_index_or_name < len(voices):
                self.tts_engine.setProperty("voice", voices[voice_index_or_name].id)
                return True
            return False
        for voice in voices:
            if str(voice_index_or_name).lower() in voice.name.lower():
                self.tts_engine.setProperty("voice", voice.id)
                return True
        return False

    # ── Microphone ───────────────────────────────────────────────────────────

    def _ensure_microphone(self):
        """Open and calibrate on first use; a failed device may be retried."""
        if not self.sr_available:
            return False
        if self.microphone is not None:
            return True
        with self._microphone_lock:
            if self.microphone is not None:
                return True
            try:
                microphone = sr.Microphone(device_index=self.selected_mic_index)
                with microphone as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=1)
                self.microphone = microphone
                return True
            except Exception as e:
                log.warning("Microphone unavailable: %s", e)
                return False

    def calibrate_microphone(self):
        if self.microphone is None:
            return self._ensure_microphone()
        if not self.sr_available:
            return False
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
            return True
        except Exception as exc:
            log.warning("Microphone calibration failed: %s", exc)
            return False

    def _recognize(self, audio):
        try:
            from core import local_speech
            text = local_speech.transcribe(audio.get_raw_data(convert_rate=16000, convert_width=2))
            if text is not None:
                return text.lower() or None
        except Exception as exc:
            log.warning("Local speech recognition failed: %s", exc)
        if Config.LOCAL_ONLY:
            return None             # local-only: the microphone audio never goes to Google
        try:
            return (self.recognizer.recognize_google(audio) or "").lower() or None
        except sr.UnknownValueError:
            return None
        except sr.RequestError as exc:
            log.warning("Speech recognition service error: %s", exc)
            return None
        except Exception as exc:   # network hiccups etc. must not kill the wake-word loop
            log.warning("Speech recognition failed: %s", exc)
            return None

    def _drop_failed_microphone(self, exc):
        """An OSError while reading means the device vanished (unplugged); reopen it next time."""
        if isinstance(exc, OSError):
            with self._microphone_lock:
                self.microphone = None

    def listen_for_command(self, timeout=5, phrase_timeout=15):
        if not self._ensure_microphone():
            return None
        self.is_listening = True
        try:
            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_timeout)
            return self._recognize(audio)
        except sr.WaitTimeoutError:
            return None
        except Exception as exc:
            log.warning("Listening failed: %s", exc)
            self._drop_failed_microphone(exc)
            return None
        finally:
            self.is_listening = False

    def listen_continuously(self, timeout=30, phrase_timeout=15, energy_threshold=None):
        if not self._ensure_microphone():
            return None
        self.is_listening = True
        try:
            with self.microphone as source:
                if energy_threshold:
                    self.recognizer.energy_threshold = energy_threshold
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_timeout)
            return self._recognize(audio)
        except sr.WaitTimeoutError:
            return None
        except Exception as exc:
            log.warning("Listening failed: %s", exc)
            self._drop_failed_microphone(exc)
            return None
        finally:
            self.is_listening = False

    # ── Wake word ────────────────────────────────────────────────────────────

    @staticmethod
    def contains_wake_word(text: str, wake_word: str) -> bool:
        return bool(text) and re.search(rf"\b{re.escape(wake_word.lower())}\b", text.lower()) is not None

    def _vosk_recognizer(self):
        if self._vosk is not None:
            return self._vosk or None
        self._vosk = False
        try:
            from core.streaming import model_dir, model_ready
            path = str(model_dir()) if model_ready() else ""
        except Exception:
            path = Config.VOSK_MODEL_PATH
        if not path or not os.path.isdir(path):
            return None
        try:
            import vosk
            vosk.SetLogLevel(-1)
            model = vosk.Model(path)
            grammar = json.dumps([Config.WAKE_WORD, "hey " + Config.WAKE_WORD, "[unk]"])
            self._vosk = (model, grammar)
            log.info("Offline wake word enabled (Vosk)")
        except Exception as exc:
            log.warning("Vosk unavailable: %s", exc)
        return self._vosk or None

    def listen_for_wake_word(self, wake_word=None):
        """Return True when the wake word is heard (whole word only)."""
        wake_word = (wake_word or Config.WAKE_WORD).lower()
        if not self._ensure_microphone():
            time.sleep(1)
            return False
        try:
            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=3)
        except sr.WaitTimeoutError:
            return False
        except Exception as exc:
            log.warning("Wake word listening failed: %s", exc)
            self._drop_failed_microphone(exc)
            time.sleep(1)
            return False
        vosk_setup = self._vosk_recognizer()
        if vosk_setup:
            try:
                import vosk
                model, grammar = vosk_setup
                rec = vosk.KaldiRecognizer(model, 16000, grammar)
                rec.AcceptWaveform(audio.get_raw_data(convert_rate=16000, convert_width=2))
                heard = json.loads(rec.FinalResult()).get("text", "")
                return self.contains_wake_word(heard, wake_word)
            except Exception as exc:
                log.warning("Offline wake word failed, using online recognition: %s", exc)
        return self.contains_wake_word(self._recognize(audio) or "", wake_word)

    # ── Device selection ─────────────────────────────────────────────────────

    def get_available_microphones(self):
        if not self.sr_available:
            return []
        try:
            return [{"index": i, "name": name, "is_default": i == 0}
                    for i, name in enumerate(sr.Microphone.list_microphone_names())]
        except Exception as exc:
            log.warning("Could not list microphones: %s", exc)
            return []

    def set_microphone(self, mic_index):
        if not self.sr_available:
            return False
        try:
            mic_list = sr.Microphone.list_microphone_names()
            if not 0 <= mic_index < len(mic_list):
                return False
            with self._microphone_lock:
                microphone = sr.Microphone(device_index=mic_index)
                with microphone as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=1)
                # Publish only after construction and calibration succeed.
                self.microphone = microphone
                self.selected_mic_index = mic_index
            return True
        except Exception as exc:
            log.warning("Error setting microphone: %s", exc)
            return False

    def get_current_microphone_info(self):
        if not self.sr_available:
            return "Speech recognition not available"
        try:
            mic_list = sr.Microphone.list_microphone_names()
            if self.selected_mic_index is not None:
                return f"Current: {mic_list[self.selected_mic_index]} (Index: {self.selected_mic_index})"
            return f"Default microphone: {mic_list[0] if mic_list else 'None'}"
        except Exception as e:
            return f"Error getting microphone info: {e}"
