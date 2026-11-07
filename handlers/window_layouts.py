"""Window layout management. Saving/restoring/moving/snapping windows just
repositions what's already open, so those run immediately; only deleting a
saved layout confirms first, since that loses data."""
import re

from core.tools import params
from handlers.base import Handler

_LIST_MONITORS = re.compile(r"\blist\s+monitors?\b", re.I)
_SAVE_LAYOUT = re.compile(r"^(?:please\s+)?save\s+(?:the\s+)?(?:current\s+)?(?:window\s+)?layout\s+as\s+"
                          r"(.+?)[.!?]*$", re.I)
_LIST_LAYOUTS = re.compile(r"\blist\s+(?:window\s+)?layouts\b|\bshow\s+saved\s+layouts\b", re.I)
_RESTORE_LAYOUT = re.compile(r"^(?:please\s+)?(?:restore|load)\s+(?:the\s+)?layout\s+(.+?)[.!?]*$", re.I)
_DELETE_LAYOUT = re.compile(r"^(?:please\s+)?delete\s+(?:the\s+)?layout\s+(.+?)[.!?]*$", re.I)
_MOVE_TO_MONITOR = re.compile(r"^(?:please\s+)?move\s+(.+?)\s+to\s+monitor\s+(\d+)[.!?]*$", re.I)
_SNAP = re.compile(r"^(?:please\s+)?snap\s+(.+?)\s+to\s+(?:the\s+)?([\w-]+(?:[\s-][\w]+)?)[.!?]*$", re.I)


class WindowLayoutHandler(Handler):
    intents = {"LAYOUT"}

    def handle(self, text, intent):
        app = self.app
        wl = getattr(app, "window_layouts", None)
        if wl is None:
            return "Window layout management isn't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        if _LIST_MONITORS.search(low):
            return wl.list_monitors()
        m = _SAVE_LAYOUT.match(low)
        if m:
            return wl.save_layout(m.group(1).strip())
        if _LIST_LAYOUTS.search(low):
            return wl.list_layouts()
        m = _RESTORE_LAYOUT.match(low)
        if m:
            return wl.restore_layout(m.group(1).strip())
        m = _DELETE_LAYOUT.match(low)
        if m:
            name = m.group(1).strip()
            return confirm(f"Delete the saved layout '{name}'?", lambda: wl.delete_layout(name), "delete_layout")
        m = _MOVE_TO_MONITOR.match(low)
        if m:
            title, index = m.group(1).strip(), int(m.group(2))
            return wl.move_window_to_monitor(title, index)
        m = _SNAP.match(low)
        if m:
            title, position = m.group(1).strip(), m.group(2).strip()
            return wl.snap_window(title, position)
        return None

    def register_tools(self, t):
        wl = getattr(self.app, "window_layouts", None)
        if wl is None:
            return
        t.add("list_monitors", "List connected monitors and their resolutions/positions.", wl.list_monitors)
        t.add("save_window_layout", "Save the current arrangement of open windows under a name.", wl.save_layout,
              params(["name"], name=("string", "Layout name")))
        t.add("list_window_layouts", "List saved window layouts.", wl.list_layouts)
        t.add("restore_window_layout", "Restore a saved window layout (repositions windows that are still open).",
              wl.restore_layout, params(["name"], name=("string", "Layout name")))
        t.add("delete_window_layout", "Delete a saved window layout.", wl.delete_layout,
              params(["name"], name=("string", "Layout name")),
              confirm=True, confirm_text="Delete the saved layout '{name}'?")
        t.add("move_window", "Move a window to a specific position and size.", wl.move_window,
              params(["title", "x", "y"], title=("string", "Window title (partial match)"),
                    x=("integer", "X position"), y=("integer", "Y position"),
                    width=("integer", "Width (optional)"), height=("integer", "Height (optional)")))
        t.add("move_window_to_monitor", "Move a window to a different monitor.", wl.move_window_to_monitor,
              params(["title", "monitor_index"], title=("string", "Window title (partial match)"),
                    monitor_index=("integer", "Monitor index, from 'list_monitors' (0-based)")))
        t.add("snap_window", "Snap a window to a half/quarter of its monitor, or maximize it.", wl.snap_window,
              params(["title", "position"], title=("string", "Window title (partial match)"),
                    position=("string", "left-half, right-half, top-half, bottom-half, top-left, top-right, "
                             "bottom-left, bottom-right or maximize")))
