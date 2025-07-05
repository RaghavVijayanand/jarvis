import os
import json
import requests
from pathlib import Path

# Advanced JARVIS Configuration
class Config:
    # Enhanced AI Settings - Multi-Model Support
    
    # OpenRouter Configuration
    OPENROUTER_API_KEY = "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"
    OPENROUTER_MODEL = "deepseek/deepseek-v3"  # Default to DeepSeek V3
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    USE_OPENROUTER = True
    
    # Gemini Configuration
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = "gemini-pro"
    USE_GEMINI = bool(os.getenv("GEMINI_API_KEY", ""))
    
    # Multi-Model Settings
    USE_MULTI_MODEL = True  # Enable advanced multi-model support
    DEFAULT_MODEL = "auto"  # auto, deepseek-v3, claude-3.5-sonnet, gpt-4o, gemini-pro
    
    # Model Selection Preferences
    MODEL_PREFERENCES = {
        "coding": "deepseek-coder",
        "analysis": "claude-3.5-sonnet", 
        "creative": "gpt-4o",
        "vision": "gemini-pro-vision",
        "fast": "gemini-flash",
        "free": "qwen-2.5-vl",
        "reasoning": "deepseek-v3"
    }
    
    # Web Search Settings
    SEARCH_ENGINE = "google"  # google, bing, or duckduckgo
    MAX_SEARCH_RESULTS = 5
    WEB_SCRAPE_ENABLED = True
    
    # Voice Settings
    WAKE_WORD = "jarvis"
    VOICE_RATE = 180        # Slower rate for more natural speech
    VOICE_VOLUME = 0.9
    VOICE_ID = 0
    
    # Enhanced Voice Settings for Natural Speech
    VOICE_SETTINGS = {
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
    
    # Create directories
    for directory in [LOGS_DIR, SKILLS_DIR, DATA_DIR, MEMORY_DIR, CACHE_DIR]:
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
        return ["gemini-pro", "gemini-pro-vision"] if Config.check_gemini_connection() else []
