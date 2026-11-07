"""Local web dashboard: a small HTTP server (Python's stdlib only — no Flask,
no new dependency) that serves a single-page UI so you can send JARVIS
commands and see its proactive notifications from your phone or another
device on the same Wi-Fi/tailnet.

No accounts and nothing leaves your network: the server binds to all local
interfaces so your phone can reach it, but there's no cloud relay involved.
The only gate is a random token minted each time the dashboard starts and
baked into the URL JARVIS gives you — good enough to keep a stranger on
public Wi-Fi from finding it by guessing, without asking you to set up an
account. Starting the server is confirm-gated (it's the one thing here that
opens the PC to commands from the network); stopping it and checking status
are not.
"""
from __future__ import annotations

import json
import math
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from core.logging_setup import get_logger

log = get_logger("jarvis.web_dashboard")

_MAX_NOTIFICATIONS = 200
_DEFAULT_PORT = 8765
_MAX_BODY = 64 * 1024

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS Dashboard</title>
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; background: #0e1116; color: #e6e6e6;
         margin: 0; padding: 0 16px 16px; }
  h1 { font-size: 1.1rem; font-weight: 600; padding: 16px 0 8px; }
  #log { border: 1px solid #2a2f3a; border-radius: 8px; padding: 10px; height: 55vh; overflow-y: auto;
         background: #161a22; margin-bottom: 10px; }
  .msg { margin: 6px 0; white-space: pre-wrap; word-break: break-word; }
  .you { color: #8ab4f8; }
  .jarvis { color: #9cdcae; }
  .note { color: #e0c36f; }
  form { display: flex; gap: 8px; }
  input[type=text] { flex: 1; padding: 10px; border-radius: 6px; border: 1px solid #2a2f3a;
                      background: #161a22; color: #e6e6e6; font-size: 1rem; }
  button { padding: 10px 16px; border-radius: 6px; border: none; background: #3a7afe; color: white;
           font-size: 1rem; }
</style>
</head>
<body>
<h1>JARVIS Dashboard</h1>
<div id="log"></div>
<form id="f">
  <input id="t" type="text" autocomplete="off" placeholder="Tell JARVIS to do something...">
  <button type="submit">Send</button>
</form>
<script>
  const token = new URLSearchParams(location.search).get("token") || "";
  const log = document.getElementById("log");
  let since = 0;
  function add(cls, text) {
    const d = document.createElement("div");
    d.className = "msg " + cls;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }
  document.getElementById("f").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("t");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    add("you", "You: " + text);
    try {
      const res = await fetch("/api/command?token=" + encodeURIComponent(token), {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text: text})
      });
      const data = await res.json();
      add("jarvis", "JARVIS: " + (data.reply || data.error || "(no reply)"));
    } catch (err) {
      add("jarvis", "JARVIS: (connection error)");
    }
  });
  async function poll() {
    try {
      const res = await fetch("/api/notifications?since=" + since + "&token=" + encodeURIComponent(token));
      const data = await res.json();
      for (const n of (data.notifications || [])) {
        add("note", n.text);
        since = Math.max(since, n.time);
      }
    } catch (err) { /* ignore, try again next tick */ }
    setTimeout(poll, 4000);
  }
  poll();
</script>
</body>
</html>
"""


def _local_ip() -> str:
    """Best-effort LAN IP (no packet is actually sent; UDP connect just picks a route)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class _Handler(BaseHTTPRequestHandler):
    server_version = "JARVISDashboard/1.0"

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _dashboard(self) -> "WebDashboard":
        return self.server.dashboard  # type: ignore[attr-defined]

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _token_ok(self) -> bool:
        token = self._dashboard().token
        if not token:
            return False        # stopping (or never started): fail closed, never open
        given = self._query().get("token", [""])[0] or self.headers.get("X-JARVIS-Token") or ""
        return secrets.compare_digest(given.encode("utf-8"), token.encode("utf-8"))

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            if not self._token_ok():
                self._send_html(403, "<h1>Missing or invalid token.</h1>")
                return
            self._send_html(200, _PAGE)
        elif path == "/api/status":
            if not self._token_ok():
                return self._send_json(403, {"error": "unauthorized"})
            self._send_json(200, self._dashboard().status_dict())
        elif path == "/api/notifications":
            if not self._token_ok():
                return self._send_json(403, {"error": "unauthorized"})
            try:
                since = float(self._query().get("since", ["0"])[0] or "0")
            except ValueError:
                since = 0.0
            if not math.isfinite(since):
                since = 0.0
            self._send_json(200, {"notifications": self._dashboard().notifications_since(since)})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/command":
            return self._send_json(404, {"error": "not found"})
        if not self._token_ok():
            return self._send_json(403, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return self._send_json(400, {"error": "bad content-length"})
        if length < 0 or length > _MAX_BODY:
            return self._send_json(413, {"error": "request too large"})
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
        except ValueError:          # includes UnicodeDecodeError
            return self._send_json(400, {"error": "bad json"})
        if not isinstance(data, dict):
            return self._send_json(400, {"error": "bad json"})
        text = str(data.get("text", "")).strip()
        if not text:
            return self._send_json(400, {"error": "empty command"})
        reply = self._dashboard().run_command(text)
        self._send_json(200, {"reply": reply})


class WebDashboard:
    """Starts/stops a local HTTP server that lets a browser on the same
    network send JARVIS commands and watch its proactive notifications."""

    def __init__(self, app):
        self.app = app
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.token: Optional[str] = None
        self.port: Optional[int] = None
        self._notifications: List[tuple] = []   # (timestamp, text)
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self, port: int = _DEFAULT_PORT) -> str:
        if self.running:
            return f"The dashboard is already running at {self.url()}"
        self.token = secrets.token_urlsafe(12)
        try:
            server = ThreadingHTTPServer(("0.0.0.0", int(port)), _Handler)
        except (OSError, OverflowError) as exc:
            self.token = None
            return f"Couldn't start the dashboard on port {port}: {exc}"
        server.dashboard = self
        server.daemon_threads = True
        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(target=server.serve_forever, daemon=True, name="jarvis-dashboard")
        self._thread.start()
        return f"Dashboard started at {self.url()} — open that link on any device on your Wi-Fi."

    def stop(self) -> str:
        if not self.running:
            return "The dashboard isn't running."
        server = self._server
        self._server = None
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            log.exception("error stopping dashboard server")
        self._thread = None
        self.token = None
        self.port = None
        return "Dashboard stopped."

    def url(self) -> str:
        if not self.running:
            return ""
        return f"http://{_local_ip()}:{self.port}/?token={self.token}"

    def status(self) -> str:
        if not self.running:
            return "The dashboard isn't running. Say 'start the dashboard' to turn it on."
        return f"Dashboard running at {self.url()}"

    def status_dict(self) -> dict:
        return {"running": self.running, "port": self.port}

    def run_command(self, text: str) -> str:
        # The GUI provides a runner that queues onto its single command worker, so a phone
        # command never runs concurrently with one typed at the PC. CLI mode has no worker.
        runner = getattr(self.app, "__dict__", {}).get("dashboard_runner")   # set on the instance by the GUI
        try:
            if callable(runner):
                return runner(text) or ""
            return self.app.process_command(text, use_voice=False) or ""
        except Exception as exc:
            log.exception("dashboard command failed")
            return f"Something went wrong handling that ({exc})."

    def on_notify(self, text: str) -> None:
        """Called by JARVIS.notify() so the dashboard can show proactive messages."""
        if not self.running:
            return
        with self._lock:
            self._notifications.append((time.time(), text))
            if len(self._notifications) > _MAX_NOTIFICATIONS:
                self._notifications.pop(0)

    def notifications_since(self, since: float) -> List[dict]:
        with self._lock:
            return [{"time": t, "text": txt} for t, txt in self._notifications if t > since]
