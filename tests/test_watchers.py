"""WatcherManager: background condition watchers, tested by calling the internal
check methods directly rather than sleeping through the real poll loop."""
import time
import unittest
from unittest.mock import Mock, patch

from skills.watchers import WatcherManager, _Watcher


class AddListStopTests(unittest.TestCase):
    def setUp(self):
        self.wm = WatcherManager(app=None, poll_seconds=1000)  # never actually fires during the test
        self.addCleanup(self.wm.stop)

    def test_watch_file_created_registers(self):
        result = self.wm.watch_file_created("/tmp/example.txt")
        self.assertIn("Watching for", result)
        self.assertEqual(len(self.wm._watchers), 1)

    def test_watch_download_finished_defaults_folder(self):
        result = self.wm.watch_download_finished("movie")
        self.assertIn("movie", result)
        self.assertEqual(len(self.wm._watchers), 1)

    def test_watch_process_ends_registers(self):
        with patch.object(WatcherManager, "_process_running", return_value=True):
            self.wm.watch_process_ends("notepad.exe")
        self.assertEqual(len(self.wm._watchers), 1)

    def test_process_not_running_is_refused_instead_of_firing_at_once(self):
        with patch.object(WatcherManager, "_process_running", return_value=False):
            self.assertIn("isn't running", self.wm.watch_process_ends("chorme"))
        self.assertIn("Which program", self.wm.watch_process_ends("  "))
        self.assertEqual(self.wm._watchers, {})

    def test_bad_thresholds_are_rejected(self):
        for threshold, minutes in ((-5, 1), (150, 1), (float("nan"), 1), ("abc", 1), (90, -1)):
            with self.subTest(threshold=threshold, minutes=minutes):
                self.assertNotIn("Watching", self.wm.watch_cpu_above(threshold, minutes))
                self.assertNotIn("Watching", self.wm.watch_memory_above(threshold, minutes))
        self.assertEqual(self.wm._watchers, {})

    def test_empty_targets_are_rejected(self):
        self.assertIn("Which file", self.wm.watch_file_created(""))
        self.assertIn("part of the download", self.wm.watch_download_finished(""))
        self.assertEqual(self.wm._watchers, {})

    def test_download_ignores_files_that_were_already_there(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "report-old.pdf"), "wb") as f:
                f.write(b"x")
            self.wm.watch_download_finished("report", folder=d)
            watcher = next(iter(self.wm._watchers.values()))
            self.assertFalse(self.wm._check_download_stable(watcher))
            with open(os.path.join(d, "report-new.pdf"), "wb") as f:
                f.write(b"y")
            with patch("skills.watchers.time.sleep"):
                self.assertTrue(self.wm._check_download_stable(watcher))

    def test_watcher_added_right_after_stop_still_gets_a_live_thread(self):
        wm = WatcherManager(app=None, poll_seconds=0.05)
        self.addCleanup(wm.stop)
        wm.start()
        old = wm._thread
        wm.stop()
        wm.watch_cpu_above(90, 1)
        self.assertIsNot(wm._thread, old)
        self.assertTrue(wm._thread.is_alive())
        self.assertFalse(wm._stop.is_set())

    def test_watch_cpu_above_registers(self):
        result = self.wm.watch_cpu_above(90, 2)
        self.assertIn("90", result)
        self.assertIn("2", result)

    def test_watch_memory_above_registers(self):
        result = self.wm.watch_memory_above(80)
        self.assertIn("80", result)

    def test_list_watchers_empty(self):
        self.assertIn("No active watchers", self.wm.list_watchers())

    def test_list_watchers_shows_entries(self):
        self.wm.watch_file_created("/tmp/x.txt")
        result = self.wm.list_watchers()
        self.assertIn("x.txt", result)

    def test_stop_watcher_found(self):
        wid = self.wm._add(_Watcher(id="abc", description="test thing", kind="file_exists", target="/x"))
        result = self.wm.stop_watcher(wid)
        self.assertIn("Stopped watching", result)
        self.assertEqual(len(self.wm._watchers), 0)

    def test_stop_watcher_not_found(self):
        self.assertIn("No watcher with id", self.wm.stop_watcher("nope"))

    def test_clear_watchers(self):
        self.wm.watch_file_created("/tmp/a.txt")
        self.wm.watch_file_created("/tmp/b.txt")
        result = self.wm.clear_watchers()
        self.assertIn("Cleared 2 watcher(s)", result)
        self.assertEqual(len(self.wm._watchers), 0)

    def test_start_starts_thread(self):
        self.wm.watch_file_created("/tmp/a.txt")
        self.assertTrue(self.wm._thread.is_alive())

    def test_start_twice_does_not_spawn_second_thread(self):
        self.wm.watch_file_created("/tmp/a.txt")
        first = self.wm._thread
        self.wm.start()
        self.assertIs(self.wm._thread, first)


class CheckConditionTests(unittest.TestCase):
    def setUp(self):
        self.wm = WatcherManager(app=None)

    def test_file_exists_true(self):
        watcher = _Watcher(id="1", description="x", kind="file_exists", target=__file__)
        self.assertTrue(self.wm._check_one(watcher))

    def test_file_exists_false(self):
        watcher = _Watcher(id="1", description="x", kind="file_exists", target="/no/such/file.txt")
        self.assertFalse(self.wm._check_one(watcher))

    def test_process_running_true_when_found(self):
        proc = Mock(info={"name": "chrome.exe"})
        with patch("psutil.process_iter", return_value=[proc]):
            self.assertTrue(self.wm._process_running("chrome"))

    def test_process_running_false_when_not_found(self):
        proc = Mock(info={"name": "notepad.exe"})
        with patch("psutil.process_iter", return_value=[proc]):
            self.assertFalse(self.wm._process_running("chrome"))

    def test_process_ends_fires_when_process_gone(self):
        watcher = _Watcher(id="1", description="x", kind="process_ends", target="chrome")
        with patch.object(self.wm, "_process_running", return_value=False):
            self.assertTrue(self.wm._check_one(watcher))
        with patch.object(self.wm, "_process_running", return_value=True):
            self.assertFalse(self.wm._check_one(watcher))

    def test_download_stable_no_folder(self):
        watcher = _Watcher(id="1", description="x", kind="download_stable", target="/no/such/dir/movie")
        self.assertFalse(self.wm._check_download_stable(watcher))

    def test_download_stable_no_match(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            watcher = _Watcher(id="1", description="x", kind="download_stable", target=f"{d}/movie")
            self.assertFalse(self.wm._check_download_stable(watcher))

    def test_download_stable_ignores_partial_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            open(f"{d}/movie.mp4.crdownload", "w").close()
            watcher = _Watcher(id="1", description="x", kind="download_stable", target=f"{d}/movie")
            self.assertFalse(self.wm._check_download_stable(watcher))

    def test_download_stable_true_when_size_unchanged(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/movie.mp4"
            with open(path, "w") as f:
                f.write("x" * 100)
            watcher = _Watcher(id="1", description="x", kind="download_stable", target=f"{d}/movie")
            with patch("time.sleep"):
                self.assertTrue(self.wm._check_download_stable(watcher))

    def test_cpu_percent_error_returns_zero(self):
        with patch("psutil.cpu_percent", side_effect=Exception("boom")):
            self.assertEqual(self.wm._cpu_percent(), 0.0)

    def test_mem_percent_error_returns_zero(self):
        with patch("psutil.virtual_memory", side_effect=Exception("boom")):
            self.assertEqual(self.wm._mem_percent(), 0.0)

    def test_check_sustained_requires_duration(self):
        watcher = _Watcher(id="1", description="x", kind="cpu_above", threshold=90, duration=60)
        self.assertFalse(self.wm._check_sustained(watcher, 95))  # just started, not sustained yet
        self.assertIsNotNone(watcher.above_since)

    def test_check_sustained_fires_after_duration(self):
        watcher = _Watcher(id="1", description="x", kind="cpu_above", threshold=90, duration=0.01)
        self.wm._check_sustained(watcher, 95)
        time.sleep(0.02)
        self.assertTrue(self.wm._check_sustained(watcher, 95))

    def test_check_sustained_resets_when_value_drops(self):
        watcher = _Watcher(id="1", description="x", kind="cpu_above", threshold=90, duration=60)
        self.wm._check_sustained(watcher, 95)
        self.assertIsNotNone(watcher.above_since)
        self.wm._check_sustained(watcher, 50)
        self.assertIsNone(watcher.above_since)

    def test_check_one_unknown_kind_returns_false(self):
        watcher = _Watcher(id="1", description="x", kind="nonsense")
        self.assertFalse(self.wm._check_one(watcher))


class FireTests(unittest.TestCase):
    def test_fire_calls_app_notify_and_removes_watcher(self):
        app = Mock()
        wm = WatcherManager(app=app)
        watcher = _Watcher(id="1", description="the thing happened", kind="file_exists", target="/x")
        wm._watchers["1"] = watcher
        wm._fire(watcher)
        app.notify.assert_called_once()
        self.assertIn("the thing happened", app.notify.call_args.args[0])
        self.assertNotIn("1", wm._watchers)

    def test_fire_without_app_does_not_raise(self):
        wm = WatcherManager(app=None)
        watcher = _Watcher(id="1", description="x", kind="file_exists", target="/x")
        wm._watchers["1"] = watcher
        wm._fire(watcher)  # should not raise

    def test_fire_swallows_notify_errors(self):
        app = Mock()
        app.notify.side_effect = Exception("boom")
        wm = WatcherManager(app=app)
        watcher = _Watcher(id="1", description="x", kind="file_exists", target="/x")
        wm._watchers["1"] = watcher
        wm._fire(watcher)  # should not raise

    def test_check_all_fires_ready_watchers(self):
        app = Mock()
        wm = WatcherManager(app=app)
        watcher = _Watcher(id="1", description="x", kind="file_exists", target=__file__)
        wm._watchers["1"] = watcher
        wm._check_all()
        app.notify.assert_called_once()

    def test_check_all_swallows_check_errors(self):
        wm = WatcherManager(app=None)
        watcher = _Watcher(id="1", description="x", kind="file_exists", target="/x")
        wm._watchers["1"] = watcher
        with patch.object(wm, "_check_one", side_effect=Exception("boom")):
            wm._check_all()  # should not raise


if __name__ == "__main__":
    unittest.main()
