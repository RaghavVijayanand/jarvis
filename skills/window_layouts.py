"""Window layout management: save/restore window arrangements, snap windows to
half/quarter positions, move windows between monitors, and list monitors — built
on top of WindowsControl's window enumeration/lookup (``_top_windows``/``_find``).

None of this destroys anything (saving/restoring/moving a window just repositions
what's already open), so nothing here is confirm-gated except deleting a saved
layout, which loses data the user might want back.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.window_layouts")

_LAYOUTS_FILE = Config.DATA_DIR / "window_layouts.json"

_SNAP_POSITIONS = ("left-half", "right-half", "top-half", "bottom-half",
                  "top-left", "top-right", "bottom-left", "bottom-right", "maximize")


class WindowLayouts:
    """Save/restore window layouts, snap windows, move windows across monitors."""

    def __init__(self, windows_control=None, layouts_file=None):
        self.windows = windows_control
        self.layouts_file = Path(layouts_file) if layouts_file else _LAYOUTS_FILE

    # ── monitors ─────────────────────────────────────────────────────────────

    def list_monitors(self) -> str:
        try:
            import win32api
        except Exception:
            return "Monitor information isn't available on this platform."
        try:
            monitors = win32api.EnumDisplayMonitors()
        except Exception as exc:
            return f"Couldn't list monitors: {exc}"
        if not monitors:
            return "No monitors found."
        lines = []
        for i, entry in enumerate(monitors):
            rect = entry[2]
            left, top, right, bottom = rect
            lines.append(f"{i}: {right - left}x{bottom - top} at ({left}, {top})")
        return "\n".join(lines)

    def _monitor_rects(self) -> List[tuple]:
        import win32api
        return [entry[2] for entry in win32api.EnumDisplayMonitors()]

    # ── position / size / monitor ───────────────────────────────────────────

    def _find_hwnd(self, title: str):
        if self.windows is None:
            return None
        matches = self.windows._find(title)
        return matches[0][0] if matches else None

    def move_window(self, title: str, x: int, y: int,
                    width: Optional[int] = None, height: Optional[int] = None) -> str:
        hwnd = self._find_hwnd(title)
        if hwnd is None:
            return f"No window matching '{title}'."
        try:
            import win32gui
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w = int(width) if width is not None else right - left
            h = int(height) if height is not None else bottom - top
            if w < 50 or h < 50:
                return f"{w}×{h} is too small — the window would be impossible to find or grab."
            x, y = int(x), int(y)
            # Keep at least 100 px of it on the (multi-monitor) desktop, so it can't be lost off-screen.
            try:
                import win32api
                vx, vy = win32api.GetSystemMetrics(76), win32api.GetSystemMetrics(77)   # SM_X/YVIRTUALSCREEN
                vw, vh = win32api.GetSystemMetrics(78), win32api.GetSystemMetrics(79)   # SM_CX/CYVIRTUALSCREEN
            except Exception:
                vw = vh = 0                                   # can't tell: move as asked
            if vw > 0 and vh > 0:
                x = max(vx - w + 100, min(x, vx + vw - 100))
                y = max(vy, min(y, vy + vh - 100))            # never hide the title bar above the top
            win32gui.MoveWindow(hwnd, x, y, w, h, True)
        except Exception as exc:
            return f"Couldn't move '{title}': {exc}"
        return f"Moved '{title}' to ({x}, {y})."

    def move_window_to_monitor(self, title: str, monitor_index: int) -> str:
        hwnd = self._find_hwnd(title)
        if hwnd is None:
            return f"No window matching '{title}'."
        try:
            rects = self._monitor_rects()
        except Exception as exc:
            return f"Couldn't read monitor layout: {exc}"
        monitor_index = int(monitor_index)
        if not (0 <= monitor_index < len(rects)):
            return f"No monitor #{monitor_index}. There are {len(rects)} monitor(s), numbered from 0."
        left, top, right, bottom = rects[monitor_index]
        try:
            import win32gui
            wl, wt, wr, wb = win32gui.GetWindowRect(hwnd)
            win32gui.MoveWindow(hwnd, left, top, wr - wl, wb - wt, True)
        except Exception as exc:
            return f"Couldn't move '{title}': {exc}"
        return f"Moved '{title}' to monitor {monitor_index}."

    def snap_window(self, title: str, position: str) -> str:
        hwnd = self._find_hwnd(title)
        if hwnd is None:
            return f"No window matching '{title}'."
        key = (position or "").strip().lower().replace(" ", "-").replace("_", "-")
        if key not in _SNAP_POSITIONS:
            return f"Unknown snap position '{position}'. Try: {', '.join(_SNAP_POSITIONS)}."
        try:
            import win32api
            import win32gui
            monitor = win32api.MonitorFromWindow(hwnd)
            info = win32api.GetMonitorInfo(monitor)
            left, top, right, bottom = info["Work"]
            w, h = right - left, bottom - top
            geometry = {
                "left-half": (left, top, w // 2, h), "right-half": (left + w // 2, top, w // 2, h),
                "top-half": (left, top, w, h // 2), "bottom-half": (left, top + h // 2, w, h // 2),
                "top-left": (left, top, w // 2, h // 2), "top-right": (left + w // 2, top, w // 2, h // 2),
                "bottom-left": (left, top + h // 2, w // 2, h // 2),
                "bottom-right": (left + w // 2, top + h // 2, w // 2, h // 2),
                "maximize": (left, top, w, h),
            }
            x, y, ww, hh = geometry[key]
            win32gui.MoveWindow(hwnd, x, y, ww, hh, True)
        except Exception as exc:
            return f"Couldn't snap '{title}': {exc}"
        return f"Snapped '{title}' to {key}."

    # ── save / restore layouts ──────────────────────────────────────────────

    def save_layout(self, name: str) -> str:
        if self.windows is None:
            return "Window control isn't available."
        try:
            wins = self.windows._top_windows()
        except Exception as exc:
            return f"Couldn't read open windows: {exc}"
        if not wins:
            return "No open windows to save."
        try:
            import win32gui
            entries = []
            for hwnd, title in wins:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                entries.append({"title": title, "x": left, "y": top,
                               "width": right - left, "height": bottom - top,
                               "maximized": bool(win32gui.IsZoomed(hwnd))})
        except Exception as exc:
            return f"Couldn't read window positions: {exc}"
        layouts = self._load_layouts()
        layouts[name] = entries
        self._save_layouts(layouts)
        return f"Saved the current layout as '{name}' ({len(entries)} window(s))."

    def list_layouts(self) -> str:
        layouts = self._load_layouts()
        if not layouts:
            return "No saved layouts."
        return "\n".join(f"• {name} ({len(entries)} window(s))" for name, entries in layouts.items())

    def restore_layout(self, name: str) -> str:
        layouts = self._load_layouts()
        entries = layouts.get(name)
        if entries is None:
            return f"No saved layout named '{name}'."
        try:
            import win32con
            import win32gui
        except Exception:
            return "Window control isn't available on this platform."
        restored, missing = 0, []
        for entry in entries:
            hwnd = self._find_hwnd(entry["title"])
            if hwnd is None:
                missing.append(entry["title"])
                continue
            try:
                if entry.get("maximized"):
                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                else:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.MoveWindow(hwnd, entry["x"], entry["y"], entry["width"], entry["height"], True)
                restored += 1
            except Exception:
                missing.append(entry["title"])
        message = f"Restored {restored} window(s) from '{name}'."
        if missing:
            message += f" Not open (skipped): {', '.join(missing[:5])}."
        return message

    def delete_layout(self, name: str) -> str:
        layouts = self._load_layouts()
        if name not in layouts:
            return f"No saved layout named '{name}'."
        del layouts[name]
        self._save_layouts(layouts)
        return f"Deleted layout '{name}'."

    # ── storage ──────────────────────────────────────────────────────────────

    def _load_layouts(self) -> Dict[str, list]:
        if not self.layouts_file.exists():
            return {}
        try:
            with self.layouts_file.open(encoding="utf-8-sig") as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_layouts(self, layouts: Dict[str, list]) -> None:
        self.layouts_file.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.layouts_file.parent,
                                            delete=False) as stream:
                temp = stream.name
                json.dump(layouts, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.layouts_file)
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)
