"""WebDashboard: a real stdlib HTTP server on an OS-assigned port, exercised
end to end with urllib — token gating, command routing, and notifications."""
import json
import time
import unittest
import urllib.error
import urllib.request

from skills.web_dashboard import WebDashboard, _local_ip


class FakeApp:
    def __init__(self):
        self.calls = []

    def process_command(self, text, use_voice=True):
        self.calls.append((text, use_voice))
        if text == "boom":
            raise RuntimeError("kaboom")
        return f"echo: {text}"


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _get_raw(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8")


def _post(url, payload, headers=None):
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class WebDashboardTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.wd = WebDashboard(self.app)

    def tearDown(self):
        if self.wd.running:
            self.wd.stop()

    def _base(self):
        # http://ip:port -> swap to localhost so the test doesn't depend on LAN routing
        return f"http://127.0.0.1:{self.wd.port}"

    def test_status_not_running(self):
        self.assertFalse(self.wd.running)
        self.assertIn("isn't running", self.wd.status())
        self.assertEqual(self.wd.url(), "")

    def test_start_and_url(self):
        msg = self.wd.start(port=0)
        self.assertTrue(self.wd.running)
        self.assertIn("Dashboard started", msg)
        self.assertIn(self.wd.token, self.wd.url())
        self.assertIn("Dashboard running", self.wd.status())

    def test_start_twice_returns_already_running(self):
        self.wd.start(port=0)
        msg = self.wd.start(port=0)
        self.assertIn("already running", msg)

    def test_stop_when_not_running(self):
        self.assertIn("isn't running", self.wd.stop())

    def test_stop_after_start(self):
        self.wd.start(port=0)
        msg = self.wd.stop()
        self.assertEqual(msg, "Dashboard stopped.")
        self.assertFalse(self.wd.running)
        self.assertIsNone(self.wd.token)

    def test_bad_port_returns_error(self):
        msg = self.wd.start(port=-1)
        self.assertIn("Couldn't start", msg)
        self.assertFalse(self.wd.running)

    def test_root_without_token_forbidden(self):
        self.wd.start(port=0)
        req = urllib.request.Request(f"{self._base()}/")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

    def test_root_with_token_ok(self):
        self.wd.start(port=0)
        status, body = _get_raw(f"{self._base()}/?token={self.wd.token}")
        self.assertEqual(status, 200)
        self.assertIn("<html", body.lower())

    def test_status_endpoint(self):
        self.wd.start(port=0)
        status, data = _get(f"{self._base()}/api/status?token={self.wd.token}")
        self.assertEqual(status, 200)
        self.assertTrue(data["running"])
        self.assertEqual(data["port"], self.wd.port)

    def test_status_endpoint_unauthorized(self):
        self.wd.start(port=0)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(f"{self._base()}/api/status")
        self.assertEqual(ctx.exception.code, 403)

    def test_command_endpoint_runs_command(self):
        self.wd.start(port=0)
        status, data = _post(f"{self._base()}/api/command?token={self.wd.token}", {"text": "open chrome"})
        self.assertEqual(status, 200)
        self.assertEqual(data["reply"], "echo: open chrome")
        self.assertEqual(self.app.calls, [("open chrome", False)])

    def test_command_endpoint_header_token(self):
        self.wd.start(port=0)
        status, data = _post(f"{self._base()}/api/command", {"text": "hi"},
                            headers={"X-JARVIS-Token": self.wd.token})
        self.assertEqual(status, 200)
        self.assertEqual(data["reply"], "echo: hi")

    def test_command_endpoint_unauthorized(self):
        self.wd.start(port=0)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _post(f"{self._base()}/api/command", {"text": "hi"})
        self.assertEqual(ctx.exception.code, 403)

    def test_command_endpoint_empty_text(self):
        self.wd.start(port=0)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _post(f"{self._base()}/api/command?token={self.wd.token}", {"text": "  "})
        self.assertEqual(ctx.exception.code, 400)

    def test_command_endpoint_bad_json(self):
        self.wd.start(port=0)
        req = urllib.request.Request(f"{self._base()}/api/command?token={self.wd.token}",
                                     data=b"not json", headers={"Content-Type": "application/json"},
                                     method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)

    def test_command_endpoint_app_error_caught(self):
        self.wd.start(port=0)
        status, data = _post(f"{self._base()}/api/command?token={self.wd.token}", {"text": "boom"})
        self.assertEqual(status, 200)
        self.assertIn("Something went wrong", data["reply"])

    def test_unknown_path_404(self):
        self.wd.start(port=0)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(f"{self._base()}/nope?token={self.wd.token}")
        self.assertEqual(ctx.exception.code, 404)

    def test_notifications_endpoint(self):
        self.wd.start(port=0)
        self.wd.on_notify("hello from watcher")
        status, data = _get(f"{self._base()}/api/notifications?token={self.wd.token}")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["notifications"]), 1)
        self.assertEqual(data["notifications"][0]["text"], "hello from watcher")

    def test_notifications_since_filters_old(self):
        self.wd.start(port=0)
        self.wd.on_notify("first")
        cutoff = time.time()
        self.wd.on_notify("second")
        results = self.wd.notifications_since(cutoff)
        self.assertEqual([r["text"] for r in results], ["second"])

    def test_on_notify_noop_when_not_running(self):
        self.wd.on_notify("ignored")
        self.assertEqual(self.wd._notifications, [])

    def test_notification_cap(self):
        self.wd.start(port=0)
        from skills import web_dashboard as wd_mod
        original = wd_mod._MAX_NOTIFICATIONS
        wd_mod._MAX_NOTIFICATIONS = 3
        try:
            for i in range(5):
                self.wd.on_notify(f"n{i}")
            self.assertEqual(len(self.wd._notifications), 3)
        finally:
            wd_mod._MAX_NOTIFICATIONS = original

    def test_gui_runner_is_used_instead_of_direct_call(self):
        seen = []
        self.app.dashboard_runner = lambda text: seen.append(text) or "queued reply"
        self.assertEqual(self.wd.run_command("open notepad"), "queued reply")
        self.assertEqual(seen, ["open notepad"])
        self.assertEqual(self.app.calls, [])          # never ran beside the GUI worker

    def test_malformed_requests_are_rejected_not_crashing(self):
        self.wd.start(port=0)
        base = f"{self._base()}/api/command?token={self.wd.token}"
        for body, length in ((b"[1, 2]", None), (b"\xff\xfe", None), (b"{}", "-5"), (b"{}", "abc"),
                             (b"{}", str(10 ** 9))):
            with self.subTest(body=body, length=length):
                req = urllib.request.Request(base, data=body, method="POST")
                if length is not None:
                    req.add_unredirected_header("Content-Length", length)
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=5)
                self.assertIn(ctx.exception.code, (400, 413))
        status, data = _get(f"{self._base()}/api/notifications?since=abc&token={self.wd.token}")
        self.assertEqual(status, 200)
        status, data = _get(f"{self._base()}/api/notifications?since=nan&token={self.wd.token}")
        self.assertEqual(status, 200)

    def test_stopped_dashboard_fails_closed(self):
        self.wd.token = None                           # the moment between stop() and teardown
        from skills.web_dashboard import _Handler
        handler = _Handler.__new__(_Handler)
        handler.server = type("S", (), {"dashboard": self.wd})()
        handler.path = "/api/status"
        handler.headers = {}
        self.assertFalse(handler._token_ok())

    def test_local_ip_returns_string(self):
        ip = _local_ip()
        self.assertIsInstance(ip, str)
        self.assertTrue(ip)


if __name__ == "__main__":
    unittest.main()
