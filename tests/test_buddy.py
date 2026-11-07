"""Buddy mode (Clicky-style cursor companion): logic, hotkey, controller, overlay."""
import json
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import core.buddy as buddy


class FakeSA:
    """Just enough of ScreenAutomationSkill for guide(): a 1000x500 model image on a 2000x1000 screen."""

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def take_screenshot(self):
        return "shot.png"

    def _model_image(self, shot):
        return "shot_model.jpg", 1000, 500

    def _ask_vision(self, prompt, img):
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    from skills.screen_automation import ScreenAutomationSkill as _S
    _point_from = staticmethod(_S._point_from)

    def _to_screen(self, x, y, w, h):
        return int(x * 2), int(y * 2)


class GuideQuestionTests(unittest.TestCase):
    def test_questions_about_the_screen(self):
        for text in ["where is the export button", "Where's the save icon?", "how do I change my wallpaper",
                     "show me where the settings are", "what is this error", "what's on my screen",
                     "which button do I press", "I can't find the bluetooth toggle", "walk me through this form",
                     "jarvis, point to the refresh button", "what do I click next"]:
            self.assertTrue(buddy.is_guide_question(text), text)

    def test_commands_and_other_questions(self):
        for text in ["open settings", "set volume to 40", "what time is it", "play rick roll",
                     "open chrome and go to youtube", "tell me a joke", ""]:
            self.assertFalse(buddy.is_guide_question(text), text)


class GuideTests(unittest.TestCase):
    def test_points_are_mapped_to_screen_pixels(self):
        sa = FakeSA('```json\n{"answer": "Click File, then Export.", "points": ['
                    '{"x": 10, "y": 20, "label": "File menu"}, {"box_2d": [100, 200, 300, 400], "label": "Export"}]}\n```')
        g = buddy.guide(sa, 'where is "export"?')
        self.assertEqual(g.answer, "Click File, then Export.")
        self.assertEqual([(p.x, p.y, p.label) for p in g.points], [(20, 40, "File menu"), (600, 200, "Export")])
        self.assertIn("1000x500", sa.prompts[0])
        self.assertIn("where is 'export'?", sa.prompts[0])       # quotes can't break the prompt

    def test_bad_points_are_skipped_and_capped(self):
        points = [{"x": i, "y": i} for i in range(9)] + ["junk", {"label": "no coords"}, {"x": "a", "y": 1}]
        g = buddy.guide(FakeSA(json.dumps({"answer": "", "points": points})), "where")
        self.assertEqual(len(g.points), 5)
        self.assertEqual(g.answer, "Here you go.")
        single = buddy.guide(FakeSA('{"answer": "There.", "points": {"x": 1, "y": 2}}'), "where")
        self.assertEqual([(p.x, p.y) for p in single.points], [(2, 4)])

    def test_plain_text_reply_and_failures(self):
        self.assertEqual(buddy.guide(FakeSA("It's the blue button at the top."), "where").answer,
                         "It's the blue button at the top.")
        self.assertIn("couldn't look", buddy.guide(FakeSA(RuntimeError("No vision model")), "where").answer)
        self.assertIn("isn't available", buddy.guide(None, "where").answer)
        self.assertIn("another way", buddy.guide(FakeSA(""), "where").answer)


class HotkeyTests(unittest.TestCase):
    def key(self, name):
        return SimpleNamespace(name=name, char=None)

    def make(self, combo):
        self.events = []
        return buddy.HoldHotkey(combo, lambda: self.events.append("down"), lambda: self.events.append("up"))

    def test_hold_ctrl_alt(self):
        hk = self.make("ctrl+alt")
        hk.press(self.key("ctrl_l"))
        self.assertEqual(self.events, [])
        hk.press(self.key("alt_l"))
        hk.press(self.key("alt_l"))                     # key repeat while held: no second "down"
        self.assertEqual(self.events, ["down"])
        hk.release(self.key("alt_l"))
        self.assertEqual(self.events, ["down", "up"])
        hk.release(self.key("ctrl_l"))
        self.assertEqual(self.events, ["down", "up"])

    def test_altgr_typing_does_not_trigger(self):
        hk = self.make("ctrl+alt")
        hk.press(self.key("ctrl_l"))                    # Windows sends Ctrl + AltGr for ₹ / €
        hk.press(self.key("alt_gr"))
        self.assertEqual(self.events, [])

    def test_other_combos(self):
        hk = self.make("right ctrl")
        hk.press(self.key("ctrl_l"))
        self.assertEqual(self.events, [])
        hk.press(self.key("ctrl_r"))
        hk.release(self.key("ctrl_r"))
        self.assertEqual(self.events, ["down", "up"])
        hk = self.make("f9")
        hk.press(SimpleNamespace(name="f9"))
        self.assertEqual(self.events, ["down"])
        hk = self.make("ctrl+win")
        hk.press(self.key("ctrl_r"))
        hk.press(self.key("cmd"))
        self.assertEqual(self.events, ["down"])

    def test_restart_replaces_listener_and_forgets_stuck_keys(self):
        hk = self.make("ctrl+alt")
        listeners = []
        keyboard = Mock()
        keyboard.Listener.side_effect = lambda **kw: listeners.append(Mock()) or listeners[-1]
        with patch.dict("sys.modules", {"pynput": Mock(keyboard=keyboard), "pynput.keyboard": keyboard}):
            self.assertTrue(hk.start())
            hk.press(self.key("ctrl_l"))               # its release is lost (e.g. the PC was locked)
            self.assertTrue(hk.start())
        listeners[0].stop.assert_called_once()         # the first listener didn't leak
        hk.press(self.key("alt_l"))                    # Alt alone is not Ctrl+Alt
        self.assertEqual(self.events, [])

    def test_callback_errors_are_contained_and_start_failure_reported(self):
        hk = buddy.HoldHotkey("f9", Mock(side_effect=RuntimeError), Mock())
        hk.press(SimpleNamespace(name="f9"))            # must not raise into pynput's thread
        with patch.dict("sys.modules", {"pynput": None}):
            self.assertFalse(hk.start())
        hk.stop()


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        # these cover the fallbacks after local Whisper (tested in test_local_speech)
        patcher = patch("core.local_speech.transcribe", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_whisper_first(self):
        with patch("core.local_speech.transcribe", return_value=" open settings ") as whisper:
            self.assertEqual(buddy.transcribe(b"\1" * 32000), "open settings")
        whisper.assert_called_once()

    def test_taps_are_ignored(self):
        self.assertEqual(buddy.transcribe(b"\0" * 100), "")

    def test_google_fallback(self):
        fake_sr = Mock()
        fake_sr.Recognizer.return_value.recognize_google.return_value = " where is the export button "
        with patch("core.streaming.vosk_available", return_value=False), \
                patch.dict("sys.modules", {"speech_recognition": fake_sr}):
            self.assertEqual(buddy.transcribe(b"\0" * 32000), "where is the export button")
        fake_sr.Recognizer.return_value.recognize_google.side_effect = RuntimeError("offline")
        with patch("core.streaming.vosk_available", return_value=False), \
                patch.dict("sys.modules", {"speech_recognition": fake_sr}):
            self.assertEqual(buddy.transcribe(b"\0" * 32000), "")

    def test_local_only_never_calls_google(self):
        fake_sr = Mock()
        fake_sr.Recognizer.return_value.recognize_google.return_value = "leaked"
        with patch.object(buddy.Config, "LOCAL_ONLY", True), \
                patch("core.streaming.vosk_available", return_value=False), \
                patch.dict("sys.modules", {"speech_recognition": fake_sr}):
            self.assertEqual(buddy.transcribe(b"\0" * 32000), "")
        fake_sr.Recognizer.return_value.recognize_google.assert_not_called()

    def test_vosk_used_when_model_is_ready(self):
        fake_vosk = Mock()
        fake_vosk.KaldiRecognizer.return_value.FinalResult.return_value = '{"text": "open settings"}'
        buddy._VOSK_CACHE.clear()
        with patch("core.streaming.vosk_available", return_value=True), \
                patch("core.streaming.model_ready", return_value=True), \
                patch.dict("sys.modules", {"vosk": fake_vosk}):
            self.assertEqual(buddy.transcribe(b"\0" * 32000), "open settings")
            buddy.transcribe(b"\0" * 32000)
        fake_vosk.Model.assert_called_once()           # the big model is loaded once
        buddy._VOSK_CACHE.clear()


class RecorderTests(unittest.TestCase):
    def test_records_until_stopped(self):
        stream = Mock()
        stream.read.side_effect = lambda n, exception_on_overflow=False: (time.sleep(0.005), b"\1\2")[1]
        pa = Mock()
        pa.PyAudio.return_value.open.return_value = stream
        with patch.dict("sys.modules", {"pyaudio": pa}):
            rec = buddy.Recorder()
            rec.start()
            time.sleep(0.05)
            audio = rec.stop()
        self.assertTrue(audio and set(audio) <= {1, 2})
        stream.close.assert_called_once()

    def test_microphone_error_is_raised_on_stop(self):
        pa = Mock()
        pa.PyAudio.return_value.open.side_effect = OSError("no mic")
        with patch.dict("sys.modules", {"pyaudio": pa}):
            rec = buddy.Recorder()
            rec.start()
            with self.assertRaisesRegex(RuntimeError, "no mic"):
                rec.stop()

    def test_missing_pyaudio_gives_an_install_hint(self):
        with patch.dict("sys.modules", {"pyaudio": None}):          # None makes the import raise
            rec = buddy.Recorder()
            rec.start()
            with self.assertRaisesRegex(RuntimeError, r"pip install PyAudio"):
                rec.stop()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.jarvis = Mock()
        self.jarvis.process_command.return_value = "Opened Settings."
        self.recorder = Mock()
        self.recorder.stop.return_value = b"audio"
        self.heard = "open settings"
        self.c = buddy.BuddyController(self.jarvis, on_state=lambda k, i: self.events.append((k, i)),
                                       hotkey="f9", recorder=self.recorder, transcriber=lambda a: self.heard)

    def kinds(self):
        return [k for k, _ in self.events]

    def run_turn(self):
        self.c.begin()
        self.c.finish()
        deadline = time.time() + 3
        while "idle" not in self.kinds()[2:] and time.time() < deadline:
            time.sleep(0.01)

    def test_command_is_done_and_spoken(self):
        self.run_turn()
        self.jarvis.voice_engine.stop_speaking.assert_called_once()        # talking interrupts the buddy
        self.jarvis.process_command.assert_called_once_with("open settings", use_voice=False)
        self.assertEqual(self.kinds(), ["listening", "thinking", "heard", "answer", "idle"])
        self.jarvis.voice_engine.speak.assert_called_once_with("Opened Settings.", summarize=True)

    def test_guide_question_points(self):
        self.heard = "where is the export button"
        with patch.object(buddy, "guide", return_value=buddy.Guidance("Top right.", [buddy.Point(5, 6, "Export")])):
            self.run_turn()
        self.jarvis.process_command.assert_not_called()
        point = dict(self.events)["point"]
        self.assertEqual(point["points"], [(5, 6, "Export")])
        self.assertIn("answer", self.kinds())

    def test_nothing_heard(self):
        self.heard = ""
        self.run_turn()
        self.assertEqual(self.events[-1], ("idle", {"message": "I didn't catch that."}))
        self.jarvis.process_command.assert_not_called()

    def test_mic_failure_and_double_events(self):
        self.c.finish()                                  # release without press: ignored
        self.recorder.stop.side_effect = RuntimeError("microphone error: busy")
        self.c.begin()
        self.c.begin()                                   # key repeat: recording starts once
        self.recorder.start.assert_called_once()
        self.c.finish()
        self.assertEqual(self.events[-1][0], "error")

    def test_typed_ask_does_not_speak_and_errors_are_friendly(self):
        result = self.c.ask("open settings", speak=False)
        self.assertEqual(result.answer, "Opened Settings.")
        self.jarvis.voice_engine.speak.assert_not_called()
        self.jarvis.process_command.side_effect = RuntimeError("boom")
        self.assertIn("Something went wrong", self.c.ask("open settings", speak=False).answer)

    def test_start_and_stop(self):
        with patch.object(self.c.hotkey, "start", return_value=True):
            self.assertTrue(self.c.start())
        self.assertEqual(self.events[-1], ("idle", {"hotkey": "Hold F9", "ready": True}))
        self.c.begin()
        self.c.stop()
        self.recorder.stop.assert_called()


class JarvisRoutingTests(unittest.TestCase):
    def test_typed_guide_question_uses_the_buddy(self):
        from tests.test_audit_regressions import bare_jarvis
        app, module = bare_jarvis()
        from core.decision import DecisionEngine
        from skills.command_processor import CommandProcessor
        app.decision = DecisionEngine(engine="rules")
        app.command_processor = CommandProcessor(app)
        app.brain = None
        app.file_skill = None
        app.buddy = Mock()
        app.buddy.ask.return_value = buddy.Guidance("It's the gear icon, top right.")
        with patch.object(module, "console"):
            reply = app.process_command("where is the settings button", use_voice=False)
            self.assertEqual(reply, "It's the gear icon, top right.")
            app.buddy.ask.assert_called_once_with("where is the settings button", speak=False)
            app.buddy = None
            self.assertNotEqual(app.process_command("where is the settings button", use_voice=False),
                                "It's the gear icon, top right.")


try:
    import PySide6  # noqa: F401
    _HAS_QT = True
except ImportError:
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT and (os.environ.get("QT_QPA_PLATFORM") == "offscreen" or os.environ.get("DISPLAY")),
                     "needs PySide6 and a Qt platform")
class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qapp = QApplication.instance() or QApplication([])

    def test_states_and_painting(self):
        from ui.buddy_overlay import BuddyOverlay, physical_to_logical
        overlay = BuddyOverlay()
        overlay.show()
        try:
            for kind, info in [("idle", {"hotkey": "Hold Ctrl + Alt", "ready": True}), ("listening", {}),
                               ("thinking", {}), ("heard", {"text": "where is export"}),
                               ("point", {"points": [(100, 100, "File"), (300, 200, "Export"), (5000, 5000, "")]}),
                               ("answer", {"text": "Click File, then Export. " * 10}), ("error", {"message": "x"}),
                               ("idle", {})]:
                overlay.set_state(kind, info)
                overlay._points_since -= 5              # skip the arrow flight animation
                image = overlay.grab()                  # runs paintEvent for real
                self.assertFalse(image.isNull())
            self.assertEqual(overlay.state, "idle")
            self.assertEqual(len(overlay._points), 3)
            overlay._points_until = 0
            overlay._tick()
            self.assertEqual(overlay._points, [])
            self.assertIsInstance(physical_to_logical(10, 10).x(), int)
            overlay.clear()
        finally:
            overlay.close()

    def test_overlay_never_takes_input(self):
        from PySide6.QtCore import Qt
        from ui.buddy_overlay import BuddyOverlay
        overlay = BuddyOverlay()
        try:
            self.assertTrue(overlay.windowFlags() & Qt.WindowTransparentForInput)
            self.assertTrue(overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
            self.assertTrue(overlay.windowFlags() & Qt.WindowStaysOnTopHint)
        finally:
            overlay.close()


if __name__ == "__main__":
    unittest.main()
