"""Global "press once" hotkeys (the command bar's Ctrl+Shift+Space).

Buddy mode's hold-to-talk hotkey lives in core.buddy.HoldHotkey; this is the
tap variant built on pynput.GlobalHotKeys. The callback runs on pynput's
thread, so UI code must hop to the GUI thread (a Qt signal) before touching
widgets.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from core.logging_setup import get_logger

log = get_logger("jarvis.hotkeys")

# Combos that don't collide with Windows (Alt+Space opens every window's system
# menu) or with Buddy mode's hold-Ctrl+Alt.
COMMAND_BAR_HOTKEYS: Dict[str, str] = {
    "ctrl+shift+space": "Ctrl + Shift + Space",
    "ctrl+shift+j": "Ctrl + Shift + J",
    "alt+j": "Alt + J",
    "f8": "F8",
}

# The global stop: cancels everything JARVIS is doing right now (never Ctrl+Shift+Esc,
# which opens Task Manager). Ctrl+Alt+Esc is also screen automation's emergency stop.
STOP_HOTKEYS: Dict[str, str] = {
    "ctrl+alt+esc": "Ctrl + Alt + Esc",
    "ctrl+alt+x": "Ctrl + Alt + X",
    "pause": "Pause",
}


def to_pynput(combo: str) -> str:
    """'ctrl+shift+space' → '<ctrl>+<shift>+<space>' (single letters stay bare)."""
    parts = []
    for part in (combo or "").lower().replace(" ", "").split("+"):
        if not part:
            continue
        parts.append(part if len(part) == 1 else f"<{part}>")
    return "+".join(parts)


class TapHotkey:
    def __init__(self, combo: str, callback: Callable[[], None]):
        self.combo = (combo or "ctrl+shift+space").lower()
        self.callback = callback
        self._listener = None

    def _fire(self):
        try:
            self.callback()
        except Exception:
            log.exception("hotkey callback failed")

    def start(self) -> bool:
        self.stop()          # a second start() must not orphan a still-running listener (double fires)
        try:
            from pynput import keyboard
            self._listener = keyboard.GlobalHotKeys({to_pynput(self.combo): self._fire})
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as exc:
            log.warning("global hotkey %s unavailable: %s", self.combo, exc)
            self._listener = None
            return False

    def stop(self):
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    @property
    def label(self) -> str:
        return COMMAND_BAR_HOTKEYS.get(self.combo) or STOP_HOTKEYS.get(self.combo, self.combo)
