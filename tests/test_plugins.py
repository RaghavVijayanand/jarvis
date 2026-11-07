"""core/plugins: built-in handler auto-discovery, plugin-folder loading, and
the setup(app) contract — all against a temp plugin folder, never the real one."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.plugins import (discover_builtin_handlers, discover_plugin_handlers, ensure_plugin_dir,
                          run_plugin_setup)
from handlers.base import Handler


class BuiltinDiscoveryTests(unittest.TestCase):
    def test_finds_known_builtin_handlers(self):
        classes = discover_builtin_handlers()
        names = {c.__name__ for c in classes}
        self.assertIn("ChatHandler", names)
        self.assertIn("FileIndexHandler", names)
        self.assertIn("WebDashboardHandler", names)
        self.assertIn("PluginsHandler", names)

    def test_excludes_base_handler_itself(self):
        classes = discover_builtin_handlers()
        self.assertNotIn(Handler, classes)

    def test_every_class_is_a_handler_subclass(self):
        for cls in discover_builtin_handlers():
            self.assertTrue(issubclass(cls, Handler), cls)

    def test_no_duplicate_intents_among_builtins(self):
        seen = {}
        for cls in discover_builtin_handlers():
            for intent in cls.intents:
                self.assertNotIn(intent, seen, f"{intent} claimed by both {seen.get(intent)} and {cls.__name__}")
                seen[intent] = cls.__name__


class EnsurePluginDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_dir_and_readme(self):
        target = self.tmp / "plugins"
        result = ensure_plugin_dir(target)
        self.assertEqual(result, target)
        self.assertTrue(target.is_dir())
        self.assertTrue((target / "README.txt").exists())

    def test_idempotent(self):
        target = self.tmp / "plugins"
        ensure_plugin_dir(target)
        (target / "README.txt").write_text("custom", encoding="utf-8")
        ensure_plugin_dir(target)
        self.assertEqual((target / "README.txt").read_text(encoding="utf-8"), "custom")


class DiscoverPluginHandlersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_plugin(self, name, content):
        (self.tmp / name).write_text(content, encoding="utf-8")

    def test_missing_dir_returns_empty(self):
        classes, setups, names = discover_plugin_handlers(self.tmp / "nope")
        self.assertEqual((classes, setups, names), ([], [], []))

    def test_empty_dir_returns_empty(self):
        classes, setups, names = discover_plugin_handlers(self.tmp)
        self.assertEqual((classes, setups, names), ([], [], []))

    def test_loads_handler_subclass(self):
        self.write_plugin("hello.py", (
            "from handlers.base import Handler\n"
            "class HelloHandler(Handler):\n"
            "    intents = {'HELLO'}\n"
            "    def handle(self, text, intent):\n"
            "        return 'hi'\n"
        ))
        classes, setups, names = discover_plugin_handlers(self.tmp)
        self.assertEqual([c.__name__ for c in classes], ["HelloHandler"])
        self.assertEqual(setups, [])
        self.assertEqual(names, ["hello"])

    def test_loads_setup_function(self):
        self.write_plugin("skilled.py", (
            "def setup(app):\n"
            "    app.marker = 'set-up'\n"
        ))
        classes, setups, names = discover_plugin_handlers(self.tmp)
        self.assertEqual(classes, [])
        self.assertEqual(len(setups), 1)
        self.assertEqual(names, ["skilled"])

    def test_skips_underscore_prefixed_files(self):
        self.write_plugin("_ignored.py", "raise RuntimeError('should not run')\n")
        classes, setups, names = discover_plugin_handlers(self.tmp)
        self.assertEqual(names, [])

    def test_broken_plugin_is_skipped_not_raised(self):
        self.write_plugin("broken.py", "this is not valid python (((\n")
        self.write_plugin("good.py", (
            "from handlers.base import Handler\n"
            "class GoodHandler(Handler):\n"
            "    intents = {'GOOD'}\n"
        ))
        classes, setups, names = discover_plugin_handlers(self.tmp)
        self.assertEqual([c.__name__ for c in classes], ["GoodHandler"])
        self.assertEqual(names, ["good"])

    def test_ignores_non_python_files(self):
        self.write_plugin("notes.txt", "not python")
        classes, setups, names = discover_plugin_handlers(self.tmp)
        self.assertEqual(names, [])

    def test_loads_multiple_plugins_sorted(self):
        self.write_plugin("b_plugin.py", "from handlers.base import Handler\nclass BH(Handler):\n    intents = set()\n")
        self.write_plugin("a_plugin.py", "from handlers.base import Handler\nclass AH(Handler):\n    intents = set()\n")
        classes, setups, names = discover_plugin_handlers(self.tmp)
        self.assertEqual(names, ["a_plugin", "b_plugin"])
        self.assertEqual([c.__name__ for c in classes], ["AH", "BH"])


class RunPluginSetupTests(unittest.TestCase):
    def test_calls_each_setup_fn(self):
        app = Mock()
        calls = []
        run_plugin_setup(app, [lambda a: calls.append(a)])
        self.assertEqual(calls, [app])

    def test_one_failing_setup_does_not_block_others(self):
        app = Mock()
        calls = []

        def boom(a):
            raise RuntimeError("nope")

        run_plugin_setup(app, [boom, lambda a: calls.append(a)])
        self.assertEqual(calls, [app])


if __name__ == "__main__":
    unittest.main()
