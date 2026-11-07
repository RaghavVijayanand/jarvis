"""PowerHandler: reads (plan listing/status, startup app listing) run immediately;
switching a power plan or toggling a startup app confirms first."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.power import PowerHandler


class FakeApp:
    def __init__(self):
        self.power_manager = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class PowerHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = PowerHandler(self.app)

    def test_list_power_plans_runs_immediately(self):
        self.app.power_manager.list_power_plans.return_value = "• Balanced (active)"
        reply = self.h.handle("list power plans", "POWER")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "• Balanced (active)")

    def test_active_power_plan_runs_immediately(self):
        self.app.power_manager.active_power_plan.return_value = "Active power plan: Balanced"
        reply = self.h.handle("what is the active power plan", "POWER")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "Active power plan: Balanced")

    def test_set_power_plan_confirms(self):
        self.h.handle("switch the power plan to balanced", "POWER")
        self.assertEqual(self.app.pending[-1][0], "set_power_plan")
        self.app.power_manager.set_power_plan.assert_not_called()
        self.app.pending[-1][1]()
        self.app.power_manager.set_power_plan.assert_called_once_with("balanced")

    def test_list_startup_apps_runs_immediately(self):
        self.app.power_manager.list_startup_apps.return_value = "• OneDrive (HKCU) — enabled"
        reply = self.h.handle("list startup apps", "POWER")
        self.assertFalse(self.app.pending)
        self.assertIn("OneDrive", reply)

    def test_enable_startup_confirms(self):
        self.h.handle("enable OneDrive at startup", "POWER")
        self.assertEqual(self.app.pending[-1][0], "enable_startup_app")
        self.app.pending[-1][1]()
        self.app.power_manager.enable_startup_app.assert_called_once_with("OneDrive")

    def test_disable_startup_confirms(self):
        self.h.handle("disable Spotify from startup", "POWER")
        self.assertEqual(self.app.pending[-1][0], "disable_startup_app")
        self.app.pending[-1][1]()
        self.app.power_manager.disable_startup_app.assert_called_once_with("Spotify")

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "POWER"))

    def test_no_power_manager(self):
        app = FakeApp()
        app.power_manager = None
        h = PowerHandler(app)
        self.assertEqual(h.handle("list power plans", "POWER"), "Power/startup management isn't available.")

    def test_register_tools_confirm_gating(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        writes = ("set_power_plan", "enable_startup_app", "disable_startup_app")
        reads = ("list_power_plans", "active_power_plan", "list_startup_apps")
        for name in writes:
            self.assertTrue(t.get(name).confirm, name)
        for name in reads:
            self.assertFalse(t.get(name).confirm, name)

    def test_register_tools_no_power_manager(self):
        app = FakeApp()
        app.power_manager = None
        h = PowerHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("list_power_plans"))


if __name__ == "__main__":
    unittest.main()
