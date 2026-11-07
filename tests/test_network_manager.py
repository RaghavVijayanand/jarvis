"""NetworkManager: Wi-Fi, diagnostics and VPN via netsh/ping/ipconfig/rasdial, all
mocked so these run without Windows."""
import socket
import subprocess
import unittest
from unittest.mock import Mock, patch

from skills.network_manager import NetworkManager


def proc(stdout="", returncode=0, stderr=""):
    return Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class WifiTests(unittest.TestCase):
    def setUp(self):
        self.net = NetworkManager()

    def test_list_networks(self):
        out = "SSID 1 : HomeNet\nSSID 2 : CoffeeShop\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.net.list_wifi_networks()
        self.assertIn("HomeNet", result)
        self.assertIn("CoffeeShop", result)

    def test_list_networks_no_adapter(self):
        with patch("subprocess.run", return_value=proc("There is no wireless interface on the system.")):
            self.assertIn("No Wi-Fi adapter", self.net.list_wifi_networks())

    def test_list_networks_missing_netsh(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("isn't available", self.net.list_wifi_networks())

    def test_current_wifi_connected(self):
        out = "    Name                   : Wi-Fi\n    State                  : connected\n    SSID                   : HomeNet\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.net.current_wifi()
        self.assertIn("HomeNet", result)
        self.assertIn("connected", result)

    def test_current_wifi_disconnected(self):
        with patch("subprocess.run", return_value=proc("There is 1 interface on the system.\n    Name : Wi-Fi\n")):
            self.assertIn("Not connected", self.net.current_wifi())

    def test_saved_profiles(self):
        out = "    All User Profile     : HomeNet\n    All User Profile     : Office\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.net.list_saved_wifi_profiles()
        self.assertIn("HomeNet", result)
        self.assertIn("Office", result)

    def test_connect_success(self):
        with patch("subprocess.run", return_value=proc("Connection request was completed successfully.", 0)):
            self.assertIn("Connecting to 'HomeNet'", self.net.connect_wifi("HomeNet"))

    def test_connect_no_saved_profile(self):
        with patch("subprocess.run", return_value=proc("", 1, "The profile 'X' is not found.")):
            result = self.net.connect_wifi("X")
        self.assertIn("no saved profile", result)

    def test_forget_success(self):
        with patch("subprocess.run", return_value=proc("Profile HomeNet is deleted", 0)):
            self.assertIn("Forgot 'HomeNet'", self.net.forget_wifi("HomeNet"))

    def test_disconnect(self):
        with patch("subprocess.run", return_value=proc("", 0)):
            self.assertIn("Disconnected", self.net.disconnect_wifi())


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.net = NetworkManager()

    def test_ping_no_host(self):
        self.assertIn("Ping what host", self.net.ping(""))

    def test_ping_success(self):
        out = "Pinging google.com [1.2.3.4]\nReply from 1.2.3.4\n\nPing statistics:\n    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)"
        with patch("subprocess.run", return_value=proc(out, 0)):
            result = self.net.ping("google.com")
        self.assertIn("Packets", result)

    def test_ping_failure(self):
        with patch("subprocess.run", return_value=proc("Request timed out.", 1)):
            result = self.net.ping("nope.invalid")
        self.assertIn("Couldn't reach", result)

    def test_flush_dns(self):
        with patch("subprocess.run", return_value=proc("Successfully flushed", 0)):
            self.assertIn("flushed", self.net.flush_dns())

    def test_ip_config_parses_adapter_and_ip(self):
        out = ("Windows IP Configuration\n\n"
               "Wireless LAN adapter Wi-Fi:\n\n"
               "   Connection-specific DNS Suffix  . :\n"
               "   IPv4 Address. . . . . . . . . . . : 192.168.1.42\n"
               "   Subnet Mask . . . . . . . . . . . : 255.255.255.0\n")
        with patch("subprocess.run", return_value=proc(out)):
            result = self.net.ip_config()
        self.assertIn("192.168.1.42", result)

    def test_check_port_open(self):
        with patch("socket.create_connection", return_value=Mock(__enter__=Mock(return_value=Mock()),
                                                                  __exit__=Mock(return_value=False))):
            result = self.net.check_port("example.com", 443)
        self.assertIn("is open", result)

    def test_check_port_closed(self):
        with patch("socket.create_connection", side_effect=OSError(0, "Connection refused")):
            result = self.net.check_port("example.com", 9999)
        self.assertIn("closed or unreachable", result)

    def test_check_port_timeout(self):
        with patch("socket.create_connection", side_effect=socket.timeout()):
            result = self.net.check_port("example.com", 9999)
        self.assertIn("timed out", result)

    def test_check_port_bad_port(self):
        self.assertIn("numeric port", self.net.check_port("example.com", "not-a-port"))


class VpnTests(unittest.TestCase):
    def setUp(self):
        self.net = NetworkManager()

    def test_list_no_connections(self):
        with patch("subprocess.run", return_value=proc("No connections\n")):
            self.assertIn("No active VPN", self.net.list_vpn_connections())

    def test_list_with_connections(self):
        with patch("subprocess.run", return_value=proc("OfficeVPN\n")):
            self.assertIn("OfficeVPN", self.net.list_vpn_connections())

    def test_connect_success(self):
        with patch("subprocess.run", return_value=proc("Successfully connected", 0)):
            self.assertIn("Connected to VPN 'Office'", self.net.connect_vpn("Office"))

    def test_connect_failure(self):
        with patch("subprocess.run", return_value=proc("", 1, "Error 623")):
            result = self.net.connect_vpn("Office")
        self.assertIn("Couldn't connect", result)

    def test_disconnect(self):
        with patch("subprocess.run", return_value=proc("", 0)):
            self.assertIn("Disconnected 'Office'", self.net.disconnect_vpn("Office"))

    def test_rasdial_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("isn't available", self.net.list_vpn_connections())


if __name__ == "__main__":
    unittest.main()
