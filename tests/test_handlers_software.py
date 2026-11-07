"""SoftwareHandler: confirm-gated install/uninstall/upgrade, unconfirmed search/list."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.software import SoftwareHandler
from skills.software_manager import Package


class FakeApp:
    def __init__(self):
        self.software_manager = Mock()
        self.software_manager.format_list.side_effect = (
            lambda pkgs, empty: empty if not pkgs else "\n".join(f"• {p}" for p in pkgs))
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class SoftwareHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = SoftwareHandler(self.app)

    def test_install_asks_to_confirm_and_does_not_run_yet(self):
        reply = self.h.handle("install VLC", "SOFTWARE")
        self.assertIn("Install 'VLC'?", reply)
        self.assertEqual(self.app.pending[-1][0], "install_app")
        self.app.software_manager.install.assert_not_called()
        self.app.pending[-1][1]()
        self.app.software_manager.install.assert_called_once_with("VLC")

    def test_uninstall_asks_to_confirm(self):
        self.h.handle("uninstall notepad++", "SOFTWARE")
        self.assertEqual(self.app.pending[-1][0], "uninstall_app_winget")
        self.app.pending[-1][1]()
        self.app.software_manager.uninstall.assert_called_once_with("notepad++")

    def test_upgrade_one_asks_to_confirm(self):
        self.h.handle("upgrade chrome", "SOFTWARE")
        self.assertEqual(self.app.pending[-1][0], "upgrade_app")
        self.app.pending[-1][1]()
        self.app.software_manager.upgrade.assert_called_once_with("chrome")

    def test_upgrade_all_asks_to_confirm(self):
        self.h.handle("update all my apps", "SOFTWARE")
        self.assertEqual(self.app.pending[-1][0], "upgrade_all_apps")
        self.app.pending[-1][1]()
        self.app.software_manager.upgrade.assert_called_once_with("")

    def test_search_runs_immediately_no_confirm(self):
        self.app.software_manager.search.return_value = [Package("VLC media player", "VideoLAN.VLC")]
        reply = self.h.handle("search for vlc in winget", "SOFTWARE")
        self.app.software_manager.search.assert_called_once_with("vlc")
        self.assertFalse(self.app.pending)
        self.assertIn("VLC media player", reply)

    def test_is_installed_runs_immediately(self):
        self.app.software_manager.is_installed.return_value = True
        reply = self.h.handle("is python installed", "SOFTWARE")
        self.assertFalse(self.app.pending)
        self.assertIn("Yes, python is installed", reply)

    def test_is_installed_false(self):
        self.app.software_manager.is_installed.return_value = False
        reply = self.h.handle("is python installed", "SOFTWARE")
        self.assertIn("don't see python installed", reply)

    def test_list_installed_runs_immediately(self):
        self.app.software_manager.list_installed.return_value = [Package("7-Zip", "7zip.7zip")]
        reply = self.h.handle("list installed apps", "SOFTWARE")
        self.assertFalse(self.app.pending)
        self.assertIn("7-Zip", reply)

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "SOFTWARE"))

    def test_no_software_manager_gives_a_plain_message(self):
        app = FakeApp()
        app.software_manager = None
        h = SoftwareHandler(app)
        self.assertEqual(h.handle("install vlc", "SOFTWARE"), "Software management isn't available.")

    def test_register_tools_marks_writes_as_confirm(self):
        app = FakeApp()
        h = SoftwareHandler(app)
        tools = ToolRegistry()
        h.register_tools(tools)
        for name in ("install_software", "uninstall_software", "upgrade_software"):
            self.assertTrue(tools.get(name).confirm, name)
        for name in ("search_software", "list_installed_software", "is_software_installed"):
            self.assertFalse(tools.get(name).confirm, name)


if __name__ == "__main__":
    unittest.main()
