import unittest

from core.natural import tidy
from tests.test_cov_jarvis import QuietCase, make_app


class TidyTests(unittest.TestCase):
    def test_casual_requests_become_commands(self):
        cases = {
            "hi um can you like start chrome": "start chrome",
            "hey jarvis could you please fire up spotify for me": "open spotify",
            "uh launch notepad real quick": "open notepad",
            "can you get youtube up": "open youtube",
            "pull the calculator up": "open the calculator",
            "yo open whatsapp": "open whatsapp",
            "chrome please": "chrome",
            "take me to youtube": "go to youtube",
            "um, uh, set an alarm for 7 am, thanks": "set an alarm for 7 am",
            "hmm what time is it": "what time is it",
            "i wanna listen to some music on spotify": "listen to some music on spotify",
            "can i get notepad open": "open notepad",
            "i need the calculator": "open calculator",
            "i need help with my essay": "i need help with my essay",       # not an app: left for the model
            "go back to notepad": "switch to notepad",
        }
        for said, command in cases.items():
            self.assertEqual(tidy(said), command, said)

    def test_plain_commands_and_bare_words_are_untouched(self):
        for text in ("open chrome", "go to chrome", "hello", "okay", "set volume to 40"):
            self.assertEqual(tidy(text), text)

    def test_text_to_type_is_kept_verbatim(self):
        self.assertEqual(tidy("can you type thank you so much please"), "type thank you so much please")


class RoutingTests(QuietCase):
    def test_casual_open_takes_the_fast_path(self):
        app = make_app()
        app.app_control.launch_app_by_name.return_value = "Opened Chrome."
        for said in ("hi um can you like start chrome", "chrome please", "uh fire up chrome for me"):
            app.app_control.reset_mock()
            self.assertEqual(app.process_command(said, use_voice=False), "Opened Chrome.", said)
            app.app_control.launch_app_by_name.assert_called_once()


if __name__ == "__main__":
    unittest.main()
