"""WindowLayoutHandler: everything runs immediately except deleting a layout,
which confirms first."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.window_layouts import WindowLayoutHandler


class FakeApp:
    def __init__(self):
        self.window_layouts = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class WindowLayoutHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = WindowLayoutHandler(self.app)

    def test_list_monitors_runs_immediately(self):
        self.app.window_layouts.list_monitors.return_value = "0: 1920x1080 at (0, 0)"
        reply = self.h.handle("list monitors", "LAYOUT")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "0: 1920x1080 at (0, 0)")

    def test_save_layout_runs_immediately(self):
        self.app.window_layouts.save_layout.return_value = "Saved the current layout as 'work' (2 window(s))."
        reply = self.h.handle("save the current layout as work", "LAYOUT")
        self.assertFalse(self.app.pending)
        self.app.window_layouts.save_layout.assert_called_once_with("work")
        self.assertIn("Saved", reply)

    def test_list_layouts_runs_immediately(self):
        self.h.handle("list window layouts", "LAYOUT")
        self.app.window_layouts.list_layouts.assert_called_once()
        self.assertFalse(self.app.pending)

    def test_restore_layout_runs_immediately(self):
        reply_val = "Restored 2 window(s) from 'work'."
        self.app.window_layouts.restore_layout.return_value = reply_val
        reply = self.h.handle("restore layout work", "LAYOUT")
        self.assertFalse(self.app.pending)
        self.app.window_layouts.restore_layout.assert_called_once_with("work")
        self.assertEqual(reply, reply_val)

    def test_delete_layout_confirms(self):
        self.h.handle("delete layout work", "LAYOUT")
        self.assertEqual(self.app.pending[-1][0], "delete_layout")
        self.app.window_layouts.delete_layout.assert_not_called()
        self.app.pending[-1][1]()
        self.app.window_layouts.delete_layout.assert_called_once_with("work")

    def test_move_to_monitor_runs_immediately(self):
        self.h.handle("move chrome to monitor 1", "LAYOUT")
        self.assertFalse(self.app.pending)
        self.app.window_layouts.move_window_to_monitor.assert_called_once_with("chrome", 1)

    def test_snap_runs_immediately(self):
        self.h.handle("snap chrome to left-half", "LAYOUT")
        self.assertFalse(self.app.pending)
        self.app.window_layouts.snap_window.assert_called_once_with("chrome", "left-half")

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "LAYOUT"))

    def test_no_window_layouts(self):
        app = FakeApp()
        app.window_layouts = None
        h = WindowLayoutHandler(app)
        self.assertEqual(h.handle("list monitors", "LAYOUT"), "Window layout management isn't available.")

    def test_register_tools_confirm_gating(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        writes = ("delete_window_layout",)
        reads = ("list_monitors", "save_window_layout", "list_window_layouts", "restore_window_layout",
                 "move_window", "move_window_to_monitor", "snap_window")
        for name in writes:
            self.assertTrue(t.get(name).confirm, name)
        for name in reads:
            self.assertFalse(t.get(name).confirm, name)

    def test_register_tools_no_window_layouts(self):
        app = FakeApp()
        app.window_layouts = None
        h = WindowLayoutHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("list_monitors"))


if __name__ == "__main__":
    unittest.main()
