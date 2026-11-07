@echo off
rem Builds dist\JARVIS-Setup-<version>.exe - double-click this file.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
echo Installing/refreshing requirements...
"%PY%" -m pip install -q -r requirements_exe.txt || goto :fail
rem PyAudio (mic input) is attempted separately: it compiles against PortAudio and has no
rem prebuilt wheel on every Python version, so it shouldn't block everything above. See
rem SETUP_GUIDE.md if this fails - JARVIS still works without it, just no voice input.
"%PY%" -m pip install -q "PyAudio>=0.2.14" || echo    PyAudio couldn't build - continuing without it (voice input will be unavailable).
"%PY%" build\build_installer.py %* || goto :fail
echo.
echo Finished. Your installer is in the dist folder.
explorer "%~dp0dist"
pause
exit /b 0
:fail
echo.
echo The build failed - scroll up for the error.
pause
exit /b 1
