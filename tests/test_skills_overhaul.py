"""Offline tests for the overhauled skills (no desktop, network, or hardware)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from skills.app_control import ApplicationControl


def app_control():
    control = ApplicationControl(scan=False)
    control._start_apps = []
    return control


class AppControlTests(unittest.TestCase):
    def setUp(self):
        self.control = app_control()
        self.opened = []
        self.control.open_url = lambda url, then_js=None, browser=None: self.opened.append((url, then_js, browser)) or f"Opened {url}."

    def test_websites_and_urls(self):
        self.control.launch_app_by_name("go to github.com")
        self.control.launch_app_by_name("open youtube")
        self.control.launch_app_by_name("visit www.python.org")
        self.assertEqual([u for u, _, _ in self.opened],
                         ["https://github.com", "https://www.youtube.com", "https://www.python.org"])

    def test_youtube_play_uses_direct_video_when_found(self):
        with patch("skills.app_control.youtube_first_video", return_value="https://www.youtube.com/watch?v=abcdefghijk"):
            reply = self.control.launch_app_by_name("go to youtube and play michael jackson", browser="chrome")
        self.assertEqual(self.opened[-1], ("https://www.youtube.com/watch?v=abcdefghijk", None, "chrome"))
        self.assertIn("Playing: michael jackson", reply)

    def test_youtube_play_falls_back_to_search_with_autoclick(self):
        with patch("skills.app_control.youtube_first_video", return_value=None):
            self.control.launch_app_by_name("play lofi beats")
        url, js, _ = self.opened[-1]
        self.assertIn("search_query=lofi+beats", url)
        self.assertIn("click", js)

    def test_google_chrome_opens_app_not_google(self):
        with patch.object(self.control, "_shell_open", return_value="Opened Chrome.") as shell:
            self.control.launch_app_by_name("open google chrome")
        self.assertEqual(shell.call_args.args[0], "chrome.exe")
        self.assertEqual(self.opened, [])

    def test_filler_words_removed_and_unknown_app_reported(self):
        with patch.object(self.control, "_shell_open", return_value="Opened Calculator.") as shell:
            self.control.launch_app_by_name("open the calculator app")
        self.assertEqual(shell.call_args.args[0], "calc.exe")
        with patch.object(self.control, "_shell_open", return_value=None):
            self.assertIn("couldn't find", self.control.launch_app_by_name("open zzqqxx frobnicator"))

    def test_no_shell_interpretation_of_names(self):
        with patch("skills.app_control.subprocess") as sub, patch.object(self.control, "_shell_open", return_value=None):
            self.control.launch_app_by_name("open calc & del C:\\important")
        for call in sub.mock_calls:
            self.assertNotIn("shell=True", str(call))

    def test_close_matches_exact_process_names(self):
        procs = []
        for name in ("chrome.exe", "chromedriver.exe", "notepad.exe"):
            p = Mock()
            p.info = {"pid": 100 + len(procs), "name": name}
            procs.append(p)
        with patch("skills.app_control.psutil") as ps:
            ps.process_iter.return_value = procs
            ps.wait_procs.return_value = ([procs[0]], [])
            ps.NoSuchProcess = ps.AccessDenied = Exception
            result = self.control.close_app_by_name("chrome")
        procs[0].terminate.assert_called_once_with()
        procs[1].terminate.assert_not_called()
        self.assertIn("Closed chrome", result)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        from core.memory import MemoryManager
        self.memory = MemoryManager.__new__(MemoryManager)
        self.memory.memory = {"user_name": None, "facts": [], "preferences": {}}
        self.memory._save = Mock()
        self.memory.fact_detector = None

    def test_name_requires_capitalised_real_name(self):
        for text in ("I'm going home", "I am tired", "i'm fine thanks", "I'm in a meeting"):
            with self.subTest(text=text):
                self.memory.extract_from_message(text)
                self.assertIsNone(self.memory.memory["user_name"])
        self.memory.extract_from_message("Hi, my name is Raghav")
        self.assertEqual(self.memory.memory["user_name"], "Raghav")

    def test_explicit_remember_and_forget(self):
        self.memory.extract_from_message("remember that my wifi is called Falcon")
        self.assertEqual(self.memory.list_facts(), ["my wifi is called Falcon"])
        self.assertEqual(self.memory.forget("falcon"), 1)
        self.assertEqual(self.memory.list_facts(), [])

    def test_decision_model_captures_other_personal_facts(self):
        self.memory.fact_detector = Mock(return_value=0.91)
        self.assertTrue(self.memory.extract_from_message("I prefer email over phone calls"))
        self.assertIn("I prefer email over phone calls", self.memory.list_facts())
        self.memory.fact_detector = Mock(return_value=0.2)
        self.assertFalse(self.memory.extract_from_message("I think it might rain"))

    def test_remember_to_is_not_a_fact(self):
        self.memory.extract_from_message("remember to buy milk")
        self.assertEqual(self.memory.list_facts(), [])


class SpeechTextTests(unittest.TestCase):
    def test_make_speakable(self):
        from core.voice import make_speakable
        text = ("**Search Summary** for cats\n- Cats sleep 16 hours. See https://example.com\n"
                "They purr. They hunt. They nap. 🐱")
        spoken = make_speakable(text)
        self.assertNotIn("**", spoken)
        self.assertNotIn("https://", spoken)
        self.assertNotIn("🐱", spoken)
        self.assertIn("full details are on screen", spoken)

    def test_wake_word_is_whole_word(self):
        from core.voice import VoiceEngine
        self.assertTrue(VoiceEngine.contains_wake_word("hey jarvis open chrome", "jarvis"))
        self.assertFalse(VoiceEngine.contains_wake_word("jarvisville is nice", "jarvis"))


class WeatherAndMathTests(unittest.TestCase):
    def test_city_extraction(self):
        from skills.weather import WeatherSkill
        w = WeatherSkill()
        cases = {"what's the weather like today": "", "weather in London": "London", "Paris weather": "Paris",
                 "forecast for New York tomorrow": "New York", "is it going to rain in delhi": "Delhi",
                 "weather": ""}
        for query, city in cases.items():
            with self.subTest(query=query):
                self.assertEqual(w._extract_city_from_query(query), city)

    def test_calculator(self):
        from skills.utility import UtilitySkill
        u = UtilitySkill()
        self.assertTrue(u.calculate("whats 12*7").endswith("= 84"))
        self.assertTrue(u.calculate("15% of 200").endswith("= 30"))
        self.assertTrue(u.calculate("square root of 81").endswith("= 9"))
        self.assertTrue(u.calculate("2^10").endswith("= 1024"))
        self.assertEqual(u.calculate("10/0"), "Error: Division by zero")
        self.assertIn("Could not calculate", u.calculate("hello there"))


class CommandProcessorTests(unittest.TestCase):
    def test_split_and_plan(self):
        from skills.command_processor import CommandProcessor
        cp = CommandProcessor()
        self.assertEqual(cp.split_steps("Open Chrome, go to YouTube and play MJ, then set the volume to 40"),
                         ["Open Chrome", "go to YouTube and play MJ", "set the volume to 40"])
        self.assertEqual(cp.split_steps("open notepad and type hello then press ctrl+s"),
                         ["open notepad", "type hello", "press ctrl+s"])
        self.assertEqual(cp.split_steps("take a screenshot and tell me what you see"),
                         ["take a screenshot and tell me what you see"])
        plan = cp.plan("open spotify, wait 2 seconds, then pause")
        self.assertEqual([s.kind for s in plan.steps], ["command", "wait", "command"])
        self.assertEqual(plan.steps[1].seconds, 2)

    def test_execute_stops_after_failure(self):
        from skills.command_processor import CommandProcessor
        cp = CommandProcessor()
        plan = cp.plan("open a then open b then open c")
        replies = iter(["ok", "Step failed: boom", "never"])
        results = cp.execute(plan, lambda text, ctx: next(replies))
        self.assertEqual(results, ["ok", "Step failed: boom", "Skipped because an earlier step failed."])


class ScreenAutomationHelperTests(unittest.TestCase):
    def test_extract_json_variants(self):
        from skills.screen_automation import extract_json
        self.assertEqual(extract_json('```json\n{"found": true, "x": 5}\n```'), {"found": True, "x": 5})
        self.assertEqual(extract_json('Sure! {"a": {"b": 1}} trailing'), {"a": {"b": 1}})
        self.assertIsNone(extract_json("no json here"))

    def test_coordinates_map_from_model_image_to_screen(self):
        from skills.screen_automation import ScreenAutomationSkill
        skill = ScreenAutomationSkill.__new__(ScreenAutomationSkill)
        with patch("skills.screen_automation.pyautogui") as gui:
            gui.size.return_value = (2732, 1536)      # physical 2x of a 1366x768 model image
            self.assertEqual(skill._to_screen(683, 384, 1366, 768), (1366, 768))
            self.assertEqual(skill._to_screen(99999, -5, 1366, 768), (2730, 1))   # never a fail-safe corner
        point = ScreenAutomationSkill._point_from({"box_2d": [100, 200, 300, 400]}, 1000, 500)
        self.assertEqual(point, (300.0, 100.0))

    def test_risky_click_needs_confirmation(self):
        from skills.screen_automation import ScreenAutomationSkill
        skill = ScreenAutomationSkill.__new__(ScreenAutomationSkill)
        skill.jarvis = Mock(confirm=Mock(return_value=False))
        skill.emergency_stop = False
        skill.automation_history = []
        with patch("skills.screen_automation.pyautogui") as gui:
            ok, msg = skill.execute_action({"type": "click", "x": 10, "y": 10, "target": "Delete account"}, (100, 100))
        self.assertFalse(ok)
        self.assertEqual(msg, "declined by user")
        gui.click.assert_not_called()

    def test_automation_refuses_without_consent(self):
        from core.config import Config
        from skills.screen_automation import ScreenAutomationSkill
        skill = ScreenAutomationSkill.__new__(ScreenAutomationSkill)
        skill.jarvis = Mock(confirm=Mock(return_value=False))
        with patch("skills.screen_automation.pyautogui", Mock()), \
                patch.object(Config, "AUTOMATION_CONFIRMATION_REQUIRED", True):
            result = skill.automate_task("open notepad")
        self.assertEqual(result["status"], "cancelled")


class FileManagerPathTests(unittest.TestCase):
    def setUp(self):
        from skills.file_manager import FileManagerSkill
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fm = FileManagerSkill()
        self.fm.current_directory = self.temp.name

    def test_subfolders_and_spaces_are_kept(self):
        self.assertIn("created successfully", self.fm.create_file("notes/2024 plan", "x"))
        self.assertTrue((Path(self.temp.name) / "notes" / "2024 plan.txt").exists())

    def test_parent_traversal_is_stripped(self):
        self.fm.create_file("../../escape", "x")
        self.assertTrue((Path(self.temp.name) / "escape.txt").exists())

    def test_natural_rename_and_copy(self):
        self.fm.create_file("a.txt", "x")
        self.assertIn("renamed", self.fm.route_command("rename a.txt to b"))
        self.assertTrue((Path(self.temp.name) / "b.txt").exists())
        self.assertIn("copied", self.fm.route_command("copy b.txt to c.txt"))

    def test_unknown_phrase_returns_none_for_ai_fallback(self):
        self.assertIsNone(self.fm.handle_file_command("tidy up my files somehow"))


if __name__ == "__main__":
    unittest.main()


class AutomateLoopTests(unittest.TestCase):
    """automate_task with a scripted vision model and a fake desktop."""

    def make(self, replies, changing=True):
        from core.config import Config
        from skills.screen_automation import ScreenAutomationSkill
        skill = ScreenAutomationSkill.__new__(ScreenAutomationSkill)
        skill.jarvis = Mock(confirm=Mock(return_value=True), decision=None)
        skill.jarvis.brain.ask_vision.side_effect = list(replies)
        skill.emergency_stop = False
        skill.is_running = False
        skill.current_task = None
        skill.automation_history = []
        skill.screenshot_dir = tempfile.mkdtemp()
        counter = {"n": 0}

        def shot(region=None):
            from PIL import Image
            counter["n"] += 1
            img = Image.new("RGB", (400, 300), (counter["n"] * 40 % 255 if changing else 10, 20, 30))
            return img
        gui = Mock()
        gui.screenshot.side_effect = shot
        gui.size.return_value = (800, 600)
        gui.FailSafeException = RuntimeError
        self.patches = [patch("skills.screen_automation.pyautogui", gui),
                        patch.object(Config, "AUTOMATION_ACTION_DELAY", 0)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        return skill, gui

    def test_clicks_then_completes(self):
        skill, gui = self.make([
            '{"done": false, "reason": "start menu closed", "action": {"type": "click", "x": 100, "y": 50, "target": "Start"}}',
            '```json\n{"done": true, "reason": "Notepad is open"}\n```'])
        result = skill.automate_task("open notepad", max_steps=4)
        self.assertEqual(result["status"], "completed")
        gui.click.assert_called_once_with(200, 100, clicks=1, button="left")   # image → screen scale ×2

    def test_stops_when_screen_stops_changing(self):
        step = '{"done": false, "reason": "x", "action": {"type": "click", "x": 1, "y": 1, "target": "OK"}}'
        skill, _ = self.make([step] * 6, changing=False)
        result = skill.automate_task("do something", max_steps=6)
        self.assertEqual(result["status"], "stuck")

    def test_bad_json_twice_is_an_error(self):
        skill, _ = self.make(["I think you should click it", "still not json"])
        self.assertEqual(skill.automate_task("x", max_steps=5)["status"], "error")
