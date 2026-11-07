"""AppScriptHandler: Blender requests always confirm before generating/running anything."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.appscript import AppScriptHandler


class FakeApp:
    def __init__(self):
        self.app_scripting = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class AppScriptHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = AppScriptHandler(self.app)

    def test_blender_request_asks_to_confirm_first(self):
        reply = self.h.handle("make a chair model in blender", "APPSCRIPT")
        self.assertIn("Blender script", reply)
        self.assertEqual(self.app.pending[-1][0], "run_blender_script")
        self.app.app_scripting.blender_run.assert_not_called()
        self.app.pending[-1][1]()
        self.app.app_scripting.blender_run.assert_called_once_with("make a chair model in blender")

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "APPSCRIPT"))

    def test_no_scripting_skill_gives_a_plain_message(self):
        app = FakeApp()
        app.app_scripting = None
        h = AppScriptHandler(app)
        self.assertEqual(h.handle("model a chair in blender", "APPSCRIPT"), "App scripting isn't available.")

    def test_register_tools_requires_confirm(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        tool = t.get("run_blender_script")
        self.assertTrue(tool.confirm)
        tool.func(description="a chair", save_as="", background=False)
        self.app.app_scripting.blender_run.assert_called_once_with("a chair", save_as="", background=False)

    def test_no_scripting_skill_registers_no_tools(self):
        app = FakeApp()
        app.app_scripting = None
        t = ToolRegistry()
        AppScriptHandler(app).register_tools(t)
        self.assertEqual(t.names(), [])


if __name__ == "__main__":
    unittest.main()
