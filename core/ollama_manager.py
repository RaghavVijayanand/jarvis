"""
OllamaManager — silently starts Ollama on app launch, pulls the local
vision model if missing, and shuts it down cleanly on exit.
"""
import os
import json
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

import requests

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.ollama")

OLLAMA_MODEL = Config.OLLAMA_VISION_MODEL or "qwen2.5vl:3b"
OLLAMA_API = Config.OLLAMA_URL

# Vision-capable model name fragments (used to tag models in brain.py)
VISION_MODEL_KEYWORDS = ("vl", "vision", "llava", "moondream", "minicpm", "phi-3.5-v")


def _api() -> str:
    """Server URL read at call time (Config.load() may run after this import)."""
    return (getattr(Config, "OLLAMA_URL", None) or OLLAMA_API or "http://localhost:11434").rstrip("/")


def _model() -> str:
    return getattr(Config, "OLLAMA_VISION_MODEL", None) or OLLAMA_MODEL


class OllamaManager:
    _instance: Optional["OllamaManager"] = None

    def __init__(self):
        self._exe       = self._find_exe()
        self._process: Optional[subprocess.Popen] = None
        self._ready     = False
        self._on_status: Optional[Callable[[str], None]] = None

    # ── singleton ─────────────────────────────────────────────────────────────
    @classmethod
    def get(cls) -> "OllamaManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── public API ────────────────────────────────────────────────────────────
    def is_installed(self) -> bool:
        return self._exe is not None

    def is_ready(self) -> bool:
        try:
            return requests.get(f"{_api()}/api/tags", timeout=2).status_code == 200
        except Exception:
            return False

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self, on_status: Callable[[str], None] = None):
        """Launch Ollama + pull model in a daemon thread. Non-blocking."""
        self._on_status = on_status
        threading.Thread(target=self._worker, daemon=True, name="OllamaManager").start()

    def stop(self):
        """Terminate the Ollama server process (and its model runners) if we spawned it."""
        proc = self._process
        if not proc:
            return
        self._process = None
        try:
            if proc.poll() is not None:
                return
            # `ollama serve` spawns runner children that hold VRAM; terminate() alone
            # (TerminateProcess on Windows) would orphan them.
            try:
                import psutil
                for child in psutil.Process(proc.pid).children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
            except Exception:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception as exc:
            log.warning("Could not stop Ollama: %s", exc)

    def list_local_models(self) -> list[dict]:
        """Return [{name, supports_vision}, ...] for every pulled model."""
        try:
            r = requests.get(f"{_api()}/api/tags", timeout=3)
            if r.status_code != 200:
                return []
            out = []
            for m in r.json().get("models", []):
                name = m.get("name", "")
                if not name:
                    continue
                vision = any(kw in name.lower() for kw in VISION_MODEL_KEYWORDS)
                out.append({"name": name, "supports_vision": vision})
            return out
        except Exception:
            return []

    # ── internal ──────────────────────────────────────────────────────────────
    def _emit(self, msg: str):
        log.info("Ollama: %s", msg)
        if self._on_status:
            try:
                self._on_status(msg)
            except Exception:
                pass

    def _find_exe(self) -> Optional[str]:
        # 1. Try PATH
        found = shutil.which("ollama")
        if found:
            return found
        # 2. Common Windows install locations
        user = os.environ.get("USERNAME", "")
        candidates = [
            rf"C:\Users\{user}\AppData\Local\Programs\Ollama\ollama.exe",
            r"C:\Program Files\Ollama\ollama.exe",
            r"C:\Program Files (x86)\Ollama\ollama.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    def _worker(self):
        if not self.is_installed():
            self._emit(
                "Ollama not found. Install from https://ollama.com to enable "
                "local AI (no API key needed)."
            )
            return

        # ── 1. Start ollama serve if not already up ────────────────────────
        if not self.is_ready():
            self._emit("Starting local Ollama server…")
            try:
                # CREATE_NO_WINDOW only exists (and is only accepted) on Windows;
                # a hard-coded 0x08000000 raises ValueError on other platforms.
                self._process = subprocess.Popen(
                    [self._exe, "serve"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as e:
                self._emit(f"Ollama failed to start: {e}")
                return

            deadline = time.monotonic() + 15      # wait up to 15 s
            while time.monotonic() < deadline:
                time.sleep(0.5)
                if self.is_ready():
                    break
                if self._process.poll() is not None:
                    self._process = None
                    self._emit("Ollama server exited during startup — skipping local AI.")
                    return
            else:
                self._emit("Ollama server did not respond — skipping local AI.")
                return

        self._emit("Ollama server ready.")

        # ── 2. Check whether our preferred model is already pulled ─────────
        existing = [m["name"] for m in self.list_local_models()]
        if existing:
            # The user already has local models; never start a surprise multi-GB download.
            self._ready = True
            self._emit(f"Local models available: {', '.join(existing[:4])}.")
            return

        # ── 3. Pull the model with progress ───────────────────────────────
        self._emit(
            f"Downloading {_model()} (~2 GB on first run). "
            "JARVIS will be fully functional in the meantime via cloud models."
        )
        self._pull_model()

    def _pull_model(self):
        model = _model()
        try:
            with requests.post(
                f"{_api()}/api/pull",
                # "model" is the current field; "name" is the deprecated alias
                # older servers still read.
                json={"model": model, "name": model, "stream": True},
                stream=True,
                timeout=(10, 600),        # connect, per-read (progress arrives often)
            ) as r:
                if r.status_code != 200:
                    self._emit(f"Model download failed: HTTP {r.status_code}")
                    return
                last_bucket = None
                succeeded = False
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("error"):
                        # e.g. {"error":"pull model manifest: file does not exist"}
                        self._emit(f"Model download failed: {data['error']}")
                        return
                    total     = data.get("total", 0)
                    completed = data.get("completed", 0)
                    status    = data.get("status", "")
                    if status == "success":
                        succeeded = True
                    if total and completed:
                        pct = min(100, int(completed / total * 100))
                        # Report each 25% band once; exact multiples of 25 are
                        # often skipped between progress lines.
                        bucket = (data.get("digest"), pct // 25)
                        if bucket != last_bucket:
                            mb_done  = completed // (1024 * 1024)
                            mb_total = total     // (1024 * 1024)
                            self._emit(
                                f"Downloading {model}: {pct}%  "
                                f"({mb_done} MB / {mb_total} MB)"
                            )
                            last_bucket = bucket
                    elif status and "pulling" not in status.lower() and status != "success":
                        self._emit(f"Ollama: {status}")

            if not succeeded:
                self._emit(f"Model download of {model} did not complete.")
                return
            self._ready = True
            self._emit(
                f"Local model '{model}' ready! "
                "GPU-accelerated vision AI is now active."
            )
        except Exception as e:
            self._emit(f"Model download failed: {e}")
