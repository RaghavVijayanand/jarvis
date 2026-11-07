"""Start JARVIS with Windows (per-user, no admin): HKCU\\...\\Run\\JARVIS.

The installer offers the same switch; this module lets the app's own settings
turn it on and off later. Works for the installed .exe and for source runs
(pythonw.exe app.py --tray).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "JARVIS"


def launch_command() -> str:
    """The command Windows runs at sign-in: start quietly in the tray."""
    if getattr(sys, "frozen", False):                       # the installed JARVIS.exe
        return f'"{sys.executable}" --tray'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")                   # no console window at sign-in
    interpreter = pythonw if pythonw.exists() else exe
    script = Path(__file__).resolve().parent.parent / "app.py"
    return f'"{interpreter}" "{script}" --tray'


def _winreg():
    if os.name != "nt":
        return None
    try:
        import winreg
        return winreg
    except ImportError:
        return None


def is_enabled() -> bool:
    reg = _winreg()
    if reg is None:
        return False
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            value, _ = reg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    # A value left behind by a moved/removed install points at nothing: report it as off, so the
    # switch shows the truth and turning it on rewrites a working command.
    program = _program_of(value)
    return bool(program) and Path(program).exists()


def _program_of(command) -> str:
    """'"C:\\Program Files\\JARVIS\\JARVIS.exe" --tray' → the exe path ('' if unparseable)."""
    command = str(command or "").strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        return command[1:end] if end > 1 else ""
    return command.split(" ", 1)[0]


def set_enabled(enabled: bool) -> str:
    """Turn start-with-Windows on or off. Returns a message for the user."""
    reg = _winreg()
    if reg is None:
        return "Starting with Windows is only available on Windows."
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
            if enabled:
                reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, launch_command())
                return "JARVIS will start when you sign in to Windows."
            try:
                reg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
            return "JARVIS won't start with Windows any more."
    except OSError as exc:
        return f"Couldn't change the startup setting: {exc}"
