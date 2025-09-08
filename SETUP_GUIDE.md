# JARVIS AI Assistant - Setup Guide

## Quick Start (for users who receive the executable)

### Option 1: Simple Run
1. Extract all files to a folder (e.g., `C:\JARVIS\`)
2. Copy `config_template.py` to `config_user.py`
3. Edit `config_user.py` and add your API keys
4. Double-click `JARVIS_AI_Assistant.exe`

### Option 2: System Installation
1. Right-click `install_jarvis.bat` and select "Run as Administrator"
2. Follow the installation prompts
3. Use the desktop shortcut to launch JARVIS

## API Key Setup (Required)

JARVIS needs at least one API key to function. Here are your options:

### OpenRouter (Recommended - gives access to multiple AI models)
1. Visit https://openrouter.ai/
2. Sign up for an account
3. Go to "Keys" and create a new API key
4. Add it to `config_user.py`: `OPENROUTER_API_KEY = "your_key_here"`

### Google Gemini (Free tier available)
1. Visit https://makersuite.google.com/app/apikey
2. Create a Google account if needed
3. Generate an API key
4. Add it to `config_user.py`: `GOOGLE_API_KEY = "your_key_here"`

### OpenAI (Paid service)
1. Visit https://platform.openai.com/api-keys
2. Create an account and add billing
3. Generate an API key
4. Add it to `config_user.py`: `OPENAI_API_KEY = "your_key_here"`

## Features Overview

### Voice Commands
- "Hey JARVIS" or just start speaking
- "Open calculator"
- "What's the weather?"
- "Take a screenshot"
- "Search for Python tutorials"

### Automation
- "Open Word and type today's date"
- "Launch Chrome and go to YouTube"
- "Take a screenshot and analyze it"
- "Find and click the save button"

### System Control
- "Show system information"
- "What processes are running?"
- "Check disk usage"
- "Monitor system performance"

### File Management
- "Create a new document"
- "List files in downloads"
- "Copy file to desktop"
- "Find files containing 'project'"

## Troubleshooting

### Voice Recognition Issues
- Check microphone permissions in Windows Settings
- Ensure microphone is not muted
- Try adjusting voice energy threshold in config

### Application Launch Failures
- Try running as Administrator
- Check Windows Defender/antivirus exclusions
- Verify API keys are correctly set

### Automation Not Working
- Run JARVIS as Administrator for full system access
- Check that target applications are installed
- Some security software may block automation

### Network/API Issues
- Verify internet connection
- Check API key validity
- Some corporate networks may block AI APIs

## System Requirements

- Windows 10/11 (64-bit)
- 4GB+ RAM (8GB recommended)
- Internet connection for AI features
- Microphone for voice commands (optional)
- Administrator privileges for full automation

## File Structure

```
JARVIS/
├── JARVIS_AI_Assistant.exe  # Main application
├── config_template.py       # Configuration template
├── config_user.py          # Your configuration (create this)
├── launcher.bat            # Simple launcher script
├── install_jarvis.bat      # System installer
└── README.txt             # Basic instructions
```

## Advanced Configuration

Edit `config_user.py` to customize:

- Voice recognition sensitivity
- Default AI model
- Automation permissions
- Logging settings
- Security restrictions

## Privacy & Security

- JARVIS processes voice locally using Windows Speech Recognition
- Text commands are sent to your chosen AI provider
- No data is stored on external servers by JARVIS itself
- Screen automation requires appropriate permissions
- Review API provider privacy policies

## Support

For issues, feature requests, or questions:
- Check the troubleshooting section above
- Review the logs in the `logs/` directory
- Ensure you're using the latest version

## License

This software is provided as-is. Use responsibly and in accordance with the terms of service of your chosen AI providers.
