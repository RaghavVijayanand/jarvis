# JARVIS AI Assistant - User Guide

## Table of Contents
1. [Introduction](#introduction)
2. [Features](#features)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [Voice Commands](#voice-commands)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Configuration](#advanced-configuration)
9. [Development](#development)

## Introduction

JARVIS (Just A Rather Very Intelligent System) is a sophisticated AI assistant inspired by Tony Stark's AI from Iron Man. It combines voice recognition, natural language processing, system control, and various intelligent capabilities to provide a comprehensive personal assistant experience.

## Features

### Core Capabilities
- 🎤 **Voice Recognition**: Advanced speech-to-text processing
- 🔊 **Text-to-Speech**: Natural voice synthesis with personality
- 🧠 **AI Brain**: Intelligent conversation and command processing
- 💻 **System Control**: Monitor and control your computer
- 🌐 **Web Integration**: Search and information retrieval
- 📊 **System Analytics**: Real-time system monitoring
- 🛠️ **Skill System**: Modular capabilities

### Available Skills
- **Weather**: Get weather information and forecasts
- **Web Search**: Search Google, Bing, DuckDuckGo, Wikipedia
- **System Info**: CPU, memory, disk usage, processes
- **Calculator**: Mathematical calculations
- **Utilities**: Password generation, dice rolling, jokes
- **Application Launcher**: Open applications by voice
- **Time & Date**: Current time and date information

## Installation

### Quick Setup (Windows)
1. Double-click `setup.bat` to run automatic setup
2. Follow the prompts to install dependencies
3. Run `start.bat` to launch JARVIS

### Manual Setup
1. Ensure Python 3.8+ is installed
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and configure API keys
4. Run JARVIS:
   ```bash
   python jarvis.py
   ```

### System Requirements
- **OS**: Windows 10/11, macOS, or Linux
- **Python**: 3.8 or higher
- **RAM**: 4GB minimum, 8GB recommended
- **Microphone**: For voice features
- **Internet**: For AI and web features

## Configuration

### Environment Variables (.env file)
```bash
# OpenAI API Key (for advanced AI responses)
OPENAI_API_KEY=your_openai_api_key_here

# Weather API Key (optional)
WEATHER_API_KEY=your_weather_api_key_here
```

### Basic Configuration (config.py)
- **Wake Word**: Default "hey jarvis"
- **Voice Settings**: Rate, volume, voice selection
- **AI Model**: GPT model selection
- **Personality**: Professional, helpful, subtle humor

## Usage

### Starting JARVIS

#### Option 1: Launcher (Recommended)
```bash
python launcher.py
```
- Provides GUI for easy mode selection
- Built-in test runner
- Status monitoring

#### Option 2: Direct Launch
```bash
# Voice mode (default)
python jarvis.py

# Text mode
python jarvis.py text
```

#### Option 3: Batch Files (Windows)
- `start.bat` - Interactive launcher
- `setup.bat` - Run setup

### Modes of Operation

#### Voice Mode
- Uses microphone for input
- Responds with speech
- Say "Hey JARVIS" to activate
- Natural conversation interface

#### Text Mode
- Keyboard input only
- Text responses
- Good for testing or quiet environments
- Type commands directly

## Voice Commands

### Basic Commands
- **"Hey JARVIS"** - Wake up JARVIS
- **"Sleep"** - Put JARVIS in standby mode
- **"Goodbye"** - Exit JARVIS

### System Commands
- **"System status"** - Get comprehensive system report
- **"Running processes"** - Show top CPU-using processes
- **"Disk usage"** - Show storage information
- **"What time is it?"** - Current time
- **"What's the date?"** - Current date

### Application Control
- **"Open [application]"** - Launch applications
  - "Open notepad"
  - "Open calculator"
  - "Open browser"
  - "Open file explorer"

### Information & Search
- **"Search for [query]"** - Web search
- **"Wikipedia [topic]"** - Wikipedia search
- **"Weather"** - Current weather
- **"News"** - Current headlines

### Utilities
- **"Tell me a joke"** - Random joke
- **"Calculate [expression]"** - Math calculations
- **"Flip a coin"** - Coin flip
- **"Roll dice"** - Roll dice

### Conversation
- **"How are you?"** - Status check
- **"Who are you?"** - JARVIS introduction
- **"Clear history"** - Reset conversation

## Troubleshooting

### Common Issues

#### "Microphone not detected"
- Check microphone connection
- Verify microphone permissions
- Run `python test.py` to test audio

#### "OpenAI API error"
- Check API key in `.env` file
- Verify internet connection
- JARVIS will use fallback responses without API

#### "Module not found" errors
- Run `python setup.py` to install dependencies
- Check Python version (3.8+ required)
- Try `pip install -r requirements.txt`

#### Voice recognition not working
- Speak clearly and close to microphone
- Check microphone levels in system settings
- Try adjusting energy threshold in config

#### "Permission denied" errors
- Run as administrator (Windows)
- Check file permissions
- Ensure Python has microphone access

### Debugging

#### Enable Debug Mode
Edit `config.py`:
```python
DEBUG_MODE = True
```

#### Run Tests
```bash
python test.py
```

#### Check Logs
- Logs are stored in `logs/` directory
- Check console output for errors

## Advanced Configuration

### Voice Engine Tuning
```python
# In config.py
VOICE_RATE = 200              # Speaking speed (words/minute)
VOICE_VOLUME = 0.9            # Volume (0.0 to 1.0)
ENERGY_THRESHOLD = 300        # Microphone sensitivity
RECOGNITION_TIMEOUT = 1       # Listen timeout
```

### AI Personality Customization
```python
PERSONALITY = {
    "name": "JARVIS",
    "style": "professional_helpful",
    "humor_level": "subtle",
    "formality": "respectful"
}
```

### Adding Custom Skills
1. Create new skill file in `skills/` directory
2. Implement skill class with required methods
3. Import in `jarvis.py`
4. Add command recognition logic

### Custom Wake Words
```python
WAKE_WORD = "computer"  # Change from "hey jarvis"
```

## Development

### Project Structure
```
jarvis/
├── jarvis.py           # Main JARVIS system
├── config.py           # Configuration settings
├── brain.py            # AI processing
├── voice_engine.py     # Speech recognition/synthesis
├── system_control.py   # System monitoring
├── skills/             # Modular skills
│   ├── weather.py

│   └── utility.py
├── setup.py            # Installation script
├── test.py             # Test suite
├── launcher.py         # GUI launcher
└── requirements.txt    # Dependencies
```

### Adding New Features
1. **Skills**: Add new capabilities in `skills/` directory
2. **Commands**: Extend command recognition in `jarvis.py`
3. **Voice**: Modify `voice_engine.py` for audio features
4. **AI**: Enhance `brain.py` for smarter responses

### API Integration
- OpenAI: Enhanced conversations
- Weather APIs: Real weather data
- News APIs: Current headlines
- Custom APIs: Extend functionality

### Testing
- Unit tests in `test.py`
- Manual testing with `python test.py`
- Voice testing in safe environment

## Getting Help

### Resources
- **Documentation**: This file
- **Source Code**: Well-commented Python files
- **Tests**: Run `python test.py` for diagnostics

### Support
- Check console output for error messages
- Review log files in `logs/` directory
- Ensure all dependencies are installed
- Verify microphone and permissions

---

*"Sometimes you gotta run before you can walk."* - Tony Stark

**JARVIS** - Your personal AI assistant, ready to serve.
