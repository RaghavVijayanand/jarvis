"""PluginsHandler (read-only status) and HandlerRegistry's plugin-folder
integration — a plugin file dropped in a temp dir is picked up, its
setup(app) runs, and its Handler subclass is dispatchable, end to end."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from handlers import HandlerRegistry
from handlers.plugins import PluginsHandler


class FakeApp:
    def __init__(self):
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class PluginsHandlerUnitTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.app._handlers = Mock(plugin_dir=Path("/fake/plugins"), plugin_names=[])
        self.h = PluginsHandler(self.app)

    def test_no_plugins_loaded(self):
        reply = self.h.handle("list plugins", "PLUGINS")
        self.assertIn("No plugins loaded", reply)
        self.assertIn(str(Path("/fake/plugins")), reply)

    def test_plugins_loaded(self):
        self.app._handlers.plugin_names = ["cool_plugin", "another"]
        reply = self.h.handle("list plugins", "PLUGINS")
        self.assertIn("2 plugin(s)", reply)
        self.assertIn("cool_plugin", reply)
        self.assertIn("another", reply)

    def test_plugin_status_alias(self):
        reply = self.h.handle("plugin status", "PLUGINS")
        self.assertIn("No plugins loaded", reply)

    def test_which_plugins_are_installed_alias(self):
        self.app._handlers.plugin_names = ["x"]
        reply = self.h.handle("which plugins are installed", "PLUGINS")
        self.assertIn("1 plugin(s)", reply)

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "PLUGINS"))

    def test_register_tools_list_plugins(self):
        from core.tools import ToolRegistry
        t = ToolRegistry()
        self.h.register_tools(t)
        tool = t.get("list_plugins")
        self.assertIsNotNone(tool)
        self.assertIn("No plugins loaded", tool.func())


class HandlerRegistryPluginIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_plugin_handler_is_dispatchable(self):
        (self.tmp / "greet.py").write_text(
            "from handlers.base import Handler\n"
            "class GreetHandler(Handler):\n"
            "    intents = {'GREETPLUGIN'}\n"
            "    def handle(self, text, intent):\n"
            "        return 'hello from a plugin'\n", encoding="utf-8")
        app = FakeApp()
        with patch("handlers.ensure_plugin_dir", return_value=self.tmp):
            reg = HandlerRegistry(app)
        self.assertEqual(reg.plugin_names, ["greet"])
        self.assertIn("GreetHandler", reg.plugin_handler_names)
        self.assertEqual(reg.dispatch("hi", "GREETPLUGIN"), "hello from a plugin")

    def test_plugin_setup_runs_before_handlers_constructed(self):
        (self.tmp / "attach.py").write_text(
            "def setup(app):\n"
            "    app.attached_skill = 'present'\n"
            "\n"
            "from handlers.base import Handler\n"
            "class UsesAttachedHandler(Handler):\n"
            "    intents = {'USESATTACHED'}\n"
            "    def handle(self, text, intent):\n"
            "        return getattr(self.app, 'attached_skill', 'missing')\n", encoding="utf-8")
        app = FakeApp()
        with patch("handlers.ensure_plugin_dir", return_value=self.tmp):
            reg = HandlerRegistry(app)
        self.assertEqual(app.attached_skill, "present")
        self.assertEqual(reg.dispatch("x", "USESATTACHED"), "present")

    def test_broken_plugin_does_not_break_registry(self):
        (self.tmp / "broken.py").write_text("not valid python (((\n", encoding="utf-8")
        app = FakeApp()
        with patch("handlers.ensure_plugin_dir", return_value=self.tmp):
            reg = HandlerRegistry(app)
        self.assertIsInstance(reg.by_name, dict)
        self.assertIn("ChatHandler", reg.by_name)

    def test_plugin_cannot_silently_break_builtin_lookup(self):
        app = FakeApp()
        with patch("handlers.ensure_plugin_dir", return_value=self.tmp):
            reg = HandlerRegistry(app)
        self.assertEqual(reg.plugin_names, [])
        self.assertEqual(reg.plugin_handler_names, [])
        self.assertIn("PLUGINS", reg.by_intent)


if __name__ == "__main__":
    unittest.main()
