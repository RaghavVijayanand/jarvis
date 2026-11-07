"""Power plans and startup-app management. Reads (listing plans/apps, checking the
active plan) run immediately; switching a plan or toggling another app's startup
entry always confirms first — it's a system-wide, if reversible, change."""
import re

from core.tools import params
from handlers.base import Handler

_LIST_PLANS = re.compile(r"\b(?:list|show)\s+power\s+plans?\b", re.I)
_ACTIVE_PLAN = re.compile(r"\b(?:what(?:'s|s| is)\s+(?:the\s+)?(?:active|current)\s+power\s+plan|"
                          r"which power plan (?:is|am i)\s+(?:active|on|using))\b", re.I)
_SET_PLAN = re.compile(r"^(?:please\s+)?(?:switch|set|change)\s+(?:the\s+)?power\s+plan\s+to\s+(.+?)[.!?]*$",
                       re.I)
_LIST_STARTUP = re.compile(r"\b(?:list|show)\s+startup\s+apps?\b", re.I)
_ENABLE_STARTUP = re.compile(r"^(?:please\s+)?enable\s+(.+?)\s+(?:at|on)\s+startup[.!?]*$", re.I)
_DISABLE_STARTUP = re.compile(r"^(?:please\s+)?disable\s+(.+?)\s+(?:at|on|from)\s+startup[.!?]*$", re.I)


class PowerHandler(Handler):
    intents = {"POWER"}

    def handle(self, text, intent):
        app = self.app
        pm = getattr(app, "power_manager", None)
        if pm is None:
            return "Power/startup management isn't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        if _LIST_PLANS.search(low):
            return pm.list_power_plans()
        if _ACTIVE_PLAN.search(low):
            return pm.active_power_plan()
        m = _SET_PLAN.match(low)
        if m:
            name = m.group(1).strip()
            return confirm(f"Switch to the '{name}' power plan?", lambda: pm.set_power_plan(name), "set_power_plan")
        if _LIST_STARTUP.search(low):
            return pm.list_startup_apps()
        m = _ENABLE_STARTUP.match(low)
        if m:
            name = m.group(1).strip()
            return confirm(f"Enable '{name}' at startup?", lambda: pm.enable_startup_app(name), "enable_startup_app")
        m = _DISABLE_STARTUP.match(low)
        if m:
            name = m.group(1).strip()
            return confirm(f"Disable '{name}' at startup?", lambda: pm.disable_startup_app(name),
                          "disable_startup_app")
        return None

    def register_tools(self, t):
        pm = getattr(self.app, "power_manager", None)
        if pm is None:
            return
        t.add("list_power_plans", "List Windows power plans and show which is active.", pm.list_power_plans)
        t.add("active_power_plan", "Show the currently active Windows power plan.", pm.active_power_plan)
        t.add("set_power_plan", "Switch the active Windows power plan.", pm.set_power_plan,
              params(["name"], name=("string", "Power plan name, e.g. 'Balanced' or 'High performance'")),
              confirm=True, confirm_text="Switch to the '{name}' power plan?")
        t.add("list_startup_apps", "List apps set to start with Windows, and whether each is enabled.",
              pm.list_startup_apps)
        t.add("enable_startup_app", "Enable an app to start with Windows.", pm.enable_startup_app,
              params(["name"], name=("string", "Startup app name")),
              confirm=True, confirm_text="Enable '{name}' at startup?")
        t.add("disable_startup_app", "Disable an app from starting with Windows.", pm.disable_startup_app,
              params(["name"], name=("string", "Startup app name")),
              confirm=True, confirm_text="Disable '{name}' at startup?")
