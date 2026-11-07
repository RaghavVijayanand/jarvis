"""Intent handlers — one module per domain. See handlers/base.py.

    apps      APP                 open/close apps, sites, folders
    media     MEDIA               playback, volume
    control   CONTROL             power, windows, resolution, brightness, settings, clipboard
    schedule  SCHEDULE            alarms, reminders, timers
    files     FILE                files and folders
    screen    SCREEN_AUTOMATION   vision, clicks, typing
    software  SOFTWARE            install/uninstall/upgrade apps (winget)
    admin     (tools only)        registry, firewall, OS-level scheduled tasks, elevation
    appscript APPSCRIPT           AI-written scripts run inside another app (Blender)
    network   NETWORK             Wi-Fi, ping/DNS/port checks, VPN
    service   SERVICE             Windows services, top CPU/RAM processes
    power     POWER               power plans, startup app management
    productivity  PRODUCTIVITY    clipboard history, OCR, PDF/docx text extraction
    security  SECURITY            Defender, BitLocker, Windows Update
    layout    LAYOUT              window layouts, snapping, multi-monitor
    outlook   EMAIL               Outlook email and calendar
    watchers  WATCH               watch-and-react: files, downloads, processes, CPU/RAM
    fileindex FILEINDEX           local file keyword search/indexing
    dashboard DASHBOARD           local web dashboard (remote control over Wi-Fi)
    plugins   PLUGINS             status of auto-discovered/plugin-folder handlers
    memory    MEMORY              user memory
    info      TIME MATH WEATHER SEARCH SYSTEM UTILITY
    chat      GENERAL             greetings (everything else → language model)

Handlers are discovered, not hand-registered: every class module in this
package that subclasses handlers.base.Handler is picked up automatically by
core.plugins.discover_builtin_handlers(), so adding one only means adding the
module — no tuple to edit here. Anything dropped into Config.PLUGINS_DIR
(a user folder, see core/plugins.py) is discovered the same way, alongside
built-ins, with no source file touched at all.
"""
from typing import Dict, List, Optional

from core.logging_setup import get_logger
from core.plugins import discover_builtin_handlers, discover_plugin_handlers, ensure_plugin_dir, run_plugin_setup

log = get_logger("jarvis.handlers")

# Computed once at import time — the built-in set doesn't change at runtime.
# Kept under this name for backward compatibility with anything that inspects it.
HANDLER_CLASSES = tuple(discover_builtin_handlers())


class HandlerRegistry:
    def __init__(self, app):
        self.app = app
        self.plugin_dir = ensure_plugin_dir()
        plugin_classes, setup_fns, self.plugin_names = discover_plugin_handlers(self.plugin_dir)
        run_plugin_setup(app, setup_fns)

        self.by_name: Dict[str, object] = {}
        self.by_intent: Dict[str, object] = {}
        self.plugin_handler_names: List[str] = []
        for cls in list(HANDLER_CLASSES) + plugin_classes:
            try:
                handler = cls(app)
            except Exception:
                log.exception("failed to instantiate handler %s", cls)
                continue
            self.by_name[cls.__name__] = handler
            if cls not in HANDLER_CLASSES:
                self.plugin_handler_names.append(cls.__name__)
            for intent in handler.intents:
                if intent in self.by_intent:
                    log.warning("intent %s already claimed by %s; %s overrides it", intent,
                               type(self.by_intent[intent]).__name__, cls.__name__)
                self.by_intent[intent] = handler

    def __getitem__(self, name):
        return self.by_name[name]

    def dispatch(self, text: str, intent: str, **kwargs) -> Optional[str]:
        handler = self.by_intent.get(intent)
        if handler is None:
            return None
        try:
            return handler.handle(text, intent, **kwargs)
        except Exception as exc:
            log.exception("handler %s failed", intent)
            return f"Something went wrong handling that ({exc})."

    def register_tools(self, tools) -> None:
        for handler in self.by_name.values():
            try:
                handler.register_tools(tools)
            except Exception:
                log.exception("tool registration failed for %s", type(handler).__name__)
