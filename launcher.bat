@echo off
setlocal
title JARVIS
set "JARVIS_EXE=%~dp0dist\JARVIS\JARVIS.exe"
if exist "%~dp0JARVIS.exe" set "JARVIS_EXE=%~dp0JARVIS.exe"
if not exist "%JARVIS_EXE%" (
    echo JARVIS.exe was not found. Run build_installer.bat first, or start_jarvis_gui.bat to run from source.
    exit /b 1
)
start "" "%JARVIS_EXE%" %*
endlocal
