"""Buddy mode: a Clicky-style companion for Windows.

Hold the push-to-talk hotkey, ask about what's on screen, let go:

    hotkey down ─► record mic            (buddy next to the cursor pulses: listening)
    hotkey up   ─► transcribe (Vosk offline, else Google)          (thinking)
                ├─ a command ("open settings and turn on dark mode")
                │     → JARVIS does it, the buddy says what happened
                └─ a question about the screen ("where's the export button?",
                   "how do I change my wallpaper?")
                      → one screenshot + one vision call → a short spoken answer
                        and the exact places to point at; the overlay draws arrows
                        and rings there (it never clicks for you)

The screen is only captured while you use the hotkey, and the overlay is
excluded from captures, so the buddy never appears in its own screenshots.

This module has no UI code: the overlay (ui/buddy_overlay.py) subscribes to
``on_state(kind, info)`` events — ``listening``, ``thinking``, ``answer``,
``point``, ``error``, ``idle``.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.buddy")

SAMPLE_RATE = 16000

# Questions about the screen get guidance; everything else is treated as a command.
_GUIDE = re.compile(
    r"^(?:hey\s+jarvis,?\s+|jarvis,?\s+)?(?:where(?:'s| is| are| do i| can i)?|how (?:do|can|would|should) (?:i|you)|"
    r"how to|show me(?: how| where)?|point (?:to|at|out)|which (?:button|one|menu|option|icon|tab)|"
    r"what (?:is|does|are|should) (?:this|that|these|it|i)|what(?:'s| is) (?:this|that|on (?:my |the )?screen)|"
    r"can you (?:show|help|point|find)|help me (?:find|with)|explain (?:this|that|what)|find (?:the|me)|"
    r"i can'?t find|guide me|walk me through|what do i (?:click|press|do))\b",
    re.I)

GUIDE_PROMPT = """You are JARVIS, a friendly on-screen helper sitting next to the user's cursor.
The screenshot is {w}x{h} pixels. The user asked: "{question}"

Answer like a helpful friend looking over their shoulder: short, spoken-style, no markdown.
If the answer involves things on screen, point at them in the order the user should use them.
Reply with JSON only:
{{"answer": "<1-3 short sentences to say out loud>",
  "points": [{{"x": <center x in pixels>, "y": <center y in pixels>, "label": "<2-5 words>"}}]}}
Use an empty "points" list when nothing on screen needs pointing at. At most 5 points.
Only point at things you can actually see in the screenshot."""


@dataclass
class Point:
    x: int
    y: int
    label: str = ""


@dataclass
class Guidance:
    answer: str
    points: List[Point] = field(default_factory=list)


def is_guide_question(text: str) -> bool:
    return bool(_GUIDE.search((text or "").strip()))


# ── Screen guidance ──────────────────────────────────────────────────────────

def guide(screen_automation, question: str, shot: Optional[str] = None) -> Guidance:
    """One screenshot + one vision call → spoken answer + screen points (physical pixels)."""
    from skills.screen_automation import extract_json
    sa = screen_automation
    if sa is None:
        return Guidance("Screen help isn't available on this system.")
    try:
        shot = shot or sa.take_screenshot()
        img, w, h = sa._model_image(shot)
        reply = sa._ask_vision(GUIDE_PROMPT.format(w=w, h=h, question=question.strip().replace('"', "'")), img)
    except Exception as exc:
        log.warning("guide failed: %s", exc)
        return Guidance(f"I couldn't look at the screen: {exc}")
    data = extract_json(reply)
    if not isinstance(data, dict):
        # A model that ignored the format still gave a useful answer.
        text = re.sub(r"```.*?```", "", str(reply or ""), flags=re.S).strip()
        return Guidance(text[:400] or "I'm not sure — could you ask that another way?")
    answer = str(data.get("answer") or "").strip() or "Here you go."
    points: List[Point] = []
    raw = data.get("points") or []
    if isinstance(raw, dict):
        raw = [raw]
    for item in raw[:5] if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            xy = sa._point_from(item, w, h)
        except (TypeError, ValueError):
            xy = None
        if not xy:
            continue
        sx, sy = sa._to_screen(xy[0], xy[1], w, h)
        points.append(Point(sx, sy, str(item.get("label") or "")[:40]))
    return Guidance(answer, points)


# ── Push-to-talk recording ───────────────────────────────────────────────────

class Recorder:
    """Records 16 kHz mono while the hotkey is held (PyAudio)."""

    def __init__(self, device_index: Optional[int] = None, max_seconds: float = 30.0):
        self.device_index = device_index
        self.max_seconds = max_seconds
        self._frames: List[bytes] = []
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._error: Optional[str] = None

    def start(self):
        self._frames, self._error = [], None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="BuddyRecorder", daemon=True)
        self._thread.start()

    def _run(self):
        pa = stream = None
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
                             frames_per_buffer=1600, input_device_index=self.device_index)
            deadline = time.monotonic() + self.max_seconds
            while not self._stop.is_set() and time.monotonic() < deadline:
                self._frames.append(stream.read(1600, exception_on_overflow=False))
        except ModuleNotFoundError as exc:
            from core.deps import missing_package_message
            self._error = missing_package_message(exc, "The microphone")
            log.warning(self._error)
        except Exception as exc:
            self._error = f"microphone error: {exc}"
            log.warning(self._error)
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
                if pa is not None:
                    pa.terminate()
            except Exception:
                pass

    def stop(self) -> bytes:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._error:
            raise RuntimeError(self._error)
        return b"".join(self._frames)


def transcribe(audio: bytes) -> str:
    """Local Whisper first; then the live-voice Vosk model when it's installed; else Google via SpeechRecognition."""
    if len(audio) < SAMPLE_RATE * 2 * 0.3:          # under 0.3 s: a tap, not speech
        return ""
    try:
        from core import local_speech
        text = local_speech.transcribe(audio)       # local Whisper when it's on and loads
        if text is not None:
            return text.strip()
    except Exception as exc:
        log.warning("local transcription failed: %s", exc)
    try:
        from core import streaming
        if streaming.vosk_available() and streaming.model_ready():
            import json
            import vosk
            model = _vosk_model(str(streaming.model_dir()))
            rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
            rec.AcceptWaveform(audio)
            return json.loads(rec.FinalResult()).get("text", "").strip()
    except Exception as exc:
        log.warning("vosk transcription failed: %s", exc)
    if Config.LOCAL_ONLY:
        log.info("local-only mode: no offline speech model recognised that; not sending it to Google")
        return ""                   # local-only: push-to-talk audio never leaves the PC
    try:
        import speech_recognition as sr
        return sr.Recognizer().recognize_google(sr.AudioData(audio, SAMPLE_RATE, 2), language="en-IN").strip()
    except Exception as exc:
        log.info("speech not recognised: %s", exc)
        return ""


_VOSK_CACHE = {}


def _vosk_model(path: str):
    if path not in _VOSK_CACHE:                    # loading the large model takes seconds; do it once
        import vosk
        _VOSK_CACHE[path] = vosk.Model(path)
    return _VOSK_CACHE[path]


# ── Global hotkey ────────────────────────────────────────────────────────────

HOTKEYS = {
    "ctrl+alt": "Hold Ctrl + Alt",
    "right ctrl": "Hold Right Ctrl",
    "ctrl+shift": "Hold Ctrl + Shift",
    "ctrl+win": "Hold Ctrl + Win",
    "f9": "Hold F9",
}


class HoldHotkey:
    """Calls on_down when the whole combination is held and on_up when any key of it is released."""

    def __init__(self, combo: str, on_down: Callable[[], None], on_up: Callable[[], None]):
        self.combo = (combo or "ctrl+alt").lower()
        self.on_down, self.on_up = on_down, on_up
        self._pressed = set()
        self._active = False
        self._listener = None

    def _names(self, key) -> List[str]:
        name = str(getattr(key, "name", "") or getattr(key, "char", "") or "").lower()
        names = [name]
        if name in ("ctrl_l", "ctrl_r"):
            names.append("ctrl")
        if name in ("alt_l", "alt_r"):            # not alt_gr: AltGr (₹, €) arrives as Ctrl+AltGr
            names.append("alt")
        if name in ("shift_l", "shift_r"):
            names.append("shift")
        if name in ("cmd", "cmd_l", "cmd_r"):
            names.append("win")
        if name == "ctrl_r":
            names.append("right ctrl")
        return names

    def _wanted(self) -> set:
        return set(self.combo.split("+")) if self.combo != "right ctrl" else {"right ctrl"}

    def press(self, key):
        self._pressed.update(self._names(key))
        if not self._active and self._wanted() <= self._pressed:
            self._active = True
            self._safe(self.on_down)

    def release(self, key):
        names = self._names(key)
        self._pressed.difference_update(names)
        if self._active and self._wanted() & set(names):
            self._active = False
            self._safe(self.on_up)

    @staticmethod
    def _safe(fn):
        try:
            fn()
        except Exception:
            log.exception("hotkey callback failed")

    def start(self) -> bool:
        self.stop()          # never two listeners (every press would fire twice)
        try:
            from pynput import keyboard
            self._listener = keyboard.Listener(on_press=self.press, on_release=self.release)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as exc:
            log.warning("global hotkey unavailable: %s", exc)
            return False

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        # Releases that happen while stopped are never seen: start clean, or a key stuck in
        # _pressed would make the next single key press count as the whole combination.
        self._pressed.clear()
        self._active = False


# ── Controller ───────────────────────────────────────────────────────────────

class BuddyController:
    """Ties hotkey, microphone, JARVIS and the overlay together. UI-agnostic and thread-safe."""

    def __init__(self, jarvis, on_state: Callable[[str, dict], None], hotkey: Optional[str] = None,
                 speak: bool = True, recorder: Optional[Recorder] = None,
                 transcriber: Callable[[bytes], str] = transcribe):
        self.jarvis = jarvis
        self.on_state = on_state
        self.speak = speak
        self.recorder = recorder or Recorder(getattr(getattr(jarvis, "voice_engine", None), "selected_mic_index", None))
        self.transcriber = transcriber
        self.hotkey = HoldHotkey(hotkey or Config.BUDDY_HOTKEY, self.begin, self.finish)
        self._busy = threading.Lock()
        self._recording = False

    def _emit(self, kind: str, **info):
        try:
            self.on_state(kind, info)
        except Exception:
            log.exception("buddy state callback failed")

    def start(self) -> bool:
        ok = self.hotkey.start()
        self._emit("idle", hotkey=HOTKEYS.get(self.hotkey.combo, self.hotkey.combo), ready=ok)
        return ok

    def stop(self):
        self.hotkey.stop()
        if self._recording:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self._recording = False

    # hotkey down
    def begin(self):
        if self._recording or self._busy.locked():
            return
        self._recording = True
        try:
            voice = getattr(self.jarvis, "voice_engine", None)
            if voice is not None and hasattr(voice, "stop_speaking"):
                voice.stop_speaking()              # talking over the buddy interrupts it
        except Exception:
            pass
        self.recorder.start()
        self._emit("listening")

    # hotkey up
    def finish(self):
        if not self._recording:
            return
        self._recording = False
        try:
            audio = self.recorder.stop()
        except Exception as exc:
            self._emit("error", message=str(exc))
            return
        threading.Thread(target=self._handle_audio, args=(audio,), name="BuddyTurn", daemon=True).start()

    def _handle_audio(self, audio: bytes):
        with self._busy:
            self._emit("thinking")
            text = self.transcriber(audio)
            if not text:
                self._emit("idle", message="I didn't catch that.")
                return
            self._emit("heard", text=text)
            self.ask(text, from_hotkey=True)

    def ask(self, text: str, speak: Optional[bool] = None, from_hotkey: bool = False) -> Guidance:
        """Answer one request. Also used for typed / live-voice questions (``speak=False``:
        the caller shows or speaks the answer itself)."""
        try:
            if is_guide_question(text):
                result = guide(getattr(self.jarvis, "screen_automation", None), text)
            else:
                reply = self.jarvis.process_command(text, use_voice=False) or "Done."
                result = Guidance(str(reply))
        except Exception as exc:
            log.exception("buddy request failed")
            result = Guidance(f"Something went wrong: {exc}")
        if result.points:
            self._emit("point", points=[(p.x, p.y, p.label) for p in result.points], answer=result.answer)
        # from_hotkey: the chat window shows it too; a typed question already gets it as the chat reply
        self._emit("answer", text=result.answer, from_hotkey=from_hotkey)
        if self.speak if speak is None else speak:
            voice = getattr(self.jarvis, "voice_engine", None)
            if voice is not None:
                try:
                    voice.speak(result.answer, summarize=True)
                except Exception:
                    log.exception("buddy speech failed")
        self._emit("idle")
        return result
