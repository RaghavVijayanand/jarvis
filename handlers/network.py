"""Wi-Fi, network diagnostics and VPN. Reading/diagnosing runs immediately;
connecting, forgetting a network, or dialing a VPN always confirms first."""
import re

from core.tools import params
from handlers.base import Handler

_LIST_WIFI = re.compile(r"\b(?:list|show|scan for)\s+(?:nearby\s+)?wi-?fi\s+networks\b|"
                        r"\bwhat wi-?fi networks?\b", re.I)
_SAVED_WIFI = re.compile(r"\b(?:list|show)\s+saved\s+wi-?fi\b", re.I)
_CURRENT_WIFI = re.compile(r"\bwhat wi-?fi (?:am i|are we) (?:on|connected to)\b|"
                           r"\bcurrent wi-?fi\b|\bwi-?fi status\b", re.I)
_CONNECT_WIFI = re.compile(r"^(?:please\s+)?connect to (?:the\s+)?wi-?fi\s+(.+?)[.!?]*$|"
                           r"^(?:please\s+)?join (?:the\s+)?wi-?fi\s+(.+?)[.!?]*$", re.I)
_FORGET_WIFI = re.compile(r"^(?:please\s+)?forget (?:the\s+)?wi-?fi\s+(.+?)[.!?]*$", re.I)
_DISCONNECT_WIFI = re.compile(r"\bdisconnect (?:from )?wi-?fi\b|\bturn off wi-?fi\b", re.I)
_PING = re.compile(r"^(?:please\s+)?ping\s+(\S+)[.!?]*$", re.I)
_FLUSH_DNS = re.compile(r"\bflush(?:ing)? (?:the )?dns\b", re.I)
# "what's my ip" is already handled as SYSTEM intent (handlers/info.py); ip_config
# below is reachable as a tool call and via the more explicit "network config" phrasing.
_IP_CONFIG = re.compile(r"\bnetwork config(?:uration)?\b|\bshow (?:my )?ip config(?:uration)?\b", re.I)
_VPN_LIST = re.compile(r"\b(?:list|show)\s+vpn(?:\s+connections)?\b", re.I)


class NetworkHandler(Handler):
    intents = {"NETWORK"}

    def handle(self, text, intent):
        app = self.app
        net = getattr(app, "network_manager", None)
        if net is None:
            return "Network control isn't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        if _LIST_WIFI.search(low):
            return net.list_wifi_networks()
        if _SAVED_WIFI.search(low):
            return net.list_saved_wifi_profiles()
        if _CURRENT_WIFI.search(low):
            return net.current_wifi()
        if _DISCONNECT_WIFI.search(low):
            return confirm("Disconnect from Wi-Fi?", net.disconnect_wifi, "disconnect_wifi")
        m = _CONNECT_WIFI.match(low)
        if m:
            ssid = (m.group(1) or m.group(2)).strip().strip('"\'')
            return confirm(f"Connect to Wi-Fi '{ssid}'?", lambda: net.connect_wifi(ssid), "connect_wifi")
        m = _FORGET_WIFI.match(low)
        if m:
            ssid = m.group(1).strip().strip('"\'')
            return confirm(f"Forget the Wi-Fi network '{ssid}'?", lambda: net.forget_wifi(ssid), "forget_wifi")
        m = _PING.match(low)
        if m:
            return net.ping(m.group(1))
        if _FLUSH_DNS.search(low):
            return net.flush_dns()
        if _IP_CONFIG.search(low):
            return net.ip_config()
        if _VPN_LIST.search(low):
            return net.list_vpn_connections()
        return None

    def register_tools(self, t):
        net = getattr(self.app, "network_manager", None)
        if net is None:
            return
        t.add("list_wifi_networks", "List nearby Wi-Fi networks.", net.list_wifi_networks)
        t.add("current_wifi", "Show the Wi-Fi network currently connected to.", net.current_wifi)
        t.add("list_saved_wifi_profiles", "List saved Wi-Fi network profiles.", net.list_saved_wifi_profiles)
        t.add("connect_wifi", "Connect to a saved Wi-Fi network by name.", net.connect_wifi,
              params(["ssid"], ssid=("string", "Network name (SSID)")),
              confirm=True, confirm_text="Connect to Wi-Fi '{ssid}'?")
        t.add("forget_wifi", "Remove a saved Wi-Fi network profile.", net.forget_wifi,
              params(["ssid"], ssid=("string", "Network name (SSID)")),
              confirm=True, confirm_text="Forget the Wi-Fi network '{ssid}'?")
        t.add("disconnect_wifi", "Disconnect from the current Wi-Fi network.", net.disconnect_wifi,
              confirm=True, confirm_text="Disconnect from Wi-Fi?")
        t.add("ping_host", "Ping a host to check connectivity/latency.", net.ping,
              params(["host"], host=("string", "Hostname or IP"), count=("integer", "Number of pings (max 10)")))
        t.add("ip_config", "Show active network adapters and their IPv4 addresses.", net.ip_config)
        t.add("flush_dns", "Flush the local DNS resolver cache.", net.flush_dns)
        t.add("check_port", "Check whether a host/port is reachable.", net.check_port,
              params(["host", "port"], host=("string", "Hostname or IP"), port=("integer", "Port number")))
        t.add("list_vpn_connections", "List active VPN (RAS) connections.", net.list_vpn_connections)
        # No password parameter: it would pass through the model, the confirmation text and the
        # tool log, and land on rasdial's command line. Windows uses the connection's saved credentials.
        t.add("connect_vpn", "Dial a configured VPN connection by name (uses its saved credentials).",
              lambda name: net.connect_vpn(name),
              params(["name"], name=("string", "VPN connection name, as configured in Windows")),
              confirm=True, confirm_text="Connect to VPN '{name}'?")
        t.add("disconnect_vpn", "Disconnect a VPN connection by name.", net.disconnect_vpn,
              params(["name"], name=("string", "VPN connection name")),
              confirm=True, confirm_text="Disconnect VPN '{name}'?")
