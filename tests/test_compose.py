import unittest
from unittest.mock import Mock, patch

from core.compose import opened_app, parse
from tests.test_cov_jarvis import QuietCase, make_app

APPS = ["notepad", "word", "outlook"]


class ParseTests(unittest.TestCase):
    def test_type_it_there(self):
        r = parse("write an essay about world peace and type it there", APPS)
        self.assertEqual((r.prompt, r.app, r.here), ("Write an essay about world peace", None, True))

    def test_named_app(self):
        r = parse("Write an essay about world peace, then paste it in notepad", APPS)
        self.assertEqual((r.prompt, r.app), ("Write an essay about world peace", "notepad"))
        r = parse("draft a cover letter for a barista job in word", APPS)
        self.assertEqual((r.prompt, r.app), ("Write a cover letter for a barista job", "word"))

    def test_type_a_piece_means_generate(self):
        r = parse("type an email to my boss asking for friday off", APPS)
        self.assertEqual((r.prompt, r.here), ("Write an email to my boss asking for friday off", True))

    def test_not_compose(self):
        for text in ("write me a poem about the sea",            # chat answer, as before
                     "write an essay about peace in the world",  # "the world" isn't an app
                     "write a note and put it on my calendar",   # scheduling, not typing
                     "type hello world",                         # literal typing
                     "open notepad", "what is world peace"):
            self.assertIsNone(parse(text, APPS), text)

    def test_opened_app(self):
        self.assertEqual(opened_app("Opened Notepad."), "Notepad")
        self.assertIsNone(opened_app("Opened youtube.com in Chrome."))
        self.assertIsNone(opened_app("Opened Downloads folder."))
        self.assertIsNone(opened_app("Couldn't open it."))


class ComposeFlowTests(QuietCase):
    def make(self, windows_found=True):
        brain = Mock(current_model="m")
        brain.ask_text.return_value = "# World Peace\n\n**Peace** matters. It always has."
        app = make_app(brain=brain)
        app.windows._find.return_value = [(1, "Untitled - Notepad")] if windows_found else []
        app.windows.window_action.return_value = "Switched to 'Untitled - Notepad'."
        app.windows.type_text.return_value = "Typed 40 character(s)."
        app.app_control.launch_app_by_name.return_value = "Opened Notepad."
        return app

    def test_open_then_type_it_there(self):
        app = self.make()
        with patch("jarvis.time.sleep"):
            self.assertEqual(app.process_command("notepad", use_voice=False), "Opened Notepad.")
            reply = app.process_command("write an essay about world peace and type it there", use_voice=False)
        self.assertIn("typed them into Notepad", reply)
        app.windows.window_action.assert_called_with("Notepad", "focus")
        app.windows.type_text.assert_called_once_with("World Peace\n\nPeace matters. It always has.")   # no markdown
        self.assertEqual(app.brain.ask_text.call_args.args[0], "Write an essay about world peace")

    def test_named_app_is_opened_when_not_running(self):
        app = self.make(windows_found=False)
        with patch("jarvis.time.sleep"), patch("jarvis.time.time", side_effect=[0, 0, 100]):
            app.process_command("write a poem about rain in notepad", use_voice=False)
        app.app_control.launch_app_by_name.assert_called_once_with("notepad")

    def test_there_with_nothing_opened_and_jarvis_focused_asks(self):
        app = self.make()
        with patch.object(app, "_foreground_title", return_value="JARVIS"):
            reply = app.process_command("write an essay about cats and type it there", use_voice=False)
        self.assertIn("Which app", reply)
        app.brain.ask_text.assert_not_called()

    def test_focus_failure_leaves_text_on_clipboard(self):
        app = self.make()
        app._last_app = "Notepad"
        app.windows.window_action.return_value = "No window matching 'Notepad'."
        with patch("jarvis.time.sleep"):
            reply = app.process_command("write an essay about cats and type it there", use_voice=False)
        self.assertIn("clipboard", reply)
        app.windows.set_clipboard.assert_called_once()
        app.windows.type_text.assert_not_called()

    def test_no_model(self):
        app = make_app()
        app._last_app = "Notepad"
        self.assertIn("need an AI model", app.process_command("write an essay about cats in notepad",
                                                               use_voice=False))


if __name__ == "__main__":
    unittest.main()
