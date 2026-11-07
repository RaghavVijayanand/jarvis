"""NetworkHandler: reads run immediately, Wi-Fi/VPN connect/forget/disconnect confirm first."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.network import NetworkHandler


class FakeApp:
    def __init__(self):
        self.network_manager = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class NetworkHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = NetworkHandler(self.app)

    def test_list_wifi_runs_immediately(self):
        self.app.network_manager.list_wifi_networks.return_value = "• HomeNet"
        reply = self.h.handle("list wifi networks", "NETWORK")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "• HomeNet")

    def test_connect_wifi_confirms(self):
        self.h.handle("connect to wifi HomeNet", "NETWORK")
        self.assertEqual(self.app.pending[-1][0], "connect_wifi")
        self.app.network_manager.connect_wifi.assert_not_called()
        self.app.pending[-1][1]()
        self.app.network_manager.connect_wifi.assert_called_once_with("HomeNet")

    def test_forget_wifi_confirms(self):
        self.h.handle("forget the wifi HomeNet", "NETWORK")
        self.assertEqual(self.app.pending[-1][0], "forget_wifi")
        self.app.pending[-1][1]()
        self.app.network_manager.forget_wifi.assert_called_once_with("HomeNet")

    def test_disconnect_wifi_confirms(self):
        self.h.handle("disconnect wifi", "NETWORK")
        self.assertEqual(self.app.pending[-1][0], "disconnect_wifi")

    def test_ping_runs_immediately(self):
        self.app.network_manager.ping.return_value = "4 packets sent"
        reply = self.h.handle("ping google.com", "NETWORK")
        self.assertFalse(self.app.pending)
        self.app.network_manager.ping.assert_called_once_with("google.com")
        self.assertEqual(reply, "4 packets sent")

    def test_flush_dns_runs_immediately(self):
        self.h.handle("flush the dns", "NETWORK")
        self.assertFalse(self.app.pending)
        self.app.network_manager.flush_dns.assert_called_once()

    def test_vpn_list_runs_immediately(self):
        self.h.handle("list vpn connections", "NETWORK")
        self.assertFalse(self.app.pending)
        self.app.network_manager.list_vpn_connections.assert_called_once()

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "NETWORK"))

    def test_no_network_manager(self):
        app = FakeApp()
        app.network_manager = None
        h = NetworkHandler(app)
        self.assertEqual(h.handle("ping google.com", "NETWORK"), "Network control isn't available.")

    def test_register_tools_confirm_gating(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        writes = ("connect_wifi", "forget_wifi", "disconnect_wifi", "connect_vpn", "disconnect_vpn")
        reads = ("list_wifi_networks", "current_wifi", "list_saved_wifi_profiles", "ping_host",
                 "ip_config", "flush_dns", "check_port", "list_vpn_connections")
        for name in writes:
            self.assertTrue(t.get(name).confirm, name)
        for name in reads:
            self.assertFalse(t.get(name).confirm, name)


if __name__ == "__main__":
    unittest.main()
