"""Regressions found by driving the real JARVIS with a battery of natural sentences."""
import unittest
from unittest.mock import Mock

from core.decision import DecisionEngine
from skills.command_processor import normalize_site_names, split_clauses


class SiteNameTests(unittest.TestCase):
    def test_typos_after_navigation_words_are_fixed(self):
        cases = {"go to the yputube and play rick roll": "go to the youtube and play rick roll",
                 "open you tube": "open youtube", "play despacito on youtub": "play despacito on youtube",
                 "open gogle": "open google", "open spotfy": "open spotify"}
        for text, expected in cases.items():
            self.assertEqual(normalize_site_names(text), expected)

    def test_ordinary_words_are_left_alone(self):
        for text in ["go to the store", "open the goggles folder", "open the outlook app", "open notepad",
                     "i watched it on netflix", "open settings"]:
            self.assertEqual(normalize_site_names(text), text)

    def test_user_sentence_with_typo_keeps_youtube_step_whole(self):
        clauses = split_clauses("open chrome and go to the yputube and play a video called rick roll and move to "
                                "the next video simultaneously open the alarm set the alarm for 10 am after which "
                                "open settings and change the screen resolution to 720p")
        self.assertEqual(clauses[1], ("seq", "go to the youtube and play a video called rick roll"))
        self.assertEqual([link for link, _ in clauses].count("par"), 1)
        self.assertEqual(len(clauses), 7)


class RoutingRuleTests(unittest.TestCase):
    def setUp(self):
        self.d = DecisionEngine(engine="rules")

    def intent(self, text):
        return self.d.decide(text).intent

    def test_control_phrases(self):
        for text in ["dim the screen", "brighten the display", "switch to chrome", "go back to chrome"]:
            self.assertEqual(self.intent(text), "control", text)

    def test_memory_phrases(self):
        for text in ["my name is raghav", "forget it", "forget green tea"]:
            self.assertEqual(self.intent(text), "memory", text)


class MemoryAndMathTests(unittest.TestCase):
    def test_plain_my_name_is_is_remembered_with_capitalisation(self):
        from handlers.memory import MemoryHandler
        app = Mock()
        handler = MemoryHandler(app)
        self.assertEqual(handler.handle("my name is raghav", "MEMORY"), "Noted — I'll call you Raghav.")
        self.assertEqual(handler.handle("My name is José McDonald.", "MEMORY"), "Noted — I'll call you José McDonald.")
        app.brain.memory.set_user_name.assert_called_with("José McDonald")

    def test_calculator_does_not_echo_the_question(self):
        from skills.utility import UtilitySkill
        u = UtilitySkill.__new__(UtilitySkill)
        self.assertEqual(u.calculate("what is 17 * 23"), "17 * 23 = 391")
        self.assertEqual(u.calculate("calculate 15% of 200?"), "15% of 200 = 30")


if __name__ == "__main__":
    unittest.main()
