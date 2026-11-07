"""Plugin status — a read-only window onto what handlers/__init__.py's
auto-discovery found, both built in and dropped into the plugins folder."""
import re

from handlers.base import Handler

_LIST = re.compile(r"^(?:please\s+)?(?:list|show)\s+plugins\b|\bplugin\s+status\b|"
                   r"^(?:please\s+)?(?:what|which)\s+plugins\s+(?:are\s+)?(?:loaded|installed)\b", re.I)


class PluginsHandler(Handler):
    intents = {"PLUGINS"}

    def handle(self, text, intent):
        if not _LIST.search(text.strip()):
            return None
        registry = getattr(self.app, "_handlers", None) or getattr(self.app, "handlers", None)
        plugin_dir = getattr(registry, "plugin_dir", None)
        names = list(getattr(registry, "plugin_names", []) or [])
        if not names:
            return (f"No plugins loaded. Drop a .py file into {plugin_dir} and restart JARVIS to add one "
                    f"(it writes a README.txt there with the format).")
        return f"{len(names)} plugin(s) loaded from {plugin_dir}: {', '.join(names)}"

    def register_tools(self, t):
        registry = getattr(self.app, "_handlers", None) or getattr(self.app, "handlers", None)

        def list_plugins():
            return self.handle("list plugins", "PLUGINS")

        t.add("list_plugins", "List JARVIS plugins loaded from the plugins folder.", list_plugins)
