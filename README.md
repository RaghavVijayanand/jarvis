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

## Windows GUI (Safe)

This repo includes a safe GUI app for multi-model chat (no system-control actions).

Run the GUI:
```powershell
py -3 -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\main_gui.py
```

Add API keys in Settings (saved to `%APPDATA%\Jarvis\.env`). Available models will appear in the dropdown. Responses are stubbed until you wire real provider calls.

Build a single EXE:
```powershell
pyinstaller --noconsole --onefile --name JarvisAI --icon assets\app.ico main_gui.py
```

Create an installer with Inno Setup: open `installer.iss` and Build. Output: `dist\JarvisAI-Installer.exe`.

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
