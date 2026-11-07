"""AppScripting: generating a Blender script via the AI brain and launching Blender
to run it, with subprocess/shutil/glob mocked so this runs without Blender installed."""
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from skills.app_scripting import AppScripting, _strip_code_fence, find_blender


class StripFenceTests(unittest.TestCase):
    def test_removes_python_fence(self):
        self.assertEqual(_strip_code_fence("```python\nimport bpy\n```"), "import bpy")

    def test_removes_bare_fence(self):
        self.assertEqual(_strip_code_fence("```\nimport bpy\n```"), "import bpy")

    def test_plain_code_is_untouched(self):
        self.assertEqual(_strip_code_fence("import bpy"), "import bpy")

    def test_none_and_empty(self):
        self.assertEqual(_strip_code_fence(""), "")
        self.assertEqual(_strip_code_fence(None), "")


class FindBlenderTests(unittest.TestCase):
    def test_found_on_path(self):
        with patch("shutil.which", return_value=r"C:\blender\blender.exe"):
            self.assertEqual(find_blender(), r"C:\blender\blender.exe")

    def test_not_found_anywhere(self):
        with patch("shutil.which", return_value=None), \
                patch("skills.app_scripting.Path.is_dir", return_value=False):
            self.assertIsNone(find_blender())


class FakeJarvis:
    def __init__(self, code="import bpy\n"):
        self.brain = Mock()
        self.brain.ask_text.return_value = code


class BlenderRunTests(unittest.TestCase):
    def setUp(self):
        self.jarvis = FakeJarvis()
        self.scripting = AppScripting(self.jarvis)

    def test_blender_missing(self):
        with patch("skills.app_scripting.find_blender", return_value=None):
            result = self.scripting.blender_run("a chair")
        self.assertIn("isn't installed", result)
        self.jarvis.brain.ask_text.assert_not_called()

    def test_no_brain_available(self):
        scripting = AppScripting(jarvis_instance=None)
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"):
            result = scripting.blender_run("a chair")
        self.assertIn("Couldn't generate", result)

    def test_foreground_run_launches_and_does_not_block(self):
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"), \
                patch("subprocess.Popen") as popen:
            result = self.scripting.blender_run("a red cube")
        self.assertIn("Opened Blender", result)
        args = popen.call_args.args[0]
        self.assertEqual(args[0], r"C:\blender.exe")
        self.assertIn("--python", args)
        self.assertNotIn("--background", args)
        script_path = Path(args[args.index("--python") + 1])
        self.assertIn("import bpy", script_path.read_text())

    def test_background_run_waits_and_reports_exit_code(self):
        proc = Mock(stdout="Saved\n", stderr="", returncode=0)
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"), \
                patch("subprocess.run", return_value=proc) as run:
            result = self.scripting.blender_run("a red cube", background=True)
        self.assertIn("Done", result)
        self.assertIn("--background", run.call_args.args[0])

    def test_background_run_failure_reports_exit_code(self):
        proc = Mock(stdout="", stderr="Python error", returncode=1)
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"), \
                patch("subprocess.run", return_value=proc):
            result = self.scripting.blender_run("a red cube", background=True)
        self.assertIn("exited with an error (code 1)", result)

    def test_save_as_appends_a_save_step(self):
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"), \
                patch("subprocess.Popen") as popen:
            self.scripting.blender_run("a red cube", save_as=r"C:\models\cube.blend")
        args = popen.call_args.args[0]
        script_path = Path(args[args.index("--python") + 1])
        text = script_path.read_text()
        self.assertIn("save_as_mainfile", text)
        self.assertIn("cube.blend", text)

    def test_empty_code_gives_a_clear_message(self):
        self.jarvis.brain.ask_text.return_value = ""
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"):
            result = self.scripting.blender_run("nothing sensible")
        self.assertIn("didn't return any code", result)

    def test_generation_failure_is_contained(self):
        self.jarvis.brain.ask_text.side_effect = RuntimeError("no model")
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"):
            result = self.scripting.blender_run("a chair")
        self.assertIn("Couldn't generate", result)

    def test_launch_failure_is_contained(self):
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"), \
                patch("subprocess.Popen", side_effect=OSError("boom")):
            result = self.scripting.blender_run("a chair")
        self.assertIn("Couldn't launch Blender", result)

    def test_background_timeout(self):
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"), \
                patch("subprocess.run", side_effect=subprocess.TimeoutExpired("blender", 180)):
            result = self.scripting.blender_run("a chair", background=True)
        self.assertIn("taking a while", result)

    def test_code_fence_is_stripped_before_saving(self):
        self.jarvis.brain.ask_text.return_value = "```python\nimport bpy\nbpy.ops.mesh.primitive_cube_add()\n```"
        with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"), \
                patch("subprocess.Popen") as popen:
            self.scripting.blender_run("a cube")
        args = popen.call_args.args[0]
        script_path = Path(args[args.index("--python") + 1])
        text = script_path.read_text()
        self.assertNotIn("```", text)
        self.assertIn("primitive_cube_add", text)


if __name__ == "__main__":
    unittest.main()
