"""SecurityHandler: status reads run immediately; starting a Defender scan or
installing updates confirms first."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.security import SecurityHandler


class FakeApp:
    def __init__(self):
        self.security_checks = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class SecurityHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = SecurityHandler(self.app)

    def test_defender_status_runs_immediately(self):
        self.app.security_checks.defender_status.return_value = "Antivirus enabled: True."
        reply = self.h.handle("defender status", "SECURITY")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "Antivirus enabled: True.")

    def test_start_scan_confirms_quick_by_default(self):
        self.h.handle("run a defender scan", "SECURITY")
        self.assertEqual(self.app.pending[-1][0], "start_defender_scan")
        self.app.security_checks.start_defender_scan.assert_not_called()
        self.app.pending[-1][1]()
        self.app.security_checks.start_defender_scan.assert_called_once_with("quick")

    def test_start_scan_confirms_full(self):
        self.h.handle("start a full defender scan", "SECURITY")
        self.app.pending[-1][1]()
        self.app.security_checks.start_defender_scan.assert_called_once_with("full")

    def test_bitlocker_status_runs_immediately(self):
        self.app.security_checks.bitlocker_status.return_value = "C: — BitLocker protection is on."
        reply = self.h.handle("bitlocker status", "SECURITY")
        self.assertFalse(self.app.pending)
        self.assertIn("BitLocker", reply)

    def test_check_windows_update_runs_immediately(self):
        self.app.security_checks.check_windows_update.return_value = "Windows is up to date."
        reply = self.h.handle("check for windows updates", "SECURITY")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "Windows is up to date.")

    def test_install_updates_confirms(self):
        self.h.handle("install windows updates", "SECURITY")
        self.assertEqual(self.app.pending[-1][0], "install_windows_updates")
        self.app.security_checks.install_windows_updates.assert_not_called()
        self.app.pending[-1][1]()
        self.app.security_checks.install_windows_updates.assert_called_once()

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "SECURITY"))

    def test_no_security_checks(self):
        app = FakeApp()
        app.security_checks = None
        h = SecurityHandler(app)
        self.assertEqual(h.handle("defender status", "SECURITY"), "Security checks aren't available.")

    def test_register_tools_confirm_gating(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        writes = ("start_defender_scan", "install_windows_updates")
        reads = ("defender_status", "bitlocker_status", "check_windows_update")
        for name in writes:
            self.assertTrue(t.get(name).confirm, name)
        for name in reads:
            self.assertFalse(t.get(name).confirm, name)

    def test_register_tools_no_security_checks(self):
        app = FakeApp()
        app.security_checks = None
        h = SecurityHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("defender_status"))


if __name__ == "__main__":
    unittest.main()
