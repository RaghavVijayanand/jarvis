"""Central logging for JARVIS (audit UC 12.5 / 12.6).

Everything logs through the standard ``logging`` module to a rotating file in
the per-user data folder, so failures that used to be swallowed by bare
``except: pass`` blocks leave a trace the user (or a bug report) can find.
"""
import logging
import logging.handlers
import os
from pathlib import Path

_CONFIGURED = False


def log_dir() -> Path:
    base = Path(os.getenv("APPDATA", str(Path.home()))) / "Jarvis" / "logs"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base


def setup_logging(level: int = logging.INFO) -> Path:
    """Configure root logging once. Returns the log file path."""
    global _CONFIGURED
    path = log_dir() / "jarvis.log"
    if _CONFIGURED:
        return path
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError:
        # Read-only profile: keep going with console logging only.
        pass
    # Quiet noisy third-party loggers.
    for noisy in ("urllib3", "httpx", "httpcore", "comtypes", "PIL", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
    return path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
