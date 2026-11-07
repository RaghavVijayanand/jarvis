"""The tray app: wires the tray icon, command bar, cursor buddy and dashboard together.

    ┌ tray icon ┐  click ───────────────► command bar ─Enter─┐
    │  menu     │  double-click ───────► dashboard           │
    └───────────┘                                            ▼
    Ctrl+Shift+Space (anywhere) ─► command bar     dashboard's CommandWorker ─► JARVIS
    hold Ctrl+Alt (anywhere) ────► cursor buddy                     │
                                                    reply ◄─────────┘ (to the bar that asked)

The dashboard (main_gui.MainWindow) owns JARVIS, the worker, voice and the
buddy; this shell only adds the always-available surfaces and never runs
commands itself, so there is one queue, one history and one set of
confirmations no matter where a request came from.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.shell")


class TrayApp(QObject):
    _summon = Signal()                 # hotkey thread → GUI thread
    _converse = Signal()               # conversation hotkey (F8) → GUI thread

    def __init__(self, window, bar, tray=None, instance=None, start_hidden=False, first_run=False):
        super().__init__()
        self.window = window
        self.bar = bar
        self.tray = tray
        self.instance = instance
        self.first_run = first_run
        self.hotkey = None
        self.talk_hotkey = None
        self._told_hidden = False
        self._quitting = False
        self._state_wired = False
        window.hide_on_close = tray is not None
        self._summon.connect(self.show_bar)
        self._converse.connect(self.toggle_conversation)

        bar.submitted.connect(self._submit)
        bar.open_dashboard.connect(self.show_dashboard)
        bar.mic_toggled.connect(self.set_live_voice)
        window.bar_reply.connect(bar.show_result)
        window.ready.connect(self._on_ready)
        window.hidden_to_tray.connect(self._on_hidden)
        window.settings_changed.connect(self._restart_hotkey)
        window.btn_voice_chat.toggled.connect(self._voice_changed)
        window.btn_buddy.toggled.connect(self._buddy_changed)
        window._bridge.notify_requested.connect(self._notify_if_hidden)
        if instance is not None:
            instance.message.connect(self._on_instance_message)
        if tray is not None:
            tray.ask.connect(self.show_bar)
            tray.dashboard.connect(self.show_dashboard)
            tray.settings.connect(self.open_settings)
            tray.buddy_toggled.connect(self.set_buddy)
            tray.voice_toggled.connect(self.set_live_voice)
            tray.startup_toggled.connect(self.set_startup)
            tray.quit.connect(self.quit)
            from core import autostart
            tray.set_checked(tray.act_startup, autostart.is_enabled())
            tray.show()
        if tray is None or not start_hidden:
            self.show_dashboard()

    # ── surfaces ─────────────────────────────────────────────────────────────
    def show_bar(self):
        self.bar.summon()

    def show_dashboard(self):
        w = self.window
        if w.isMinimized():
            w.showNormal()
        else:
            w.show()
        w.raise_()
        w.activateWindow()

    def open_settings(self):
        self.show_dashboard()
        self.window.open_settings()

    def _submit(self, text):
        if not self.window.submit_from_bar(text):
            self.bar.show_result("JARVIS is still starting — try again in a moment.", error=True)

    # ── toggles (kept in sync across tray, bar and dashboard) ───────────────
    def set_buddy(self, on: bool):
        self.window.btn_buddy.setChecked(bool(on))
        self.window.toggle_buddy(bool(on))

    def set_live_voice(self, on: bool):
        btn = self.window.btn_voice_chat
        if btn.isChecked() != bool(on):
            btn.setChecked(bool(on))
            self.window.toggle_voice_chat()        # reads the button: starts or stops voice

    def set_startup(self, on: bool):
        from core import autostart
        message = autostart.set_enabled(bool(on))
        if self.tray is not None:
            self.tray.set_checked(self.tray.act_startup, autostart.is_enabled())
            self.tray.notify("JARVIS", message)

    def _voice_changed(self, on):
        self.bar.set_mic(on)
        if self.tray is not None:
            self.tray.set_checked(self.tray.act_voice, on)

    def _buddy_changed(self, on):
        if self.tray is not None:
            self.tray.set_checked(self.tray.act_buddy, on)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def _on_ready(self):
        self._buddy_changed(self.window.btn_buddy.isChecked())
        state_changed = getattr(self.window, "state_changed", None)
        if state_changed is not None and not self._state_wired:
            # one source of truth: the dashboard's state drives the tray icon and the bar's orb
            self._state_wired = True
            if self.tray is not None:
                state_changed.connect(self.tray.set_state)
            if hasattr(self.bar, "set_state"):
                state_changed.connect(self.bar.set_state)
            current = getattr(self.window, "jarvis_state", None)
            if isinstance(current, str):
                self._apply_state(current)
        elif state_changed is None:
            worker = getattr(self.window, "worker", None)
            if worker is not None and self.tray is not None:
                worker.busy_changed.connect(self.tray.set_busy)
        self._restart_hotkey()
        if self.tray is not None and (self.first_run or not self.window.isVisible()):
            from core.buddy import HOTKEYS
            buddy = HOTKEYS.get(Config.BUDDY_HOTKEY, Config.BUDDY_HOTKEY) if Config.BUDDY_ENABLED else ""
            bar = self.hotkey.label if self.hotkey else ""
            parts = [f"{bar} to ask" if bar else "", f"{buddy} and talk" if buddy else ""]
            self.tray.notify("JARVIS is ready", " · ".join(p for p in parts if p) or "Click the tray icon to ask.")

    def _apply_state(self, state):
        if self.tray is not None and hasattr(self.tray, "set_state"):
            self.tray.set_state(state)
        if hasattr(self.bar, "set_state"):
            self.bar.set_state(state)

    def _restart_hotkey(self):
        from core.hotkeys import TapHotkey
        if self.hotkey is not None:
            if self.hotkey.combo == Config.COMMAND_BAR_HOTKEY:
                return
            self.hotkey.stop()
        self.hotkey = TapHotkey(Config.COMMAND_BAR_HOTKEY, self._summon.emit)
        if not self.hotkey.start():
            log.warning("command bar hotkey unavailable; use the tray icon")
        self._restart_talk_hotkey()

    def _restart_talk_hotkey(self):
        from core.hotkeys import TapHotkey
        combo = Config.CONVERSATION_HOTKEY
        if self.talk_hotkey is not None:
            if self.talk_hotkey.combo == combo and combo != Config.COMMAND_BAR_HOTKEY:
                return
            self.talk_hotkey.stop()
            self.talk_hotkey = None
        if combo == Config.COMMAND_BAR_HOTKEY:       # the command bar keeps its key
            log.warning("conversation hotkey %s is taken by the command bar", combo)
            return
        self.talk_hotkey = TapHotkey(combo, self._converse.emit)
        if not self.talk_hotkey.start():
            log.warning("conversation hotkey unavailable")
            self.talk_hotkey = None

    def toggle_conversation(self):
        toggle = getattr(self.window, "toggle_conversation", None)
        if toggle is not None:
            toggle()

    def _on_hidden(self):
        if self.tray is not None and not self._told_hidden:
            self._told_hidden = True
            label = self.hotkey.label if self.hotkey else "the tray icon"
            self.tray.notify("JARVIS is still running", f"It's in the tray. Press {label} to ask anything.")

    def _notify_if_hidden(self, text):
        if self.tray is not None and not self.window.isVisible():
            self.tray.notify("JARVIS", text)

    def _on_instance_message(self, message):
        (self.show_dashboard if message == "dashboard" else self.show_bar)()

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        if self.hotkey is not None:
            self.hotkey.stop()
        if self.talk_hotkey is not None:
            self.talk_hotkey.stop()
        self.bar.hide()
        self.window.quit_app()                 # stops voice, buddy, worker, JARVIS
        if self.tray is not None:
            self.tray.hide()
        if self.instance is not None:
            self.instance.close()
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)
