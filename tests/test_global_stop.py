"""The global stop: one call (hotkey, button, tray, "stop") cancels all work in progress — plans,
live-voice steps, confirmations, screen automation, speech — and leaves reminders, alarms and
watchers alone. Nothing here presses real keys: pynput listeners are mocked."""
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import jarvis as jm
from core.config import Config
from core.executor import ExecutionSession
from core.streaming import StreamingSession
from tests.test_cov_jarvis import QuietCase, make_app


def blocking_step(release):
    def run(text, context):
        if text == "block":
            release.wait(5)
        return f"did {text}"
    return run


class ExecutorStopTests(unittest.TestCase):
    def test_stop_reports_running_and_queued_then_is_idempotent(self):
        release = threading.Event()
        s = ExecutionSession(blocking_step(release))
        s.submit("block")
        s.submit("after")
        for _ in range(100):
            if s.steps[0].status == "running":
                break
            time.sleep(0.01)
        self.assertEqual(s.stop(), {"running": 1, "queued": 1})
        self.assertEqual(s.stop(), {"running": 0, "queued": 0})
        release.set()
        s.close_and_wait(timeout=5)
        self.assertEqual(s.steps[0].status, "done")          # a running command finishes its call
        self.assertEqual(s.steps[1].status, "stopped")       # the queued one never starts

    def test_stop_ends_a_long_wait_and_close_and_wait_returns(self):
        s = ExecutionSession(lambda t, c: "ok")
        s.submit("", kind="wait", seconds=3000)
        time.sleep(0.05)
        started = time.time()
        s.stop()
        s.close_and_wait(timeout=5)
        self.assertLess(time.time() - started, 2)
        self.assertEqual(s.steps[0].status, "stopped")


class StopEverythingTests(QuietCase):
    def app(self):
        app = make_app()
        app.task_scheduler = Mock()
        app.watchers = Mock()
        app.screen_automation = Mock(is_running=False)
        app.voice_engine = Mock(is_speaking=False)
        return app

    def test_cancels_plan_confirmations_hooks_automation_and_speech(self):
        app = self.app()
        release = threading.Event()
        app._run_step = blocking_step(release)
        session = app.new_execution_session()
        session.submit("block")
        session.submit("then this")
        for _ in range(100):
            if session.steps[0].status == "running":
                break
            time.sleep(0.01)
        approved = Mock()
        app._ask_to_confirm("Delete it?", approved, "delete_file")
        hook = Mock(return_value=1)
        app.add_stop_hook(hook)
        app.screen_automation.is_running = True

        summary = app.stop_everything()

        self.assertEqual(summary, "Stopped 1 running step, 1 queued step, 2 pending confirmations "
                                  "and screen automation.")
        approved.assert_not_called()
        self.assertEqual(app._pending_actions, [])
        hook.assert_called_once()
        app.screen_automation.stop_automation.assert_called_once()
        app.voice_engine.stop_speaking.assert_called_once()
        self.assertTrue(app._stop_plan.is_set())
        release.set()
        session.close_and_wait(timeout=5)
        self.assertEqual(session.steps[1].status, "stopped")

    def test_reminders_alarms_and_watchers_are_left_alone(self):
        app = self.app()
        app.stop_everything()
        self.assertEqual(app.task_scheduler.mock_calls, [])
        self.assertEqual(app.watchers.mock_calls, [])

    def test_idempotent_and_nothing_running(self):
        app = self.app()
        self.assertEqual(app.stop_everything(), "Stopped. Nothing else was running.")
        self.assertEqual(app.stop_everything(), "Stopped. Nothing else was running.")
        self.assertEqual(app.stop_current_task(), "Stopped. Nothing else was running.")

    def test_concurrent_stops_never_approve_and_count_once(self):
        app = self.app()
        approved = Mock()
        for i in range(3):
            app._ask_to_confirm(f"Q{i}?", approved)
        results = []
        threads = [threading.Thread(target=lambda: results.append(app.stop_everything())) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        approved.assert_not_called()
        self.assertEqual(sum("3 pending confirmations" in r for r in results), 1)

    def test_live_voice_steps_and_spoken_question_are_cancelled(self):
        app = self.app()
        stream = StreamingSession(app, beep=False)
        stream._deferred = ["what's the weather"]
        holder = {"event": threading.Event(), "answer": True}
        stream._ask = holder
        app.stream = stream
        self.assertTrue(app.is_busy())
        summary = app.stop_everything()
        self.assertIn("1 queued step", summary)
        self.assertIn("1 pending confirmation", summary)
        self.assertTrue(holder["event"].is_set())
        self.assertFalse(holder["answer"])                    # a stop is a "no", never a "yes"
        self.assertEqual(stream._deferred, [])

    def test_a_failing_part_does_not_block_the_rest(self):
        app = self.app()
        app.screen_automation.stop_automation.side_effect = RuntimeError("boom")
        app.add_stop_hook(Mock(side_effect=RuntimeError("hook")))
        app.voice_engine.stop_speaking.side_effect = RuntimeError("tts")
        approved = Mock()
        app._ask_to_confirm("Q?", approved)
        self.assertIn("1 pending confirmation", app.stop_everything())
        approved.assert_not_called()


class StopCommandTests(QuietCase):
    def test_stop_phrases(self):
        for text in ("stop", "Stop!", "stop everything", "cancel that", "abort", "jarvis, stop", "stop it now",
                     "halt", "stop what you're doing", "cancel all tasks", "stop automation"):
            self.assertTrue(jm.JARVIS.is_stop_request(text), text)
        for text in ("stop the music", "cancel shutdown", "stop the spooler service", "stop watching downloads",
                     "abort the restart", "stopwatch", "", None):
            self.assertFalse(jm.JARVIS.is_stop_request(text), text)

    def test_stop_while_busy_stops_everything(self):
        app = make_app()
        app.voice_engine = Mock(is_speaking=False)
        app._active_session = Mock(busy=True)
        app._active_session.stop.return_value = {"running": 2, "queued": 0}
        self.assertEqual(app.process_command("cancel that", use_voice=False), "Stopped 2 running steps.")

    def test_stop_when_idle_is_not_hijacked(self):
        app = make_app()
        app.voice_engine = Mock(is_speaking=False)
        with patch.object(app, "stop_everything") as stop:
            app.process_command("stop", use_voice=False)
            app.process_command("stop the music", use_voice=False)
        stop.assert_not_called()

    def test_targeted_stop_keeps_its_route_while_busy(self):
        app = make_app()
        app.voice_engine = Mock(is_speaking=False)
        app._active_session = Mock(busy=True)
        with patch.object(app, "stop_everything") as stop:
            app.process_command("stop the music", use_voice=False)
        stop.assert_not_called()


class StopHotkeyTests(QuietCase):
    def test_install_swap_and_remove(self):
        app = make_app()
        made = []

        def fake_hotkey(combo, callback):
            hk = Mock(combo=combo, callback=callback)
            hk.start.return_value = True
            made.append(hk)
            return hk

        with patch("core.hotkeys.TapHotkey", side_effect=fake_hotkey), \
                patch.object(Config, "STOP_HOTKEY", "ctrl+alt+esc"):
            self.assertTrue(app.install_stop_hotkey())
            self.assertTrue(app.install_stop_hotkey())        # same combo: no second listener
            self.assertEqual(len(made), 1)
            with patch.object(Config, "STOP_HOTKEY", "pause"):
                app.install_stop_hotkey()
            made[0].stop.assert_called_once()
            self.assertEqual(made[1].combo, "pause")
            app.remove_stop_hotkey()
            made[1].stop.assert_called_once()

    def test_unavailable_hotkey_is_reported(self):
        app = make_app()
        with patch("core.hotkeys.TapHotkey") as cls:
            cls.return_value.start.return_value = False
            self.assertFalse(app.install_stop_hotkey())
        self.assertIsNone(app._stop_hotkey)

    def test_hotkey_stops_and_announces(self):
        app = make_app()
        app.voice_engine = Mock(is_speaking=False)
        app.notify = Mock()
        app._ask_to_confirm("Q?", Mock())
        app._stop_from_hotkey()
        app.notify.assert_called_once_with("Stopped 1 pending confirmation.")

    def test_config_accepts_only_known_combos(self):
        for raw, expected in (("PAUSE", "pause"), ("ctrl+shift+esc", "ctrl+alt+esc"), ("", "ctrl+alt+esc")):
            with patch.dict(os.environ, {"JARVIS_STOP_HOTKEY": raw}):
                Config.reload()
                self.assertEqual(Config.STOP_HOTKEY, expected, raw)
        Config.reload()


class GuiStopTests(unittest.TestCase):
    def test_open_confirm_dialogs_are_answered_no(self):
        import main_gui
        waiting = {"event": threading.Event(), "answer": True, "box": Mock()}
        done = {"event": threading.Event(), "answer": True}
        done["event"].set()
        fake = SimpleNamespace(_pending_confirms=[waiting, done])
        with patch.object(main_gui, "QMetaObject") as meta:
            cancelled = main_gui.MainWindow._cancel_open_confirms(fake)
        self.assertEqual(cancelled, 1)
        self.assertFalse(waiting["answer"])
        self.assertTrue(waiting["event"].is_set())
        self.assertTrue(done["answer"])                      # an answered dialog keeps its answer
        meta.invokeMethod.assert_called_once()

    def test_typed_stop_skips_the_busy_queue(self):
        import main_gui
        j = Mock(is_stop_request=jm.JARVIS.is_stop_request)
        j.is_busy.return_value = True
        j.stop_everything.return_value = "Stopped 1 running step."
        fake = SimpleNamespace(jarvis=j, append_text=Mock())
        self.assertEqual(main_gui.MainWindow._stop_now_if_asked(fake, "stop"), "Stopped 1 running step.")
        fake.append_text.assert_called_with("JARVIS", "Stopped 1 running step.")
        self.assertIsNone(main_gui.MainWindow._stop_now_if_asked(fake, "open notepad"))
        j.is_busy.return_value = False
        self.assertIsNone(main_gui.MainWindow._stop_now_if_asked(fake, "stop"))   # idle: normal routing

    def test_tray_has_stop_item(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from ui.tray import Tray
        tray = Tray("Ctrl+Shift+Space")
        fired = []
        tray.stop.connect(lambda: fired.append(True))
        self.assertIn(tray.act_stop, tray.menu.actions())
        tray.act_stop.trigger()
        self.assertEqual(fired, [True])


if __name__ == "__main__":
    unittest.main()
