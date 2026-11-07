"""Opening and closing applications, websites and folders."""
import re

from core.tools import params
from handlers.base import Handler


class AppsHandler(Handler):
    intents = {"APP"}

    def handle(self, text, intent, browser=None):
        app = self.app
        text = text.strip()
        low = text.lower()
        control = app.app_control
        m = re.match(r"^(?:please\s+)?(?:close|quit|exit|kill|end|terminate)\s+(?:the\s+)?(.+?)(?:\s+app)?$", low)
        if m and re.fullmatch(r"(all|every)( open)? windows?|all the windows|everything", m.group(1).strip()):
            return app.handlers.dispatch("close all windows", "CONTROL")    # needs only WindowsControl
        if m and control:
            name = m.group(1).strip()
            return app._ask_to_confirm(f"Close {name}? Unsaved work in it may be lost.",
                                       lambda: control.close_app_by_name(name), "close_app")
        m = re.match(r"^(?:please\s+)?(?:list|show)(?:\s+me)?\s+(?:(?:all|my|the)\s+)*(?:installed\s+)?"
                     r"(?:apps|applications|programs)"
                     r"(?:\s+(?:matching|with|like)?\s*(.+))?$", low)
        if m and control:
            return control.list_installed_apps(m.group(1) or "")
        if re.search(r"\b(discover|scan for|refresh)\b.*\b(apps|applications|programs)\b", low) and control:
            return control.discover_applications()
        if control is None:
            return "Application control isn't available on this system."
        return control.launch_app_by_name(text, browser=browser)

    def register_tools(self, t):
        control = self.app.app_control
        if not control:
            return
        t.add("open_app_or_website",
              "Open an application, folder or website. For media, include the action, e.g. "
              "'youtube and play lofi beats'.",
              lambda target, browser="": control.launch_app_by_name(target, browser=browser or None),
              params(["target"], target=("string", "App/site/folder name or URL, e.g. 'spotify', 'github.com'; "
                                                   "to play something include it: 'youtube and play lofi beats'"),
                     browser=("string", "Optional browser to use: chrome, edge, firefox")))
        t.add("close_app", "Close a running application gracefully.", control.close_app_by_name,
              params(["name"], name=("string", "App name, e.g. 'chrome'")), confirm=True,
              confirm_text="Close {name}? Unsaved work may be lost.")
        t.add("list_installed_apps", "List installed applications, optionally filtered.",
              control.list_installed_apps, params(filter_text=("string", "Optional filter")))
