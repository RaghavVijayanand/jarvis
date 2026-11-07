"""Install, remove and update Windows software (winget), and OS-level admin actions
(registry, firewall, scheduled tasks) that go beyond what JARVIS's own skills touch.

Installs/uninstalls/upgrades always ask first — same rule as shutdown or delete.
Searching and listing never do; they're read-only.
"""
import re

from core.tools import params
from handlers.base import Handler

_NOT_FILE = r"(?!.*\b(?:file|files|folder|folders)\b)"
_INSTALL = re.compile(rf"^(?:please\s+)?install\s+{_NOT_FILE}(?:the\s+)?(?:app(?:lication)?\s+)?(.+?)[.!?]*$", re.I)
_UNINSTALL = re.compile(rf"^(?:please\s+)?uninstall\s+{_NOT_FILE}(?:the\s+)?(?:app(?:lication)?\s+)?(.+?)[.!?]*$",
                        re.I)
_UPGRADE = re.compile(r"^(?:please\s+)?(?:upgrade|update)\s+(?:the\s+)?(?:app(?:lication)?\s+)?(.+?)[.!?]*$", re.I)
_UPGRADE_ALL = re.compile(r"\b(?:upgrade|update)\s+(?:all\s+)?(?:my\s+)?(?:apps?|applications?|programs?|"
                          r"software|packages?)\b", re.I)
_SEARCH = re.compile(r"^(?:please\s+)?search\s+(?:for\s+)?(.+?)\s+(?:in|on|via)\s+winget[.!?]*$|"
                     r"^(?:please\s+)?winget\s+search\s+(?:for\s+)?(.+?)[.!?]*$", re.I)
_IS_INSTALLED = re.compile(r"^(?:please\s+)?(?:is|do i have)\s+(.+?)\s+installed\??$|"
                           r"^(?:please\s+)?(?:check|see) if\s+(.+?)\s+is installed\??$", re.I)


class SoftwareHandler(Handler):
    intents = {"SOFTWARE"}

    def handle(self, text, intent):
        app = self.app
        sm = getattr(app, "software_manager", None)
        if sm is None:
            return "Software management isn't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        m = _SEARCH.match(low)
        if m:
            query = (m.group(1) or m.group(2)).strip()
            return sm.format_list(sm.search(query), f"No results for '{query}' in winget.")

        m = _IS_INSTALLED.match(low)
        if m:
            name = (m.group(1) or m.group(2)).strip()
            return f"Yes, {name} is installed." if sm.is_installed(name) else f"I don't see {name} installed."

        if re.search(r"\blist installed(?: apps| applications| programs| software)?\b", low, re.I):
            return sm.format_list(sm.list_installed(), "Nothing found (or winget isn't available).")

        if _UPGRADE_ALL.search(low):
            return confirm("Upgrade every app winget manages? This may take a while.",
                           lambda: sm.upgrade(""), "upgrade_all_apps")

        m = _INSTALL.match(low)
        if m:
            name = m.group(1).strip().strip('"\'')
            return confirm(f"Install '{name}'?", lambda: sm.install(name), "install_app")

        m = _UNINSTALL.match(low)
        if m:
            name = m.group(1).strip().strip('"\'')
            return confirm(f"Uninstall '{name}'?", lambda: sm.uninstall(name), "uninstall_app_winget")

        m = _UPGRADE.match(low)
        if m:
            name = m.group(1).strip().strip('"\'')
            return confirm(f"Upgrade '{name}'?", lambda: sm.upgrade(name), "upgrade_app")

        return None

    def register_tools(self, t):
        sm = getattr(self.app, "software_manager", None)
        if sm is None:
            return
        t.add("search_software", "Search for installable Windows software by name (winget).",
              lambda query: sm.format_list(sm.search(query), f"No results for '{query}'."),
              params(["query"], query=("string", "App name to search for")))
        t.add("list_installed_software", "List installed software that winget manages, optionally filtered.",
              lambda query="": sm.format_list(sm.list_installed(query), "Nothing found."),
              params(query=("string", "Optional filter")))
        t.add("is_software_installed", "Check whether a program is installed.",
              lambda name: "yes" if sm.is_installed(name) else "no",
              params(["name"], name=("string", "App name")))
        t.add("install_software", "Install a Windows program via winget.", sm.install,
              params(["name"], name=("string", "App name, e.g. 'VLC media player'")),
              confirm=True, confirm_text="Install '{name}'?")
        t.add("uninstall_software", "Uninstall a Windows program via winget.", sm.uninstall,
              params(["name"], name=("string", "App name")),
              confirm=True, confirm_text="Uninstall '{name}'?")
        t.add("upgrade_software", "Upgrade one program (or, with 'all', every program winget manages).",
              lambda name="": sm.upgrade(name), params(name=("string", "App name, or 'all'")),
              confirm=True, confirm_text="Upgrade '{name}'?")
