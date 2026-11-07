"""Plugin discovery: turns the hand-wired "edit five files" pattern into a
discoverable one.

Built-in capabilities still live as one module per domain under handlers/,
exactly as before — but ``discover_builtin_handlers`` finds them by scanning
the package instead of requiring a manually maintained tuple, so adding a
class to an existing handler module (or a whole new handlers/foo.py) is
picked up automatically.

Third-party/user plugins go one step further: dropping a single .py file
into ``Config.PLUGINS_DIR`` (``%APPDATA%/Jarvis/plugins`` — see
``ensure_plugin_dir``) is enough for JARVIS to pick it up at next start, with
*no* source file to edit at all. A plugin module may define:

  - one or more subclasses of ``handlers.base.Handler``, auto-registered
    exactly like a built-in handler (its ``intents`` need a matching
    ``core/decision.py`` rule to be reachable by text, but it works
    immediately for the language model via ``register_tools``);
  - a module-level ``setup(app)`` function, called once during startup,
    where the plugin can attach its own skill object(s) to ``app`` (e.g.
    ``app.my_skill = MySkill()``) for its handler(s) to use.

A plugin that fails to import, or whose ``setup()`` raises, is logged and
skipped — it never prevents JARVIS from starting, the same promise
``JARVIS._safe`` makes for built-in skills.
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from typing import Callable, List, Tuple, Type

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.plugins")


def ensure_plugin_dir(plugin_dir: Path = None) -> Path:
    """Create the plugins folder (with a short README) if it doesn't exist yet."""
    plugin_dir = plugin_dir or Config.PLUGINS_DIR
    try:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        readme = plugin_dir / "README.txt"
        if not readme.exists():
            readme.write_text(
                "Drop a .py file here to add a JARVIS capability without touching JARVIS's own source.\n\n"
                "A plugin file may define:\n"
                "  - one or more subclasses of handlers.base.Handler (import it with\n"
                "    'from handlers.base import Handler')\n"
                "  - a module-level setup(app) function, run once at startup, where you can attach your\n"
                "    own skill object(s) to `app` (e.g. app.my_skill = MySkill()) for your handler(s) to use\n\n"
                "Restart JARVIS after adding or changing a plugin file. Say 'list plugins' to confirm it "
                "loaded.\n", encoding="utf-8")
    except OSError:
        log.exception("couldn't prepare plugin dir %s", plugin_dir)
    return plugin_dir


def discover_builtin_handlers() -> List[Type]:
    """Import every module in the handlers package and collect the Handler
    subclasses each one defines directly (not ones it merely imports)."""
    import handlers as handlers_pkg
    from handlers.base import Handler

    found: List[Type] = []
    for info in pkgutil.iter_modules(handlers_pkg.__path__, prefix="handlers."):
        name = info.name
        if name == "handlers.base":
            continue
        try:
            module = importlib.import_module(name)
        except Exception:
            log.exception("failed to import handler module %s", name)
            continue
        for attr in vars(module).values():
            if (isinstance(attr, type) and issubclass(attr, Handler) and attr is not Handler
                    and attr.__module__ == module.__name__):
                found.append(attr)
    return found


def discover_plugin_handlers(plugin_dir: Path = None) -> Tuple[List[Type], List[Callable], List[str]]:
    """Load every .py file directly under the plugins folder.

    Returns (handler_classes, setup_fns, plugin_names) — plugin_names lists the
    file stems that loaded successfully, in load order, for status reporting."""
    from handlers.base import Handler

    plugin_dir = plugin_dir or Config.PLUGINS_DIR
    handler_classes: List[Type] = []
    setup_fns: List[Callable] = []
    plugin_names: List[str] = []
    if not plugin_dir.is_dir():
        return handler_classes, setup_fns, plugin_names

    for path in sorted(plugin_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        module_name = f"jarvis_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"couldn't build an import spec for {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except (Exception, SystemExit):         # a plugin's sys.exit() must not end JARVIS's startup
            log.exception("failed to load plugin %s", path)
            sys.modules.pop(module_name, None)
            continue

        found_here = 0
        for attr in vars(module).values():
            if (isinstance(attr, type) and issubclass(attr, Handler) and attr is not Handler
                    and attr.__module__ == module_name):
                handler_classes.append(attr)
                found_here += 1
        setup = getattr(module, "setup", None)
        if callable(setup):
            setup_fns.append(setup)
        plugin_names.append(path.stem)
        log.info("loaded plugin %s (%d handler class(es), setup=%s)", path.name, found_here, bool(setup))
    return handler_classes, setup_fns, plugin_names


def run_plugin_setup(app, setup_fns: List[Callable]) -> None:
    for fn in setup_fns:
        try:
            fn(app)
        except (Exception, SystemExit):
            log.exception("plugin setup() failed: %s", getattr(fn, "__module__", fn))
