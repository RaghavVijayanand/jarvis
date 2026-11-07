"""WindowLayouts: monitor listing, window move/snap, and save/restore layouts to
a JSON file, all with win32gui/win32api/win32con mocked so these run without Windows."""
import json
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

from skills.window_layouts import WindowLayouts


class FakeWindowsControl:
    """Mimics the bits of WindowsControl that WindowLayouts reuses."""

    def __init__(self, windows):
        # windows: list of (hwnd, title)
        self._windows = windows

    def _top_windows(self):
        return list(self._windows)

    def _find(self, title):
        needle = (title or "").strip().lower()
        exact = [w for w in self._windows if w[1].lower() == needle]
        return exact or [w for w in self._windows if needle and needle in w[1].lower()]


def _fake_win32gui(rects=None):
    mod = types.ModuleType("win32gui")
    rects = rects or {}
    mod.GetWindowRect = Mock(side_effect=lambda hwnd: rects.get(hwnd, (0, 0, 100, 100)))
    mod.MoveWindow = Mock()
    mod.ShowWindow = Mock()
    mod.IsZoomed = Mock(return_value=False)
    return mod


def _fake_win32con():
    mod = types.ModuleType("win32con")
    mod.SW_MAXIMIZE = 3
    mod.SW_RESTORE = 9
    return mod


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.wl = WindowLayouts(layouts_file="/tmp/does-not-matter.json")

    def test_list_monitors_no_pywin32(self):
        with patch.dict(sys.modules, {"win32api": None}):
            self.assertIn("isn't available", self.wl.list_monitors())

    def test_list_monitors(self):
        fake_win32api = types.ModuleType("win32api")
        fake_win32api.EnumDisplayMonitors = Mock(return_value=[
            (1, None, (0, 0, 1920, 1080)), (2, None, (1920, 0, 3840, 1080)),
        ])
        with patch.dict(sys.modules, {"win32api": fake_win32api}):
            result = self.wl.list_monitors()
        self.assertIn("1920x1080", result)
        self.assertIn("(1920, 0)", result)

    def test_list_monitors_none_found(self):
        fake_win32api = types.ModuleType("win32api")
        fake_win32api.EnumDisplayMonitors = Mock(return_value=[])
        with patch.dict(sys.modules, {"win32api": fake_win32api}):
            self.assertIn("No monitors", self.wl.list_monitors())

    def test_list_monitors_error(self):
        fake_win32api = types.ModuleType("win32api")
        fake_win32api.EnumDisplayMonitors = Mock(side_effect=Exception("boom"))
        with patch.dict(sys.modules, {"win32api": fake_win32api}):
            self.assertIn("Couldn't list monitors", self.wl.list_monitors())


class MoveSnapTests(unittest.TestCase):
    def setUp(self):
        self.windows = FakeWindowsControl([(1001, "Chrome - Google"), (1002, "Notepad")])
        self.wl = WindowLayouts(self.windows, layouts_file="/tmp/does-not-matter.json")

    def test_move_window_no_match(self):
        result = self.wl.move_window("Nonexistent", 0, 0)
        self.assertIn("No window matching", result)

    def test_move_window_success(self):
        fake_gui = _fake_win32gui({1001: (10, 10, 110, 210)})
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            result = self.wl.move_window("chrome", 50, 60)
        self.assertIn("Moved 'chrome' to (50, 60)", result)
        fake_gui.MoveWindow.assert_called_once_with(1001, 50, 60, 100, 200, True)

    def test_move_window_with_size(self):
        fake_gui = _fake_win32gui()
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            self.wl.move_window("chrome", 0, 0, width=300, height=400)
        fake_gui.MoveWindow.assert_called_once_with(1001, 0, 0, 300, 400, True)

    def test_move_window_cannot_lose_the_window_off_screen(self):
        fake_api = types.ModuleType("win32api")
        fake_api.GetSystemMetrics = Mock(side_effect=lambda i: {76: 0, 77: 0, 78: 1920, 79: 1080}[i])
        fake_gui = _fake_win32gui({1001: (0, 0, 400, 300)})
        with patch.dict(sys.modules, {"win32gui": fake_gui, "win32api": fake_api}):
            self.wl.move_window("chrome", 99999, -5000)
            fake_gui.MoveWindow.assert_called_once_with(1001, 1820, 0, 400, 300, True)
            self.assertIn("too small", self.wl.move_window("chrome", 0, 0, width=0, height=300))
        fake_gui.MoveWindow.assert_called_once()

    def test_move_window_error(self):
        fake_gui = _fake_win32gui()
        fake_gui.GetWindowRect.side_effect = Exception("no window")
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            result = self.wl.move_window("chrome", 0, 0)
        self.assertIn("Couldn't move", result)

    def test_move_window_to_monitor_success(self):
        fake_win32api = types.ModuleType("win32api")
        fake_win32api.EnumDisplayMonitors = Mock(return_value=[
            (1, None, (0, 0, 1920, 1080)), (2, None, (1920, 0, 3840, 1080)),
        ])
        fake_gui = _fake_win32gui({1001: (0, 0, 100, 200)})
        with patch.dict(sys.modules, {"win32api": fake_win32api, "win32gui": fake_gui}):
            result = self.wl.move_window_to_monitor("chrome", 1)
        self.assertIn("Moved 'chrome' to monitor 1", result)
        fake_gui.MoveWindow.assert_called_once_with(1001, 1920, 0, 100, 200, True)

    def test_move_window_to_monitor_no_match(self):
        result = self.wl.move_window_to_monitor("Nonexistent", 0)
        self.assertIn("No window matching", result)

    def test_move_window_to_monitor_out_of_range(self):
        fake_win32api = types.ModuleType("win32api")
        fake_win32api.EnumDisplayMonitors = Mock(return_value=[(1, None, (0, 0, 1920, 1080))])
        with patch.dict(sys.modules, {"win32api": fake_win32api}):
            result = self.wl.move_window_to_monitor("chrome", 5)
        self.assertIn("No monitor #5", result)

    def test_snap_window_no_match(self):
        result = self.wl.snap_window("Nonexistent", "left-half")
        self.assertIn("No window matching", result)

    def test_snap_window_unknown_position(self):
        result = self.wl.snap_window("chrome", "diagonal")
        self.assertIn("Unknown snap position", result)

    def test_snap_window_left_half(self):
        fake_win32api = types.ModuleType("win32api")
        fake_win32api.MonitorFromWindow = Mock(return_value=1)
        fake_win32api.GetMonitorInfo = Mock(return_value={"Work": (0, 0, 1920, 1080)})
        fake_gui = _fake_win32gui()
        with patch.dict(sys.modules, {"win32api": fake_win32api, "win32gui": fake_gui}):
            result = self.wl.snap_window("chrome", "left half")
        self.assertIn("Snapped 'chrome' to left-half", result)
        fake_gui.MoveWindow.assert_called_once_with(1001, 0, 0, 960, 1080, True)

    def test_snap_window_error(self):
        fake_win32api = types.ModuleType("win32api")
        fake_win32api.MonitorFromWindow = Mock(side_effect=Exception("boom"))
        with patch.dict(sys.modules, {"win32api": fake_win32api}):
            result = self.wl.snap_window("chrome", "maximize")
        self.assertIn("Couldn't snap", result)


class LayoutPersistenceTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.layouts_path = f"{self.tmpdir}/window_layouts.json"
        self.windows = FakeWindowsControl([(1001, "Chrome"), (1002, "Notepad")])
        self.wl = WindowLayouts(self.windows, layouts_file=self.layouts_path)

    def test_list_layouts_empty(self):
        self.assertIn("No saved layouts", self.wl.list_layouts())

    def test_save_layout_no_windows_control(self):
        wl = WindowLayouts(None, layouts_file=self.layouts_path)
        self.assertEqual(wl.save_layout("x"), "Window control isn't available.")

    def test_save_layout_no_open_windows(self):
        wl = WindowLayouts(FakeWindowsControl([]), layouts_file=self.layouts_path)
        self.assertIn("No open windows", wl.save_layout("x"))

    def test_save_and_list_layout(self):
        fake_gui = _fake_win32gui({1001: (0, 0, 100, 200), 1002: (10, 10, 210, 310)})
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            result = self.wl.save_layout("work")
        self.assertIn("Saved the current layout as 'work' (2 window(s))", result)
        self.assertIn("work (2 window(s))", self.wl.list_layouts())

    def test_save_layout_persists_to_disk(self):
        fake_gui = _fake_win32gui({1001: (0, 0, 100, 200), 1002: (10, 10, 210, 310)})
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            self.wl.save_layout("work")
        with open(self.layouts_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("work", data)
        self.assertEqual(len(data["work"]), 2)

    def test_restore_layout_not_found(self):
        self.assertIn("No saved layout named", self.wl.restore_layout("nope"))

    def test_restore_layout_success(self):
        fake_gui = _fake_win32gui({1001: (0, 0, 100, 200), 1002: (10, 10, 210, 310)})
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            self.wl.save_layout("work")
        fake_con = _fake_win32con()
        with patch.dict(sys.modules, {"win32gui": fake_gui, "win32con": fake_con}):
            result = self.wl.restore_layout("work")
        self.assertIn("Restored 2 window(s)", result)

    def test_restore_layout_missing_window_reported(self):
        fake_gui = _fake_win32gui({1001: (0, 0, 100, 200), 1002: (10, 10, 210, 310)})
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            self.wl.save_layout("work")
        # Now simulate Notepad being closed by removing it from the fake window list.
        self.windows._windows = [(1001, "Chrome")]
        fake_con = _fake_win32con()
        with patch.dict(sys.modules, {"win32gui": fake_gui, "win32con": fake_con}):
            result = self.wl.restore_layout("work")
        self.assertIn("Restored 1 window(s)", result)
        self.assertIn("Notepad", result)

    def test_restore_layout_no_pywin32(self):
        fake_gui = _fake_win32gui({1001: (0, 0, 100, 200), 1002: (10, 10, 210, 310)})
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            self.wl.save_layout("work")
        with patch.dict(sys.modules, {"win32con": None}):
            result = self.wl.restore_layout("work")
        self.assertIn("isn't available", result)

    def test_delete_layout_not_found(self):
        self.assertIn("No saved layout named", self.wl.delete_layout("nope"))

    def test_delete_layout_success(self):
        fake_gui = _fake_win32gui({1001: (0, 0, 100, 200), 1002: (10, 10, 210, 310)})
        with patch.dict(sys.modules, {"win32gui": fake_gui}):
            self.wl.save_layout("work")
        result = self.wl.delete_layout("work")
        self.assertIn("Deleted layout 'work'", result)
        self.assertIn("No saved layouts", self.wl.list_layouts())

    def test_load_layouts_corrupt_file_returns_empty(self):
        with open(self.layouts_path, "w", encoding="utf-8") as f:
            f.write("not json")
        self.assertEqual(self.wl._load_layouts(), {})

    def test_load_layouts_non_dict_returns_empty(self):
        with open(self.layouts_path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        self.assertEqual(self.wl._load_layouts(), {})


if __name__ == "__main__":
    unittest.main()
