@echo off
title JARVIS AI Assistant Launcher

echo.
echo ========================================
echo   JARVIS AI Assistant
echo ========================================
echo.

REM Check if executable exists
if not exist "JARVIS_AI_Assistant.exe" (
    echo Error: JARVIS_AI_Assistant.exe not found!
    echo Please make sure you're running this from the correct directory.
    echo.
    pause
    exit /b 1
)

echo Starting JARVIS AI Assistant...
echo.

REM Launch JARVIS
start "" "JARVIS_AI_Assistant.exe"

REM Wait a moment for the application to start
timeout /t 2 /nobreak >nul

echo JARVIS has been launched!
echo.
echo If you encounter any issues:
echo - Check that you have set up API keys in config_user.py
echo - Ensure your microphone is working for voice commands
echo - Try running as Administrator for full automation features
echo.
echo Press any key to close this launcher...
pause >nul
