"""JARVIS configuration.

All user-changeable settings live in one per-user ``.env`` file
(``%APPDATA%\\Jarvis\\.env`` on Windows, ``~/Jarvis/.env`` elsewhere). The
Settings dialog writes it; ``Config.reload()`` re-reads it at runtime. User
data (memory, chat history, schedules, logs, screenshots) is stored next to it,
never inside the program folder, so a packaged/installed EXE keeps working.
"""
import math
import os
import shutil
from pathlib import Path


def _status_print(message: str) -> None:
    """Print status without crashing on consoles that can't encode emoji."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"))


APPDATA_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "Jarvis"
ENV_PATH = APPDATA_DIR / ".env"

# Program folder (read-only in an installed build).
BASE_DIR = Path(__file__).resolve().parent.parent


def load_env() -> None:
    """Load the per-user .env into os.environ (best effort)."""
    try:
        from dotenv import load_dotenv
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        load_dotenv(dotenv_path=str(ENV_PATH), override=True)
        # No location default is injected: unset JARVIS_LOCATION means
        # "auto-detect" (audit UC 10.4).
    except Exception as exc:  # pragma: no cover - dotenv missing/corrupt
        _status_print(f"Could not load settings from {ENV_PATH}: {exc}")


def save_setting(key: str, value) -> None:
    """Persist one setting to the per-user .env and publish it to os.environ.

    ``None`` or an empty string removes the key. Errors propagate so the UI
    never claims a failed save succeeded.
    """
    from dotenv import set_key, unset_key
    value = "" if value is None else str(value).strip()
    if any(ch in value for ch in ("\r", "\n", "\x00")):
        raise ValueError(f"{key} must be a single line.")
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    if value:
        set_key(str(ENV_PATH), key, value, quote_mode="always")
        os.environ[key] = value
    else:
        if ENV_PATH.exists():
            unset_key(str(ENV_PATH), key)
        os.environ.pop(key, None)


def get_location_preference() -> str:
    """The shared location preference used by Settings, memory and weather."""
    return os.getenv("JARVIS_LOCATION", "").strip()


def save_location_preference(location) -> None:
    """Persist first, then publish the preference. Empty means auto-detect."""
    location = (location or "").strip()
    if any(char in location for char in ("\r", "\n", "\x00")):
        raise ValueError("Location must be a single line.")
    save_setting("JARVIS_LOCATION", location)


def save_api_keys(openrouter_key=None, gemini_key=None) -> None:
    """Persist API keys. ``None`` leaves a key unchanged; ``""`` removes it."""
    if openrouter_key is not None:
        save_setting("OPENROUTER_API_KEY", openrouter_key)
    if gemini_key is not None:
        save_setting("GEMINI_API_KEY", gemini_key)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if math.isfinite(value) else default      # 'nan' / 'inf' would slip past min/max clamps


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, "") or default))
    except (ValueError, OverflowError):     # 'abc', 'nan', 'inf'
        return default


def _migrate_legacy_file(old: Path, new: Path) -> None:
    """Copy data that older versions kept in the program folder, once."""
    try:
        if old.exists() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)
    except OSError:
        pass


load_env()


class Config:
    """Runtime settings. Call ``Config.reload()`` after the .env changes."""

    # ── Paths ────────────────────────────────────────────────────────────────
    BASE_DIR = BASE_DIR
    USER_DIR = APPDATA_DIR
    LOGS_DIR = APPDATA_DIR / "logs"
    DATA_DIR = APPDATA_DIR / "data"
    MEMORY_DIR = APPDATA_DIR / "memory"
    CACHE_DIR = APPDATA_DIR / "cache"
    SCREENSHOTS_DIR = CACHE_DIR / "screenshots"
    AUTOMATION_SCREENSHOT_PATH = str(SCREENSHOTS_DIR)
    MODELS_DIR = APPDATA_DIR / "models"
    PLUGINS_DIR = APPDATA_DIR / "plugins"

    # ── Endpoints ────────────────────────────────────────────────────────────
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
    OLLAMA_URL = "http://localhost:11434"

    # ── Values populated by reload() ────────────────────────────────────────
    OPENROUTER_API_KEY = ""
    GEMINI_API_KEY = ""
    USE_OPENROUTER = False
    USE_GEMINI = False
    USE_VISION = False
    DEFAULT_MODEL = ""
    LOCAL_ONLY = False
    REQUEST_TIMEOUT = 45

    # Decision model (Laya, local)
    DECISION_ENGINE = "laya"          # "laya" or "rules"
    LAYA_MODEL = "english"            # "english" or "multilingual"
    LAYA_REPO = "convaiinnovations/laya"
    DECISION_THRESHOLD = 0.45         # below this, the decision is treated as unsure

    # Voice
    WAKE_WORD = "jarvis"
    TTS_ENGINE = "kokoro"             # "kokoro" (neural, local), "edge" (neural, online) or "sapi" (offline)
    EDGE_TTS_VOICE = "en-GB-RyanNeural"
    KOKORO_VOICE = "bm_george"        # see core.local_speech.KOKORO_VOICES
    KOKORO_SPEED = 1.0
    STT_ENGINE = "whisper"            # "whisper" (local) or "google" (online)
    WHISPER_GPU_MODEL = "distil-whisper/distil-large-v3.5"   # NVIDIA GPU, via the bundled PyTorch
    WHISPER_CPU_MODEL = "small.en"    # no GPU: faster-whisper, int8
    VOICE_RATE = 180
    VOICE_VOLUME = 0.9
    VOICE_SETTINGS = {"enabled": True, "rate": 180, "volume": 0.9}
    VOSK_MODEL_PATH = ""              # optional explicit Vosk model folder
    VOSK_MODEL_NAME = "vosk-model-en-in-0.5"   # downloaded to MODELS_DIR on first live-voice use
    LIVE_VOICE = True                 # act while the user is still speaking (needs vosk)
    ACT_MODE = "clause"               # "clause" (mid-sentence) or "pause" (at each short pause)
    BUDDY_ENABLED = True              # Clicky-style cursor buddy with a push-to-talk hotkey
    BUDDY_HOTKEY = "ctrl+alt"         # hold to talk; see core.buddy.HOTKEYS
    COMMAND_BAR_HOTKEY = "ctrl+shift+space"   # opens the floating command bar; see core.hotkeys
    CONVERSATION_HOTKEY = "f8"        # starts / ends hands-free conversation mode (core.conversation)
    ONBOARDED = False                 # the first-run welcome has been completed

    # Safety / automation
    AUTOMATION_SAFE_MODE = True
    AUTOMATION_CONFIRMATION_REQUIRED = True
    AUTOMATION_VISION_PROVIDER = "auto"  # auto | openrouter | gemini | ollama
    AUTOMATION_VISION_MODEL = ""
    OLLAMA_VISION_MODEL = "qwen2.5vl:3b"
    OLLAMA_AUTOSTART = True
    AUTOMATION_CONFIDENCE_THRESHOLD = 0.6
    AUTOMATION_MAX_STEPS = 8
    AUTOMATION_ACTION_DELAY = 0.8
    SCREEN_AUTOMATION_ENABLED = True

    # Misc
    SEARCH_ENGINE = "google"
    MAX_SEARCH_RESULTS = 5
    DEBUG_MODE = False
    BRAVE_API_KEY = ""
    WEATHER_API_KEY = ""
    NEWS_API_KEY = ""

    # Destructive actions always require an explicit "yes".
    CONFIRM_ACTIONS = ("shutdown", "restart", "sign_out", "sleep", "kill_process",
                       "close_app", "delete_file", "empty_recycle_bin", "uninstall_app")

    @classmethod
    def reload(cls) -> None:
        """Re-read every setting from the environment / .env."""
        cls.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
        cls.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
        cls.USE_OPENROUTER = bool(cls.OPENROUTER_API_KEY)
        cls.USE_GEMINI = bool(cls.GEMINI_API_KEY)
        cls.USE_VISION = bool(cls.OPENROUTER_API_KEY or cls.GEMINI_API_KEY)
        cls.DEFAULT_MODEL = os.getenv("JARVIS_DEFAULT_MODEL", "").strip()
        cls.LOCAL_ONLY = _env_bool("JARVIS_LOCAL_ONLY", False)   # only Ollama models: nothing goes to the cloud
        cls.OLLAMA_URL = os.getenv("JARVIS_OLLAMA_URL", "http://localhost:11434").rstrip("/")
        cls.REQUEST_TIMEOUT = _env_int("JARVIS_REQUEST_TIMEOUT", 45)

        engine = os.getenv("JARVIS_DECISION_ENGINE", "laya").strip().lower()
        cls.DECISION_ENGINE = engine if engine in ("laya", "rules") else "laya"
        laya_model = os.getenv("JARVIS_LAYA_MODEL", "english").strip().lower()
        cls.LAYA_MODEL = laya_model if laya_model in ("english", "multilingual") else "english"
        cls.DECISION_THRESHOLD = min(0.95, max(0.05, _env_float("JARVIS_DECISION_THRESHOLD", 0.45)))

        cls.WAKE_WORD = (os.getenv("JARVIS_WAKE_WORD", "jarvis").strip().lower() or "jarvis")
        tts = os.getenv("JARVIS_TTS_ENGINE", "kokoro").strip().lower()
        cls.TTS_ENGINE = tts if tts in ("kokoro", "edge", "sapi") else "kokoro"
        cls.KOKORO_VOICE = os.getenv("JARVIS_KOKORO_VOICE", "bm_george").strip() or "bm_george"
        cls.KOKORO_SPEED = min(1.5, max(0.6, _env_float("JARVIS_KOKORO_SPEED", 1.0)))
        stt = os.getenv("JARVIS_STT_ENGINE", "whisper").strip().lower()
        cls.STT_ENGINE = stt if stt in ("whisper", "google") else "whisper"
        cls.WHISPER_GPU_MODEL = os.getenv("JARVIS_WHISPER_GPU_MODEL", "distil-whisper/distil-large-v3.5").strip() \
            or "distil-whisper/distil-large-v3.5"
        cls.WHISPER_CPU_MODEL = os.getenv("JARVIS_WHISPER_CPU_MODEL", "small.en").strip() or "small.en"
        cls.EDGE_TTS_VOICE = os.getenv("JARVIS_VOICE", "en-GB-RyanNeural").strip() or "en-GB-RyanNeural"
        cls.VOICE_RATE = _env_int("JARVIS_VOICE_RATE", 180)
        cls.VOICE_VOLUME = min(1.0, max(0.0, _env_float("JARVIS_VOICE_VOLUME", 0.9)))
        cls.VOICE_SETTINGS = {"enabled": True, "rate": cls.VOICE_RATE, "volume": cls.VOICE_VOLUME}
        cls.VOSK_MODEL_PATH = os.getenv("JARVIS_VOSK_MODEL", "").strip()
        cls.VOSK_MODEL_NAME = os.getenv("JARVIS_VOSK_MODEL_NAME", "vosk-model-en-in-0.5").strip() or "vosk-model-en-in-0.5"
        cls.LIVE_VOICE = _env_bool("JARVIS_LIVE_VOICE", True)
        mode = os.getenv("JARVIS_ACT_MODE", "clause").strip().lower()
        cls.ACT_MODE = mode if mode in ("clause", "pause") else "clause"
        cls.BUDDY_ENABLED = _env_bool("JARVIS_BUDDY", True)
        hotkey = os.getenv("JARVIS_BUDDY_HOTKEY", "ctrl+alt").strip().lower()
        cls.BUDDY_HOTKEY = hotkey if hotkey in ("ctrl+alt", "right ctrl", "ctrl+shift", "ctrl+win", "f9") else "ctrl+alt"
        bar = os.getenv("JARVIS_COMMAND_BAR_HOTKEY", "ctrl+shift+space").strip().lower()
        cls.COMMAND_BAR_HOTKEY = bar if bar in ("ctrl+shift+space", "ctrl+shift+j", "alt+j", "f8") else "ctrl+shift+space"
        talk = os.getenv("JARVIS_CONVERSATION_HOTKEY", "f8").strip().lower()
        cls.CONVERSATION_HOTKEY = talk if talk in ("f8", "f7", "f10", "ctrl+shift+t") else "f8"
        cls.ONBOARDED = _env_bool("JARVIS_ONBOARDED", False)

        cls.AUTOMATION_SAFE_MODE = _env_bool("JARVIS_SAFE_MODE", True)
        cls.AUTOMATION_CONFIRMATION_REQUIRED = _env_bool("JARVIS_CONFIRM_ACTIONS", True)
        provider = os.getenv("JARVIS_VISION_PROVIDER", "auto").strip().lower()
        cls.AUTOMATION_VISION_PROVIDER = provider if provider in (
            "auto", "openrouter", "gemini", "ollama") else "auto"
        cls.AUTOMATION_VISION_MODEL = os.getenv("JARVIS_VISION_MODEL", "").strip()
        cls.OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b").strip() or "qwen2.5vl:3b"
        cls.OLLAMA_AUTOSTART = _env_bool("JARVIS_OLLAMA_AUTOSTART", True)
        cls.DEBUG_MODE = _env_bool("JARVIS_DEBUG", False)

        cls.BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
        cls.WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
        cls.NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

    @classmethod
    def ensure_dirs(cls) -> None:
        for directory in (cls.USER_DIR, cls.LOGS_DIR, cls.DATA_DIR, cls.MEMORY_DIR,
                          cls.CACHE_DIR, cls.SCREENSHOTS_DIR, cls.MODELS_DIR):
            try:
                Path(directory).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _status_print(f"Cannot create {directory}: {exc}")
        # One-time migration from the old in-program-folder locations.
        _migrate_legacy_file(BASE_DIR / "memory" / "memory.json", cls.MEMORY_DIR / "memory.json")
        _migrate_legacy_file(BASE_DIR / "logs" / "conversation_history.json",
                             cls.LOGS_DIR / "conversation_history.json")

    @staticmethod
    def check_gemini_connection() -> bool:
        return bool(Config.GEMINI_API_KEY)


Config.reload()
Config.ensure_dirs()
