"""WatcherHandler: everything runs immediately (no confirm) — starting, listing,
stopping and clearing watchers only touch JARVIS's own in-memory watch list."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.watchers import WatcherHandler


class FakeApp:
    def __init__(self):
        self.watchers = Mock()


class WatcherHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = WatcherHandler(self.app)

    def test_watch_file_created(self):
        self.app.watchers.watch_file_created.return_value = "Watching for '/tmp/x.txt' to appear. (id: abc)"
        reply = self.h.handle("watch for /tmp/x.txt to appear", "WATCH")
        self.app.watchers.watch_file_created.assert_called_once_with("/tmp/x.txt")
        self.assertIn("Watching", reply)

    def test_watch_download_finished(self):
        self.h.handle("notify me when the download of movie finishes", "WATCH")
        self.app.watchers.watch_download_finished.assert_called_once_with("movie")

    def test_watch_process_ends(self):
        self.h.handle("tell me when notepad closes", "WATCH")
        self.app.watchers.watch_process_ends.assert_called_once_with("notepad")

    def test_watch_cpu_above_with_duration(self):
        self.h.handle("notify me if cpu stays above 90 for 2 minutes", "WATCH")
        self.app.watchers.watch_cpu_above.assert_called_once_with(90.0, 2.0)

    def test_watch_cpu_above_default_duration(self):
        self.h.handle("notify me if cpu is above 90", "WATCH")
        self.app.watchers.watch_cpu_above.assert_called_once_with(90.0, 1.0)

    def test_watch_memory_above(self):
        self.h.handle("notify me if memory stays above 80 for 5 minutes", "WATCH")
        self.app.watchers.watch_memory_above.assert_called_once_with(80.0, 5.0)

    def test_list_watchers(self):
        self.app.watchers.list_watchers.return_value = "• [abc] the thing happened"
        reply = self.h.handle("list watchers", "WATCH")
        self.assertIn("abc", reply)

    def test_stop_watcher(self):
        self.h.handle("stop watching abc123", "WATCH")
        self.app.watchers.stop_watcher.assert_called_once_with("abc123")

    def test_clear_watchers(self):
        self.h.handle("clear all watchers", "WATCH")
        self.app.watchers.clear_watchers.assert_called_once()

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "WATCH"))

    def test_no_watchers(self):
        app = FakeApp()
        app.watchers = None
        h = WatcherHandler(app)
        self.assertEqual(h.handle("list watchers", "WATCH"), "Watchers aren't available.")

    def test_register_tools_no_confirm(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        names = ("watch_file_created", "watch_download_finished", "watch_process_ends", "watch_cpu_above",
                 "watch_memory_above", "list_watchers", "stop_watcher", "clear_watchers")
        for name in names:
            self.assertFalse(t.get(name).confirm, name)

    def test_register_tools_no_watchers(self):
        app = FakeApp()
        app.watchers = None
        h = WatcherHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("list_watchers"))


if __name__ == "__main__":
    unittest.main()
