#!/usr/bin/env python3
"""JARVIS for Windows — the tray app (the installer's JARVIS.exe runs this).

    JARVIS.exe              start (or, if already running, open the command bar)
    JARVIS.exe --tray       start quietly in the tray (used at Windows sign-in)
    JARVIS.exe --dashboard  start and open the dashboard window
    JARVIS.exe --setup      show the first-run welcome again
    JARVIS.exe --selftest   load every module and exit (build check; prints OK)

From source:  python app.py   (python main_gui.py still opens the classic window)
"""
from __future__ import annotations

import argparse
import os
import sys


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="JARVIS", add_help=True)
    parser.add_argument("--tray", action="store_true", help="start hidden in the system tray")
    parser.add_argument("--dashboard", action="store_true", help="open the dashboard window")
    parser.add_argument("--setup", action="store_true", help="show the first-run welcome")
    parser.add_argument("--selftest", action="store_true", help="import everything and exit (build check)")
    args, _unknown = parser.parse_known_args(argv)     # Qt may add its own arguments
    return args


MUTEX_NAME = "JARVIS-Assistant-Mutex"      # the installer's AppMutex: setup/uninstall wait for JARVIS to close


def hold_mutex():
    """Windows only: a named mutex the installer can see while JARVIS runs."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        return ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    except Exception:
        return None


SELFTEST_MODULES = [
    "jarvis", "main_gui", "core.config", "core.brain", "core.decision", "core.tools", "core.memory",
    "core.voice", "core.executor", "core.streaming", "core.buddy", "core.hotkeys", "core.autostart", "core.deps",
    "core.ollama_manager", "core.plugins", "handlers", "skills.app_control", "skills.windows_control",
    "skills.screen_automation",
    "skills.task_scheduler", "skills.file_manager", "skills.command_processor", "skills.software_manager",
    "skills.system_admin", "skills.app_scripting", "skills.network_manager", "skills.service_manager",
    "skills.power_manager", "skills.productivity", "skills.security_checks", "skills.window_layouts",
    "skills.outlook_manager", "skills.watchers", "skills.file_index", "skills.web_dashboard", "ui.theme",
    "ui.settings",
    "ui.command_bar", "ui.tray", "ui.shell", "ui.onboarding", "ui.buddy_overlay", "ui.widgets", "ui.chat_view",
    "ui.activity", "ui.dash_widgets", "ui.settings_widgets", "ui.bar_markdown",
]


def selftest() -> int:
    """Used by the build (and CI) to prove the packaged app can load all of itself.

    The packaged JARVIS.exe has no console, so the exit code is the verdict and
    JARVIS_SELFTEST_LOG (a file path) receives the details when set."""
    import importlib
    lines = []

    def say(text):
        lines.append(text)
        if sys.stdout is not None:
            print(text)
    failures = []
    for name in SELFTEST_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:                       # pragma: no cover - reported, not raised
            failures.append(f"{name}: {exc!r}")
    for optional in ("vosk", "pynput.keyboard", "pyaudio", "PySide6.QtWebEngineWidgets"):
        try:
            importlib.import_module(optional)
        except Exception as exc:
            say(f"note: optional {optional} unavailable ({exc.__class__.__name__})")
    code = 0
    if failures:
        say("SELFTEST FAILED\n" + "\n".join(failures))
        code = 1
    else:
        say(f"SELFTEST OK ({len(SELFTEST_MODULES)} modules)")
    log_path = os.environ.get("JARVIS_SELFTEST_LOG")
    if log_path:
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return code


def main(argv=None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.selftest:
        return selftest()

    from core.logging_setup import setup_logging
    setup_logging()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    import main_gui
    if main_gui.WEBENGINE_AVAILABLE:
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)   # QtWebEngine: before the QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("JARVIS")
    app.setApplicationDisplayName("JARVIS")
    app.setApplicationVersion("3.1")
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)                        # it lives in the tray

    from ui import theme
    from ui.tray import SingleInstance, Tray
    app.setWindowIcon(theme.app_icon())
    instance = SingleInstance()
    if instance.notify_running("dashboard" if args.dashboard else "ask"):
        return 0                                                # the running JARVIS takes it from here
    instance.listen()
    app._jarvis_mutex = hold_mutex()

    from core.config import Config, load_env
    first_run = args.setup or not Config.ONBOARDED
    if first_run:
        from ui.onboarding import run_onboarding
        run_onboarding()
        load_env()
        Config.reload()

    from core.hotkeys import COMMAND_BAR_HOTKEYS
    from ui.command_bar import CommandBar
    from ui.shell import TrayApp
    label = COMMAND_BAR_HOTKEYS.get(Config.COMMAND_BAR_HOTKEY, "")
    window = main_gui.MainWindow()
    bar = CommandBar(hotkey_label=label)
    tray = Tray(bar_hotkey=label) if Tray.available() else None
    shell = TrayApp(window, bar, tray=tray, instance=instance,
                    start_hidden=args.tray and not args.dashboard, first_run=first_run)
    app._jarvis_shell = shell                                   # keep a reference for the app's lifetime

    code = app.exec()
    if window.threads_still_running():
        # A command is still blocked (e.g. a slow network call): leave without waiting for it.
        import logging
        logging.shutdown()
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        os._exit(code)
    return code


if __name__ == "__main__":
    sys.exit(main())
