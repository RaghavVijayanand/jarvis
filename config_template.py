# JARVIS AI Assistant Configuration Template
# Copy this file to config_user.py and fill in your API keys

# ============================================================
# API KEYS - Get these from the respective service providers
# ============================================================

# OpenRouter API Key (for multiple AI models)
# Get from: https://openrouter.ai/
OPENROUTER_API_KEY = ""

# OpenAI API Key (for GPT models)
# Get from: https://platform.openai.com/api-keys
OPENAI_API_KEY = ""

# Anthropic API Key (for Claude models)
# Get from: https://console.anthropic.com/
ANTHROPIC_API_KEY = ""

# Google Gemini API Key (for Gemini models)
# Get from: https://makersuite.google.com/app/apikey
GOOGLE_API_KEY = ""

# ============================================================
# MODEL PREFERENCES
# ============================================================

# Use multi-model brain (recommended)
USE_MULTI_MODEL = True

# Use OpenRouter as primary provider
USE_OPENROUTER = True

# Default model to use
DEFAULT_MODEL = "google/gemini-2.0-flash-exp"

# ============================================================
# VOICE SETTINGS
# ============================================================

# Enable voice recognition
VOICE_RECOGNITION_ENABLED = True

# Voice recognition settings
VOICE_ENERGY_THRESHOLD = 4000
VOICE_PAUSE_THRESHOLD = 0.8
VOICE_PHRASE_TIMEOUT = 3

# Text-to-speech settings
TTS_RATE = 200
TTS_VOLUME = 0.9

# ============================================================
# AUTOMATION SETTINGS
# ============================================================

# Enable advanced automation features
AUTOMATION_ENABLED = True

# Enable screen automation
SCREEN_AUTOMATION_ENABLED = True

# Screenshot directory
SCREENSHOT_DIR = "cache/screenshots"

# ============================================================
# SYSTEM SETTINGS
# ============================================================

# Enable system monitoring
SYSTEM_MONITORING_ENABLED = True

# Enable file operations
FILE_OPERATIONS_ENABLED = True

# Enable web scraping
WEB_SCRAPING_ENABLED = True

# Maximum file size for operations (in MB)
MAX_FILE_SIZE_MB = 100

# ============================================================
# SECURITY SETTINGS
# ============================================================

# Allow system modifications
ALLOW_SYSTEM_MODIFICATIONS = True

# Allow file deletion
ALLOW_FILE_DELETION = False

# Allow registry modifications
ALLOW_REGISTRY_MODIFICATIONS = False

# ============================================================
# LOGGING
# ============================================================

# Enable logging
LOGGING_ENABLED = True

# Log level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL = "INFO"

# Log file path
LOG_FILE = "logs/jarvis.log"

# ============================================================
# INSTRUCTIONS FOR USERS
# ============================================================

"""
To use JARVIS AI Assistant:

1. Copy this file to 'config_user.py' in the same directory
2. Fill in at least one API key above (OpenRouter recommended for best experience)
3. Adjust other settings as needed
4. Run JARVIS_AI_Assistant.exe

For OpenRouter (recommended):
- Visit https://openrouter.ai/
- Create an account and get an API key
- Set OPENROUTER_API_KEY above
- This gives you access to multiple AI models

For best experience:
- Use a good microphone for voice commands
- Ensure stable internet connection
- Run with administrator privileges for full automation features

Troubleshooting:
- If voice recognition doesn't work, check microphone permissions
- If automation fails, try running as administrator
- Check the logs/ directory for detailed error information
"""
