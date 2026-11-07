"""Local speech: Whisper hears you, Kokoro speaks. Nothing leaves the PC.

* Speech-to-text: Whisper. On an NVIDIA GPU, distil-large-v3.5 runs through the
  PyTorch + transformers that already ship with JARVIS (about 0.3 s a sentence on
  an RTX 5060); without one, faster-whisper small.en on the CPU (int8, ~2 s).
* Text-to-speech: Kokoro (82M-parameter neural voice, ONNX on the CPU). Replies
  are spoken sentence by sentence — the first sentence plays while the next is
  being made — so speech starts quickly and stops the moment you interrupt.

Models download once into %APPDATA%\\Jarvis\\models on first use.
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.local_speech")

SAMPLE_RATE = 16000
KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
KOKORO_VOICES = {
    "bm_george": "George (British, male)", "bm_lewis": "Lewis (British, male)",
    "bm_daniel": "Daniel (British, male)", "bm_fable": "Fable (British, male)",
    "bf_emma": "Emma (British, female)", "bf_isabella": "Isabella (British, female)",
    "am_michael": "Michael (American, male)", "af_heart": "Heart (American, female)",
}
# What Whisper "hears" in near-silence; dropped when the clip is short.
_HALLUCINATIONS = {"", ".", "you", "thank you.", "thank you", "thanks for watching!", "thanks for watching.",
                   "bye.", "bye", "okay.", "so", "uh", "um"}


def _say(on_status: Optional[Callable[[str], None]], message: str):
    log.info(message)
    if on_status:
        try:
            on_status(message)
        except Exception:
            pass


def _download(url: str, target: Path, label: str, on_status=None) -> bool:
    import requests
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            done, last = 0, -1
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if total and (done * 100 // total) // 25 != last:
                        last = (done * 100 // total) // 25
                        _say(on_status, f"Downloading {label}: {done * 100 // total}%")
        if total and done != total:
            # A dropped connection can end the stream quietly; a cut-off model must never be
            # published as complete (it would fail to load on every start).
            raise IOError(f"incomplete download ({done} of {total} bytes)")
        tmp.replace(target)
        return True
    except Exception as exc:
        log.warning("download of %s failed: %s", url, exc)
        _say(on_status, f"Couldn't download {label} ({exc}).")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def split_sentences(text: str, first_max: int = 90) -> List[str]:
    """Short first chunk (fast start), then whole sentences grouped to ~200 characters."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?;])\s+", re.sub(r"\s+", " ", text or "").strip()) if p.strip()]
    chunks: List[str] = []
    for part in parts:
        if chunks and len(chunks) > 1 and len(chunks[-1]) + len(part) < 200:
            chunks[-1] += " " + part
        elif chunks and len(chunks) == 1 and len(chunks[0]) < 25 and len(chunks[0]) + len(part) < first_max:
            chunks[0] += " " + part
        else:
            chunks.append(part)
    return chunks


# ── Text-to-speech: Kokoro ───────────────────────────────────────────────────

class KokoroVoice:
    def __init__(self, model_dir: Optional[Path] = None):
        self.model_dir = Path(model_dir or Path(Config.MODELS_DIR) / "kokoro")
        self._kokoro = None
        self._lock = threading.Lock()
        self._failed = False

    @staticmethod
    def installed() -> bool:
        try:
            import kokoro_onnx  # noqa: F401
            return True
        except Exception:
            return False

    def files_ready(self) -> bool:
        return all((self.model_dir / name).is_file() for name in KOKORO_FILES)

    def ensure(self, on_status=None) -> bool:
        """Download the voice files (about 340 MB, once) and load the model."""
        if self._kokoro is not None:
            return True
        if self._failed or not self.installed():
            return False
        with self._lock:
            if self._kokoro is not None:
                return True
            for name, url in KOKORO_FILES.items():
                if not (self.model_dir / name).is_file():
                    _say(on_status, "Downloading JARVIS's local voice (one time only)…")
                    if not _download(url, self.model_dir / name, "the voice model", on_status):
                        return False
            try:
                from kokoro_onnx import Kokoro
                self._kokoro = Kokoro(str(self.model_dir / "kokoro-v1.0.onnx"), str(self.model_dir / "voices-v1.0.bin"))
            except Exception as exc:
                log.warning("Kokoro failed to load: %s", exc)
                self._failed = True
                return False
        return True

    def synth(self, text: str):
        voice = Config.KOKORO_VOICE if Config.KOKORO_VOICE in KOKORO_VOICES else "bm_george"
        lang = "en-gb" if voice.startswith("b") else "en-us"
        return self._kokoro.create(text, voice=voice, speed=Config.KOKORO_SPEED, lang=lang)

    def speak(self, text: str, stop_event: threading.Event) -> bool:
        """Speak to completion or until ``stop_event``. False if nothing could be played."""
        if not self.ensure():
            return False
        chunks = split_sentences(text)
        if not chunks:
            return True
        ready: "queue.Queue" = queue.Queue(maxsize=2)

        def produce():
            for chunk in chunks:
                if stop_event.is_set():
                    break
                try:
                    item = self.synth(chunk)
                except Exception as exc:
                    item = exc
                while not stop_event.is_set():
                    try:
                        ready.put(item, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                if isinstance(item, Exception):
                    return
            ready.put(None)

        threading.Thread(target=produce, name="KokoroSynth", daemon=True).start()
        played = False
        while not stop_event.is_set():
            try:
                item = ready.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                break
            if isinstance(item, Exception):
                log.warning("Kokoro synthesis failed: %s", item)
                return played
            samples, rate = item
            _play(samples, rate, stop_event)
            played = True
        return True


def _play(samples, rate: int, stop_event: threading.Event):
    """Blocking playback that stops within ~50 ms of ``stop_event``."""
    try:
        import sounddevice as sd
        sd.play(samples, rate)
        end = time.monotonic() + len(samples) / float(rate) + 0.5
        while time.monotonic() < end and not stop_event.is_set():
            stream = sd.get_stream()
            if stream is None or not stream.active:
                break
            time.sleep(0.03)
        sd.stop()
        return
    except Exception as exc:
        log.debug("sounddevice playback failed, using a temp WAV: %s", exc)
    import tempfile
    import soundfile as sf
    from core.voice import _play_mp3_blocking
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        sf.write(path, samples, rate)
        _play_mp3_blocking(path, stop_event)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ── Speech-to-text: Whisper ──────────────────────────────────────────────────

class WhisperEars:
    def __init__(self):
        self._lock = threading.Lock()
        self._backend = None        # ("gpu", processor, model) | ("cpu", model)
        self._failed = False

    @property
    def ready(self) -> bool:
        return self._backend is not None

    def load(self, on_status=None) -> bool:
        if self._backend is not None:
            return True
        if self._failed:
            return False
        with self._lock:
            if self._backend is not None:
                return True
            self._backend = self._load_gpu(on_status) or self._load_cpu(on_status)
            if self._backend is None:
                self._failed = True
                return False
        return True

    def _load_gpu(self, on_status):
        try:
            import torch
            if not torch.cuda.is_available():
                return None
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
            name = Config.WHISPER_GPU_MODEL
            _say(on_status, "Loading local speech recognition (GPU)…")
            cache = str(Path(Config.MODELS_DIR) / "hf_cache" / "hub")   # survives reinstalls, unlike the app folder
            processor = WhisperProcessor.from_pretrained(name, cache_dir=cache)
            model = WhisperForConditionalGeneration.from_pretrained(
                name, torch_dtype=torch.float16, cache_dir=cache).to("cuda").eval()
            return ("gpu", processor, model)
        except Exception as exc:
            log.warning("GPU Whisper unavailable: %s", exc)
            return None

    def _load_cpu(self, on_status):
        try:
            from faster_whisper import WhisperModel
            _say(on_status, "Loading local speech recognition…")
            model = WhisperModel(Config.WHISPER_CPU_MODEL, device="cpu", compute_type="int8",
                                 download_root=str(Path(Config.MODELS_DIR) / "whisper"))
            return ("cpu", model)
        except Exception as exc:
            log.warning("CPU Whisper unavailable: %s", exc)
            return None

    def transcribe(self, pcm16: bytes) -> str:
        if not self.load():
            return ""
        import numpy as np
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        seconds = len(audio) / SAMPLE_RATE
        if seconds < 0.3:
            return ""
        backend = self._backend
        try:
            if backend[0] == "gpu":
                import torch
                _, processor, model = backend
                feats = processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
                kwargs = {} if Config.WHISPER_GPU_MODEL.endswith(".en") else {"language": "en", "task": "transcribe"}
                with self._lock, torch.inference_mode():
                    ids = model.generate(feats.to("cuda", torch.float16), max_new_tokens=160, **kwargs)
                text = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
            else:
                _, model = backend
                with self._lock:
                    segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                                   condition_on_previous_text=False)
                    text = " ".join(s.text for s in segments if s.no_speech_prob < 0.6).strip()
        except Exception as exc:
            log.warning("Whisper transcription failed: %s", exc)
            return ""
        if seconds < 2.0 and text.lower().strip() in _HALLUCINATIONS:
            return ""
        return text


_EARS: Optional[WhisperEars] = None
_VOICE: Optional[KokoroVoice] = None


def ears() -> WhisperEars:
    global _EARS
    if _EARS is None:
        _EARS = WhisperEars()
    return _EARS


def voice() -> KokoroVoice:
    global _VOICE
    if _VOICE is None:
        _VOICE = KokoroVoice()
    return _VOICE


def transcribe(pcm16: bytes) -> Optional[str]:
    """Whisper text, or None when local recognition is off or unavailable (callers then fall back)."""
    if Config.STT_ENGINE != "whisper":
        return None
    e = ears()
    if not e.load():
        return None
    return e.transcribe(pcm16)


def warm_up(on_status=None):
    """Load / download both models in the background so the first conversation turn is quick."""
    def run():
        if Config.STT_ENGINE == "whisper":
            ears().load(on_status)
        if Config.TTS_ENGINE == "kokoro":
            voice().ensure(on_status)
    threading.Thread(target=run, name="LocalSpeechWarmUp", daemon=True).start()
