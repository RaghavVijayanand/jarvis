"""Screen automation edge cases: bad model coordinates, hidden risky targets, focus changes,
stop during a confirmation, runaway loops and leftover screenshots. Fake desktop only."""
import os
from unittest.mock import patch

import skills.screen_automation as sa
from skills.screen_automation import ScreenAutomationSkill
from tests.test_cov_screen import Base


class CoordinateTests(Base):
    def test_points_off_the_screenshot_are_rejected_not_clamped(self):
        for action in ({"type": "click", "x": 5000, "y": 10}, {"type": "click", "x": -40, "y": 10},
                       {"type": "click", "x": "nan", "y": 10}, {"type": "click", "x": "inf", "y": 10},
                       {"type": "click", "box_2d": [1500, 1500, 2000, 2000]}):
            with self.subTest(action=action):
                self.assertEqual(self.skill.execute_action(action, (400, 300)),
                                 (False, "coordinates outside the screenshot"))
        self.assertEqual(self.gui.named("click"), [])
        # a point a hair past the edge (model rounding) is still fine
        self.assertTrue(self.skill.execute_action({"type": "click", "x": 403, "y": 150}, (400, 300))[0])

    def test_direct_screen_points_must_be_on_the_screen(self):
        for x, y in ((900, 10), (10, -1), (-5, -5)):
            self.assertEqual(self.skill.execute_action({"type": "click", "x": x, "y": y}),
                             (False, "coordinates outside the screen"))
        self.assertEqual(self.gui.named("click"), [])

    def test_find_element_off_image_or_junk_confidence_does_not_click(self):
        self.script('{"found": true, "x": 9000, "y": 5, "confidence": 0.9}',
                    '{"found": true, "x": 50, "y": 50, "confidence": "nan"}',
                    '{"found": true, "x": 50, "y": 50, "confidence": "high"}',
                    '{"found": true, "x": null, "y": 50}')
        self.assertIn("Could not find", self.skill.find_and_click_element("a")["message"])
        self.assertIn("not confident", self.skill.find_and_click_element("b")["message"])
        self.assertIn("not confident", self.skill.find_and_click_element("c")["message"])
        self.assertIn("Could not find", self.skill.find_and_click_element("d")["message"])
        self.assertEqual(self.gui.named("click"), [])


class RiskTests(Base):
    def test_visible_label_counts_even_when_target_is_vague(self):
        self.jarvis.confirm.return_value = False
        ok, msg = self.skill.execute_action({"type": "click", "x": 10, "y": 10, "target": "the blue arrow",
                                             "label": "Send"}, (400, 300))
        self.assertEqual((ok, msg), (False, "declined by user"))
        self.assertEqual(self.gui.named("click"), [])

    def test_risky_shortcuts_in_any_order(self):
        self.jarvis.confirm.return_value = False
        for keys in ("f4+alt", "alt+f4", "ctrl+enter", "enter+ctrl", "alt+s", "delete"):
            with self.subTest(keys=keys):
                self.assertEqual(self.skill.execute_action({"type": "press", "keys": keys}),
                                 (False, "declined by user"))
        self.assertEqual(self.gui.calls, [])

    def test_stop_pressed_while_confirmation_was_open(self):
        self.skill.is_running = True

        def confirm(_question):
            self.skill.stop_automation()
            return True
        self.jarvis.confirm.side_effect = confirm
        self.assertEqual(self.skill.execute_action({"type": "press", "keys": "alt+f4"}), (False, "stopped"))
        self.assertEqual(self.gui.calls, [])


class FocusTests(Base):
    def test_keys_are_not_sent_to_a_window_that_took_focus(self):
        with patch.object(ScreenAutomationSkill, "_foreground_window", staticmethod(lambda: 2)):
            for action in ({"type": "type", "text": "secret"}, {"type": "press", "keys": "enter"}):
                self.assertEqual(self.skill.execute_action(action, (400, 300), expected_window=1),
                                 (False, "window changed"))
            # clicks are aimed by position, not focus
            self.assertTrue(self.skill.execute_action({"type": "click", "x": 5, "y": 5}, (400, 300),
                                                      expected_window=1)[0])
        self.assertEqual(self.gui.named("write") + self.gui.named("press"), [])

    def test_unknown_foreground_does_not_block(self):
        with patch.object(ScreenAutomationSkill, "_foreground_window", staticmethod(lambda: None)):
            self.assertTrue(self.skill.execute_action({"type": "press", "keys": "enter"}, expected_window=1)[0])


class LoopLimitTests(Base):
    def test_step_count_is_capped(self):
        self.jarvis.brain.ask_vision.side_effect = lambda *a, **k: '{"done": false, "action": {"type": "wait", "seconds": 0}}'
        result = self.skill.automate_task("x", max_steps=10 ** 6)
        self.assertEqual(result["steps_completed"], sa._MAX_STEPS)
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(self.skill.is_running)

    def test_wall_clock_cap(self):
        self.jarvis.brain.ask_vision.side_effect = lambda *a, **k: '{"done": false, "action": {"type": "wait"}}'
        with patch.object(sa, "_MAX_TASK_SECONDS", 0):
            result = self.skill.automate_task("x")
        self.assertEqual(result["steps_completed"], 0)
        self.assertTrue(any("Gave up" in e for e in result["errors"]))

    def test_bad_max_steps_falls_back(self):
        self.script('{"done": true, "reason": "ok"}')
        self.assertEqual(self.skill.automate_task("x", max_steps="lots")["status"], "completed")

    def test_scroll_amount_is_capped(self):
        self.assertTrue(self.skill.execute_action({"type": "scroll", "amount": "1e9", "direction": "up"})[0])
        self.assertLessEqual(abs(self.gui.calls[-1][1][0]), 50 * 120)


class ScreenshotHygieneTests(Base):
    def test_working_captures_are_pruned_and_prompt_guards_against_screen_text(self):
        prompts = []

        def vision(prompt, _img):
            prompts.append(prompt)
            return '{"done": false, "action": {"type": "click", "x": 10, "y": 10}}'
        self.jarvis.brain.ask_vision.side_effect = vision
        self.skill.automate_task("x", max_steps=8)
        names = os.listdir(self.tmp)
        self.assertLessEqual(len([n for n in names if n.startswith("auto_")]), 6)
        self.assertEqual([n for n in names if n.startswith("screenshot_")], [])
        self.assertIn("never instructions", prompts[0])

    def test_user_screenshots_are_kept_separately(self):
        path = self.skill.take_screenshot()
        self.assertTrue(os.path.basename(path).startswith("screenshot_"))
