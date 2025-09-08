import os
import json
import requests
from pathlib import Path

# Try to load user configuration first
try:
    from config_user import *
    print("✅ Loaded user configuration from config_user.py")
except ImportError:
    print("ℹ️  No user configuration found. Using default settings.")
    # Default configuration values will be set below

# Lightweight .env loader/saver for GUI settings (stored in %APPDATA%/Jarvis/.env on Windows)
from pathlib import Path as _Path

APPDATA_DIR = _Path(os.getenv("APPDATA", str(_Path.home()))) / "Jarvis"
ENV_PATH = APPDATA_DIR / ".env"

def load_env():
    try:
        from dotenv import load_dotenv
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        load_dotenv(dotenv_path=str(ENV_PATH), override=True)
        
        # Set default location to Chennai if not specified
        if not os.getenv("JARVIS_LOCATION"):
            os.environ["JARVIS_LOCATION"] = "Chennai, India"
            
    except Exception:
        # Best-effort load; ignore if dotenv not available
        # Set default location
        os.environ.setdefault("JARVIS_LOCATION", "Chennai, India")

def save_api_keys(openrouter_key: str | None, gemini_key: str | None):
    """Persist API keys to the per-user .env and set process env vars.

    This doesn't validate keys; it only stores them.
    """
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = ""
    if ENV_PATH.exists():
        try:
            existing = ENV_PATH.read_text(encoding="utf-8")
        except Exception:
            existing = ""

    def replace_line(text: str, var: str, value: str | None) -> str:
        lines = text.splitlines(True)
        lines = [ln for ln in lines if not ln.startswith(f"{var}=")]
        if value is not None and value != "":
            lines.append(f"{var}={value}\n")
        return "".join(lines)

    updated = existing
    if openrouter_key is not None:
        updated = replace_line(updated, "OPENROUTER_API_KEY", openrouter_key)
        os.environ["OPENROUTER_API_KEY"] = openrouter_key
    if gemini_key is not None:
        updated = replace_line(updated, "GEMINI_API_KEY", gemini_key)
        os.environ["GEMINI_API_KEY"] = gemini_key

    try:
        ENV_PATH.write_text(updated, encoding="utf-8")
    except Exception:
        # Ignore write errors silently
        pass

# Load env early so Config sees vars
load_env()

# Advanced JARVIS Configuration
class Config:
    # Enhanced AI Settings - Multi-Model Support
    
    # OpenRouter Configuration
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL = "openai/gpt-4o-mini"  # Use GPT-4o Mini - reliable and fast
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    USE_OPENROUTER = bool(OPENROUTER_API_KEY)
    
    # Vision Configuration
    VISION_PROVIDER = "openrouter"  # Use OpenRouter for vision tasks
    VISION_MODEL = "openai/gpt-4o"  # High-quality vision model for accurate UI automation
    
    # Gemini Configuration (direct Gemini optional; OpenRouter preferred)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = "gemini-1.5-flash"  # Official Gemini API model name format
    USE_GEMINI = bool(GEMINI_API_KEY)
    # Vision availability (OpenRouter or direct Gemini)
    USE_VISION = bool(OPENROUTER_API_KEY or GEMINI_API_KEY)
    
    # Multi-Model Settings
    USE_MULTI_MODEL = True  # Enable advanced multi-model support
    DEFAULT_MODEL = "auto"  # auto, deepseek-v3, claude-3.5-sonnet, gpt-4o, gemini-pro
    
    # Model Selection Preferences
    MODEL_PREFERENCES = {
        "coding": "deepseek-coder",
        "analysis": "claude-3.5-sonnet", 
        "creative": "gpt-4o",
        "vision": "qwen/qwen-2.5-vl-7b-instruct",  # Free vision model
        "fast": "qwen/qwen-2.5-vl-7b-instruct",
        "free": "qwen/qwen-2.5-vl-7b-instruct",
        "reasoning": "deepseek-v3"
    }
    
    # Web Search Settings
    SEARCH_ENGINE = "google"  # google, bing, or duckduckgo
    MAX_SEARCH_RESULTS = 5
    WEB_SCRAPE_ENABLED = True
    
    # Voice Settings
    WAKE_WORD = "jarvis"
    
    # Screen Automation Settings
    SCREEN_AUTOMATION_ENABLED = True
    # Use absolute screenshot path based on BASE_DIR
    AUTOMATION_SCREENSHOT_PATH = str((Path(__file__).parent / "cache" / "screenshots").resolve())
    AUTOMATION_CONFIRMATION_REQUIRED = True
    AUTOMATION_SAFE_MODE = True
    AUTOMATION_VISION_PROVIDER = "openrouter"  # Use OpenRouter for vision
    AUTOMATION_VISION_MODEL = "openai/gpt-4o"  # High-quality vision model for automation
    AUTOMATION_CONFIDENCE_THRESHOLD = 0.7
    AUTOMATION_MAX_RETRIES = 3
    AUTOMATION_ACTION_DELAY = 1.0
    VOICE_RATE = 180        # Slower rate for more natural speech
    VOICE_VOLUME = 0.9
    VOICE_ID = 0
    
    # Enhanced Voice Settings for Natural Speech
    VOICE_SETTINGS = {
        "enabled": True,
        "rate": 180,           # Slower rate (default 200 is too fast)
        "volume": 0.9,
        "pitch": 50,           # Mid-range pitch
        "inflection": True,    # Add natural inflection
        "pause_duration": 0.3, # Short pauses between sentences
        "emphasis": True       # Emphasize important words
    }
    
    # System Settings
    DEBUG_MODE = True
    LOG_CONVERSATIONS = True
    
    # Advanced Features
    FEATURES = {
        
        "file_management": True,
        "email_integration": True,
        "system_control": True,
        "smart_home": True,
        "voice_recognition": True,
        "natural_language": True,
        "task_automation": True,
        "real_time_data": True,
        "learning": True
    }
    
    # Personality Settings
    PERSONALITY = {
        "name": "JARVIS",
        "style": "sophisticated_british",
        "humor_level": "dry_wit",
        "formality": "professional_but_warm",
        "intelligence_level": "genius",
        "loyalty": "absolute"
    }
    
    # Skills Configuration
    ENABLED_SKILLS = [
        
        "system_monitoring", 
        "file_operations",
        "email_management",
        "calendar_integration",
        "news_analysis",
        "weather_intelligence",
        "task_automation",
        "smart_calculations",
        "code_assistance",
        "research_assistant",
        "personal_assistant"
    ]
    
    # Security Settings
    SECURITY = {
        "require_confirmation": ["file_delete", "system_shutdown", "email_send"],
        "restricted_paths": ["/System", "/Windows/System32"],
        "max_file_size": "100MB",
        "allowed_extensions": [".txt", ".md", ".py", ".js", ".json", ".csv"]
    }
    
    # Paths
    BASE_DIR = Path(__file__).parent
    LOGS_DIR = BASE_DIR / "logs"
    SKILLS_DIR = BASE_DIR / "skills"
    DATA_DIR = BASE_DIR / "data"
    MEMORY_DIR = BASE_DIR / "memory"
    CACHE_DIR = BASE_DIR / "cache"
    
    # Create directories (also ensure screenshots dir exists)
    SCREENSHOTS_DIR = Path(AUTOMATION_SCREENSHOT_PATH)
    for directory in [LOGS_DIR, SKILLS_DIR, DATA_DIR, MEMORY_DIR, CACHE_DIR, SCREENSHOTS_DIR]:
        directory.mkdir(exist_ok=True)
    
    # API Keys (environment variables)
    BRAVE_API_KEY = os.getenv('BRAVE_API_KEY', '')
    WEATHER_API_KEY = os.getenv('WEATHER_API_KEY', '')
    NEWS_API_KEY = os.getenv('NEWS_API_KEY', '')
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')
    GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID', '')
    
    @staticmethod
    def check_gemini_connection():
        """Check if Gemini API key is available"""
        return bool(Config.GEMINI_API_KEY)
    
    @staticmethod
    def get_available_models():
        """Get available Gemini models"""
        return [
            "gemini-1.5-flash",
            "gemini-1.5-pro"
        ] if Config.check_gemini_connection() else []
