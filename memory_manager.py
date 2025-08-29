import json
import time
from pathlib import Path
from typing import List, Dict, Optional

from config import Config


class ConversationMemory:
    """Lightweight persistent conversation memory stored as JSON.

    Schema per message: {"role": "user|assistant", "content": str, "timestamp": float}
    """

    def __init__(self, path: Optional[Path] = None, max_messages: int = 200):
        self.path: Path = path or (Config.MEMORY_DIR / "conversation.json")
        self.max_messages = max_messages
        self.messages: List[Dict] = []
        self._loaded = False

    def load(self) -> List[Dict]:
        if self._loaded:
            return self.messages
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    # Validate minimal schema
                    self.messages = [
                        {
                            "role": m.get("role", "user"),
                            "content": m.get("content", ""),
                            "timestamp": float(m.get("timestamp", time.time())),
                        }
                        for m in data
                        if isinstance(m, dict) and "content" in m
                    ]
                else:
                    self.messages = []
            else:
                self.messages = []
        except Exception:
            # On any parse error, start fresh
            self.messages = []
        self._loaded = True
        return self.messages

    def save(self) -> None:
        try:
            # Keep only the last max_messages
            if len(self.messages) > self.max_messages:
                self.messages = self.messages[-self.max_messages :]
            self.path.write_text(json.dumps(self.messages, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # Best-effort persistence; ignore write failures
            pass

    def append_message(self, role: str, content: str, timestamp: Optional[float] = None) -> None:
        self.load()
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": float(timestamp or time.time()),
        })
        self.save()

    def extend(self, msgs: List[Dict]) -> None:
        self.load()
        for m in msgs:
            if not isinstance(m, dict) or "content" not in m:
                continue
            role = m.get("role", "user")
            content = m.get("content", "")
            ts = float(m.get("timestamp", time.time()))
            self.messages.append({"role": role, "content": content, "timestamp": ts})
        self.save()

    def get_recent(self, n: int = 20) -> List[Dict]:
        self.load()
        return self.messages[-n:]

    def clear(self) -> None:
        self.messages = []
        try:
            if self.path.exists():
                self.path.unlink(missing_ok=True)
        except Exception:
            pass
