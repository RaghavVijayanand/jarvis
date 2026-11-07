"""Live voice: act on commands while the user is still speaking.

    microphone ──► StreamingRecognizer (Vosk, offline, partial results)
                       │ partial text / final segment
                       ▼
                 ClauseTracker  — closes a clause once the connector after it and the
                       │          next word are heard, and the words stop changing
                       ▼
                 StreamingSession — routes each closed clause (local decision model),
                       │           runs actions immediately in ordered / parallel lanes,
                       │           holds back questions until the user stops talking
                       ▼
                 core.executor.ExecutionSession  → JARVIS skills

"open chrome and go to youtube and play rick roll, simultaneously open the
alarm …" — Chrome starts opening while the user is still saying "go to youtube".
JARVIS stays silent while the user talks (a short beep marks each action) and
speaks one summary after they stop.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core.config import Config
from core.logging_setup import get_logger
from skills.command_processor import split_clauses

log = get_logger("jarvis.streaming")

VOSK_MODELS: Dict[str, Tuple[str, str]] = {
    # name: (url, human size)
    "vosk-model-en-in-0.5": ("https://alphacephei.com/vosk/models/vosk-model-en-in-0.5.zip", "1 GB"),
    "vosk-model-small-en-in-0.4": ("https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip", "36 MB"),
    "vosk-model-en-us-0.22-lgraph": ("https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip", "128 MB"),
    "vosk-model-small-en-us-0.15": ("https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip", "40 MB"),
}
SAMPLE_RATE = 16000

# Intents that can safely start before the user has finished the sentence.
ACT_NOW = {"APP", "MEDIA", "CONTROL", "SCHEDULE", "SCREEN_AUTOMATION", "FILE", "SYSTEM", "TIME", "WEATHER",
           "MATH", "UTILITY", "MEMORY", "SEARCH"}
YES = re.compile(r"^\s*(?:yes|yeah|yep|yup|sure|confirm|do it|go ahead|okay do it|ok do it)(?: please)?\s*$", re.I)
NO = re.compile(r"^\s*(?:no|nope|cancel|don'?t|do not|stop|never mind)(?: thanks)?\s*$", re.I)
STOP = re.compile(r"^\s*(?:stop|cancel|abort|never ?mind)(?: it| that| everything| all)?\s*$", re.I)


# ── Model management ─────────────────────────────────────────────────────────

def vosk_available() -> bool:
    try:
        import vosk  # noqa: F401
        return True
    except Exception:
        return False


def model_dir(name: Optional[str] = None) -> Path:
    if Config.VOSK_MODEL_PATH and Path(Config.VOSK_MODEL_PATH).is_dir():
        return Path(Config.VOSK_MODEL_PATH)
    return Path(Config.MODELS_DIR) / (name or Config.VOSK_MODEL_NAME)


def model_ready(name: Optional[str] = None) -> bool:
    path = model_dir(name)
    return path.is_dir() and ((path / "am").exists() or (path / "conf").exists())


def ensure_model(name: Optional[str] = None, on_progress: Optional[Callable[[str], None]] = None) -> Optional[Path]:
    """Return the model folder, downloading and unpacking it the first time."""
    name = name or Config.VOSK_MODEL_NAME
    target = model_dir(name)
    if model_ready(name):
        return target
    url, size = VOSK_MODELS.get(name, (f"https://alphacephei.com/vosk/models/{name}.zip", "?"))
    say = on_progress or (lambda msg: log.info(msg))
    say(f"Downloading speech model {name} ({size}) for live voice — one time only…")
    import requests
    Path(Config.MODELS_DIR).mkdir(parents=True, exist_ok=True)
    tmp = Path(Config.MODELS_DIR) / f"{name}.zip.part"
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            done, last = 0, -1
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        if pct // 20 != last:
                            last = pct // 20
                            say(f"Speech model download: {pct}%")
        say("Unpacking speech model…")
        with zipfile.ZipFile(tmp) as zf:
            zf.extractall(Config.MODELS_DIR)
        tmp.unlink(missing_ok=True)
        if not model_ready(name):
            # Some archives unpack to a differently named folder.
            candidates = [p for p in Path(Config.MODELS_DIR).iterdir() if p.is_dir() and p.name.startswith(name[:18])]
            if candidates:
                candidates[0].rename(target)
        if model_ready(name):
            say("Speech model ready — live voice enabled.")
            return target
        say("The speech model archive looked wrong; live voice stays off.")
    except Exception as exc:
        log.exception("model download failed")
        say(f"Couldn't download the speech model ({exc}). Voice falls back to the normal mode.")
        tmp.unlink(missing_ok=True)
    return None


# ── Clause tracking ──────────────────────────────────────────────────────────

class ClauseTracker:
    """Turns a growing transcript into clauses that are safe to act on.

    A clause is closed when split_clauses() puts another clause after it —
    which only happens once the connector *and* the next word have been
    heard — and the closed prefix is unchanged across two updates (Vosk
    sometimes rewrites the last few words). A final segment closes everything.

    Progress is tracked as a *word position* in the transcript, not as a
    clause count: only the words after what was already acted on are
    re-split. So a final result that regroups or rewrites earlier clauses can
    neither re-run an action nor drop the words that follow it.
    """

    def __init__(self, stable_updates: int = 2):
        self.stable_updates = stable_updates
        self.reset()

    def reset(self):
        self._consumed = 0
        self._prefix: List[str] = []          # the words already acted on
        self._candidate: List[Tuple[str, str]] = []
        self._seen = 0
        self.text = ""

    @staticmethod
    def _end_of(clause: str, words: List[str], start: int) -> int:
        """Index just past `clause`'s last word, matching its words in order."""
        pos = start
        for word in clause.lower().split():
            for i in range(pos, len(words)):
                if ClauseTracker._norm(words[i]) == ClauseTracker._norm(word):
                    pos = i + 1
                    break
        return pos

    @staticmethod
    def _norm(word: str) -> str:
        return word.lower().strip(".,;:!?")

    def _realign(self, words: List[str]) -> int:
        """Where the already-acted-on prefix ends in a (possibly rewritten) transcript."""
        old = [self._norm(w) for w in self._prefix]
        new = [self._norm(w) for w in words]
        if new[:len(old)] == old:
            return len(old)
        import difflib
        end = len(old)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag == "equal" and i1 <= end <= i2:
                return j1 + (end - i1)
            if tag != "equal" and i1 < end <= i2:
                # A rewritten word at the boundary ("notepad" → "note pad", "crime" →
                # "chrome") counts as heard. The new side of the opcode also holds
                # everything said since, so take only as many new words as spell
                # the old ones, or the same number of words.
                target = "".join(old[i1:i2])
                for j in range(j1 + 1, j2 + 1):
                    joined = "".join(new[j1:j])
                    if joined == target:
                        return j
                    if len(joined) >= len(target):
                        break
                return min(j1 + (i2 - i1), len(words))
        return min(end, len(words))

    def update(self, text: str, final: bool = False) -> List[Tuple[str, str]]:
        self.text = (text or "").strip()
        words = self.text.split()
        consumed = self._realign(words) if self._prefix else 0
        clauses = split_clauses(" ".join(words[consumed:]))
        ready = clauses if final else clauses[:-1]
        if not ready:
            if final:
                self.reset()
            return []
        if not final:
            if ready == self._candidate:
                self._seen += 1
            else:
                self._candidate, self._seen = ready, 1
            if self._seen < self.stable_updates:
                return []
        pos = consumed
        for _, clause in ready:
            pos = self._end_of(clause, words, pos)
        self._consumed = pos
        self._prefix = words[:pos]
        self._candidate, self._seen = [], 0
        if final:
            self.reset()
        return ready


# ── Session: routing + execution of heard clauses ────────────────────────────

class StreamingSession:
    """Glue between live transcripts and JARVIS. Thread-safe; UI-agnostic."""

    def __init__(self, jarvis, on_event: Optional[Callable[[str, dict], None]] = None,
                 act_mode: str = "clause", require_wake_word: bool = False, beep: bool = True):
        self.jarvis = jarvis
        self.on_event = on_event or (lambda kind, info: None)
        self.act_mode = act_mode              # "clause": act mid-sentence · "pause": act per segment
        self.require_wake_word = require_wake_word
        self.beep = beep
        self.tracker = ClauseTracker()
        self._lock = threading.RLock()
        self._exec = None
        self._deferred: List[str] = []
        self._heard: List[str] = []
        self._awake_until = 0.0
        self._ask: Optional[dict] = None
        self._utterance_started = False

    # events
    def _emit(self, kind: str, **info):
        try:
            self.on_event(kind, info)
        except Exception:
            log.exception("stream event failed")

    def _beep(self):
        if not self.beep or os.name != "nt":
            return
        def run():
            try:
                import winsound
                winsound.Beep(1250, 45)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    # wake word
    def _strip_wake(self, text: str) -> Optional[str]:
        if not self.require_wake_word or time.time() < self._awake_until:
            return text
        wake = Config.WAKE_WORD.lower()
        m = re.match(rf"^\s*(?:hey\s+|ok\s+|okay\s+)?{re.escape(wake)}\b[\s,]*(.*)$", text, re.I)
        return m.group(1) if m else None

    # confirmations asked by tools while streaming
    def ask_yes_no(self, question: str, timeout: float = 20.0) -> bool:
        holder = {"event": threading.Event(), "answer": False}
        with self._lock:
            self._ask = holder
        self._emit("ask", question=question)
        try:
            self.jarvis.voice_engine.speak(question + " Say yes or no.")
        except Exception:
            pass
        holder["event"].wait(timeout)
        with self._lock:
            self._ask = None
        return holder["answer"]

    # transcript input (called from the recognizer thread)
    def partial(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        self._emit("partial", text=text)
        if self.act_mode != "clause":
            return
        with self._lock:   # end_utterance() flushes the same tracker from another thread
            stripped = self._strip_wake(text)
            if stripped is None:
                return
            for link, clause in self.tracker.update(stripped, final=False):
                self._dispatch(link, clause)

    def segment(self, text: str):
        """A finalized chunk (Vosk detected a short pause)."""
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            ask = self._ask
        if ask is not None and (YES.match(text) or NO.match(text)):
            ask["answer"] = bool(YES.match(text))
            ask["event"].set()
            self.tracker.reset()
            return
        with self._lock:
            stripped = self._strip_wake(text)
            if stripped is None:
                self.tracker.reset()
                return
            self._emit("heard", text=stripped)
            if STOP.match(stripped) and self._cancel_utterance(stripped):
                return
            if YES.match(stripped) or NO.match(stripped):
                # Answer to a pending "Reply yes to confirm" from an earlier step.
                self.tracker.reset()
                threading.Thread(target=self._answer_pending, args=(stripped,), daemon=True).start()
                return
            self._heard.append(stripped)
            for link, clause in self.tracker.update(stripped, final=True):
                self._dispatch(link, clause)

    def _cancel_utterance(self, text: str) -> bool:
        """"stop" / "cancel" said while this utterance's steps are live: drop everything not yet done.

        Returns False when there's nothing live (the word then answers an earlier confirmation).
        """
        if getattr(self.jarvis, "_pending_actions", None):
            return False
        with self._lock:
            session, deferred = self._exec, self._deferred
            if session is None and not deferred:
                return False
            self._exec, self._deferred, self._heard = None, [], []
            self.tracker.reset()
        if session is not None:
            session.stop()
            session.close()
        self._emit("utterance_done", heard=text, summary="Stopped.", details="Stopped.")
        return True

    def _dispatch(self, link: str, clause: str):
        intent = self.jarvis._classify_command_intent(clause)
        with self._lock:
            if intent not in ACT_NOW:
                self._deferred.append(clause)
                self._emit("deferred", text=clause, intent=intent)
                return
            session = self._exec_session()
            parallel = link == "par"
            step = session.submit(clause, parallel=parallel)
        self._beep()
        self._emit("dispatched", text=clause, intent=intent, lane=step.lane, index=step.index)

    def _new_session(self):
        try:
            return self.jarvis.new_execution_session(on_event=lambda kind, info: self._emit(kind, **info), voice=True)
        except TypeError:                      # an older / fake JARVIS without the voice flag
            return self.jarvis.new_execution_session(on_event=lambda kind, info: self._emit(kind, **info))

    def _answer_pending(self, text: str):
        reply = self.jarvis.process_command(text, use_voice=False) or ""
        self._emit("utterance_done", heard=text, summary=reply, details=reply)

    def _exec_session(self):
        if self._exec is None:
            self._exec = self._new_session()
        return self._exec

    def end_utterance(self) -> Optional[str]:
        """The user stopped talking: run what's left, then report back once."""
        with self._lock:
            for link, clause in self.tracker.update(self.tracker.text, final=True):
                self._dispatch(link, clause)
            deferred, self._deferred = self._deferred, []
            session, self._exec = self._exec, None
            heard, self._heard = " ".join(self._heard), []
        if not deferred and session is None:
            return None
        if self.require_wake_word:
            self._awake_until = time.time() + 8   # follow-ups don't need the wake word
        if deferred:
            question = " and ".join(deferred)
            chat_session = session or self._new_session()
            chat_session.submit(question, parallel=bool(session and session.steps))
            session = chat_session
        session.close_and_wait(timeout=180)
        summary = self.summarize(session)
        self._emit("utterance_done", heard=heard, summary=summary,
                   details=self.jarvis.format_session(session) if len(session.steps) > 1 else summary)
        return summary

    @staticmethod
    def summarize(session) -> str:
        parts = []
        for step in session.steps:
            reply = (step.reply or step.status).strip()
            first = re.split(r"(?<=[.!?])\s+|\n", reply, maxsplit=1)[0]
            if "Reply yes to confirm" in reply:
                first = reply.replace("Reply yes to confirm, or no to cancel.", "Say yes to confirm.")
            parts.append(first)
        if len(parts) == 1:
            return session.steps[0].reply if session.steps else ""
        return " ".join(parts)


# ── Recognizer + microphone loop ─────────────────────────────────────────────

class StreamingListener:
    """Reads the microphone and feeds a StreamingSession. Run it on its own thread."""

    def __init__(self, session: StreamingSession, voice_engine=None, device_index=None,
                 end_silence: float = 1.1, model_path: Optional[Path] = None):
        self.session = session
        self.voice = voice_engine
        self.device_index = device_index
        self.end_silence = end_silence
        self.model_path = model_path or model_dir()
        self._stop = threading.Event()
        self.running = False

    def stop(self):
        self._stop.set()

    def _speaking(self) -> bool:
        return bool(self.voice is not None and getattr(self.voice, "is_speaking", False))

    def run(self):
        import pyaudio
        import vosk
        vosk.SetLogLevel(-1)
        model = vosk.Model(str(self.model_path))
        rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
        rec.SetWords(False)
        audio = pyaudio.PyAudio()
        stream = audio.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
                            frames_per_buffer=4000, input_device_index=self.device_index)
        self.running = True
        last_voice = time.time()
        pending_end = False
        last_partial = ""
        try:
            while not self._stop.is_set():
                data = stream.read(2000, exception_on_overflow=False)
                if self._speaking():
                    # Ignore our own voice; start clean afterwards.
                    rec.Reset()
                    last_partial, pending_end = "", False
                    continue
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "")
                    last_partial = ""
                    if text:
                        self.session.segment(text)
                        pending_end, last_voice = True, time.time()
                else:
                    partial = json.loads(rec.PartialResult()).get("partial", "")
                    if partial and partial != last_partial:
                        last_partial, last_voice = partial, time.time()
                        self.session.partial(partial)
                if pending_end and not last_partial and time.time() - last_voice > self.end_silence:
                    pending_end = False
                    threading.Thread(target=self.session.end_utterance, daemon=True).start()
        finally:
            self.running = False
            try:
                stream.stop_stream()
                stream.close()
                audio.terminate()
            except Exception:
                pass
