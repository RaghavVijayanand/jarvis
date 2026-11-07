"""System-tray presence and single-instance handling for the JARVIS tray app.

The tray icon carries a small status dot (green listening, blue thinking, amber
acting, red error, none when idle) and its menu opens with a HUD header row that
shows the live state ("● STANDING BY"). ``Tray.set_state(state)`` drives both.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget, QWidgetAction

from ui import theme

INSTANCE_NAME = "JARVIS-Assistant-Instance"
_EOM = bytes([10])          # end of a single-instance message (newline)


class SingleInstance(QObject):
    """Only one JARVIS runs. Starting it again tells the running one to show itself."""
    message = Signal(str)

    def __init__(self, name: str = INSTANCE_NAME):
        super().__init__()
        self.name = name
        self.server = None

    def notify_running(self, message: str = "show", timeout_ms: int = 400) -> bool:
        """True if another instance answered (and got ``message``).

        The message is newline-terminated and the running instance acknowledges it. Waiting for
        that ack matters on Windows: if this (usually about-to-exit) process drops the pipe before
        the other side has read it, the bytes are discarded and only a bare "show" arrives."""
        # Owned by the application, not ``self``: a throwaway SingleInstance must not take the
        # socket down with it before the pipe has drained.
        sock = QLocalSocket(QCoreApplication.instance())
        sock.connectToServer(self.name)
        if not sock.waitForConnected(timeout_ms):
            sock.deleteLater()
            return False
        sock.write(message.strip().encode("utf-8") + _EOM)
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.waitForReadyRead(timeout_ms * 3)            # the ack; times out harmlessly in-process
        sock.disconnectFromServer()
        if sock.state() == QLocalSocket.UnconnectedState:
            sock.deleteLater()
        else:
            sock.disconnected.connect(sock.deleteLater)
        return True

    def listen(self) -> bool:
        QLocalServer.removeServer(self.name)          # a crashed instance may have left a stale socket
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept)
        return self.server.listen(self.name)

    def _accept(self):
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            buf, done = bytearray(), []

            def deliver(conn=conn, buf=buf, done=done):
                if done:
                    return
                done.append(True)
                self.message.emit(bytes(buf).split(_EOM, 1)[0].decode("utf-8", "ignore").strip() or "show")

            def on_ready(conn=conn, buf=buf):
                buf.extend(bytes(conn.readAll()))
                if _EOM in buf:
                    deliver()
                    conn.write(b"ok" + _EOM)
                    conn.flush()
                    conn.disconnectFromServer()

            def on_gone(conn=conn, buf=buf):
                buf.extend(bytes(conn.readAll()))
                deliver()                              # an older client without the newline

            conn.readyRead.connect(on_ready)
            conn.disconnected.connect(on_gone)
            if conn.bytesAvailable():
                on_ready()
            if conn.state() == QLocalSocket.UnconnectedState:
                on_gone()

    def close(self):
        if self.server is not None:
            self.server.close()
            self.server = None


# tray-icon status dot per state (idle / offline: none)
STATE_DOTS = {"listening": theme.STATE_COLORS["listening"], "thinking": theme.STATE_COLORS["thinking"],
              "acting": theme.STATE_COLORS["acting"], "speaking": theme.STATE_COLORS["speaking"],
              "error": theme.STATE_COLORS["error"]}
_ICONS = {}


def state_icon(state: str = "idle") -> QIcon:
    """The JARVIS mark with a small coloured status dot in the corner (none when idle). Cached per state."""
    colour = STATE_DOTS.get(state)
    if colour in _ICONS:
        return _ICONS[colour]
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        theme.draw_logo(p, size)
        if colour:
            p.setRenderHint(QPainter.Antialiasing)
            d = size * 0.42
            rect = QRectF(size - d - 0.5, size - d - 0.5, d, d)
            p.setPen(QPen(QColor(theme.BG), max(1.0, size * 0.07)))
            p.setBrush(QColor(colour))
            p.drawEllipse(rect)
        p.end()
        icon.addPixmap(pix)
    _ICONS[colour] = icon
    return icon


class _MenuHeader(QWidget):
    """The top row of the tray menu: the JARVIS mark, the name, and the live state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.setMinimumSize(236, 46)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_state(self, state: str):
        self.state = state
        self.update()

    def sizeHint(self):
        return QSize(236, 46)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 3, -4, -5)
        col = QColor(theme.STATE_COLORS.get(self.state, theme.ACCENT))
        # plate + brackets
        p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.18), 1))
        p.setBrush(theme.qcolor(theme.CARD, 0.9))
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.8), 1.3))
        L = 7
        for (ax, ay, bx, by, cx, cy) in ((r.left(), r.top() + L, r.left(), r.top(), r.left() + L, r.top()),
                                         (r.right() - L, r.bottom(), r.right(), r.bottom(), r.right(), r.bottom() - L)):
            p.drawLine(QPointF(ax, ay), QPointF(bx, by))
            p.drawLine(QPointF(bx, by), QPointF(cx, cy))
        # mark
        p.save()
        p.translate(r.left() + 9, r.center().y() - 11)
        theme.draw_logo(p, 22, background=False)
        p.restore()
        p.setFont(theme.hud_font(9.5))
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(r.left() + 38, r.top(), 80, r.height()), Qt.AlignLeft | Qt.AlignVCenter, "JARVIS")
        # state: ● STANDING BY
        label = theme.STATE_LABELS.get(self.state, self.state).upper()
        p.setFont(theme.hud_font(7.5))
        w = QFontMetrics(p.font()).horizontalAdvance(label)
        x = r.right() - 12 - w
        p.setPen(col)
        p.drawText(QRectF(x, r.top(), w + 4, r.height()), Qt.AlignLeft | Qt.AlignVCenter, label)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qcolor(col.name(), 0.25))
        p.drawEllipse(QPointF(x - 10, r.center().y()), 5, 5)
        p.setBrush(col)
        p.drawEllipse(QPointF(x - 10, r.center().y()), 2.6, 2.6)
        p.end()


def _menu_stylesheet() -> str:
    return f"""
QMenu {{
    background: rgba(6, 12, 20, 246); color: {theme.TEXT}; border: 1px solid {theme.BORDER};
    border-radius: 12px; padding: 6px; font-family: {theme.FONT}; font-size: 13px;
}}
QMenu::item {{ padding: 8px 18px 8px 10px; border-radius: 7px; border: 1px solid transparent; background: transparent; }}
QMenu::item:selected {{ background: rgba(0, 229, 255, 20); border: 1px solid rgba(0, 229, 255, 70); color: {theme.ACCENT}; }}
QMenu::item:disabled {{ color: {theme.FAINT}; }}
QMenu::icon {{ padding-left: 10px; }}
QMenu::icon:checked {{ background: transparent; border: none; }}
QMenu::indicator {{ width: 0px; height: 0px; }}
QMenu::separator {{ height: 1px; background: {theme.BORDER_SOFT}; margin: 5px 10px; }}
QMenu::right-arrow {{ width: 0px; }}
"""


class Tray(QObject):
    """The tray icon and its menu. Emits intents; the app decides what they do."""
    ask = Signal()
    dashboard = Signal()
    settings = Signal()
    buddy_toggled = Signal(bool)
    voice_toggled = Signal(bool)
    startup_toggled = Signal(bool)
    quit = Signal()

    ICONS = {"ask": "sparkle", "dash": "home", "buddy": "cursor", "voice": "mic", "startup": "power",
             "settings": "gear", "quit": "close"}

    def __init__(self, bar_hotkey: str = "", parent=None):
        super().__init__(parent)
        self._state = "idle"
        self.icon = QSystemTrayIcon(state_icon("idle"), parent)
        self.icon.setToolTip(self._tooltip("idle"))
        menu = QMenu()
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)      # rounded corners without black edges
        menu.setStyleSheet(_menu_stylesheet())

        self.header = _MenuHeader()
        self.act_header = QWidgetAction(menu)
        self.act_header.setDefaultWidget(self.header)
        self.act_header.setEnabled(False)
        self.act_header.setText(self._header_text("idle"))

        def action(text, key, checkable=False, color=None):
            act = QAction(text, menu, checkable=checkable)
            act.setIcon(theme.icon(self.ICONS[key], 16, color=color or theme.TEXT_2, active=theme.ACCENT,
                                   checked=theme.STATE_COLORS["listening"] if checkable else theme.ACCENT))
            act.setIconVisibleInMenu(True)
            return act

        self.act_ask = action(f"Ask JARVIS…\t{bar_hotkey}" if bar_hotkey else "Ask JARVIS…", "ask",
                              color=theme.ACCENT)
        self.act_ask.triggered.connect(self.ask.emit)
        self.act_dash = action("Open dashboard", "dash")
        self.act_dash.triggered.connect(self.dashboard.emit)
        self.act_buddy = action("Cursor buddy", "buddy", checkable=True)
        self.act_buddy.toggled.connect(self.buddy_toggled.emit)
        self.act_voice = action("Live voice", "voice", checkable=True)
        self.act_voice.toggled.connect(self.voice_toggled.emit)
        self.act_startup = action("Start with Windows", "startup", checkable=True)
        self.act_startup.toggled.connect(self.startup_toggled.emit)
        self.act_settings = action("Settings…", "settings")
        self.act_settings.triggered.connect(self.settings.emit)
        self.act_quit = action("Quit JARVIS", "quit", color=theme.MUTED)
        self.act_quit.triggered.connect(self.quit.emit)
        self._toggle_names = {}
        for act in (self.act_buddy, self.act_voice, self.act_startup):
            self._toggle_names[act] = act.text()
            act.toggled.connect(lambda _on, a=act: self._label_toggle(a))
            self._label_toggle(act)
        menu.addAction(self.act_header)
        for item in (self.act_ask, self.act_dash, None, self.act_buddy, self.act_voice, self.act_startup, None,
                     self.act_settings, self.act_quit):
            menu.addSeparator() if item is None else menu.addAction(item)
        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self):
        self.icon.show()

    def hide(self):
        self.icon.hide()

    def _activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:          # single click → command bar
            self.ask.emit()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.dashboard.emit()

    def _label_toggle(self, action: QAction):
        """Checkable rows show their state on the right: "Live voice      ON"."""
        action.setText(f"{self._toggle_names[action]}\t{'ON' if action.isChecked() else 'OFF'}")

    def set_checked(self, action: QAction, on: bool):
        action.blockSignals(True)                      # reflect state without re-triggering it
        action.setChecked(bool(on))
        action.blockSignals(False)
        if action in self._toggle_names:
            self._label_toggle(action)

    # ── state ────────────────────────────────────────────────────────────────
    @property
    def state(self) -> str:
        return self._state

    @staticmethod
    def _header_text(state: str) -> str:
        return f"● {theme.STATE_LABELS.get(state, state)}"

    @staticmethod
    def _tooltip(state: str) -> str:
        text = f"JARVIS — {theme.STATE_LABELS.get(state, state)}"
        if state in ("thinking", "acting"):
            text += " (working…)"
        return text

    def set_state(self, state: str):
        """Show JARVIS's state (a ``theme.STATE_COLORS`` key): icon dot, tooltip and the menu header."""
        state = state if state in theme.STATE_COLORS else "idle"
        self._state = state
        self.icon.setIcon(state_icon(state))
        self.icon.setToolTip(self._tooltip(state))
        self.act_header.setText(self._header_text(state))
        self.header.set_state(state)

    def set_busy(self, busy: bool):
        self.set_state("thinking" if busy else "idle")

    def notify(self, title: str, text: str, seconds: int = 6):
        if self.icon.isVisible() and QSystemTrayIcon.supportsMessages():
            self.icon.showMessage(title, text[:250], theme.app_icon(), seconds * 1000)
