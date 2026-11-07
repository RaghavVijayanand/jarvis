@echo off
rem Run JARVIS from source (the tray app). Use build_installer.bat for a real install.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" app.py %*
) else (
    start "" pythonw app.py %*
)
