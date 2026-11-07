"""Conversation mode: talk with JARVIS like a person (toggle with F8).

    microphone (always open) ──► turn detector ──► transcribe ──► JARVIS ──► speak
         ▲                          │ you start talking while JARVIS speaks
         └──────── EchoGuard ◄──────┘   → it stops mid-sentence and listens

* No wake word, no button per turn: speak, pause, JARVIS answers, speak again.
* Barge-in: talk over JARVIS and it stops and listens. Its own voice coming back
  through the speakers is told apart from yours by what is said: a small offline
  Vosk model transcribes the mic while JARVIS talks, and only words JARVIS isn't
  saying (or "stop" / "wait" / "jarvis") count as you. With headphones there is
  no echo, so plain loudness is enough.
* Keep talking while JARVIS is still thinking and the two parts are answered as
  one request; a stale answer is dropped instead of spoken.

UI-agnostic: progress is reported through ``on_event(kind, info)`` — ``status``,
``started``, ``listening``, ``heard``, ``thinking``, ``answer``, ``interrupted``,
``idle``, ``stopped``.
"""
from __future__ import annotations

import array
import collections
import json
import math
import re
import sys
import threading
import time
from typing import Callable, List, Optional

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.conversation")

SAMPLE_RATE = 16000
FRAME = 480                                  # 30 ms of 16-bit mono
FRAME_S = FRAME / SAMPLE_RATE
BARGE_IN_MODEL = "vosk-model-small-en-in-0.4"   # 36 MB, loads in about a second

# Said over JARVIS, any of these interrupts it straight away (unless JARVIS itself is saying it).
STOP_WORDS = {"stop", "wait", "jarvis", "hold", "pause", "quiet", "enough", "shut"}
# Too common to tell the user from a misheard echo.
_FILLER = {"the", "a", "an", "and", "to", "of", "in", "is", "it", "i", "you", "that", "this", "on", "for", "uh", "um",
           "huh", "oh", "ah", "mm", "hmm", "yeah", "so", "but", "or", "be", "are", "was", "with", "at", "as"}
YES = re.compile(r"^\s*(?:yes|yeah|yep|yup|sure|confirm|do it|go ahead|ok(?:ay)?(?: do it)?)\b", re.I)


def rms(frame: bytes) -> float:
    samples = array.array("h", frame)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def words(text: str) -> List[str]:
    return re.findall(r"[a-z']+", (text or "").lower())


class EchoGuard:
    """While JARVIS speaks: is the sound on the mic the user talking over it, or JARVIS's own voice?"""

    def __init__(self, model=None):
        self.model = model
        self.recent = collections.deque(maxlen=int(1.2 / FRAME_S))   # audio kept for the interrupting turn
        self.active = False
        self.noise = 120.0
        self._spoken = set()
        self._rec = None
        self._heard: List[str] = []
        self._partial: List[str] = []
        self._frames = 0
        self._echo = 0.0
        self._loud_run = 0

    def begin(self, spoken_text: str, noise: float):
        self.active = True
        self.noise = max(noise, 30.0)
        self._spoken = set(words(spoken_text))
        self._heard, self._partial = [], []
        self._frames, self._echo, self._loud_run = 0, 0.0, 0
        self.recent.clear()
        self._rec = None
        if self.model is not None:
            try:
                import vosk
                self._rec = vosk.KaldiRecognizer(self.model, SAMPLE_RATE)
            except Exception as exc:
                log.debug("barge-in recognizer unavailable: %s", exc)

    def end(self):
        self.active = False
        self._rec = None

    def _novel(self, w: str) -> bool:
        return w not in self._spoken and w not in _FILLER and len(w) > 1

    def user_words(self, tail: List[str]) -> bool:
        """Words on the mic that JARVIS isn't saying: a stop word, or two new words in a row."""
        if any(w in STOP_WORDS and w not in self._spoken for w in tail[-3:]):
            return True
        return len(tail) >= 2 and self._novel(tail[-1]) and self._novel(tail[-2])

    def feed(self, frame: bytes, level: float) -> bool:
        """Returns True when the user is talking over JARVIS."""
        self.recent.append(frame)
        self._frames += 1
        elapsed = self._frames * FRAME_S
        if self._rec is not None:
            try:
                if self._rec.AcceptWaveform(frame):
                    self._heard += words(json.loads(self._rec.Result()).get("text", ""))
                    self._partial = []
                else:
                    self._partial = words(json.loads(self._rec.PartialResult()).get("partial", ""))
            except Exception as exc:
                log.debug("barge-in recognizer failed: %s", exc)
                self._rec = None
            if self.user_words((self._heard + self._partial)[-6:]):
                return True
        # Loudness: how strongly JARVIS's voice leaks back into the mic (none with headphones).
        loud_floor = max(self.noise * 4.0, 300.0)
        if elapsed < 0.5:                     # learn the echo level first: JARVIS has just started talking
            self._echo = max(self._echo, level) if self._frames < 4 else 0.8 * self._echo + 0.2 * level
            return False
        loud = level > max(loud_floor, self._echo * 2.5)
        if not loud:
            self._echo = 0.95 * self._echo + 0.05 * level
        self._loud_run = self._loud_run + 1 if loud else 0
        headphones = self._echo < self.noise * 2.0
        if headphones:
            return self._loud_run * FRAME_S >= 0.25
        if self._rec is None:                 # speakers and no recognizer: only clearly-louder-than-echo speech
            return level > max(loud_floor, self._echo * 3.5) and self._loud_run * FRAME_S >= 0.45
        return False


def transcribe(audio: bytes, model=None) -> str:
    """Local Whisper; the small Vosk model if Whisper can't load; Google only when chosen in settings."""
    try:
        from core import local_speech
        text = local_speech.transcribe(audio)
        if text is not None:
            return text
    except Exception as exc:
        log.warning("local transcription failed: %s", exc)
    if Config.STT_ENGINE == "google" and not Config.LOCAL_ONLY:
        try:
            import speech_recognition as sr
            return sr.Recognizer().recognize_google(sr.AudioData(audio, SAMPLE_RATE, 2), language="en-IN").strip()
        except Exception as exc:
            if exc.__class__.__name__ == "UnknownValueError":
                return ""
            log.info("online transcription unavailable: %s", exc)
    if model is not None:
        try:
            import vosk
            rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
            rec.AcceptWaveform(audio)
            return json.loads(rec.FinalResult()).get("text", "").strip()
        except Exception as exc:
            log.warning("offline transcription failed: %s", exc)
    return ""


def load_barge_in_model(on_status: Callable[[str], None]):
    try:
        from core import streaming
        if not streaming.vosk_available():
            return None
        path = streaming.ensure_model(BARGE_IN_MODEL, on_progress=on_status)
        if path is None:
            return None
        from core.buddy import _vosk_model
        return _vosk_model(str(path))
    except Exception as exc:
        log.warning("barge-in model unavailable: %s", exc)
        return None


class ConversationMode:
    """Hands-free back-and-forth with JARVIS. ``start()`` returns at once; ``stop()`` ends it."""

    def __init__(self, jarvis, on_event: Optional[Callable[[str, dict], None]] = None,
                 device_index: Optional[int] = None, end_silence: float = 0.8,
                 transcriber: Optional[Callable[[bytes], str]] = None, model_loader=load_barge_in_model):
        self.jarvis = jarvis
        self.voice = getattr(jarvis, "voice_engine", None)
        self.on_event = on_event or (lambda kind, info: None)
        self.device_index = device_index
        self.end_silence = end_silence
        self.transcriber = transcriber
        self.model_loader = model_loader
        self.model = None
        self.guard = EchoGuard()
        self.noise = 120.0
        self.capturing = False
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._turn = 0                        # bumps when new speech arrives; older answers are dropped
        self._transcribing = 0
        self._unanswered = ""                 # what the user said that hasn't been answered yet
        self._ask: Optional[dict] = None
        self._quiet_until = 0.0

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def _emit(self, kind: str, **info):
        try:
            self.on_event(kind, info)
        except Exception:
            log.exception("conversation event failed")

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Conversation", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            self._turn += 1
            if self._ask:
                self._ask["event"].set()
        if self.voice is not None:
            try:
                self.voice.stop_speaking()
            except Exception:
                pass

    def _run(self):
        pa = stream = None
        previous_stream = getattr(self.jarvis, "stream", None)
        previous_voice_mode = getattr(self.jarvis, "_voice_mode", False)
        try:
            import pyaudio
            status = lambda msg: self._emit("status", message=msg)   # noqa: E731
            if self.transcriber is None:
                try:
                    from core import local_speech
                    local_speech.warm_up(status)       # Whisper + Kokoro load while the mic opens
                except Exception:
                    log.exception("local speech warm-up failed")
            self.model = self.model_loader(status)
            self.guard.model = self.model
            if self.model is None:
                self._emit("status", message="Talking over JARVIS works best with headphones on this setup.")
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
                             frames_per_buffer=FRAME, input_device_index=self.device_index)
            self.jarvis.stream = self              # spoken yes/no confirmations come through ask_yes_no
            self.jarvis._voice_mode = True
            self._calibrate(stream)
            self._emit("started")
            self._loop(stream)
        except ModuleNotFoundError as exc:
            from core.deps import missing_package_message
            self._emit("status", message=missing_package_message(exc, "Conversation mode"))
        except Exception as exc:
            log.exception("conversation mode failed")
            self._emit("status", message=f"Conversation mode stopped: {exc}")
        finally:
            self._stop.set()
            if getattr(self.jarvis, "stream", None) is self:
                self.jarvis.stream = previous_stream
            self.jarvis._voice_mode = previous_voice_mode
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
                if pa is not None:
                    pa.terminate()
            except Exception:
                pass
            self._emit("stopped")

    def _calibrate(self, stream, seconds: float = 0.5):
        levels = [rms(stream.read(FRAME, exception_on_overflow=False)) for _ in range(int(seconds / FRAME_S))]
        if levels:
            self.noise = max(30.0, sorted(levels)[len(levels) // 2])

    # ── the microphone loop ──────────────────────────────────────────────────

    def _speaking(self) -> bool:
        return bool(self.voice is not None and getattr(self.voice, "is_speaking", False))

    def _loop(self, stream):
        preroll = collections.deque(maxlen=int(0.4 / FRAME_S))
        frames: List[bytes] = []
        speech_run = silence = voiced = 0
        while not self._stop.is_set():
            frame = stream.read(FRAME, exception_on_overflow=False)
            level = rms(frame)
            if not self.capturing and self._speaking():
                if not self.guard.active:
                    self.guard.begin(getattr(self.voice, "speaking_text", ""), self.noise)
                if self.guard.feed(frame, level):
                    self._interrupt()
                    frames, silence, voiced = list(self.guard.recent), 0, int(0.3 / FRAME_S)
                    self.capturing = True
                    self.guard.end()
                    self._emit("listening")
                continue
            if self.guard.active:
                self.guard.end()
                self._quiet_until = time.monotonic() + 0.3       # let the speaker's tail die away
            start_at = max(self.noise * 3.0, 250.0)
            if not self.capturing:
                if level < start_at:
                    self.noise = 0.95 * self.noise + 0.05 * max(level, 30.0)
                speech_run = speech_run + 1 if level > start_at and time.monotonic() > self._quiet_until else 0
                preroll.append(frame)
                if speech_run >= 3:
                    self.capturing = True
                    frames, silence, voiced = list(preroll), 0, speech_run
                    self._emit("listening")
                continue
            frames.append(frame)
            if level > max(self.noise * 2.0, 180.0):
                silence, voiced = 0, voiced + 1
            else:
                silence += 1
            if silence * FRAME_S >= self.end_silence or len(frames) * FRAME_S >= 30:
                self.capturing = False
                speech_run = 0
                preroll.clear()
                if voiced * FRAME_S >= 0.25:
                    self._submit(b"".join(frames))
                else:
                    self._emit("idle")
                frames = []

    def _interrupt(self):
        # The turn counter moves when the interrupting words are transcribed, not here: cutting off a
        # "Shall I delete it? Say yes or no." with "yes" must still let that command finish.
        if self.voice is not None:
            try:
                self.voice.stop_speaking()
            except Exception:
                pass
        self._emit("interrupted")

    # ── turns ────────────────────────────────────────────────────────────────

    def _submit(self, audio: bytes):
        with self._lock:
            self._transcribing += 1
        threading.Thread(target=self._take_turn, args=(audio,), name="ConversationTurn", daemon=True).start()

    def _transcribe(self, audio: bytes) -> str:
        if self.transcriber is not None:
            return self.transcriber(audio)
        return transcribe(audio, self.model)

    def _take_turn(self, audio: bytes):
        try:
            text = self._transcribe(audio).strip()
        except Exception:
            log.exception("transcription failed")
            text = ""
        with self._lock:
            self._transcribing -= 1
            if not text or self._stop.is_set():
                self._emit("idle")
                return
            if self._ask is not None:           # a confirmation was waiting for this
                self._ask["answer"] = bool(YES.match(text))
                self._ask["event"].set()
                self._emit("heard", text=text)
                return
            self._turn += 1
            turn = self._turn
            self._unanswered = f"{self._unanswered} {text}".strip()
            request = self._unanswered
        self._emit("heard", text=text)
        self._emit("thinking")
        reply = self._ask_jarvis(request)
        # Don't talk over the user: wait until they finish, then answer only if nothing newer came in.
        while not self._stop.is_set() and (self.capturing or self._transcribing):
            time.sleep(0.05)
        with self._lock:
            if turn != self._turn or self._stop.is_set():
                return
            self._unanswered = ""
        self._emit("answer", text=reply)
        if self.voice is not None and reply:
            try:
                self.voice.speak(reply, summarize=True)
            except Exception:
                log.exception("conversation speech failed")
        with self._lock:
            if turn == self._turn and not self.capturing:
                self._emit("idle")

    def _ask_jarvis(self, text: str) -> str:
        origin = getattr(sys.modules.get(type(self.jarvis).__module__), "_ORIGIN", None)
        if origin is not None:
            origin.voice = True                 # confirmations for this command are asked out loud
        try:
            return str(self.jarvis.process_command(text, use_voice=False) or "Done.")
        except Exception as exc:
            log.exception("conversation request failed")
            return f"Something went wrong: {exc}"
        finally:
            if origin is not None:
                origin.voice = False

    def ask_yes_no(self, question: str, timeout: float = 20.0) -> bool:
        """Called by JARVIS (on the turn thread) before risky actions."""
        holder = {"event": threading.Event(), "answer": False}
        with self._lock:
            self._ask = holder
        self._emit("answer", text=question + " (say yes or no)")
        try:
            if self.voice is not None:
                self.voice.speak(question + " Say yes or no.")
            holder["event"].wait(timeout)
        finally:
            with self._lock:
                self._ask = None
        return holder["answer"]
