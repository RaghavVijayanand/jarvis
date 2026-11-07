"""Networking: Wi-Fi, basic diagnostics and VPN, all via built-in Windows CLIs
(netsh, ping, ipconfig, rasdial) — no extra packages needed.

Connecting/forgetting a Wi-Fi network and VPN actions are confirm-gated by the
caller (handlers/network.py); diagnostics and listing are read-only and run
immediately.
"""
from __future__ import annotations

import re
import subprocess
from typing import List, Optional

from core.logging_setup import get_logger

log = get_logger("jarvis.network")

_TIMEOUT = 15


def console_encoding() -> str:
    """netsh/sc/ipconfig/ping/powercfg write the OEM code page (e.g. cp437) to a pipe, not
    UTF-8: decoding them as UTF-8 garbles any SSID or name with an accent ('Café' → 'Caf�')."""
    try:
        import codecs
        return codecs.lookup("oem").name
    except LookupError:          # not Windows
        return "utf-8"


def _run(args: List[str], timeout: int = _TIMEOUT) -> "subprocess.CompletedProcess[str]":
    # stdin=DEVNULL: a CLI that wants to prompt (rasdial asks for a missing password) must fail
    # at once instead of blocking the worker until the timeout.
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          encoding=console_encoding(), errors="replace", check=False)


def _option_like(value: str) -> bool:
    """A host/name the CLI would read as a switch ('-t', '/?'), not as data."""
    return value.startswith(("-", "/"))


class NetworkManager:
    """Wi-Fi, ping/DNS/port diagnostics and VPN dialing."""

    # ── Wi-Fi ────────────────────────────────────────────────────────────────

    def list_wifi_networks(self) -> str:
        try:
            proc = _run(["netsh", "wlan", "show", "networks", "mode=bssid"])
        except FileNotFoundError:
            return "Wi-Fi control isn't available on this machine."
        except subprocess.TimeoutExpired:
            return "Listing Wi-Fi networks timed out."
        if "no wireless interface" in proc.stdout.lower():
            return "No Wi-Fi adapter found."
        names = re.findall(r"^SSID\s+\d+\s*:\s*(.*)$", proc.stdout, re.M)
        names = [n.strip() for n in names if n.strip()]
        return "\n".join(f"• {n}" for n in names) if names else "No Wi-Fi networks found nearby."

    def current_wifi(self) -> str:
        try:
            proc = _run(["netsh", "wlan", "show", "interfaces"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't check Wi-Fi status: {exc}"
        m = re.search(r"^\s*SSID\s*:\s*(.+)$", proc.stdout, re.M)
        state = re.search(r"^\s*State\s*:\s*(.+)$", proc.stdout, re.M)
        if not m:
            return "Not connected to any Wi-Fi network."
        return f"Connected to '{m.group(1).strip()}'" + (f" ({state.group(1).strip()})" if state else "")

    def list_saved_wifi_profiles(self) -> str:
        try:
            proc = _run(["netsh", "wlan", "show", "profiles"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't list saved networks: {exc}"
        names = re.findall(r"^\s*All User Profile\s*:\s*(.+)$", proc.stdout, re.M)
        names = [n.strip() for n in names]
        return "\n".join(f"• {n}" for n in names) if names else "No saved Wi-Fi profiles."

    def connect_wifi(self, ssid: str) -> str:
        try:
            # A saved profile connects by name; a network never connected to before
            # needs its password, which JARVIS doesn't collect over voice/text — point
            # the user at the one flow that's actually safe for that.
            proc = _run(["netsh", "wlan", "connect", f"name={ssid}"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't connect to Wi-Fi: {exc}"
        if proc.returncode == 0:
            return f"Connecting to '{ssid}'…"
        if "no profile" in (proc.stdout + proc.stderr).lower() or "not found" in (proc.stdout + proc.stderr).lower():
            return (f"There's no saved profile for '{ssid}'. Connect to it once from Windows' own Wi-Fi "
                    f"menu (so the password stays out of chat), and I can reconnect to it after that.")
        return f"Couldn't connect to '{ssid}': {(proc.stdout + proc.stderr).strip()[-300:]}"

    def forget_wifi(self, ssid: str) -> str:
        try:
            proc = _run(["netsh", "wlan", "delete", "profile", f"name={ssid}"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't forget the network: {exc}"
        combined = (proc.stdout + proc.stderr).strip()
        return f"Forgot '{ssid}'." if proc.returncode == 0 else f"Couldn't forget '{ssid}': {combined[-300:]}"

    def disconnect_wifi(self) -> str:
        try:
            proc = _run(["netsh", "wlan", "disconnect"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't disconnect: {exc}"
        return "Disconnected from Wi-Fi." if proc.returncode == 0 else "Couldn't disconnect from Wi-Fi."

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def ping(self, host: str, count: int = 4) -> str:
        host = (host or "").strip()
        if not host:
            return "Ping what host?"
        if _option_like(host) or any(ch.isspace() for ch in host):
            return f"'{host}' isn't a host name or IP address."
        try:
            count = max(1, min(10, int(count)))
        except (TypeError, ValueError):
            count = 4
        try:
            proc = _run(["ping", "-n", str(count), host], timeout=_TIMEOUT + count * 2)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Ping failed: {exc}"
        summary = re.search(r"Packets:.*|Minimum = .*", proc.stdout)
        if proc.returncode == 0:
            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            return "\n".join(lines[-4:]) if lines else f"{host} replied."
        return f"Couldn't reach {host}." + (f" ({summary.group(0)})" if summary else "")

    def ip_config(self) -> str:
        try:
            proc = _run(["ipconfig"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't read network config: {exc}"
        adapters = re.findall(r"^(.+?adapter.+?):\s*\n((?:.+\n)+?)(?=\n|\Z)", proc.stdout, re.M)
        out = []
        for name, block in adapters:
            ip = re.search(r"IPv4 Address[.\s]*:\s*(\S+)", block)
            if ip:
                out.append(f"• {name.strip()}: {ip.group(1)}")
        return "\n".join(out) if out else "No active network adapters with an IPv4 address."

    def flush_dns(self) -> str:
        try:
            proc = _run(["ipconfig", "/flushdns"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't flush DNS: {exc}"
        return "DNS cache flushed." if proc.returncode == 0 else "Couldn't flush the DNS cache."

    def check_port(self, host: str, port: int, timeout: float = 3.0) -> str:
        import socket
        host = (host or "").strip()
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            return "Give me a numeric port."
        if not host:
            return "Check which host?"
        if not 0 < port_int < 65536:
            return f"{port_int} isn't a valid port (1-65535)."
        try:
            with socket.create_connection((host, port_int), timeout=timeout):
                return f"{host}:{port_int} is open."
        except socket.timeout:
            return f"{host}:{port_int} didn't respond (timed out)."
        except OSError as exc:
            return f"{host}:{port_int} is closed or unreachable ({exc.strerror or exc})."

    # ── VPN ──────────────────────────────────────────────────────────────────

    def list_vpn_connections(self) -> str:
        try:
            proc = _run(["rasdial"])
        except FileNotFoundError:
            return "VPN control isn't available on this machine."
        except subprocess.TimeoutExpired:
            return "Listing VPN connections timed out."
        lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
        if not lines or lines[0].lower().startswith("no connections"):
            return "No active VPN connections."
        return "\n".join(f"• {l}" for l in lines)

    def connect_vpn(self, name: str, username: str = "", password: str = "") -> str:
        name = (name or "").strip()
        if not name or _option_like(name):
            return "Which VPN connection? Give its name as configured in Windows."
        args = ["rasdial", name] + ([username, password] if username else [])
        try:
            proc = _run(args, timeout=30)
        except FileNotFoundError:
            return "VPN control isn't available on this machine."
        except subprocess.TimeoutExpired:
            return f"Connecting to VPN '{name}' timed out."
        combined = (proc.stdout + proc.stderr).strip()
        return f"Connected to VPN '{name}'." if proc.returncode == 0 else f"Couldn't connect to '{name}': {combined[-300:]}"

    def disconnect_vpn(self, name: str) -> str:
        name = (name or "").strip()
        if not name or _option_like(name):
            return "Which VPN connection should I disconnect?"
        try:
            proc = _run(["rasdial", name, "/disconnect"])
        except FileNotFoundError:
            return "VPN control isn't available on this machine."
        except subprocess.TimeoutExpired:
            return f"Disconnecting '{name}' timed out."
        return f"Disconnected '{name}'." if proc.returncode == 0 else f"Couldn't disconnect '{name}'."
