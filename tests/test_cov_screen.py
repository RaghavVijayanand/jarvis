"""Coverage + regression tests for skills.screen_automation (fake desktop and vision model)."""
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import skills.screen_automation as sa
from core.config import Config
from skills.screen_automation import ScreenAutomationSkill, extract_json, process_automation_command


class FailSafe(Exception):
    pass


class FakeGui:
    """Records every call; screenshots are real PIL images that can change or not."""
    FailSafeException = FailSafe
    KEYBOARD_KEYS = ["enter", "esc", "ctrl", "alt", "shift", "s", "a", "win", "f4", "w",
                     "delete", "tab", "pageup", "up", "space"]

    def __init__(self, changing=True, size=(800, 600), shot_size=(400, 300)):
        self.calls = []
        self.changing = changing
        self._size = size
        self.shot_size = shot_size
        self.n = 0
        self.raise_on = {}

    def _rec(self, name, *a, **k):
        self.calls.append((name, a, k))
        if name in self.raise_on:
            raise self.raise_on[name]

    def size(self):
        return self._size

    def screenshot(self, region=None):
        self.n += 1
        colour = (self.n * 60 % 255, 20, 30) if self.changing else (10, 20, 30)
        return Image.new("RGB", region[2:] if region else self.shot_size, colour)

    def click(self, *a, **k):
        self._rec("click", *a, **k)

    def write(self, *a, **k):
        self._rec("write", *a, **k)

    def press(self, *a, **k):
        self._rec("press", *a, **k)

    def hotkey(self, *a, **k):
        self._rec("hotkey", *a, **k)

    def scroll(self, *a, **k):
        self._rec("scroll", *a, **k)

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.gui = FakeGui()
        for p in (patch.object(sa, "pyautogui", self.gui),
                  patch.object(Config, "SCREENSHOTS_DIR", self.tmp),
                  patch.object(Config, "AUTOMATION_ACTION_DELAY", 0),
                  patch.object(Config, "AUTOMATION_CONFIRMATION_REQUIRED", True),
                  patch.object(sa, "_install_emergency_stop", lambda cb: None),
                  # the real desktop's front window must not decide test outcomes
                  patch.object(ScreenAutomationSkill, "_foreground_window", staticmethod(lambda: 1))):
            p.start()
            self.addCleanup(p.stop)
        self.jarvis = Mock(decision=None)
        self.jarvis.confirm.return_value = True
        self.skill = ScreenAutomationSkill(self.jarvis)

    def script(self, *replies):
        self.jarvis.brain.ask_vision.side_effect = list(replies)


class ExtractJsonTests(unittest.TestCase):
    def test_variants(self):
        self.assertIsNone(extract_json(""))
        self.assertEqual(extract_json({"a": 1}), {"a": 1})
        self.assertEqual(extract_json([1, {"a": 2}]), {"a": 2})
        self.assertEqual(extract_json('```json\n{"a": {"b": 1}}\n```'), {"a": {"b": 1}})
        self.assertEqual(extract_json('```\n[{"type": "click"}, {"type": "x"}]\n```'), {"type": "click"})
        self.assertEqual(extract_json('ok {"reason": "the } button", "done": false} more'),
                         {"reason": "the } button", "done": False})
        self.assertEqual(extract_json("{'done': False, 'reason': \"it's\"}"), {"done": False, "reason": "it's"})
        self.assertEqual(extract_json("{'done': false, 'x': null}"), {"done": False, "x": None})
        self.assertEqual(extract_json('use {curly} then {"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('{"a": "esc \\" q"}'), {"a": 'esc " q'})
        self.assertIsNone(extract_json("[1, 2] {broken"))
        self.assertIsNone(extract_json("{'a': }"))
        self.assertEqual(extract_json(12), None)

    def test_truthy(self):
        self.assertFalse(sa._truthy("false"))
        self.assertTrue(sa._truthy("True"))
        self.assertTrue(sa._truthy(1))
        self.assertFalse(sa._truthy(None))


class HotkeyTests(unittest.TestCase):
    def setUp(self):
        self.saved = (sa._hotkey_listener, list(sa._stop_callbacks))
        sa._stop_callbacks.clear()

    def tearDown(self):
        sa._hotkey_listener = self.saved[0]
        sa._stop_callbacks[:] = self.saved[1]

    def test_listener_created_once_and_callbacks_weak_and_deduped(self):
        created = []

        class Listener:
            def __init__(self, mapping):
                created.append(mapping)

            def start(self):
                pass
        fake_kb = Mock(GlobalHotKeys=Listener)
        sa._hotkey_listener = None
        with patch.dict("sys.modules", {"pynput": Mock(keyboard=fake_kb), "pynput.keyboard": fake_kb}):
            a = ScreenAutomationSkill.__new__(ScreenAutomationSkill)
            a.emergency_stop = False
            sa._install_emergency_stop(a.stop_automation)
            sa._install_emergency_stop(a.stop_automation)
            hits = []
            sa._install_emergency_stop(lambda: hits.append(1))
            sa._install_emergency_stop(lambda: 1 / 0)
        self.assertEqual(len(created), 1)
        self.assertIn("<ctrl>+<alt>+<esc>", created[0])
        self.assertEqual(len(sa._stop_callbacks), 3)
        created[0]["<ctrl>+<alt>+<esc>"]()
        self.assertTrue(a.emergency_stop)
        self.assertEqual(hits, [1])
        del a                       # dead weak refs are skipped and later pruned
        sa._fire_emergency_stop()
        sa._install_emergency_stop(lambda: None)
        self.assertEqual(len(sa._stop_callbacks), 3)

    def test_listener_failure_is_logged_once(self):
        sa._hotkey_listener = None
        with patch.dict("sys.modules", {"pynput": None}):
            sa._install_emergency_stop(lambda: None)
        self.assertIs(sa._hotkey_listener, False)


class VisionTests(Base):
    def test_screenshot_prune_and_model_image(self):
        self.gui.shot_size = (2732, 1536)
        path = self.skill.take_screenshot()
        img, w, h = self.skill._model_image(path)
        self.assertEqual((w, h), (1366, 768))
        self.assertTrue(os.path.exists(img))
        self.skill.take_screenshot(region=(0, 0, 50, 40))
        for i in range(5):
            open(os.path.join(self.tmp, f"screenshot_old{i}.png"), "w").close()
        self.skill._prune_screenshots(keep=2)
        self.assertEqual(len([f for f in os.listdir(self.tmp) if f.startswith("screenshot_")]), 2)
        with patch("os.listdir", side_effect=OSError):
            self.skill._prune_screenshots()

    def test_require_gui(self):
        with patch.object(sa, "pyautogui", None):
            with self.assertRaises(RuntimeError):
                self.skill._require_gui()
            self.assertEqual(self.skill.automate_task("x")["status"], "error")

    def test_point_from_and_to_screen(self):
        p = ScreenAutomationSkill._point_from
        self.assertEqual(p({"box_2d": [0, 0, 1000, 1000]}, 400, 300), (200.0, 150.0))
        self.assertEqual(p({"coordinates": [3, 4]}, 1, 1), (3.0, 4.0))
        self.assertIsNone(p({}, 1, 1))
        self.assertEqual(self.skill._to_screen(200, 150, 400, 300), (400, 300))

    def test_describe_screen(self):
        self.script("A desktop.")
        self.assertEqual(self.skill.describe_screen(), "A desktop.")
        self.assertEqual(self.skill.get_history()[-1]["action"], "describe")
        self.jarvis.brain = None
        self.assertIn("couldn't analyze", self.skill.describe_screen("what?"))


class ClickElementTests(Base):
    def test_clicks_mapped_point(self):
        self.script('{"found": true, "x": 100, "y": 50, "label": "OK", "confidence": 0.9}')
        res = self.skill.find_and_click_element("the OK button", double=True)
        self.assertTrue(res["success"])
        self.assertEqual(self.gui.named("click")[0], ("click", (200, 100), {"clicks": 2, "button": "left"}))

    def test_not_found_low_confidence_and_declined(self):
        self.script('{"found": "false"}', '{"found": true, "x": 1, "y": 1, "confidence": 0}',
                    '{"found": true, "x": 9, "y": 9, "label": "Delete", "confidence": 0.9}')
        self.assertIn("Could not find", self.skill.find_and_click_element("x")["message"])
        # confidence 0 used to be coerced to 0.7 and clicked
        self.assertIn("not confident", self.skill.find_and_click_element("y")["message"])
        self.jarvis.confirm.return_value = False
        self.assertIn("declined", self.skill.find_and_click_element("z")["message"])
        self.assertEqual(self.gui.named("click"), [])

    def test_failure_is_reported(self):
        self.jarvis.brain.ask_vision.side_effect = RuntimeError("offline")
        self.assertIn("Click failed", self.skill.find_and_click_element("x")["message"])

    def test_no_confirm_means_no(self):
        skill = ScreenAutomationSkill(object())
        self.assertFalse(skill._confirm("?"))


class ExecuteActionTests(Base):
    def run_action(self, action, size=(400, 300)):
        return self.skill.execute_action(action, size)

    def test_clicks(self):
        self.assertEqual(self.run_action({"type": "Right-Click", "box_2d": [500, 500, 500, 500]})[0], True)
        self.assertEqual(self.gui.calls[-1], ("click", (400, 300), {"clicks": 1, "button": "right"}))
        self.assertEqual(self.run_action({"type": "click"}), (False, "no coordinates"))
        ok, _ = self.skill.execute_action({"type": "click", "x": 10, "y": 20})
        self.assertTrue(ok)
        self.assertEqual(self.gui.calls[-1][1], (10, 20))
        # no coordinates and no image size: must not click the (0, 0) fail-safe corner
        self.assertEqual(self.skill.execute_action({"type": "click"}), (False, "no coordinates"))
        self.assertEqual(self.run_action({"type": "click", "x": "abc", "y": 1})[0], False)

    def test_type_ascii_chunks_unicode_and_enter(self):
        ok, msg = self.run_action({"type": "type", "text": "a" * 40, "enter": True})
        self.assertTrue(ok)
        self.assertEqual(len(self.gui.named("write")), 3)
        self.assertEqual(self.gui.calls[-1][0:2], ("press", ("enter",)))
        self.jarvis.windows.type_text.return_value = "Typed 3 character(s)."
        self.assertTrue(self.run_action({"type": "type", "text": "héé"})[0])
        self.jarvis.windows.type_text.return_value = "Typing is only available on Windows."
        ok, msg = self.run_action({"type": "type", "text": "héé", "enter": "false"})
        self.assertFalse(ok)
        self.assertIn("only available", msg)
        skill = ScreenAutomationSkill(Mock(spec=["confirm"]))
        with patch("skills.windows_control.WindowsControl") as wc:
            wc.return_value.type_text.return_value = "Typed 1 character(s)."
            self.assertTrue(skill.execute_action({"type": "type", "text": "\n"})[0])

    def test_emergency_stop_interrupts_typing_and_wait(self):
        self.skill.is_running = True
        orig = self.gui.write

        def write(*a, **k):
            orig(*a, **k)
            self.skill.stop_automation()
        self.gui.write = write
        self.assertEqual(self.run_action({"type": "type", "text": "x" * 100}), (False, "stopped"))
        self.assertEqual(len(self.gui.named("write")), 1)
        self.assertEqual(self.run_action({"type": "wait", "seconds": 5}), (False, "stopped"))
        self.skill.emergency_stop = False
        threading.Timer(0.1, self.skill.stop_automation).start()
        t0 = time.monotonic()
        self.assertEqual(self.run_action({"type": "wait", "seconds": 5}), (False, "stopped"))
        self.assertLess(time.monotonic() - t0, 2)

    def test_stale_stop_does_not_block_direct_calls(self):
        self.skill.stop_automation()
        self.assertEqual(self.skill.execute_action({"type": "press", "keys": "enter"}), (True, "pressed enter"))

    def test_keys(self):
        self.assertEqual(self.run_action({"type": "hotkey", "keys": "Control + S"}), (True, "pressed ctrl+s"))
        self.assertEqual(self.gui.calls[-1][0:2], ("hotkey", ("ctrl", "s")))
        self.assertEqual(self.run_action({"type": "key", "key": ["Escape"]}), (True, "pressed esc"))
        self.assertEqual(self.run_action({"type": "press"}), (False, "no key"))
        self.assertEqual(self.run_action({"type": "press", "keys": "bogus"}), (False, "unknown key bogus"))
        self.jarvis.confirm.return_value = False
        self.assertEqual(self.run_action({"type": "press", "keys": "alt+f4"}), (False, "declined by user"))

    def test_scroll_wait_open_unknown(self):
        self.assertTrue(self.run_action({"type": "scroll", "amount": -3, "direction": "down"})[0])
        self.assertLess(self.gui.calls[-1][1][0], 0)       # negative amount must not flip direction
        self.assertTrue(self.run_action({"type": "scroll", "direction": "up"})[0])
        self.assertGreater(self.gui.calls[-1][1][0], 0)
        self.assertEqual(self.run_action({"type": "wait", "seconds": -1}), (True, "waited"))
        self.jarvis.app_control.launch_app_by_name.return_value = "Opened Notepad."
        self.assertEqual(self.run_action({"type": "open", "target": "notepad"}), (True, "Opened Notepad."))
        self.skill.jarvis = Mock(spec=["confirm"])
        self.assertEqual(self.run_action({"type": "open", "target": "x"}), (False, "app control unavailable"))
        self.assertEqual(self.run_action({"type": "fly"}), (False, "unknown action 'fly'"))
        self.assertEqual(self.run_action("click"), (False, "invalid action"))

    def test_failsafe_and_errors(self):
        self.gui.raise_on["click"] = FailSafe()
        ok, msg = self.run_action({"type": "click", "x": 1, "y": 1})
        self.assertTrue(msg.startswith("fail-safe"))
        self.assertTrue(self.skill.emergency_stop)
        self.gui.raise_on["click"] = ValueError("bad")
        self.assertEqual(self.run_action({"type": "click", "x": 1, "y": 1}), (False, "click failed: bad"))

    def test_risky_target_needs_confirmation(self):
        self.jarvis.confirm.return_value = False
        self.assertEqual(self.run_action({"type": "click", "x": 1, "y": 1, "target": "Send"}),
                         (False, "declined by user"))


class AutomateTaskTests(Base):
    def test_completes_and_maps_coordinates(self):
        self.script('{"done": false, "action": {"type": "click", "x": 100, "y": 50, "target": "Start"}}',
                    '{"done": true, "reason": "Notepad is open"}')
        res = self.skill.automate_task("open notepad", max_steps=4)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(self.gui.named("click")[0][1], (200, 100))
        self.assertFalse(self.skill.is_running)
        self.assertIn("Done", ScreenAutomationSkill.format_result(res))

    def test_string_false_done_is_not_completion(self):
        self.script('{"done": "false", "action": {"type": "press", "keys": "enter"}}',
                    '{"done": true, "reason": "ok"}')
        res = self.skill.automate_task("x", max_steps=3)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(len(res["actions_taken"]), 1)

    def test_done_action_type(self):
        self.script('{"action": {"type": "done"}, "reason": "finished"}')
        self.assertEqual(self.skill.automate_task("x")["status"], "completed")

    def test_verification_disagrees_then_runs_out_of_steps(self):
        self.jarvis.decision = Mock(laya_ready=True)
        self.jarvis.decision.yes_no.return_value = 0.1
        self.script('{"done": true, "reason": "maybe"}', '{"done": true, "reason": "maybe"}')
        res = self.skill.automate_task("x", max_steps=2)
        self.assertEqual(res["status"], "incomplete")
        self.assertIn("ran out", ScreenAutomationSkill.format_result(res))

    def test_bad_replies_must_be_consecutive(self):
        good = '{"action": {"type": "press", "keys": "tab"}}'
        self.script("nope", good, '{"action": "click"}', good, '{"done": true}')
        self.assertEqual(self.skill.automate_task("x", max_steps=6)["status"], "completed")
        self.script("nope", '{"done": false}')
        res = self.skill.automate_task("x", max_steps=6)
        self.assertEqual(res["status"], "error")
        self.assertIn("Automation failed", ScreenAutomationSkill.format_result(res))

    def test_stuck_detection_but_wait_is_not_stuck(self):
        self.gui.changing = False
        step = '{"action": {"type": "click", "x": 1, "y": 1}}'
        self.script(step, step, step, step)
        self.assertEqual(self.skill.automate_task("x", max_steps=6)["status"], "stuck")
        wait = '{"action": {"type": "wait", "seconds": 0}}'
        self.script(wait, wait, wait, '{"done": true}')
        self.assertEqual(self.skill.automate_task("x", max_steps=6)["status"], "completed")

    def test_vision_error_and_unexpected_error(self):
        self.jarvis.brain.ask_vision.side_effect = RuntimeError("down")
        self.assertEqual(self.skill.automate_task("x")["status"], "error")
        with patch.object(self.skill, "_model_image", side_effect=OSError("disk")):
            res = self.skill.automate_task("x")
        self.assertEqual(res["status"], "error")
        self.assertFalse(self.skill.is_running)

    def test_declined_risky_and_consent(self):
        self.script('{"action": {"type": "click", "x": 1, "y": 1, "target": "Delete all"}}')
        self.jarvis.confirm.side_effect = [True, False]
        self.assertEqual(self.skill.automate_task("x")["status"], "stopped")
        self.jarvis.confirm.side_effect = None
        self.jarvis.confirm.return_value = False
        self.assertEqual(self.skill.automate_task("x")["status"], "cancelled")

    def test_stop_during_vision_call(self):
        def ask(prompt, img):
            self.skill.stop_automation()
            return '{"action": {"type": "click", "x": 1, "y": 1}}'
        self.jarvis.brain.ask_vision.side_effect = ask
        res = self.skill.automate_task("x")
        self.assertEqual(res["status"], "stopped")
        self.assertEqual(self.gui.named("click"), [])

    def test_stop_during_delay_and_at_step_start(self):
        with patch.object(Config, "AUTOMATION_ACTION_DELAY", 5):
            self.script('{"action": {"type": "press", "keys": "tab"}}')
            threading.Timer(0.1, self.skill.stop_automation).start()
            t0 = time.monotonic()
            self.assertEqual(self.skill.automate_task("x")["status"], "stopped")
            self.assertLess(time.monotonic() - t0, 3)
        with patch.object(self.skill, "_sleep", side_effect=lambda s: setattr(self.skill, "emergency_stop", True) or True):
            self.script('{"action": {"type": "press", "keys": "tab"}}')
            self.assertEqual(self.skill.automate_task("x", max_steps=2)["status"], "stopped")
            self.script('{"action": {"type": "press", "keys": "tab"}}')
            self.assertEqual(self.skill.automate_task("x", max_steps=1)["status"], "stopped")

    def test_stop_keeps_running_flag_until_loop_exits_and_blocks_second_task(self):
        self.skill.is_running = True
        self.skill.stop_automation()
        self.assertTrue(self.skill.is_running)
        res = self.skill.automate_task("second")
        self.assertEqual(res["status"], "error")
        self.assertIn("already running", res["summary"])


class StatusAndCommandTests(Base):
    def test_status_history(self):
        self.skill._log({"action": "click", "target": "OK"})
        self.assertEqual(self.skill.get_status()["history_count"], 1)
        self.skill.clear_history()
        self.assertEqual(self.skill.get_history(), [])
        self.skill.cleanup()
        self.assertTrue(self.skill.emergency_stop)
        self.assertEqual(ScreenAutomationSkill.format_result({"status": "weird", "goal": "g",
                                                             "errors": ["e"], "summary": "s"}).split("\n")[0], "weird: g")

    def test_process_command(self):
        self.jarvis.screen_automation = self.skill
        run = lambda t: process_automation_command(t, self.jarvis)
        self.assertEqual(run("stop automation"), "Automation stopped.")
        self.assertIn("Running: False", run("automation status"))
        self.assertEqual(run("automation history"), "No automation history.")
        self.skill._log({"action": "click", "target": "OK"})
        self.assertIn("click OK", run("automation history"))
        self.script('{"found": true, "x": 1, "y": 1, "confidence": 0.9}', "Looks like a desktop.")
        self.assertIn("Clicked", run("right-click on the icon"))
        self.assertIn("Screenshot saved", run("take a screenshot"))
        with patch.object(self.skill, "take_screenshot", side_effect=OSError("x")):
            self.assertIn("Screenshot failed", run("screenshot"))
        self.assertEqual(run("what's on my screen"), "Looks like a desktop.")
        self.assertIn("Tell me what", run("automate"))
        self.script('{"done": true, "reason": "done already"}')
        self.assertIn("Done", run("automate open notepad"))


if __name__ == "__main__":
    unittest.main()
