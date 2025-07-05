# JARVIS - AI Assistant

A sophisticated AI assistant inspired by Tony Stark's JARVIS from Iron Man.

## Features

- 🎤 Voice Recognition & Speech-to-Text
- 🔊 Text-to-Speech with natural voice
- 🧠 Natural Language Processing
- 💻 System Control & Monitoring
- 🌐 Web Search & Information Retrieval
- 📊 System Analytics
- 🎯 Task Automation
- 📱 Smart Home Integration Ready
- 🔒 Security Features

## Setup

1. Install Python 3.8 or higher
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your API keys:
   ```
   OPENAI_API_KEY=your_openai_api_key_here
   ```
4. Run JARVIS:
   ```bash
   python jarvis.py
   ```

## Voice Commands

- "Hey JARVIS" - Wake up command
- "What's the weather?" - Get weather information
- "Open [application]" - Launch applications
- "System status" - Get system information
- "Search for [query]" - Web search
- "Sleep" - Put JARVIS to sleep
- "Shutdown" - Close JARVIS

## Customization

You can customize JARVIS by modifying the configuration in `config.py`.

## Architecture

- `jarvis.py` - Main JARVIS system
- `voice_engine.py` - Speech recognition and TTS
- `brain.py` - AI processing and responses
- `system_control.py` - System monitoring and control
- `skills/` - Modular skill system
- `config.py` - Configuration settings

## Requirements

- Microphone for voice input
- Speakers for audio output
- Internet connection for AI features
- Windows/Mac/Linux compatible

---

*"Sometimes you gotta run before you can walk."* - Tony Stark
