"""Windows services and richer process breakdowns. Start/stop/restart always
confirm first — a service often backs something the user is actively using."""
import re

from core.tools import params
from handlers.base import Handler

_TOP_CPU = re.compile(r"\bwhat(?:'s|s| is)\s+(?:using|eating|hogging)\s+(?:my\s+)?cpu\b|"
                      r"\btop processes?\b(?!.*\bmemory|ram\b)", re.I)
_TOP_MEM = re.compile(r"\bwhat(?:'s|s| is)\s+(?:using|eating|hogging)\s+(?:my\s+)?(?:ram|memory)\b|"
                      r"\btop processes?.*\b(?:memory|ram)\b", re.I)
_LIST_SERVICES = re.compile(r"\b(?:list|show)\s+(?:running\s+)?(?:windows\s+)?services\b", re.I)
_SERVICE_STATUS = re.compile(r"^(?:please\s+)?(?:is|check if)\s+(?:the\s+)?(.+?)\s+service\s+(?:running|status)\??$",
                             re.I)
_START = re.compile(r"^(?:please\s+)?start\s+(?:the\s+)?(.+?)\s+service[.!?]*$", re.I)
_STOP = re.compile(r"^(?:please\s+)?stop\s+(?:the\s+)?(.+?)\s+service[.!?]*$", re.I)
_RESTART = re.compile(r"^(?:please\s+)?restart\s+(?:the\s+)?(.+?)\s+service[.!?]*$", re.I)


class ServiceHandler(Handler):
    intents = {"SERVICE"}

    def handle(self, text, intent):
        app = self.app
        sm = getattr(app, "service_manager", None)
        if sm is None:
            return "Service control isn't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        if _TOP_MEM.search(low):
            return sm.top_processes(by="memory")
        if _TOP_CPU.search(low):
            return sm.top_processes(by="cpu")
        if _LIST_SERVICES.search(low):
            return sm.list_services(running_only="running" in low.lower())
        m = _SERVICE_STATUS.match(low)
        if m:
            return sm.service_status(m.group(1).strip())
        m = _START.match(low)
        if m:
            name = m.group(1).strip()
            return confirm(f"Start the '{name}' service?", lambda: sm.start_service(name), "start_service")
        m = _STOP.match(low)
        if m:
            name = m.group(1).strip()
            return confirm(f"Stop the '{name}' service?", lambda: sm.stop_service(name), "stop_service")
        m = _RESTART.match(low)
        if m:
            name = m.group(1).strip()
            return confirm(f"Restart the '{name}' service?", lambda: sm.restart_service(name), "restart_service")
        return None

    def register_tools(self, t):
        sm = getattr(self.app, "service_manager", None)
        if sm is None:
            return
        t.add("top_processes", "Show the top processes by CPU or memory usage right now.",
              lambda by="cpu", limit=10: sm.top_processes(by=by, limit=limit),
              params(by=("string", "cpu or memory", ("cpu", "memory")), limit=("integer", "How many to show")))
        t.add("list_services", "List Windows services, optionally only running ones.",
              lambda query="", running_only=False: sm.list_services(query, bool(running_only)),
              params(query=("string", "Optional name filter"), running_only=("boolean", "Only running services")))
        t.add("service_status", "Check whether a Windows service is running.", sm.service_status,
              params(["name"], name=("string", "Service name")))
        t.add("start_service", "Start a Windows service.", sm.start_service,
              params(["name"], name=("string", "Service name")),
              confirm=True, confirm_text="Start the '{name}' service?")
        t.add("stop_service", "Stop a Windows service.", sm.stop_service,
              params(["name"], name=("string", "Service name")),
              confirm=True, confirm_text="Stop the '{name}' service?")
        t.add("restart_service", "Restart a Windows service.", sm.restart_service,
              params(["name"], name=("string", "Service name")),
              confirm=True, confirm_text="Restart the '{name}' service?")
