"""WebDashboardHandler: starting confirms (opens the PC to network commands);
stopping and status don't."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.web_dashboard import WebDashboardHandler


class FakeApp:
    def __init__(self):
        self.web_dashboard = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class WebDashboardHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = WebDashboardHandler(self.app)

    def test_start_confirms(self):
        reply = self.h.handle("start the dashboard", "DASHBOARD")
        self.assertEqual(self.app.pending[-1][0], "start_dashboard")
        self.app.web_dashboard.start.assert_not_called()
        self.assertIn("Reply yes", reply)
        self.app.pending[-1][1]()
        self.app.web_dashboard.start.assert_called_once()

    def test_enable_alias_confirms(self):
        self.h.handle("enable the web dashboard", "DASHBOARD")
        self.assertEqual(self.app.pending[-1][0], "start_dashboard")

    def test_stop_runs_immediately(self):
        self.app.web_dashboard.stop.return_value = "Dashboard stopped."
        reply = self.h.handle("stop the dashboard", "DASHBOARD")
        self.assertFalse(self.app.pending)
        self.app.web_dashboard.stop.assert_called_once()
        self.assertEqual(reply, "Dashboard stopped.")

    def test_disable_alias_runs_immediately(self):
        self.h.handle("disable the dashboard", "DASHBOARD")
        self.app.web_dashboard.stop.assert_called_once()

    def test_status_runs_immediately(self):
        self.app.web_dashboard.status.return_value = "Dashboard running at http://..."
        reply = self.h.handle("dashboard status", "DASHBOARD")
        self.assertFalse(self.app.pending)
        self.app.web_dashboard.status.assert_called_once()
        self.assertIn("running", reply)

    def test_is_dashboard_running(self):
        self.h.handle("is the dashboard running", "DASHBOARD")
        self.app.web_dashboard.status.assert_called_once()

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "DASHBOARD"))

    def test_no_web_dashboard(self):
        app = FakeApp()
        app.web_dashboard = None
        h = WebDashboardHandler(app)
        self.assertEqual(h.handle("dashboard status", "DASHBOARD"), "The web dashboard isn't available.")

    def test_register_tools_confirm_gating(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        self.assertTrue(t.get("start_web_dashboard").confirm)
        self.assertFalse(t.get("stop_web_dashboard").confirm)
        self.assertFalse(t.get("web_dashboard_status").confirm)

    def test_register_tools_no_web_dashboard(self):
        app = FakeApp()
        app.web_dashboard = None
        h = WebDashboardHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("start_web_dashboard"))


if __name__ == "__main__":
    unittest.main()
