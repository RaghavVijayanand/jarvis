"""Long-term user memory (name, facts, preferences).

Facts are captured three ways (audit UC 10.1):
  * explicit requests — "remember that …", "note that …";
  * clear patterns — "my name is …", "I live in …";
  * the local decision model (Laya), when loaded, flags other lasting personal
    statements ("I'm allergic to peanuts", "I prefer email over calls").
Everything is visible and editable (UC 10.3): ``list_facts``, ``forget``,
``forget_all`` and the GUI Memory dialog use the same store.
"""
import json
import re
import threading
from datetime import datetime
from typing import Callable, List, Optional

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.memory")

# Words that can follow "I am"/"I'm" but are not names.
# "I'm from work", "I live in fear", "I moved to the kitchen" are not places. Voice text is
# lower-case, so capitalisation can't tell; a place never starts with one of these words.
_NOT_PLACES = {
    "the", "a", "an", "my", "your", "his", "her", "our", "their", "this", "that", "work", "home", "school",
    "college", "uni", "university", "office", "fear", "hope", "love", "peace", "denial", "here", "there",
    "now", "today", "bed", "town", "it", "a lot", "pain", "debt", "hiding",
}

_NOT_NAMES = {
    "a", "an", "the", "not", "so", "very", "just", "going", "doing", "fine", "good", "ok", "okay",
    "here", "there", "back", "home", "sure", "sorry", "happy", "sad", "tired", "busy", "ready",
    "done", "in", "at", "from", "on", "looking", "trying", "working", "thinking", "feeling", "still",
    "also", "really", "gonna", "about", "curious", "interested", "new", "sick", "hungry", "late",
    "afraid", "glad", "excited", "bored", "confused", "sure", "free", "available", "awake", "leaving",
    # Nationalities / groups, capitalised in English but not names ("I'm Indian").
    "indian", "american", "british", "english", "canadian", "australian", "german", "french",
    "chinese", "japanese", "korean", "italian", "spanish", "mexican", "russian", "african",
    "european", "asian", "irish", "scottish", "welsh", "dutch", "brazilian", "pakistani",
    "tamil", "hindu", "muslim", "jewish", "buddhist", "sikh", "catholic", "vegan", "vegetarian",
}


class MemoryManager:
    MAX_FACTS = 100
    # Class-level so instances created with __new__ (tests) work too. Guards
    # the in-memory store and the tmp-file rename (GUI + voice threads).
    _lock = threading.RLock()
    fact_detector: Optional[Callable[[str], Optional[float]]] = None

    def __init__(self):
        self.memory_file = Config.MEMORY_DIR / "memory.json"
        self.memory = self._load()
        # Optional: Callable[[str], Optional[float]] returning P(personal fact).
        self.fact_detector: Optional[Callable[[str], Optional[float]]] = None

    def _load(self):
        if self.memory_file.exists():
            try:
                data = json.loads(self.memory_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("memory.json is not an object")
                return self._sanitize(data)
            except Exception as exc:
                # Keep the unreadable file for recovery instead of silently losing it.
                backup = self.memory_file.with_suffix(".corrupt.json")
                try:
                    self.memory_file.replace(backup)
                except OSError:
                    pass
                log.error("memory.json was unreadable (%s); moved to %s", exc, backup)
        return {"user_name": None, "facts": [], "preferences": {}}

    @staticmethod
    def _sanitize(data: dict) -> dict:
        """Drop malformed entries so one bad hand edit can't break every lookup."""
        facts = data.get("facts")
        data["facts"] = [f for f in (facts if isinstance(facts, list) else [])
                         if isinstance(f, dict) and isinstance(f.get("fact"), str) and f["fact"].strip()]
        if not isinstance(data.get("preferences"), dict):
            data["preferences"] = {}
        name = data.get("user_name")
        data["user_name"] = name.strip() if isinstance(name, str) and name.strip() else None
        return data

    def _save(self):
        with self._lock:
            try:
                Config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
                tmp = self.memory_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.memory, indent=2, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.memory_file)
            except OSError as exc:
                # Disk full / locked by antivirus: keep running with the in-memory copy.
                log.error("Could not save memory.json: %s", exc)

    # ── Writing ──────────────────────────────────────────────────────────────

    def remember_fact(self, fact: str) -> bool:
        normalized = (fact or "").strip().strip("\"'").rstrip(".!?").strip()
        if not normalized or len(normalized) > 500:
            return False
        with self._lock:
            facts = self.memory.setdefault("facts", [])
            if any(f["fact"].casefold() == normalized.casefold() for f in facts):
                return False
            facts.append({"fact": normalized, "date": datetime.now().strftime("%Y-%m-%d")})
            del facts[:-self.MAX_FACTS]
            self._save()
        return True

    def set_user_name(self, name: str):
        with self._lock:
            self.memory["user_name"] = (name or "").strip() or None
            self._save()

    def set_preference(self, key: str, value: str):
        if key == "location":
            from core.config import save_location_preference
            save_location_preference(value)
            return
        with self._lock:
            self.memory.setdefault("preferences", {})[key] = value
            self._save()

    # ── Reading / editing ────────────────────────────────────────────────────

    def list_facts(self) -> List[str]:
        return [f["fact"] for f in self.memory.get("facts", [])]

    def summary(self) -> str:
        from core.config import get_location_preference
        lines = []
        if self.memory.get("user_name"):
            lines.append(f"Name: {self.memory['user_name']}")
        location = get_location_preference()
        if location:
            lines.append(f"Location: {location}")
        for key, value in self.memory.get("preferences", {}).items():
            if key != "location":
                lines.append(f"Preference — {key}: {value}")
        facts = self.list_facts()
        if facts:
            lines.append("Facts:")
            lines.extend(f"  {i}. {fact}" for i, fact in enumerate(facts, 1))
        return "\n".join(lines) if lines else "I don't have anything stored about you yet."

    def forget(self, text_or_index) -> int:
        """Forget facts matching text (substring, case-insensitive) or a 1-based index."""
        with self._lock:
            facts = self.memory.setdefault("facts", [])
            before = len(facts)
            if isinstance(text_or_index, int) or (isinstance(text_or_index, str) and text_or_index.strip().isdigit()):
                idx = int(text_or_index) - 1
                if 0 <= idx < len(facts):
                    facts.pop(idx)
            else:
                needle = str(text_or_index).strip().casefold()
                if not needle:   # "" is a substring of everything: never wipe all facts
                    return 0
                if needle in ("my name", "name") and self.memory.get("user_name"):
                    self.memory["user_name"] = None
                    self._save()
                    return 1
                facts[:] = [f for f in facts if needle not in f["fact"].casefold()]
            removed = before - len(facts)
            if removed:
                self._save()
            return removed

    def forget_all(self) -> None:
        with self._lock:
            self.memory = {"user_name": None, "facts": [], "preferences": {}}
            self._save()

    def get_context_string(self) -> str:
        lines = []
        if self.memory.get("user_name"):
            lines.append(f"The user's name is {self.memory['user_name']}.")
        # Legacy memory.json location is deliberately not a fallback: clearing
        # Settings must not resurrect an old city from a second store.
        from core.config import get_location_preference
        location = get_location_preference()
        if location:
            lines.append(f"User location: {location}.")
        prefs = {k: v for k, v in self.memory.get("preferences", {}).items() if k != "location"}
        if prefs:
            lines.append("User preferences: " + ", ".join(f"{k}={v}" for k, v in prefs.items()) + ".")
        facts = self.memory.get("facts", [])[-15:]
        if facts:
            lines.append("Remember about this user: " + "; ".join(f["fact"] for f in facts) + ".")
        return " ".join(lines)

    # ── Extraction ───────────────────────────────────────────────────────────

    def extract_from_message(self, message: str) -> bool:
        """Parse a user message for facts worth remembering. Returns True if anything was stored."""
        if not message or len(message) > 400:
            return False
        stored = False

        message = message.replace("\u2019", "'")   # curly apostrophes from phones/autocorrect

        # Explicit memory request wins and is stored verbatim. It must be a
        # request at the start of a clause ("remember that…", "Jarvis, please
        # remember…", "can you remember…"), not a question such as "do you
        # remember my birthday?" or "what do you remember about me".
        m = re.search(r"(?:^|[,.!?;:]\s*)\s*(?:(?:hey|hi|ok|okay|also|and|oh|so|jarvis)\b[,\s]+)*(?:please\s+)?"
                      r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
                      r"(?:remember that|remember|note that|keep in mind that|don'?t forget that)\s+(.+)",
                      message, re.IGNORECASE)
        if m and not re.match(r"\s*(?:to|when|where|what|how|who|why|which|whether|if|me|us|about|"
                              r"anything|everything|this|it)\b", m.group(1), re.I):
            return self.remember_fact(m.group(1)) or True

        # Name: the name itself must be capitalised (case-sensitive), so
        # "I'm going home" is never stored as a name.
        # Unicode-aware ("José", "Zoë"): letters only, first letter uppercase.
        m = re.search(r"\b(?:[Mm]y name is|[Cc]all me|I am|I'm|i'm)\s+([^\W\d_]+(?:\s+[^\W\d_]+)?)", message)
        if m:
            words = []
            for word in m.group(1).split():
                if not (word[0].isupper() and (len(word) == 1 or not word[1:].isupper())):
                    break
                words.append(word)
            if words and words[0].lower() not in _NOT_NAMES and len(words[0]) > 1:
                if len(words) > 1 and words[1].lower() in _NOT_NAMES:
                    words = words[:1]
                self.set_user_name(" ".join(words))
                stored = True

        # Location
        m = re.search(r"\b(?:i live in|i'm based in|i am based in|i'm from|i am from|i moved to)\s+"
                      r"([^\W\d_][\w .'-]{1,40}?(?:,\s*[^\W\d_][\w .'-]{1,40})?)\s*(?:[.!?]|$)",
                      message, re.IGNORECASE)
        if m and m.group(1).split()[0].lower().strip(",") not in _NOT_PLACES:
            self.set_preference("location", m.group(1).strip())
            stored = True

        # Anything else that reads like a lasting personal statement.
        if not stored and self.fact_detector and re.match(r"\s*(?:i'm|i am|i've|i|my)\b", message, re.I):
            try:
                p = self.fact_detector(message)
            except Exception:
                p = None
            if p is not None and p >= 0.7:
                stored = self.remember_fact(message)
        return stored
