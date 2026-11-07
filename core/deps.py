"""Friendly, actionable messages for optional third-party packages that aren't installed.

JARVIS works without any of these — voice, buddy mode and now-playing degrade
gracefully — but when a feature can't run because a package is missing, the
message the person sees should say exactly what to type, not just repeat
Python's ModuleNotFoundError text.
"""
from __future__ import annotations

# module name (as Python reports it in ModuleNotFoundError.name) -> pip install argument(s) and,
# for the packages that are notoriously fussy to build on Windows, a fallback command.
PACKAGE_HINTS = {
    "pyaudio": ("PyAudio", "if that fails to build: pip install pipwin && pipwin install pyaudio"),
    "vosk": ("vosk", ""),
    "winsdk": ("winsdk", ""),
    "pycaw": ("pycaw", ""),
    "wmi": ("WMI", ""),
    "win32gui": ("pywin32", "then run: python Scripts/pywin32_postinstall.py -install"),
    "win32com": ("pywin32", "then run: python Scripts/pywin32_postinstall.py -install"),
    "winshell": ("winshell", ""),
    "send2trash": ("send2trash", ""),
    "speech_recognition": ("SpeechRecognition", ""),
    "edge_tts": ("edge-tts", ""),
    "pyttsx3": ("pyttsx3", ""),
    "pypdf": ("pypdf", ""),
    "docx": ("python-docx", ""),
}


def missing_package_message(exc: Exception, feature: str) -> str:
    """"No module named 'pyaudio'" + "The microphone" -> a message with the actual install command.

    Falls back to str(exc) for anything that isn't a plain missing-module error, so callers can use
    this uniformly without checking the exception type themselves."""
    name = getattr(exc, "name", None)
    if not name or not isinstance(exc, ModuleNotFoundError):
        return f"{feature}: {exc}"
    pip_name, extra = PACKAGE_HINTS.get(name, (name, ""))
    message = f"{feature} needs the '{name}' package, which isn't installed. Install it with: pip install {pip_name}"
    return f"{message}  ({extra})" if extra else message
