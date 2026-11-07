"""ServiceHandler: top-process/list/status reads run immediately, start/stop/restart confirm first."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.service import ServiceHandler


class FakeApp:
    def __init__(self):
        self.service_manager = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class ServiceHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = ServiceHandler(self.app)

    def test_top_cpu_runs_immediately(self):
        self.app.service_manager.top_processes.return_value = " 40.0%    200 MB  chrome.exe (pid 100)"
        reply = self.h.handle("what is using my cpu", "SERVICE")
        self.assertFalse(self.app.pending)
        self.app.service_manager.top_processes.assert_called_once_with(by="cpu")
        self.assertIn("chrome.exe", reply)

    def test_top_memory_runs_immediately(self):
        self.h.handle("top processes by memory", "SERVICE")
        self.assertFalse(self.app.pending)
        self.app.service_manager.top_processes.assert_called_once_with(by="memory")

    def test_what_is_using_my_ram_routes_to_memory(self):
        self.h.handle("what is using my ram", "SERVICE")
        self.app.service_manager.top_processes.assert_called_once_with(by="memory")

    def test_list_services_runs_immediately(self):
        self.app.service_manager.list_services.return_value = "• Print Spooler (Spooler)"
        reply = self.h.handle("list services", "SERVICE")
        self.assertFalse(self.app.pending)
        self.app.service_manager.list_services.assert_called_once_with(running_only=False)
        self.assertIn("Print Spooler", reply)

    def test_list_running_services(self):
        self.h.handle("list running services", "SERVICE")
        self.app.service_manager.list_services.assert_called_once_with(running_only=True)

    def test_service_status_runs_immediately(self):
        self.app.service_manager.service_status.return_value = "'Spooler' is running."
        reply = self.h.handle("is the spooler service running", "SERVICE")
        self.assertFalse(self.app.pending)
        self.app.service_manager.service_status.assert_called_once_with("spooler")
        self.assertEqual(reply, "'Spooler' is running.")

    def test_start_service_confirms(self):
        self.h.handle("start the spooler service", "SERVICE")
        self.assertEqual(self.app.pending[-1][0], "start_service")
        self.app.service_manager.start_service.assert_not_called()
        self.app.pending[-1][1]()
        self.app.service_manager.start_service.assert_called_once_with("spooler")

    def test_stop_service_confirms(self):
        self.h.handle("stop the spooler service", "SERVICE")
        self.assertEqual(self.app.pending[-1][0], "stop_service")
        self.app.pending[-1][1]()
        self.app.service_manager.stop_service.assert_called_once_with("spooler")

    def test_restart_service_confirms(self):
        self.h.handle("restart the spooler service", "SERVICE")
        self.assertEqual(self.app.pending[-1][0], "restart_service")
        self.app.pending[-1][1]()
        self.app.service_manager.restart_service.assert_called_once_with("spooler")

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "SERVICE"))

    def test_no_service_manager(self):
        app = FakeApp()
        app.service_manager = None
        h = ServiceHandler(app)
        self.assertEqual(h.handle("list services", "SERVICE"), "Service control isn't available.")

    def test_register_tools_confirm_gating(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        writes = ("start_service", "stop_service", "restart_service")
        reads = ("top_processes", "list_services", "service_status")
        for name in writes:
            self.assertTrue(t.get(name).confirm, name)
        for name in reads:
            self.assertFalse(t.get(name).confirm, name)

    def test_register_tools_no_service_manager(self):
        app = FakeApp()
        app.service_manager = None
        h = ServiceHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("top_processes"))


if __name__ == "__main__":
    unittest.main()
