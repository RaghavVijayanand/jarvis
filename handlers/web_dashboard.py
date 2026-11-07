"""Local web dashboard control. Starting it opens the PC to commands from
your network, so it confirms first; stopping and checking status don't."""
import re

from core.tools import params
from handlers.base import Handler

_START = re.compile(r"^(?:please\s+)?(?:start|enable|turn on|launch)\s+(?:the\s+)?(?:remote\s+|web\s+)*"
                    r"dashboard\b", re.I)
_STOP = re.compile(r"^(?:please\s+)?(?:stop|disable|turn off|shut down)\s+(?:the\s+)?(?:remote\s+|web\s+)*"
                   r"dashboard\b", re.I)
_STATUS = re.compile(r"\bdashboard\s+status\b|\bis\s+the\s+dashboard\s+running\b", re.I)


class WebDashboardHandler(Handler):
    intents = {"DASHBOARD"}

    def handle(self, text, intent):
        app = self.app
        wd = getattr(app, "web_dashboard", None)
        if wd is None:
            return "The web dashboard isn't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        if _START.search(low):
            return confirm("Start the web dashboard? This lets any device on your Wi-Fi that has the "
                           "link send JARVIS commands.", wd.start, "start_dashboard")
        if _STOP.search(low):
            return wd.stop()
        if _STATUS.search(low):
            return wd.status()
        return None

    def register_tools(self, t):
        wd = getattr(self.app, "web_dashboard", None)
        if wd is None:
            return
        t.add("start_web_dashboard", "Start the local web dashboard so other devices on your network can "
              "send JARVIS commands.", wd.start, params([], port=("integer", "Port to listen on (optional)")),
              confirm=True, confirm_text="Start the web dashboard? Any device on your Wi-Fi with the link "
                                         "could send JARVIS commands.")
        t.add("stop_web_dashboard", "Stop the local web dashboard.", wd.stop)
        t.add("web_dashboard_status", "Show whether the web dashboard is running, and its URL.", wd.status)
