# Build and Package (Windows)

This app provides a safe GUI for multi-model chat. No system-control features are included.

## Prerequisites
- Python 3.10 or 3.11 (64-bit)
- VS Code or terminal (PowerShell)

## 1) Create venv & install deps
```powershell
py -3 -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2) Run the GUI
```powershell
python .\main_gui.py
```

Optional: add API keys in Settings dialog. They are saved to %APPDATA%\Jarvis\.env.

## 3) Build a single EXE (no console)
```powershell
pyinstaller --noconsole --onefile --name JarvisAI --icon assets\app.ico main_gui.py
```
If you don't have an icon, remove `--icon assets\app.ico`.

The output EXE will be at `dist\JarvisAI.exe`.

## 4) Create an installer (Inno Setup)
1. Install Inno Setup from https://jrsoftware.org/isinfo.php
2. Open `installer.iss` in Inno Setup.
3. Build. The installer will be at `dist\JarvisAI-Installer.exe`.

## Troubleshooting
- If imports for PySide6 fail: `pip install PySide6`
- If antivirus flags the EXE, sign your EXE or distribute the zip.
- To reset API keys, delete `%APPDATA%\Jarvis\.env`.
