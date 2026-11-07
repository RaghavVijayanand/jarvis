"""AdminHandler: never intercepts text (tools only), and registers every admin tool
with the right confirm gating (writes confirm, reads don't)."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.admin import AdminHandler


class FakeApp:
    def __init__(self):
        self.system_admin = Mock()


class AdminHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = AdminHandler(self.app)

    def test_never_handles_text_directly(self):
        self.assertIsNone(self.h.handle("open port 8080", "GENERAL"))
        self.assertEqual(self.h.intents, set())

    def test_no_system_admin_registers_nothing(self):
        app = FakeApp()
        app.system_admin = None
        t = ToolRegistry()
        AdminHandler(app).register_tools(t)
        self.assertEqual(t.names(), [])

    def test_reads_do_not_confirm_writes_do(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        reads = ("is_admin", "read_registry_value", "list_firewall_rules", "list_scheduled_tasks")
        writes = ("run_elevated_command", "write_registry_value", "delete_registry_value",
                  "add_firewall_rule", "remove_firewall_rule", "create_scheduled_task",
                  "delete_scheduled_task")
        for name in reads:
            self.assertFalse(t.get(name).confirm, name)
        for name in writes:
            self.assertTrue(t.get(name).confirm, name)

    def test_registry_write_calls_through_to_skill(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        t.get("write_registry_value").func("HKCU", r"Software\X", "N", "v", "dword")
        self.app.system_admin.write_registry_value.assert_called_once_with("HKCU", r"Software\X", "N", "v", "dword")


if __name__ == "__main__":
    unittest.main()
