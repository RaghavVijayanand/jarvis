"""JARVIS desktop GUI (PySide6) — the HUD dashboard.

The window appears immediately; JARVIS initialises right after the first paint
(UC 1.1). All commands run on one persistent worker thread with a real,
pausable task queue — no ``QThread.terminate()`` anywhere (UC 5.1/5.2).
Confirmation requests from skills and tools are shown as dialogs on the GUI
thread while the worker waits (UC 6.2).

Layout::

    ┌ rail ┐┌ header: orb · J.A.R.V.I.S. · status pill ······ model chip · voice · buddy · mic · new ┐
    │ Chat ││ ┌ page (chat / automate / system) ─────────────────────────┐ ┌ ACTIVITY ─────────┐ │
    │ Auto ││ │  hero or messages (ui/chat_view.py)                       │ │ state · timeline  │ │
    │ Sys  ││ │  [📷  Ask JARVIS or tell it what to do…      🎤  ➤]       │ │ recent            │ │
    │ Mem  ││ └───────────────────────────────────────────────────────────┘ └───────────────────┘ │
    └──────┘└────────────────────────────────────────────────────────────────────────────────────┘

One state source of truth: ``MainWindow.set_jarvis_state(state, detail)`` →
``state_changed(str)``; it drives the header orb, hero orb, status pill,
activity panel and typing indicator.
"""
import sys
import os
import queue
import threading
import time
from datetime import datetime

# A windowed (no-console) EXE has no stdout/stderr; give prints somewhere to go.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QTextEdit, QLineEdit, QPushButton, QComboBox, QLabel,
    QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox,
    QStatusBar, QDialog, QListWidget, QDialogButtonBox, QStackedWidget, QFrame,
    QScrollArea, QInputDialog, QSizePolicy, QStyledItemDelegate, QStyle, QAbstractItemView
)
from PySide6.QtCore import (Qt, QThread, Signal, QTimer, QUrl, QObject, QEvent, QSize, QRectF, QPointF,
                            QMetaObject)
from PySide6.QtGui import QFont, QAction, QColor, QPainter, QPen, QFontMetrics, QPainterPath

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except Exception:  # QtWebEngine is an optional, large component
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False

from core.config import Config
from core.logging_setup import setup_logging, get_logger
from ui.settings import SettingsDialog
from ui import theme as _theme
from ui.widgets import ArcOrb, Caption, GridBackground, HudPanel, IconButton, StatusPill
from ui.dash_widgets import (FlowLayout, GlassFrame, HeaderBar, LiveCaption, NavButton, OrbButton, RailFrame, ReflowGrid,
                             StatTile, read_system_stats)
from ui.chat_view import ChatView, greeting_for
from ui.activity import ActivityPanel

log = get_logger("jarvis.gui")

# ── Palette ──────────────────────────────────────────────────────────────────
# One palette for every surface (ui/theme.py): dashboard, command bar, tray, buddy, setup.
_BG      = _theme.BG
_SIDE    = _theme.SIDE
_PANEL   = _theme.PANEL
_CARD    = _theme.CARD
_INPUT   = _theme.INPUT
_BORDER  = _theme.BORDER
_CYAN    = _theme.ACCENT
_PURPLE  = _theme.ACCENT_2
_TEXT    = _theme.TEXT
_MUTED   = _theme.MUTED
_SUCCESS = _theme.SUCCESS
_WARN    = _theme.WARN
_ERR     = _theme.ERROR
_LISTEN  = _theme.STATE_COLORS["listening"]

APP_STYLESHEET = _theme.app_stylesheet() + f"""
QMainWindow {{ background: {_BG}; }}
QStackedWidget, QWidget#page {{ background: transparent; }}

QComboBox#modelChip {{
    background: {_CARD}; border: 1px solid {_BORDER}; border-radius: 15px;
    padding: 4px 26px 4px 30px; color: {_theme.TEXT_2}; font-size: 12px;
}}
QComboBox#modelChip:hover {{ border-color: {_theme.ACCENT_DIM}; color: {_TEXT}; }}
QComboBox#modelChip:disabled {{ color: {_theme.FAINT}; }}

QLineEdit#chatInput {{
    background: transparent; border: none; padding: 8px 4px; font-size: 14px; color: {_TEXT};
}}
QLineEdit#chatInput:focus {{ background: transparent; border: none; }}
QLineEdit#chatInput:disabled {{ color: {_theme.FAINT}; }}

QLabel#wordmark {{ color: {_TEXT}; background: transparent; font-family: {_theme.HUD_FONT}; font-size: 17px;
    font-weight: 600; letter-spacing: 4px; }}
QLabel#wordsub {{ color: {_theme.FAINT}; background: transparent; font-family: {_theme.HUD_FONT}; font-size: 9px;
    font-weight: 600; letter-spacing: 3px; }}
QPushButton#chip {{ border-radius: 13px; padding: 0 14px; }}
QComboBox#modelChip::drop-down {{ width: 0; border: none; }}
QComboBox#modelChip::down-arrow {{ image: none; width: 0; height: 0; border: none; }}
QLabel#pageTitle {{ color: {_TEXT}; font-family: {_theme.HUD_FONT}; font-size: 19px; font-weight: 600;
    letter-spacing: 2px; background: transparent; }}
QLabel#pageSub {{ color: {_MUTED}; font-size: 12px; background: transparent; }}
QLabel#cardTitle {{ color: {_theme.TEXT_2}; font-family: {_theme.HUD_FONT}; font-size: 10px; font-weight: 600;
    letter-spacing: 2px; background: transparent; }}
QLabel#cardHint {{ color: {_MUTED}; font-size: 12px; background: transparent; }}
QLabel#liveCaption {{ color: {_LISTEN}; font-size: 12px; font-style: italic; background: transparent; }}

QTextEdit#log, QTextEdit#sysinfo {{
    background: #03070B; border: 1px solid {_theme.BORDER_SOFT}; border-radius: 10px;
    font-family: {_theme.MONO}; font-size: 12px; color: #BFEFFF; padding: 8px;
}}
QTextEdit#taskInput {{ font-size: 13px; }}

QStatusBar {{ background: {_theme.BG_2}; color: {_MUTED}; border-top: 1px solid {_theme.BORDER_SOFT};
    font-family: {_theme.HUD_FONT}; font-size: 10px; letter-spacing: 1px; min-height: 24px; }}
QStatusBar QLabel {{ color: {_MUTED}; font-family: {_theme.HUD_FONT}; font-size: 10px; letter-spacing: 1px;
    padding: 0 8px; background: transparent; }}
QMenuBar {{ font-size: 12px; padding: 1px 4px; }}
"""


class MicrophoneSettingsDialog(QDialog):
    def __init__(self, voice_engine, parent=None):
        super().__init__(parent)
        self.voice_engine = voice_engine
        self.setWindowTitle("Microphone Settings")
        self.setModal(True)
        self.resize(500, 400)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Current Microphone:"))
        self.current_mic_label = QLabel(self.voice_engine.get_current_microphone_info())
        layout.addWidget(self.current_mic_label)
        layout.addWidget(QLabel(""))
        layout.addWidget(QLabel("Available Microphones:"))
        self.mic_list = QListWidget()
        self.populate_microphones()
        layout.addWidget(self.mic_list)
        btn_layout = QHBoxLayout()
        test_btn = QPushButton("Test Selected")
        test_btn.clicked.connect(self.test_microphone)
        btn_layout.addWidget(test_btn)
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.populate_microphones)
        btn_layout.addWidget(refresh_btn)
        layout.addLayout(btn_layout)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def populate_microphones(self):
        self.mic_list.clear()
        mics = self.voice_engine.get_available_microphones()
        if not mics:
            self.mic_list.addItem("No microphones found")
            return
        for mic in mics:
            txt = f"[{mic['index']}] {mic['name']}"
            if mic.get('is_default'):
                txt += " (Default)"
            self.mic_list.addItem(txt)
            if (self.voice_engine.selected_mic_index is not None and
                    mic['index'] == self.voice_engine.selected_mic_index):
                # The device index is not the list row (input devices are sparse).
                self.mic_list.setCurrentRow(self.mic_list.count() - 1)

    def test_microphone(self):
        item = self.mic_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Warning", "Please select a microphone to test.")
            return
        try:
            mic_index = int(item.text().split(']')[0].split('[')[1])
            original = self.voice_engine.selected_mic_index
            if self.voice_engine.set_microphone(mic_index):
                QMessageBox.information(self, "Test",
                    f"Microphone set to: {item.text()}\n\nSpeak now — listening for 5 seconds.")
                result = self.voice_engine.listen_for_command(timeout=5)
                if result:
                    QMessageBox.information(self, "Test Result", f"Microphone working!\n\nRecognized: '{result}'")
                else:
                    QMessageBox.warning(self, "Test Result", "No speech detected.")
                    if original is not None:
                        self.voice_engine.set_microphone(original)
            else:
                QMessageBox.critical(self, "Error", "Failed to set microphone.")
        except (ValueError, IndexError):
            QMessageBox.critical(self, "Error", "Invalid microphone selection.")

    def accept(self):
        item = self.mic_list.currentItem()
        if item:
            try:
                mic_index = int(item.text().split(']')[0].split('[')[1])
                if self.voice_engine.set_microphone(mic_index):
                    QMessageBox.information(self, "Success", "Microphone settings saved!")
                else:
                    QMessageBox.critical(self, "Error", "Failed to apply microphone settings.")
            except (ValueError, IndexError):
                QMessageBox.critical(self, "Error", "Invalid microphone selection.")
        super().accept()


# ── Standalone Browser Window ────────────────────────────────────────────────

class BrowserWindow(QMainWindow):
    """A Chromium browser window that JARVIS can control independently."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS Browser")
        self.resize(1280, 860)
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {_BG}; color: {_TEXT};
                font-family: "Segoe UI", Arial, sans-serif; }}
        """)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        vl = QVBoxLayout(central)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setStyleSheet(f"background:{_PANEL}; border-bottom:1px solid {_BORDER};")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(6)

        def nav_btn(icon):
            b = QPushButton(icon)
            b.setFixedSize(30, 30)
            b.setStyleSheet(f"""
                QPushButton {{ background:{_INPUT}; color:{_TEXT}; border:1px solid {_BORDER};
                    border-radius:4px; font-size:14px; }}
                QPushButton:hover {{ background:{_BORDER}; }}
            """)
            return b

        self._back_btn    = nav_btn("◀")
        self._forward_btn = nav_btn("▶")
        self._reload_btn  = nav_btn("↻")
        self._back_btn.clicked.connect(lambda: self.webview.back())
        self._forward_btn.clicked.connect(lambda: self.webview.forward())
        self._reload_btn.clicked.connect(lambda: self.webview.reload())

        self._url_bar = QLineEdit()
        self._url_bar.setPlaceholderText("Enter URL…")
        self._url_bar.setStyleSheet(f"""
            QLineEdit {{ background:{_INPUT}; color:{_TEXT}; border:1px solid {_BORDER};
                border-radius:4px; padding:5px 10px; font-size:13px; }}
            QLineEdit:focus {{ border-color:{_CYAN}; }}
        """)
        self._url_bar.returnPressed.connect(self._go)

        go_btn = QPushButton("Go")
        go_btn.setFixedWidth(50)
        go_btn.setStyleSheet(f"""
            QPushButton {{ background:{_CYAN}; color:#000; font-weight:bold;
                border-radius:4px; padding:5px; }}
            QPushButton:hover {{ background:#00B8D9; }}
        """)
        go_btn.clicked.connect(self._go)

        tl.addWidget(self._back_btn)
        tl.addWidget(self._forward_btn)
        tl.addWidget(self._reload_btn)
        tl.addWidget(self._url_bar, 1)
        tl.addWidget(go_btn)
        vl.addWidget(toolbar)

        # ── WebView ───────────────────────────────────────────────────────────
        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("about:blank"))
        self.webview.urlChanged.connect(self._url_changed)
        self.webview.loadFinished.connect(self._load_finished)
        self.webview.titleChanged.connect(lambda t: self.setWindowTitle(f"JARVIS Browser — {t}" if t else "JARVIS Browser"))
        vl.addWidget(self.webview, 1)

        # ── Status / JS bar ──────────────────────────────────────────────────
        status_bar = QWidget()
        status_bar.setStyleSheet(f"background:{_PANEL}; border-top:1px solid {_BORDER};")
        sl = QHBoxLayout(status_bar)
        sl.setContentsMargins(8, 3, 8, 3)
        sl.setSpacing(6)

        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet(f"color:{_MUTED}; font-size:11px;")

        self._js_bar = QLineEdit()
        self._js_bar.setPlaceholderText("Run JS… e.g.  document.querySelector('button').click()")
        self._js_bar.setStyleSheet(f"""
            QLineEdit {{ background:{_INPUT}; color:{_TEXT}; border:1px solid {_BORDER};
                border-radius:3px; padding:3px 8px; font-size:12px; font-family: Consolas, monospace; }}
            QLineEdit:focus {{ border-color:{_PURPLE}; }}
        """)
        self._js_bar.returnPressed.connect(self._run_js_bar)

        js_btn = QPushButton("▶ JS")
        js_btn.setFixedWidth(52)
        js_btn.setStyleSheet(f"""
            QPushButton {{ background:{_PURPLE}; color:#fff; font-weight:bold;
                border-radius:3px; padding:3px; font-size:11px; }}
            QPushButton:hover {{ background:#6D28D9; }}
        """)
        js_btn.clicked.connect(self._run_js_bar)

        sl.addWidget(self._status_lbl, 1)
        sl.addWidget(self._js_bar, 2)
        sl.addWidget(js_btn)
        vl.addWidget(status_bar)

    # ── Public API (called by JARVIS) ─────────────────────────────────────────

    def navigate(self, url: str):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.webview.setUrl(QUrl(url))

    def navigate_then_js(self, url: str, js_code: str):
        """Navigate to url, then execute js_code once after the page loads."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._pending_js = js_code
        try:
            self.webview.loadFinished.disconnect(self._exec_pending_js)
        except Exception:
            pass
        self.webview.loadFinished.connect(self._exec_pending_js)
        self.webview.setUrl(QUrl(url))

    def _exec_pending_js(self, ok: bool):
        js = getattr(self, "_pending_js", None)
        self._pending_js = None
        try:
            self.webview.loadFinished.disconnect(self._exec_pending_js)
        except Exception:
            pass
        if js:
            QTimer.singleShot(1000, lambda: self.webview.page().runJavaScript(js))

    def run_js(self, code: str, callback=None):
        if callback:
            # Qt 6 signature is (script, worldId, callback); (script, callback) raises TypeError.
            self.webview.page().runJavaScript(code, 0, callback)
        else:
            self.webview.page().runJavaScript(code)

    def get_page_text(self, callback):
        """Extract all visible text from the current page and pass to callback."""
        self.run_js("document.body.innerText", callback)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _go(self):
        text = self._url_bar.text().strip()
        if not text:
            return
        if not text.startswith(("http://", "https://")):
            text = "https://" + text
        self.navigate(text)

    def _url_changed(self, url: QUrl):
        self._url_bar.setText(url.toString())

    def _load_finished(self, ok: bool):
        title = self.webview.title() or self.webview.url().toString()
        self._status_lbl.setText(title[:120])

    def _run_js_bar(self):
        code = self._js_bar.text().strip()
        if not code:
            return
        self.run_js(code, lambda r: self._status_lbl.setText(f"JS → {str(r)[:200]}"))
        self._js_bar.clear()



# ── Worker: one persistent thread, chat first, pausable task queue ──────────

class CommandWorker(QThread):
    """Runs every JARVIS command off the GUI thread, one at a time.

    Chat messages always run before queued tasks. The task queue can be paused
    (the current task finishes; nothing new starts), resumed and cleared.
    """
    response_ready = Signal(str, str)      # (kind, text) kind: chat | task | auto
    status_update = Signal(str)
    queue_changed = Signal(list)           # pending task labels
    busy_changed = Signal(bool)

    def __init__(self, jarvis):
        super().__init__()
        self.jarvis = jarvis
        self._chat = queue.Queue()
        self._priority = queue.Queue()     # (label, fn, kind) that must not wait behind a paused queue
        self._tasks = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = False
        self.paused = False

    # public API (GUI thread)
    def submit_chat(self, text, voice=False):
        self._chat.put((text, voice))
        self._wake.set()

    def submit_task(self, label, fn, kind="task", priority=False):
        """``priority`` items run right after chat, even while the task queue is paused."""
        if priority:
            self._priority.put((label, fn, kind))
            self._wake.set()
            return
        with self._lock:
            self._tasks.append((label, fn, kind))
        self._emit_queue()
        self._wake.set()

    def pause(self):
        self.paused = True
        self._emit_queue()

    def resume(self):
        self.paused = False
        self._emit_queue()
        self._wake.set()

    def clear_tasks(self):
        with self._lock:
            self._tasks.clear()
        self._emit_queue()

    def stop(self):
        self._stopping = True
        self._wake.set()

    def _emit_queue(self):
        with self._lock:
            labels = [label for label, _, _ in self._tasks]
        self.queue_changed.emit(labels)

    # worker thread
    def _next(self):
        try:
            text, voice = self._chat.get_nowait()
            return "chat", text, lambda: self.jarvis.process_command(text, use_voice=voice)
        except queue.Empty:
            pass
        try:
            label, fn, kind = self._priority.get_nowait()
            return kind, label, fn
        except queue.Empty:
            pass
        with self._lock:
            item = self._tasks.pop(0) if self._tasks and not self.paused else None
        if item is None:
            return None
        self._emit_queue()
        label, fn, kind = item
        return kind, label, fn

    def run(self):
        while not self._stopping:
            item = self._next()
            if item is None:
                self._wake.wait(0.25)
                self._wake.clear()
                continue
            kind, label, fn = item
            self.busy_changed.emit(True)
            self.status_update.emit(f"Working: {label[:60]}")
            try:
                result = fn()
                text = str(result) if result not in (None, "") else "Done."
            except Exception as exc:
                log.exception("command failed")
                text = f"Error: {exc}"
            self.response_ready.emit(kind, text)
            self.busy_changed.emit(False)
            self.status_update.emit("Ready")


class VoiceChatWorker(QThread):
    message_received = Signal(str)
    response_ready = Signal(str)
    status_update = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, jarvis):
        super().__init__()
        self.jarvis = jarvis
        self.voice_engine = jarvis.voice_engine
        self.active = False

    def run(self):
        self.active = True
        self.jarvis._voice_mode = True
        while self.active:
            try:
                self.status_update.emit("Listening…")
                command = self.voice_engine.listen_continuously(timeout=30)
                if not self.active:
                    break
                if not command:
                    continue
                self.message_received.emit(command)
                self.status_update.emit("Thinking…")
                response = self.jarvis.process_command(command, use_voice=False) or "I'm not sure how to respond to that."
                self.response_ready.emit(str(response))
                self.status_update.emit("Speaking…")
                self.voice_engine.speak(str(response), summarize=True)
            except Exception as e:
                if self.active:
                    self.error_occurred.emit(f"Voice chat error: {e}")
                    self.msleep(1500)
        self.jarvis._voice_mode = False
        self.status_update.emit("Voice chat stopped")

    def stop(self):
        self.active = False
        try:
            self.voice_engine.stop_speaking()
        except Exception:
            pass


def _chime(on: bool):
    """Rising tones: conversation on; falling: off — audible when the window is hidden in the tray."""
    if os.name != "nt":
        return

    def run():
        try:
            import winsound
            for freq in ((880, 1320) if on else (1320, 880)):
                winsound.Beep(freq, 70)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


class _Bridge(QObject):
    """Marshals requests from worker threads onto the GUI thread."""
    live_event = Signal(str, object)          # live-voice events (partial, dispatched, step_done, …)
    live_failed = Signal()
    confirm_requested = Signal(str, object)   # question, holder
    notify_requested = Signal(str)
    exit_requested = Signal()
    decision_status = Signal(str)
    catalog_ready = Signal(str)
    ollama_ready = Signal()
    system_info_ready = Signal(str)
    buddy_event = Signal(str, object)         # Buddy mode (core/buddy.py) → overlay + transcript
    conversation_event = Signal(str, object)  # Conversation mode (core/conversation.py) → transcript + orb


class _FactDelegate(QStyledItemDelegate):
    """Facts as wrapped glass cards with a delete icon on hover / selection."""
    PAD, TRASH = 12, 26

    def __init__(self, view, on_delete):
        super().__init__(view)
        self.view = view
        self.on_delete = on_delete

    def _text_width(self):
        return max(80, self.view.viewport().width() - 2 * self.PAD - 36 - self.TRASH - 12)

    def sizeHint(self, option, index):
        fm = QFontMetrics(_theme.text_font(10))
        br = fm.boundingRect(0, 0, self._text_width(), 10000, Qt.TextWordWrap, index.data() or "")
        return QSize(self.view.viewport().width() - 8, max(46, br.height() + 24))

    def _trash_rect(self, rect):
        return QRectF(rect.right() - self.TRASH - 10, rect.center().y() - self.TRASH / 2, self.TRASH, self.TRASH)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 3, -2, -3)
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        p.setPen(QPen(QColor(_theme.ACCENT_DIM if selected else _theme.BORDER if hover else _theme.BORDER_SOFT), 1))
        p.setBrush(QColor(_theme.CARD_HI if selected or hover else _theme.CARD))
        p.drawRoundedRect(r, 10, 10)
        p.drawPixmap(int(r.left() + 12), int(r.center().y() - 8), _theme.icon_pixmap("sparkle", 16, _theme.ACCENT))
        p.setFont(_theme.text_font(10))
        p.setPen(QColor(_TEXT))
        text_rect = QRectF(r.left() + 38, r.top(), self._text_width(), r.height())
        p.drawText(text_rect, Qt.TextWordWrap | Qt.AlignVCenter, index.data() or "")
        if selected or hover:
            tr = self._trash_rect(r)
            p.setPen(Qt.NoPen)
            p.setBrush(_theme.qcolor(_ERR, 0.12))
            p.drawRoundedRect(tr, 7, 7)
            p.drawPixmap(int(tr.center().x() - 8), int(tr.center().y() - 8), _theme.icon_pixmap("trash", 16, _ERR))
        p.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease:
            r = QRectF(option.rect).adjusted(2, 3, -2, -3)
            if self._trash_rect(r).contains(event.position()):
                self.on_delete(index.row())
                return True
        return super().editorEvent(event, model, option, index)


class MemoryDialog(QDialog):
    """View and edit what JARVIS remembers (UC 10.3)."""

    def __init__(self, memory, parent=None):
        super().__init__(parent)
        self.memory = memory
        self.setWindowTitle("What JARVIS remembers")
        self.setWindowIcon(_theme.app_icon())
        self.resize(560, 520)
        self.setMinimumSize(440, 380)
        self.setStyleSheet(APP_STYLESHEET + f"""
            QDialog {{ background: {_BG}; }}
            QListWidget#facts {{ background: transparent; border: none; padding: 0; }}
            QListWidget#facts::item, QListWidget#facts::item:hover, QListWidget#facts::item:selected
                {{ background: transparent; border: none; padding: 0; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        card = HudPanel("Profile", glow=True)
        cl = QHBoxLayout(card)
        cl.setContentsMargins(16, 30, 16, 14)
        cl.setSpacing(14)
        avatar = QLabel()
        avatar.setFixedSize(46, 46)
        avatar.setPixmap(self._avatar())
        cl.addWidget(avatar, 0, Qt.AlignTop)
        self.header = QLabel()
        self.header.setWordWrap(True)
        self.header.setTextFormat(Qt.RichText)
        self.header.setStyleSheet("background: transparent;")
        cl.addWidget(self.header, 1)
        layout.addWidget(card)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.count_lbl = Caption("Facts")
        row.addWidget(self.count_lbl)
        row.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search facts…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.addAction(_theme.icon("search", 16, _MUTED), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        row.addWidget(self.search)
        layout.addLayout(row)

        self.facts = QListWidget()
        self.facts.setObjectName("facts")
        self.facts.setMouseTracking(True)
        self.facts.setWordWrap(True)
        self.facts.setResizeMode(QListWidget.Adjust)
        self.facts.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.facts.setSpacing(1)
        self.facts.setItemDelegate(_FactDelegate(self.facts, self._forget_row))
        layout.addWidget(self.facts, 1)
        self.empty = QLabel("Nothing remembered yet.\nSay “remember that …” or share lasting details and they appear here.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(f"color: {_theme.FAINT}; font-size: 12px; background: transparent;")
        layout.addWidget(self.empty, 1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        add = QPushButton("  Add fact")
        add.setObjectName("primary")
        add.setIcon(_theme.icon("plus", 16, "#00121A", active="#00121A"))
        add.clicked.connect(self._add)
        btns.addWidget(add)
        forget = QPushButton("Forget selected")
        forget.clicked.connect(self._forget)
        btns.addWidget(forget)
        btns.addStretch()
        wipe = QPushButton("Forget everything")
        wipe.setObjectName("danger")
        wipe.clicked.connect(self._wipe)
        btns.addWidget(wipe)
        close = QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(self.reject)
        btns.addWidget(close)
        layout.addLayout(btns)
        self._refresh()

    @staticmethod
    def _avatar():
        from PySide6.QtGui import QPixmap
        pix = QPixmap(92, 92)
        pix.setDevicePixelRatio(2.0)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(_theme.qcolor(_CYAN, 0.6), 1.2))
        p.setBrush(_theme.qcolor(_CYAN, 0.08))
        p.drawEllipse(QRectF(1, 1, 44, 44))
        p.drawPixmap(11, 11, _theme.icon_pixmap("user", 24, _CYAN))
        p.end()
        return pix

    def _refresh(self):
        from core.config import get_location_preference
        name = self.memory.memory.get("user_name") or "not set"
        loc = get_location_preference() or "auto-detect"
        self.header.setText(
            f"<div style='font-size:17px; color:{_TEXT}; font-weight:600;'>{_esc(name)}</div>"
            f"<div style='color:{_theme.TEXT_2}; margin-top:3px;'>Name: {_esc(name)} &nbsp;·&nbsp; Location: {_esc(loc)}</div>"
            f"<div style='color:{_MUTED}; margin-top:6px;'>Facts are added when you say ‘remember that …’ "
            "or share lasting personal details.</div>")
        self.facts.clear()
        facts = self.memory.list_facts()
        for fact in facts:
            self.facts.addItem(fact)
        self.count_lbl.setText(f"{len(facts)} fact{'s' if len(facts) != 1 else ''} remembered")
        self._filter(self.search.text())

    def _filter(self, text=""):
        needle = (text or "").strip().lower()
        shown = 0
        for i in range(self.facts.count()):
            hide = bool(needle) and needle not in self.facts.item(i).text().lower()
            self.facts.setRowHidden(i, hide)
            shown += not hide
        self.facts.setVisible(shown > 0)
        self.empty.setVisible(shown == 0)
        if needle and not shown:
            self.empty.setText(f"No facts match “{text}”.")
        elif not shown:
            self.empty.setText("Nothing remembered yet.\nSay “remember that …” or share lasting details "
                               "and they appear here.")

    def _add(self):
        text, ok = QInputDialog.getText(self, "Add a fact", "Fact about you:")
        if ok and text.strip():
            self.memory.remember_fact(text)
            self._refresh()

    def _forget_row(self, row):
        if 0 <= row < self.facts.count():
            self.facts.setCurrentRow(row)
            self._forget()

    def _forget(self):
        row = self.facts.currentRow()
        if row >= 0:
            self.memory.forget(row + 1)
            self._refresh()

    def _wipe(self):
        if QMessageBox.question(self, "Forget everything", "Erase everything JARVIS remembers about you?") \
                == QMessageBox.Yes:
            self.memory.forget_all()
            self._refresh()


def _chevron_pixmap():
    from PySide6.QtGui import QPixmap
    pix = QPixmap(20, 20)
    pix.setDevicePixelRatio(2.0)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(_MUTED), 1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(2, 3.5))
    path.lineTo(QPointF(5, 6.5))
    path.lineTo(QPointF(8, 3.5))
    p.drawPath(path)
    p.end()
    return pix


def _esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Main Window ───────────────────────────────────────────────────────────────

QUICK_CHIPS = [("Weather", "what's the weather today"), ("System", "system status"),
               ("Now playing", "what's playing"), ("Screen", "what's on my screen"),
               ("Reminders", "list reminders"), ("Help", "help")]


class _SystemPage(QWidget):
    """The System page: gauges refresh every 2 s, but only while the page is on screen."""

    def __init__(self, window):
        super().__init__()
        self.setObjectName("page")
        self.window_ref = window
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(window.refresh_gauges)

    def showEvent(self, e):
        super().showEvent(e)
        self.window_ref.refresh_gauges()
        self.timer.start()

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)


class MainWindow(QMainWindow):
    _browser_open = Signal(str)
    _browser_open_js = Signal(str, str)
    ready = Signal()                  # JARVIS finished starting (or failed to): the tray app hooks in here
    bar_reply = Signal(str)           # a reply to something typed in the command bar
    hidden_to_tray = Signal()
    settings_changed = Signal()
    state_changed = Signal(str)       # idle | listening | thinking | acting | speaking | error | offline

    ERROR_FLASH_MS = 2500
    ACTIVITY_AUTO_WIDTH = 1180        # narrower windows start with the activity panel folded away

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.setWindowIcon(_theme.app_icon())
        self.hide_on_close = False    # tray app: closing the dashboard only hides it
        self._quitting = False
        self._reply_sources = []      # "window" / "bar" per queued chat, in worker order
        self._browser_open.connect(self.navigate_browser)
        self._browser_open_js.connect(self.navigate_browser_with_js)
        self.setMinimumSize(960, 660)
        self.setGeometry(80, 80, 1280, 820)

        self.jarvis = None
        self.brain = None
        self.voice_engine = None
        self.skills = {}
        self.worker = None
        self.voice_chat_active = False
        self.voice_chat_worker = None
        self._browser_win = None
        self._bridge = _Bridge()
        self._bridge.confirm_requested.connect(self._show_confirm)
        self._bridge.notify_requested.connect(self._on_notify)
        self._bridge.exit_requested.connect(self.close)
        self._bridge.decision_status.connect(self._on_decision_status)
        self._bridge.catalog_ready.connect(self._on_catalog_ready)
        self._bridge.live_event.connect(self._on_live_event)
        self._bridge.live_failed.connect(self._on_live_failed)
        self._bridge.ollama_ready.connect(lambda: QTimer.singleShot(300, self._on_ollama_ready))
        self._bridge.buddy_event.connect(self._on_buddy_event)
        self._bridge.conversation_event.connect(self._on_conversation_event)
        self._conversation = None
        self._buddy = None
        self._buddy_overlay = None
        self._live_listener = None
        self._voice_session = 0            # bumps on every mic toggle; stale live-voice starts stop themselves
        self._retired_threads = []         # QThreads asked to stop but not finished yet (never GC a running QThread)
        self._pending_confirms = []
        self._closing = False
        self._closed = False

        # state (one source of truth → orbs, pill, activity, typing indicator, tray via state_changed)
        self._jarvis_state = "offline"
        self._state_detail = ""
        self._busy = False
        self._busy_label = ""
        self._init_failed = False
        self._error_until = 0.0
        self._last_reply_failed = False
        self._partial_len = 0
        self._live_rows = {}               # live step index → ActionMessage row
        self._activity_user_choice = None  # None: follow the window width; True/False: the user decided
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setTimerType(Qt.PreciseTimer)
        self._settle_timer.timeout.connect(self._settle_state)
        self._level_timer = QTimer(self)
        self._level_timer.setSingleShot(True)
        self._level_timer.timeout.connect(lambda: self._set_level(0.0))
        self._speak_poll = QTimer(self)
        self._speak_poll.setInterval(300)
        self._speak_poll.timeout.connect(self._poll_speaking)

        self.setup_ui()
        self._bridge.system_info_ready.connect(self.system_info.setText)
        self.setup_menus()
        self._set_ready(False)
        self.set_jarvis_state("offline", "Starting up")
        self.append_text("System", "Starting JARVIS…", ambient=True)
        # Build JARVIS after the window has painted (UC 1.1).
        QTimer.singleShot(50, self._init_jarvis)

    # ── Startup ──────────────────────────────────────────────────────────────

    def _init_jarvis(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from jarvis import JARVIS
            self.jarvis = JARVIS(show_banner=False)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            log.exception("JARVIS failed to start")
            self._init_failed = True
            self.chat.hero.set_text(subtitle="JARVIS couldn't start. The details are below — "
                                             "fix them in Settings or run doctor.py, then restart.")
            self.append_text("Error", f"JARVIS failed to start: {exc}")
            self.append_text("System", "Open ⚙ Settings or run doctor.py to find what's missing, then restart JARVIS.")
            self.status_label.setText("JARVIS failed to start")
            self._set_ready(False)
            self._settle_state()
            self.ready.emit()
            return
        QApplication.restoreOverrideCursor()
        j = self.jarvis
        self.brain = j.brain
        self.voice_engine = j.voice_engine
        self.skills = j.skills
        j.confirm_callback = self._confirm_from_worker
        j.notify_callback = self._bridge.notify_requested.emit
        j.exit_callback = self._bridge.exit_requested.emit
        j.decision.set_status_callback(self._bridge.decision_status.emit)
        self._on_decision_status(j.decision.status)
        if j.app_control:
            j.app_control.set_browser_callback(self._on_browser_open)
        if self.brain:
            self.brain.refresh_catalog_async(on_done=self._bridge.catalog_ready.emit)

        self.worker = CommandWorker(j)
        self.worker.response_ready.connect(self._on_worker_response)
        self.worker.status_update.connect(self.on_status_update)
        self.worker.queue_changed.connect(self._on_queue_changed)
        self.worker.busy_changed.connect(self._set_thinking)
        self.worker.start()
        j.dashboard_runner = self._run_for_dashboard     # web dashboard commands share this one queue
        if hasattr(j, "add_stop_hook"):
            j.add_stop_hook(self._cancel_open_confirms)   # the global stop answers open dialogs "no"

        for step in (self.refresh_models, self.update_skills_tree, self.refresh_system_info):
            try:
                step()
            except Exception:
                log.exception("startup step %s failed", step.__name__)
        self._set_ready(True)
        self._update_greeting()
        if self.brain and self.brain.current_model:
            greeting = self.brain.get_personality_response("startup") + " Type 'help' to see what I can do."
            self.append_text("JARVIS", greeting, ambient=True)
            self.chat.hero.set_text(subtitle="All systems online. Ask anything — or tell me what to do.")
        else:
            self.chat.hero.set_text(subtitle="Online in offline mode: apps, media, files and system commands work.")
            self.append_text("System", "No AI model is configured yet. Open ⚙ Settings to add a Gemini or "
                                       "OpenRouter key, or install Ollama for offline chat. Apps, media, files, "
                                       "reminders and system commands already work.")
        self._speak_poll.start()
        self.status_label.setText("Ready")
        self._settle_state()
        j.is_running = True
        try:
            j._report_missed_tasks()
        except Exception:
            log.exception("missed-task report failed")
        if Config.OLLAMA_AUTOSTART:
            self._start_ollama()
        if Config.BUDDY_ENABLED:
            self.start_buddy()
        try:
            from core import local_speech
            local_speech.warm_up()           # Whisper takes ~20 s to load; do it before the first F8
        except Exception:
            log.exception("local speech warm-up failed")
        self._install_stop_hotkey()
        self.ready.emit()

    def _update_greeting(self):
        name = None
        try:
            if self.brain is not None:
                name = (self.brain.memory.memory or {}).get("user_name")
        except Exception:
            name = None
        self.chat.hero.set_text(title=greeting_for(datetime.now().hour, name))

    # ── State: the one source of truth ───────────────────────────────────────

    @property
    def jarvis_state(self) -> str:
        return self._jarvis_state

    def set_jarvis_state(self, state: str, detail: str = ""):
        """Show what JARVIS is doing everywhere at once; emits ``state_changed`` when the state changes.

        ``error`` is a flash: it holds for ERROR_FLASH_MS, then the window settles back to
        what the steady sources say (worker busy → thinking, otherwise idle / offline).
        """
        if state not in _theme.STATE_COLORS:
            state = "idle"
        if state == "error":
            self._error_until = time.monotonic() + self.ERROR_FLASH_MS / 1000.0
            self._settle_timer.start(self.ERROR_FLASH_MS)
        elif time.monotonic() < self._error_until and state not in ("offline",):
            return                              # let the error flash finish; the settle timer restores state
        self._apply_state(state, detail)

    def _apply_state(self, state: str, detail: str = ""):
        previous = self._jarvis_state
        detail = " ".join(str(detail or "").split())
        self._jarvis_state, self._state_detail = state, detail
        short = ""
        roomy = self.width() >= 1100            # narrow windows: the pill shows the state only
        if detail and roomy and (state in ("thinking", "acting", "listening") or self._init_failed):
            short = detail if len(detail) <= 24 else detail[:23].rstrip() + "…"
        self.header_orb.set_state(state)
        self.chat.hero.orb.set_state(state)
        self.status_pill.set_state(state, short)
        self.status_pill.setToolTip(detail or _theme.STATE_LABELS.get(state, state))
        self.activity.set_state(state, detail)
        color = _theme.STATE_COLORS[state]
        label = detail if (detail and state in ("thinking", "acting")) else _theme.STATE_LABELS[state]
        self.chat.set_typing(self._busy and state in ("thinking", "acting", "speaking"), label, color)
        if state != previous:
            self.state_changed.emit(state)

    def _resting_state(self):
        if self.jarvis is None:
            return ("error", "Not running") if self._init_failed else ("offline", "Starting up")
        if self._busy:
            return "thinking", self._busy_label
        if self._conversation is not None and self._conversation.active:
            return "listening", "Conversation · F8 to end"
        return "idle", ""

    def _settle_state(self):
        """Return to whatever the steady sources say (worker busy / idle / offline)."""
        remaining = self._error_until - time.monotonic()
        if remaining > 0.01:                     # timers may fire a little early: wait out the error flash
            self._settle_timer.start(int(remaining * 1000) + 15)
            return
        self._error_until = 0.0
        self._apply_state(*self._resting_state())

    def _transient_state(self, state, detail="", settle_ms=None):
        self.set_jarvis_state(state, detail)
        if settle_ms:
            self._settle_timer.start(settle_ms)
        elif self._settle_timer.isActive() and time.monotonic() >= self._error_until:
            self._settle_timer.stop()

    def _set_level(self, level):
        self.header_orb.set_level(level)
        self.chat.hero.orb.set_level(level)
        self.activity.set_level(level)

    def _poll_speaking(self):
        v = self.voice_engine
        speaking = bool(getattr(v, "is_speaking", False)) if v is not None else False
        if speaking and self._jarvis_state in ("idle", "thinking", "listening"):
            self._transient_state("speaking", "")
        elif not speaking and self._jarvis_state == "speaking" and not self._settle_timer.isActive():
            self._settle_state()

    # ── Conversation mode (F8: talk back and forth, interrupt by talking) ────

    def toggle_conversation(self):
        if self._conversation is not None and self._conversation.active:
            self.stop_conversation()
        else:
            self.start_conversation()

    def start_conversation(self) -> bool:
        if self.jarvis is None or self.voice_engine is None:
            self.append_text("System", "JARVIS is still starting — press F8 again in a moment.")
            return False
        if self._conversation is not None and self._conversation.active:
            return True
        if self.btn_voice_chat.isChecked():          # one owner of the microphone at a time
            self.btn_voice_chat.setChecked(False)
            self.toggle_voice_chat()
        from core.conversation import ConversationMode
        self._conversation = ConversationMode(self.jarvis, on_event=self._bridge.conversation_event.emit,
                                              device_index=self.voice_engine.selected_mic_index)
        self._conversation.start()
        _chime(True)
        self.append_text("System", "Conversation on — just talk, and talk over me any time to interrupt. "
                                   "Press F8 to end.")
        self._settle_state()
        return True

    def stop_conversation(self):
        conversation, self._conversation = self._conversation, None
        if conversation is not None:
            conversation.stop()
            _chime(False)
            if not self._closing:
                self.append_text("System", "Conversation ended.")
        self._settle_state()

    def _on_conversation_event(self, kind, info):
        info = info if isinstance(info, dict) else {}
        try:
            if kind == "status" and info.get("message"):
                self.append_text("System", info["message"])
            elif kind in ("listening", "interrupted"):
                self._transient_state("listening", "Hearing you")
            elif kind == "heard" and info.get("text"):
                self.append_text("You", info["text"])
            elif kind == "thinking":
                self._transient_state("thinking", "Thinking")
            elif kind == "answer" and info.get("text"):
                self.append_text("JARVIS", info["text"])
            elif kind == "stopped":
                conversation = self._conversation
                if conversation is not None and not conversation.active:   # ended on its own (mic error)
                    self._conversation = None
                    self.append_text("System", "Conversation ended.")
                self._settle_state()
            elif kind in ("started", "idle"):
                self._settle_state()
        except Exception:
            log.exception("conversation event %s failed", kind)

    # ── Buddy mode (Clicky-style cursor companion) ───────────────────────────

    def start_buddy(self) -> bool:
        if self._buddy is not None or self.jarvis is None:
            return self._buddy is not None
        try:
            from core.buddy import BuddyController, HOTKEYS
            from ui.buddy_overlay import BuddyOverlay
            if self._buddy_overlay is None:
                self._buddy_overlay = BuddyOverlay()
            self._buddy_overlay.show()
            controller = BuddyController(self.jarvis, on_state=self._bridge.buddy_event.emit)
            if not controller.start():
                self.append_text("System", "Buddy mode needs the keyboard hook (pynput); it isn't available here.")
                self._buddy_overlay.hide()
                self.btn_buddy.setChecked(False)
                return False
        except Exception as exc:
            log.exception("buddy mode failed to start")
            self.append_text("Error", f"Buddy mode couldn't start: {exc}")
            self.btn_buddy.setChecked(False)
            return False
        self._buddy = controller
        self.jarvis.buddy = controller
        self.btn_buddy.setChecked(True)
        hotkey = HOTKEYS.get(controller.hotkey.combo, controller.hotkey.combo)
        self.append_text("System", f"Buddy is on: {hotkey} anywhere, ask about your screen, let go. "
                                   "Ask \"where is…\" or \"how do I…\" and it points; say a command and it does it.")
        return True

    def stop_buddy(self):
        if self._buddy is not None:
            try:
                self._buddy.stop()
            except Exception:
                log.exception("buddy stop failed")
            self._buddy = None
        if self.jarvis is not None:
            self.jarvis.buddy = None
        if self._buddy_overlay is not None:
            self._buddy_overlay.clear()
            self._buddy_overlay.hide()
        self.btn_buddy.setChecked(False)

    def toggle_buddy(self, checked=None):
        on = self.btn_buddy.isChecked() if checked is None else bool(checked)
        if on:
            self.start_buddy()
        else:
            self.stop_buddy()

    def _on_buddy_event(self, kind, info):
        info = info or {}
        try:
            if self._buddy_overlay is not None:
                self._buddy_overlay.set_state(kind, info)
            if kind == "heard":
                self.append_text("You", f"🎯 {info.get('text', '')}")
            elif kind == "answer" and info.get("text") and info.get("from_hotkey"):
                self.append_text("JARVIS", info["text"])
            elif kind == "error":
                self.append_text("Error", info.get("message", "Buddy error"))
        except Exception:
            log.exception("buddy event %s failed", kind)
        try:
            self.activity.on_buddy_event(kind, info)
            if kind == "listening":
                self._transient_state("listening", "Buddy is listening")
            elif kind in ("thinking", "heard"):
                self._transient_state("thinking", "Buddy is looking at your screen")
            elif kind == "point":
                self._transient_state("acting", "Pointing it out", settle_ms=4000)
            elif kind == "answer":
                self._transient_state("speaking", "Buddy is answering", settle_ms=6000)
            elif kind == "idle":
                self._settle_state()
        except Exception:
            log.exception("buddy state %s failed", kind)

    def _set_ready(self, ready: bool):
        for w in (getattr(self, "input", None), getattr(self, "btn_send", None),
                  getattr(self, "btn_voice_chat", None), getattr(self, "btn_camera", None),
                  getattr(self, "model_combo", None)):
            if w is not None:
                w.setEnabled(ready)
        chat = getattr(self, "chat", None)
        if chat is not None:
            chat.hero.set_enabled_cards(ready)
            for chip in getattr(self, "_chips", []):
                chip.setEnabled(ready)
        if getattr(self, "input", None) is not None:
            self.input.setPlaceholderText("Ask JARVIS or tell it what to do…" if ready else
                                          ("JARVIS isn't running" if self._init_failed else "JARVIS is starting…"))

    # ── Bridges ──────────────────────────────────────────────────────────────

    def _confirm_from_worker(self, question: str) -> bool:
        """Called on a worker thread; blocks it until the user answers on the GUI thread."""
        if self._closing:
            return False
        if threading.current_thread() is threading.main_thread():
            return QMessageBox.question(self, "JARVIS needs your OK", question) == QMessageBox.Yes
        holder = {"event": threading.Event(), "answer": False}
        self._pending_confirms.append(holder)
        try:
            self._bridge.confirm_requested.emit(question, holder)
            if not holder["event"].wait(timeout=300):
                # Gave up waiting: the action won't run, so the dialog must not stay up and
                # take a "Yes" that silently does nothing. Not-yet-shown dialogs are skipped too.
                holder["answer"] = False
                holder["event"].set()
                box = holder.get("box")
                if box is not None:
                    try:
                        QMetaObject.invokeMethod(box, "reject", Qt.QueuedConnection)
                    except RuntimeError:
                        pass            # already answered and deleted
        finally:
            try:
                self._pending_confirms.remove(holder)
            except ValueError:
                pass
        return holder["answer"]

    def _run_for_dashboard(self, text: str, timeout: float = 120.0) -> str:
        """Called on a web-dashboard HTTP thread. The command runs on the single worker (never
        concurrently with a chat or automation command) and this thread waits for its reply."""
        worker = self.worker
        if worker is None or self._closing:
            return "JARVIS is shutting down."
        done, out = threading.Event(), {}

        def run():
            try:
                out["text"] = self.jarvis.process_command(text, use_voice=False)
                return out["text"]
            finally:
                done.set()

        worker.submit_task(f"Dashboard: {text[:50]}", run, priority=True)
        if not done.wait(timeout):
            return "Still working on that — check the PC for the result."
        return str(out.get("text") or "Done.")

    def _show_confirm(self, question, holder):
        if self._closing or holder["event"].is_set():   # timed out / released at exit: don't pop a stale dialog
            holder["event"].set()
            return
        box = QMessageBox(self)
        box.setWindowTitle("JARVIS needs your OK")
        box.setIcon(QMessageBox.Question)
        box.setText(question)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        holder["box"] = box
        self.activity.add_recent(f"Asked: {question}", "info")
        try:
            holder["answer"] = box.exec() == QMessageBox.Yes and not holder["event"].is_set()
        finally:
            holder["event"].set()
            holder.pop("box", None)
            box.deleteLater()           # parented to the window: would otherwise pile up per question

    def _on_notify(self, text):
        text = str(text)
        # Local-AI start-up chatter is status, not conversation.
        self.append_text("System" if text.startswith("Local AI:") else "JARVIS", text)

    def _on_decision_status(self, status: str):
        if not hasattr(self, "_decision_dot"):
            return
        ready = status.lower().startswith("laya ready")
        loading = "loading" in status.lower()
        color = _SUCCESS if ready else _WARN if loading else _MUTED
        self._decision_dot.setText("● Laya" if ready or loading else "● Rules")
        self._decision_dot.setStyleSheet(f"color: {color};")
        self._decision_dot.setToolTip(f"Decision engine: {status}")
        if ready or "failed" in status.lower() or "install" in status.lower():
            self.append_text("System", f"Decision engine: {status}")

    def _on_catalog_ready(self, message: str):
        self.refresh_models()
        log.info("catalog: %s", message)

    # ── UI construction ───────────────────────────────────────────────────────

    def setup_ui(self):
        self.setStyleSheet(APP_STYLESHEET)
        central = GridBackground()
        central.setObjectName("dashRoot")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_chat_page())
        self.stack.addWidget(self._build_automate_page())
        self.stack.addWidget(self._build_system_page())
        body.addWidget(self.stack, 1)
        self.activity = ActivityPanel()
        self.activity.collapse_requested.connect(lambda: self.set_activity_visible(False, user=True))
        body.addWidget(self.activity)
        main.addLayout(body, 1)
        root.addLayout(main, 1)

        self.statusBar = QStatusBar()
        self.statusBar.setSizeGripEnabled(False)
        self.setStatusBar(self.statusBar)
        self.status_label = QLabel("Starting…")
        self.statusBar.addWidget(self.status_label, 1)
        self._decision_dot = QLabel("● Rules")
        self._decision_dot.setToolTip("Decision engine")
        self.statusBar.addPermanentWidget(self._decision_dot)
        self._local_ai_dot = QLabel("● Local AI")
        self._local_ai_dot.setToolTip("Local Ollama AI status")
        self.statusBar.addPermanentWidget(self._local_ai_dot)
        self._model_status = QLabel()
        self.statusBar.addPermanentWidget(self._model_status)

    def _build_sidebar(self) -> QWidget:
        sidebar = RailFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(76)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(2)
        logo = QLabel()
        logo.setPixmap(_theme.logo_pixmap(30))
        logo.setToolTip("JARVIS")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedHeight(44)
        layout.addWidget(logo)
        layout.addSpacing(14)
        self._nav_buttons = []
        for icon_name, label, idx in [("chat", "Chat", 0), ("bolt", "Automate", 1), ("pulse", "System", 2)]:
            btn = NavButton(icon_name, label)
            btn.clicked.connect(lambda _=False, i=idx: self._switch_page(i))
            layout.addWidget(btn)
            self._nav_buttons.append(btn)
        layout.addStretch()
        for icon_name, label, fn in (("brain", "Memory", self.open_memory), ("gear", "Settings", self.open_settings)):
            b = NavButton(icon_name, label, checkable=False)
            b.clicked.connect(lambda _=False, f=fn: f())
            layout.addWidget(b)
        self._nav_buttons[0].setChecked(True)
        return sidebar

    def _build_header(self) -> QWidget:
        header = HeaderBar()
        header.setObjectName("chatHeader")
        header.setFixedHeight(62)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 12, 0)
        hl.setSpacing(6)
        self.header_orb = ArcOrb(40, interactive=True)
        self.header_orb.setToolTip("Show the activity panel")
        self.header_orb.clicked.connect(lambda: self.set_activity_visible(True, user=True))
        hl.addWidget(self.header_orb)
        hl.addSpacing(4)
        mark = QVBoxLayout()
        mark.setSpacing(0)
        mark.addStretch()
        word = QLabel("J.A.R.V.I.S.")
        word.setObjectName("wordmark")
        mark.addWidget(word)
        self._wordsub = QLabel("PERSONAL ASSISTANT")
        self._wordsub.setObjectName("wordsub")
        mark.addWidget(self._wordsub)
        mark.addStretch()
        hl.addLayout(mark)
        hl.addSpacing(8)
        self.status_pill = StatusPill(state="offline")
        hl.addWidget(self.status_pill, 0, Qt.AlignVCenter)
        hl.addStretch(1)

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("modelChip")
        self.model_combo.setToolTip("AI model")
        self.model_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.model_combo.setMinimumWidth(128)          # shrinks (eliding) in narrow windows
        self.model_combo.setMaximumWidth(250)
        self.model_combo.setFixedHeight(30)
        chip_icon = QLabel(self.model_combo)
        chip_icon.setPixmap(_theme.icon_pixmap("chip", 15, _CYAN))
        chip_icon.setStyleSheet("background: transparent;")
        chip_icon.move(11, 7)
        chip_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._combo_chevron = QLabel(self.model_combo)
        self._combo_chevron.setPixmap(_chevron_pixmap())
        self._combo_chevron.setStyleSheet("background: transparent;")
        self._combo_chevron.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.model_combo.installEventFilter(self)
        self.model_combo.currentTextChanged.connect(self.on_model_change)
        hl.addWidget(self.model_combo, 0, Qt.AlignVCenter)
        btn_refresh_models = IconButton("refresh", "Rescan local Ollama models and refresh the cloud model lists",
                                        size=32, icon_size=16)
        btn_refresh_models.clicked.connect(self._refresh_all_models)
        hl.addWidget(btn_refresh_models)
        sep = QFrame()
        sep.setFixedSize(1, 26)
        sep.setStyleSheet(f"background: {_theme.BORDER_SOFT};")
        hl.addSpacing(4)
        hl.addWidget(sep)
        hl.addSpacing(4)
        self.btn_voice = IconButton("speaker_off", "Voice replies are off — click to speak replies aloud",
                                    size=36, icon_size=18, checkable=True)
        self.btn_voice.clicked.connect(self.toggle_voice)
        hl.addWidget(self.btn_voice)
        self.btn_buddy = IconButton("eye", "Cursor buddy: hold the hotkey anywhere, ask about your screen, let go",
                                    size=36, icon_size=18, checkable=True)
        self.btn_buddy.clicked.connect(self.toggle_buddy)
        hl.addWidget(self.btn_buddy)
        btn_mic_cfg = IconButton("sliders", "Microphone settings", size=36, icon_size=18)
        btn_mic_cfg.clicked.connect(self.open_mic_settings)
        hl.addWidget(btn_mic_cfg)
        btn_clear = IconButton("plus", "New conversation (clears the chat)", size=36, icon_size=18)
        btn_clear.clicked.connect(self.on_clear)
        hl.addWidget(btn_clear)
        self.btn_activity = IconButton("list", "Show / hide the activity panel", size=36, icon_size=18,
                                       checkable=True)
        self.btn_activity.setChecked(True)
        self.btn_activity.clicked.connect(lambda on: self.set_activity_visible(on, user=True))
        hl.addWidget(self.btn_activity)
        return header

    def _build_chat_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 10)
        vl.setSpacing(0)

        self.chat = ChatView()
        self.chat.suggestion.connect(self.quick_command)
        self.transcript = self.chat               # the old QTextEdit name: toPlainText() / clear()
        vl.addWidget(self.chat, 1)

        # live transcript (what the mic hears right now) — hidden while empty
        live = QWidget()
        ll = QHBoxLayout(live)
        ll.setContentsMargins(0, 2, 0, 6)
        ll.setSpacing(8)
        ll.addStretch()
        wave = QLabel()
        wave.setPixmap(_theme.icon_pixmap("wave", 16, _LISTEN))
        wave.setStyleSheet("background: transparent;")
        ll.addWidget(wave)
        self._thinking_lbl = LiveCaption(live)
        self._thinking_lbl.setObjectName("liveCaption")
        self._thinking_lbl.setMaximumWidth(760)
        ll.addWidget(self._thinking_lbl)
        ll.addStretch()
        live.hide()
        vl.addWidget(live)

        # the floating glass input bar
        row = QHBoxLayout()
        row.setContentsMargins(22, 0, 22, 0)
        row.addStretch(1)
        self._input_glass = GlassFrame(radius=24)
        self._input_glass.setMaximumWidth(880)
        self._input_glass.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._input_glass.setFixedHeight(58)
        il = QHBoxLayout(self._input_glass)
        il.setContentsMargins(9, 8, 9, 8)
        il.setSpacing(8)
        self.btn_camera = OrbButton("camera", "Look at the screen and describe it", diameter=40, icon_size=18)
        self.btn_camera.clicked.connect(self.take_screenshot_and_analyze)
        il.addWidget(self.btn_camera)
        self.input = QLineEdit()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText("Ask JARVIS or tell it what to do…")
        self.input.returnPressed.connect(self.on_send)
        self.input.installEventFilter(self)
        il.addWidget(self.input, 1)
        self.btn_stop = OrbButton("stop", "Stop the running multi-step task or screen automation", diameter=40,
                                  icon_size=16, accent=_ERR)
        self.btn_stop.clicked.connect(self.stop_current)
        self.btn_stop.hide()
        il.addWidget(self.btn_stop)
        self.btn_voice_chat = OrbButton("mic", "Voice chat — click to start/stop", diameter=40, icon_size=18,
                                        checkable=True, accent=_LISTEN)
        self.btn_voice_chat.clicked.connect(self.toggle_voice_chat)
        il.addWidget(self.btn_voice_chat)
        self.btn_send = OrbButton("send", "Send (Enter)", diameter=40, icon_size=18, primary=True)
        self.btn_send.clicked.connect(self.on_send)
        il.addWidget(self.btn_send)
        row.addWidget(self._input_glass, 100)
        row.addStretch(1)
        vl.addLayout(row)

        qc = QHBoxLayout()
        qc.setContentsMargins(22, 8, 22, 0)
        qc.setSpacing(6)
        qc.addStretch(1)
        self._chips = []
        for lbl, cmd in QUICK_CHIPS:
            b = QPushButton(lbl)
            b.setObjectName("chip")
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(26)
            b.setToolTip(cmd)
            b.clicked.connect(lambda _=False, c=cmd: self.quick_command(c))
            qc.addWidget(b)
            self._chips.append(b)
        qc.addStretch(1)
        vl.addLayout(qc)
        return page

    def eventFilter(self, obj, event):
        if obj is getattr(self, "model_combo", None) and event.type() == QEvent.Resize:
            self._combo_chevron.move(obj.width() - 20, (obj.height() - 10) // 2)
        if obj is getattr(self, "input", None) and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self._input_glass.set_focused(event.type() == QEvent.FocusIn)
        return super().eventFilter(obj, event)

    # page helpers
    @staticmethod
    def _page_header(title: str, subtitle: str = "", right=None) -> QWidget:
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 4)
        hl.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title.upper())
        t.setObjectName("pageTitle")
        col.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("pageSub")
            s.setWordWrap(True)
            col.addWidget(s)
        hl.addLayout(col, 1)
        for w in right or []:
            hl.addWidget(w, 0, Qt.AlignBottom)
        return head

    @staticmethod
    def _card(caption: str, hint: str = ""):
        card = HudPanel(caption)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 32, 16, 16)
        lay.setSpacing(10)
        if hint:
            h = QLabel(hint)
            h.setObjectName("cardHint")
            h.setWordWrap(True)
            lay.addWidget(h)
        return card, lay

    @staticmethod
    def _button(text, fn, icon_name=None, primary=False, danger=False):
        b = QPushButton(("  " + text) if icon_name else text)
        if primary:
            b.setObjectName("primary")
        elif danger:
            b.setObjectName("danger")
        if icon_name:
            color = "#00121A" if primary else _theme.TEXT_2
            b.setIcon(_theme.icon(icon_name, 16, color, active="#00121A" if primary else _CYAN))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False: fn())
        return b

    @staticmethod
    def _scroll_page(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_automate_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(26, 22, 26, 22)
        cl.setSpacing(16)
        cl.addWidget(self._page_header(
            "Automation", "Stop any automation with Ctrl+Alt+Esc or by moving the mouse into a screen corner."))

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(14)
        vis, vl2 = self._card("Screen vision", "Let JARVIS look at your screen, or click something by describing it.")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._button("Take screenshot", self.take_screenshot_only, "camera"))
        row.addWidget(self._button("Describe screen", self.analyze_current_screen, "eye"))
        row.addStretch()
        vl2.addLayout(row)
        vis_task_row = QHBoxLayout()
        vis_task_row.setSpacing(8)
        self.visual_task_input = QLineEdit()
        self.visual_task_input.setPlaceholderText("Click something on screen, e.g. 'the Save button'")
        self.visual_task_input.setFixedHeight(36)
        self.visual_task_input.returnPressed.connect(self.execute_visual_task)
        vis_task_row.addWidget(self.visual_task_input, 1)
        btn_exec_vis = self._button("Click it", self.execute_visual_task, "cursor", primary=True)
        btn_exec_vis.setFixedHeight(36)
        vis_task_row.addWidget(btn_exec_vis)
        vl2.addLayout(vis_task_row)
        ll.addWidget(vis)

        multi, ml = self._card("Multi-step task", "Describe the steps in plain words. Prefix with ‘automate’ to let "
                                                   "the vision model drive the mouse and keyboard.")
        self.complex_task_input = QTextEdit()
        self.complex_task_input.setObjectName("taskInput")
        self.complex_task_input.setAcceptRichText(False)
        self.complex_task_input.setPlaceholderText("e.g. open Notepad, type 'hello from JARVIS', then press ctrl+s")
        self.complex_task_input.setFixedHeight(84)
        ml.addWidget(self.complex_task_input)
        task_btns = QHBoxLayout()
        task_btns.setSpacing(8)
        task_btns.addWidget(self._button("Add to queue", self.execute_complex_task, "play", primary=True))
        task_btns.addWidget(self._button("Plan steps", self.plan_task_steps, "list"))
        task_btns.addStretch()
        ml.addLayout(task_btns)
        ll.addWidget(multi)

        apps, al = self._card("Applications", "Index installed programs or launch one by name.")
        app_btns = QHBoxLayout()
        app_btns.setSpacing(8)
        app_btns.addWidget(self._button("Discover apps", self.discover_applications, "search"))
        app_btns.addWidget(self._button("Launch app…", self.launch_application_dialog, "play"))
        app_btns.addStretch()
        al.addLayout(app_btns)
        ll.addWidget(apps)
        ll.addStretch(1)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(14)
        qcard = HudPanel("", brackets=True)
        ql = QVBoxLayout(qcard)
        ql.setContentsMargins(16, 12, 16, 16)
        ql.setSpacing(10)
        self._queue_label = QLabel("TASK QUEUE — 0 waiting")
        self._queue_label.setObjectName("cardTitle")
        ql.addWidget(self._queue_label)
        self.task_queue_list = QListWidget()
        self.task_queue_list.setMinimumHeight(96)
        self.task_queue_list.setMaximumHeight(150)
        ql.addWidget(self.task_queue_list)
        queue_btns = FlowLayout(spacing=6)
        for lbl, fn, icon_name in [("Pause", self.pause_task_queue, "pause"), ("Resume", self.resume_task_queue, "play"),
                                   ("Clear", self.clear_task_queue, "trash")]:
            queue_btns.addWidget(self._button(lbl, fn, icon_name))
        queue_btns.addWidget(self._button("Stop current", self.stop_current, "stop", danger=True))
        ql.addLayout(queue_btns)
        rl.addWidget(qcard)

        logc, lgl = self._card("Log")
        self.automation_log = QTextEdit()
        self.automation_log.setObjectName("log")
        self.automation_log.setReadOnly(True)
        self.automation_log.setPlaceholderText("Automation activity will appear here…")
        self.automation_log.setMinimumHeight(200)
        lgl.addWidget(self.automation_log, 1)
        rl.addWidget(logc, 1)
        # Backwards-compatible alias
        self.task_execution_log = self.automation_log

        grid = ReflowGrid([(820, 2), (0, 1)], spacing=16)
        grid.add(left)
        grid.add(right, stretch=1)
        cl.addWidget(grid, 1)
        vl.addWidget(self._scroll_page(content), 1)
        return page

    def _build_system_page(self) -> QWidget:
        page = _SystemPage(self)
        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(26, 22, 26, 22)
        cl.setSpacing(16)
        btn_refresh_sys = self._button("Refresh", self.refresh_system_info, "refresh")
        cl.addWidget(self._page_header("System", "Live readings refresh every two seconds while this page is open.",
                                       [btn_refresh_sys]))
        self.gauges = {}
        gauges = ReflowGrid([(760, 4), (0, 2)], spacing=14)
        for key, caption, icon_name in (("cpu", "CPU", "chip"), ("ram", "Memory", "sliders"),
                                        ("disk", "Disk", "folder"), ("battery", "Battery", "power")):
            tile = StatTile(caption, icon_name, invert=(key == "battery"))
            self.gauges[key] = tile
            gauges.add(tile)
        cl.addWidget(gauges)

        details, dl = self._card("Details")
        self.system_info = QTextEdit()
        self.system_info.setObjectName("sysinfo")
        self.system_info.setReadOnly(True)
        self.system_info.setMinimumHeight(180)
        dl.addWidget(self.system_info, 1)
        sys_btns = FlowLayout(spacing=6)
        for lbl, fn, icon_name in [
                ("Health check", lambda: self._run_task("System health check",
                                                        lambda: self.jarvis.system_monitor.check_system_health()), "shield"),
                ("Disk usage", lambda: self._run_task("Disk usage", lambda: self.jarvis.system_control.get_disk_usage()),
                 "folder"),
                ("Benchmark", lambda: self._run_task("Benchmark models", lambda: self.brain.benchmark_models()), "clock"),
                ("Test voice", self.test_voice, "speaker")]:
            sys_btns.addWidget(self._button(lbl, fn, icon_name))
        dl.addLayout(sys_btns)

        skills, sl = self._card("Skills")
        self.skills_tree = QTreeWidget()
        self.skills_tree.setHeaderLabels(["Skill", "Status", "Detail"])
        self.skills_tree.setColumnWidth(0, 150)
        self.skills_tree.setColumnWidth(1, 84)
        self.skills_tree.setRootIsDecorated(False)
        self.skills_tree.setMinimumHeight(180)
        sl.addWidget(self.skills_tree, 1)
        skill_btns = FlowLayout(spacing=6)
        for lbl, fn, icon_name in (("Refresh", self.update_skills_tree, "refresh"),
                                   ("Test selected", self.test_selected_skill, "play"),
                                   ("Test all", self.test_all_skills, "check")):
            skill_btns.addWidget(self._button(lbl, fn, icon_name))
        sl.addLayout(skill_btns)

        lower = ReflowGrid([(980, 2), (0, 1)], spacing=16)
        lower.add(details, stretch=1)
        lower.add(skills, stretch=1)
        cl.addWidget(lower, 1)
        vl.addWidget(self._scroll_page(content), 1)
        return page

    # ── Activity panel ───────────────────────────────────────────────────────

    def set_activity_visible(self, on: bool, user: bool = False):
        if user:
            self._activity_user_choice = bool(on)
        self.activity.setVisible(bool(on))
        self.btn_activity.setChecked(bool(on))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_wordsub"):
            self._wordsub.setVisible(self.width() >= 1100)
        if hasattr(self, "activity"):
            self.activity.setFixedWidth(304 if self.width() >= 1100 else 264)
            self._apply_state(self._jarvis_state, self._state_detail)
        if self._activity_user_choice is None and hasattr(self, "activity"):
            self.set_activity_visible(self.width() >= self.ACTIVITY_AUTO_WIDTH)

    # ── Browser window ────────────────────────────────────────────────────────

    def _on_browser_open(self, url: str, then_js: str = None):
        """Called from worker threads — routed through thread-safe signals."""
        if then_js:
            self._browser_open_js.emit(url, then_js)
        else:
            self._browser_open.emit(url)

    def _ensure_browser(self):
        if not WEBENGINE_AVAILABLE:
            return None
        if self._browser_win is None:
            try:
                self._browser_win = BrowserWindow()
            except Exception:
                # QtWebEngine present but unusable (no GPU/sandbox/resources): use the system browser.
                log.exception("Embedded browser unavailable")
                return None
        return self._browser_win

    def navigate_browser(self, url: str):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        win = self._ensure_browser()
        if win is None:
            import webbrowser
            webbrowser.open(url)
            return
        win.navigate(url)
        win.show()
        win.raise_()
        win.activateWindow()

    def navigate_browser_with_js(self, url: str, js_code: str):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        win = self._ensure_browser()
        if win is None:
            import webbrowser
            webbrowser.open(url)
            return
        win.navigate_then_js(url, js_code)
        win.show()
        win.raise_()
        win.activateWindow()

    def run_js(self, code: str, callback=None):
        win = self._ensure_browser()
        if win is not None:
            win.show()
            win.run_js(code, callback)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("cardTitle")
        return lbl

    def _switch_page(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)

    def setup_menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("File")
        a = QAction("Export Chat…", self)
        a.triggered.connect(self.export_chat)
        fm.addAction(a)
        a = QAction("Open Data Folder", self)
        a.triggered.connect(lambda: os.startfile(str(Config.USER_DIR)) if os.name == "nt" else None)
        fm.addAction(a)
        fm.addSeparator()
        a = QAction("Exit", self)
        a.triggered.connect(self.close)
        fm.addAction(a)
        vm = mb.addMenu("View")
        for label, idx in (("Chat", 0), ("Automation", 1), ("System", 2)):
            a = QAction(label, self)
            a.triggered.connect(lambda _=False, i=idx: self._switch_page(i))
            vm.addAction(a)
        vm.addSeparator()
        a = QAction("Activity Panel", self)
        a.triggered.connect(lambda: self.set_activity_visible(not self.activity.isVisible(), user=True))
        vm.addAction(a)
        tm = mb.addMenu("Tools")
        for label, fn in [("Settings…", self.open_settings), ("Memory…", self.open_memory),
                          ("Test Voice", self.test_voice), ("Test All Skills", self.test_all_skills),
                          ("Benchmark Models", lambda: self._run_task("Benchmark models",
                                                                      lambda: self.brain.benchmark_models()))]:
            a = QAction(label, self)
            a.triggered.connect(fn)
            tm.addAction(a)
        hm = mb.addMenu("Help")
        a = QAction("What can JARVIS do?", self)
        a.triggered.connect(lambda: self.quick_command("help"))
        hm.addAction(a)
        a = QAction("About", self)
        a.triggered.connect(self.show_about)
        hm.addAction(a)

    # ── Ollama ────────────────────────────────────────────────────────────────

    def _start_ollama(self):
        try:
            from core.ollama_manager import OllamaManager

            def on_status(msg: str):
                self._bridge.notify_requested.emit(f"Local AI: {msg}")
                if "ready" in msg.lower():
                    self._bridge.ollama_ready.emit()   # called on Ollama's thread: no QTimer/widgets here

            OllamaManager.get().start(on_status=on_status)
        except Exception as e:
            log.warning("OllamaManager failed: %s", e)
        QTimer.singleShot(2500, self._on_ollama_ready)

    def _on_ollama_ready(self):
        if not self.brain:
            return
        try:
            found = self.brain._check_local_models()
            if not self.brain.current_model:
                self.brain._set_default_model()
            if self.brain.prefer_default_model():
                self.append_text("System", f"Using your local model: {self.brain.current_model}.")
            self.refresh_models()
            if found:
                self._local_ai_dot.setStyleSheet(f"color: {_SUCCESS};")
                self._local_ai_dot.setToolTip("Local models: " + ", ".join(found))
        except Exception:
            log.exception("Ollama scan failed")

    def _refresh_all_models(self):
        self._on_ollama_ready()
        if self.brain:
            self.brain.refresh_catalog_async(on_done=self._bridge.catalog_ready.emit)
            self.append_text("System", "Refreshing model lists…")

    # ── Model control ─────────────────────────────────────────────────────────

    def refresh_models(self):
        if not self.brain:
            return
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for name in self.brain.available_models:
            self.model_combo.addItem(name)
        if self.brain.current_model:
            idx = self.model_combo.findText(self.brain.current_model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
        empty = self.model_combo.count() == 0
        self.model_combo.setPlaceholderText("No model")
        self.model_combo.setEnabled(not empty)
        self.model_combo.setToolTip("Add a Gemini or OpenRouter key in Settings, or install Ollama"
                                    if empty else "The AI model JARVIS uses for conversation")
        self.model_combo.blockSignals(False)
        self._update_model_status()

    def _update_model_status(self):
        if self.brain and self.brain.current_model:
            cfg = self.brain.available_models.get(self.brain.current_model, {})
            tags = [cfg.get("provider", "")] + [t for t, on in (("tools", cfg.get("supports_tools")),
                                                                 ("vision", cfg.get("supports_vision"))) if on]
            self._model_status.setText(" · ".join(t for t in tags if t))
        else:
            self._model_status.setText("No model")

    def on_model_change(self, name: str):
        if not name or not self.brain:
            return
        self.append_text("System", self.brain.switch_model(name))
        self._update_model_status()

    # ── Chat ─────────────────────────────────────────────────────────────────

    def _stop_now_if_asked(self, text: str):
        """A typed "stop" must not wait in the worker's queue behind the very task it should stop:
        while something is running it is handled here, on the GUI thread, straight away."""
        j = self.jarvis
        if j is None or not hasattr(j, "stop_everything") or not j.is_stop_request(text) or not j.is_busy():
            return None
        summary = j.stop_everything()
        self.append_text("JARVIS", summary)
        return summary

    def on_send(self):
        text = self.input.text().strip()
        if not text or self.worker is None:
            return
        self.append_text("You", text)
        self.input.clear()
        if self._stop_now_if_asked(text) is not None:
            return
        self._reply_sources.append("window")
        self.worker.submit_chat(text, voice=self.btn_voice.isChecked())

    def submit_from_bar(self, text: str) -> bool:
        """The command bar's Enter: same worker, history and confirmations as the chat box."""
        if not text or self.worker is None:
            return False
        self.append_text("You", text)
        summary = self._stop_now_if_asked(text)
        if summary is not None:
            self.bar_reply.emit(summary)
            return True
        self._reply_sources.append("bar")
        self.worker.submit_chat(text, voice=self.btn_voice.isChecked())
        return True

    def quick_command(self, command: str):
        self.input.setText(command)
        self.on_send()

    def _on_worker_response(self, kind: str, text: str):
        self._last_reply_failed = str(text).startswith("Error:")
        if kind == "chat":
            self.append_text("JARVIS", text)
            source = self._reply_sources.pop(0) if self._reply_sources else "window"
            if source == "bar":
                self.bar_reply.emit(text)
        else:
            self._auto_log(text)
            if kind == "task":
                self.append_text("JARVIS", text)

    def on_error(self, error: str):
        self.append_text("Error", error)

    def on_status_update(self, status: str):
        self.status_label.setText(status)
        low = status.lower()
        if status.startswith("Working: "):
            self._busy_label = status[len("Working: "):]
            self.activity.task_started(self._busy_label)
            if self._busy:
                self.set_jarvis_state("thinking", self._busy_label)
        elif self.voice_chat_worker is not None and self.voice_chat_active:
            if low.startswith("listening"):
                self._transient_state("listening", "Voice chat")
            elif low.startswith("thinking"):
                self._transient_state("thinking", "Voice chat")
            elif low.startswith("speaking"):
                self._transient_state("speaking", "Voice chat")

    def _set_thinking(self, active: bool):
        self._busy = bool(active)
        self.btn_stop.setVisible(active)
        if active:
            self.set_jarvis_state("thinking", self._busy_label)
        else:
            self.activity.task_finished(not self._last_reply_failed)
            self._busy_label = ""
            self._settle_state()
            self.chat.set_typing(False)

    def stop_current(self):
        """The Stop button, the tray's "Stop everything" and the queue's "Stop current"."""
        if self.jarvis:
            stop = getattr(self.jarvis, "stop_everything", None) or self.jarvis.stop_current_task
            summary = str(stop() or "Stop requested.")
            self.append_text("System", summary)
            return summary
        return None

    def _cancel_open_confirms(self) -> int:
        """Global-stop hook (any thread): every yes/no dialog still waiting is answered "no"."""
        cancelled = 0
        for holder in list(self._pending_confirms):
            if holder["event"].is_set():
                continue
            holder["answer"] = False
            holder["event"].set()               # the waiting worker thread resumes with "no" now
            cancelled += 1
            box = holder.get("box")
            if box is not None:
                try:
                    QMetaObject.invokeMethod(box, "reject", Qt.QueuedConnection)
                except RuntimeError:
                    pass                        # already answered and deleted
        return cancelled

    def _install_stop_hotkey(self):
        install = getattr(self.jarvis, "install_stop_hotkey", None)
        if install is None:
            return
        if not install():
            log.warning("global stop hotkey unavailable; use the Stop button or the tray menu")

    def _run_task(self, label, fn, kind="auto"):
        if self.worker is None:
            return
        self._auto_log(f"Queued: {label}")
        self.worker.submit_task(label, fn, kind)

    # ── Voice ─────────────────────────────────────────────────────────────────

    def toggle_voice(self):
        on = self.btn_voice.isChecked()
        self.btn_voice.set_icon("speaker" if on else "speaker_off")
        self.btn_voice.setToolTip("Voice replies are on — click to mute" if on else
                                  "Voice replies are off — click to speak replies aloud")
        if self.jarvis:
            self.jarvis.voice_output_enabled = on
        self.append_text("System", "Replies will be spoken." if on else "Voice output off.")

    def toggle_voice_chat(self):
        if not self.jarvis:
            return
        if self.btn_voice_chat.isChecked():
            if not self.voice_engine.sr_available:
                self.btn_voice_chat.setChecked(False)
                self.append_text("Error", "Speech recognition isn't installed (pip install SpeechRecognition pyaudio).")
                return
            if self._conversation is not None:
                self.stop_conversation()               # one owner of the microphone at a time
            self.voice_chat_active = True
            self._voice_session += 1
            try:
                from core import streaming
                live = Config.LIVE_VOICE and streaming.vosk_available()
            except Exception:
                log.exception("live voice check failed")
                live = False
            if live:
                self.append_text("System", "Live voice starting — JARVIS acts while you speak. "
                                           "Click the mic again to stop.")
                session = self._voice_session
                threading.Thread(target=self._start_live_voice, args=(session,), daemon=True).start()
            else:
                self._start_classic_voice_chat()
            self._transient_state("listening", "Mic is live", settle_ms=2500)
        else:
            self.voice_chat_active = False
            self._voice_session += 1
            if self._live_listener:
                self._live_listener.stop()
                self._live_listener = None
            if self.voice_chat_worker:
                self._retire_thread(self.voice_chat_worker, 3000)
                self.voice_chat_worker = None
            self._thinking_lbl.setText("")
            self.append_text("System", "Voice chat stopped.")
            self._settle_state()

    def _retire_thread(self, thread, timeout_ms):
        """Stop a QThread without ever dropping the last reference to a running one
        (that aborts the process with 'QThread: Destroyed while thread is still running')."""
        thread.stop()
        if not thread.wait(timeout_ms):
            self._retired_threads.append(thread)
            # finished is emitted on the dying thread: queue the cleanup to the GUI thread.
            thread.finished.connect(self._reap_threads, Qt.QueuedConnection)

    def _reap_threads(self):
        self._retired_threads = [t for t in self._retired_threads if not t.wait(100)]

    def _start_live_voice(self, session=None):
        """Worker thread: may download the speech model first. Only emits signals — no widgets here."""
        if session is None:
            session = self._voice_session
        try:
            listener = self.jarvis.start_live_voice(
                on_event=lambda kind, info: self._bridge.live_event.emit(kind, info),
                on_status=self._bridge.notify_requested.emit)
        except Exception as exc:
            log.exception("live voice failed to start")
            self._bridge.notify_requested.emit(f"Live voice failed ({exc}).")
            listener = None
        if listener is None:
            if session == self._voice_session and self.voice_chat_active:
                self._bridge.notify_requested.emit("Live voice unavailable — using normal voice chat.")
                self._bridge.live_failed.emit()
            return
        if session != self._voice_session or not self.voice_chat_active:
            listener.stop()                 # user switched off (or toggled again) while the model loaded
            return
        self._live_listener = listener

    def _on_live_failed(self):
        self._start_classic_voice_chat()

    def _start_classic_voice_chat(self):
        if not self.voice_chat_active or self.jarvis is None or self.voice_chat_worker is not None:
            return
        self.voice_chat_worker = VoiceChatWorker(self.jarvis)
        self.voice_chat_worker.message_received.connect(lambda msg: self.append_text("You", msg))
        self.voice_chat_worker.response_ready.connect(lambda msg: self.append_text("JARVIS", msg))
        self.voice_chat_worker.status_update.connect(self.on_status_update)
        self.voice_chat_worker.error_occurred.connect(self.on_error)
        self.append_text("System", "Voice chat on — speak, then pause. Click the mic again to stop.")
        self.voice_chat_worker.start()

    def _on_live_event(self, kind, info):
        info = info if isinstance(info, dict) else {}
        if kind == "partial":
            text = str(info.get("text", ""))
            self._thinking_lbl.setText(text[-110:])
            grew = max(0, len(text) - self._partial_len)
            self._partial_len = len(text)
            self._set_level(min(1.0, 0.3 + grew / 12.0))
            self._level_timer.start(450)
            self._transient_state("listening", "Hearing you", settle_ms=2000)
        elif kind == "heard":
            self._partial_len = 0
            self.append_text("You", info.get("text", ""))
            self._transient_state("listening", "Got it", settle_ms=1500)
        elif kind == "dispatched":
            lane = f" · lane {info['lane'] + 1}" if info.get("lane") else ""
            row = self.append_text("Action", f"▶ {info.get('text', '')}{lane}")
            if info.get("index") is not None and row is not None:
                self._live_rows[info["index"]] = row
            self._transient_state("acting", str(info.get("text", "")))
        elif kind == "step_started":
            row = self._live_rows.get(info.get("index"))
            if row is not None:
                row.set_status("running")
            self._transient_state("acting", str(info.get("text", "")))
        elif kind == "step_done":
            self._auto_log(f"[lane {(info.get('lane') or 0) + 1}] {info.get('text', '')} → {info.get('reply', '')}")
            row = self._live_rows.get(info.get("index"))
            if row is not None:
                row.set_status(info.get("status") or "done")
        elif kind == "ask":
            self.append_text("JARVIS", str(info.get("question", "")) + " (say yes or no)")
            self._transient_state("listening", "Waiting for yes or no")
        elif kind == "utterance_done":
            self._thinking_lbl.setText("")
            self._partial_len = 0
            self._live_rows = {}
            self.append_text("JARVIS", info.get("details") or info.get("summary", ""))
            summary = info.get("summary")
            if summary and self.voice_engine is not None:
                threading.Thread(target=lambda: self.voice_engine.speak(summary, summarize=True), daemon=True).start()
            self._settle_state()
        self.activity.on_live_event(kind, info)

    def open_mic_settings(self):
        if self.voice_engine:
            MicrophoneSettingsDialog(self.voice_engine, self).exec()

    # ── Helpers / dialogs ────────────────────────────────────────────────────

    def on_clear(self):
        if self.brain:
            self.brain.clear_history()
        self.transcript.clear()
        self._live_rows = {}
        self._update_greeting()
        self.append_text("System", "Conversation cleared.")

    def open_settings(self):
        dlg = SettingsDialog(self, decision=getattr(self.jarvis, "decision", None))
        if not dlg.exec():
            return
        from core.config import load_env
        load_env()
        Config.reload()
        try:
            if self.jarvis:
                d = self.jarvis.decision
                changed = (d.engine, d.model) != (Config.DECISION_ENGINE, Config.LAYA_MODEL)
                d.engine, d.model, d.threshold = Config.DECISION_ENGINE, Config.LAYA_MODEL, Config.DECISION_THRESHOLD
                if changed:
                    d.unload()
                    d.warm_up_async()
                self._on_decision_status(d.status)
                self.jarvis.voice_engine.setup_tts()
                if self._buddy is not None and (not Config.BUDDY_ENABLED
                                                or self._buddy.hotkey.combo != Config.BUDDY_HOTKEY):
                    self.stop_buddy()               # restarted below with the new hotkey
                if Config.BUDDY_ENABLED and self._buddy is None:
                    self.start_buddy()
            if self.brain:
                self.brain._initialize_providers()
                self.brain._set_default_model()
                self.refresh_models()
                self.brain.refresh_catalog_async(on_done=self._bridge.catalog_ready.emit)
        except Exception as exc:
            log.exception("applying settings failed")
            self.append_text("Error", f"Settings were saved but could not all be applied now: {exc}. "
                                      "Restart JARVIS to apply them.")
            return
        self.append_text("System", "Settings saved.")
        self._update_greeting()
        self._install_stop_hotkey()                       # picks up a changed stop hotkey
        self.settings_changed.emit()

    def open_memory(self):
        if self.brain:
            MemoryDialog(self.brain.memory, self).exec()
            self._update_greeting()

    def export_chat(self):
        fname, _ = QFileDialog.getSaveFileName(self, "Export Chat", "jarvis_chat.txt", "Text Files (*.txt)")
        if fname:
            try:
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(self.transcript.toPlainText())
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Export failed: {e}")

    # ── Skills tab ────────────────────────────────────────────────────────────

    _SKILL_PROBES = {
        "weather": lambda s: s.get_weather(""),
        "web_search": lambda s: s.search_web("current UTC time", llm_brain=None)[:300],
        "utility": lambda s: s.calculate("2+2"),
        "file_manager": lambda s: s.get_current_directory(),
        "system_monitor": lambda s: s.get_system_info()[:300],
        "automation": lambda s: str(s.get_screen_size()),
        "app_control": lambda s: f"{len(s.installed_apps)} installed programs indexed",
        "windows": lambda s: s.get_volume(),
        "command_processor": lambda s: " | ".join(s.split_steps("open notepad and type hi then press enter")),
        "task_scheduler": lambda s: f"{sum(1 for t in s.active_tasks.values() if t.get('status') == 'scheduled')} pending task(s); running={s.is_running}",
        "screen_automation": lambda s: "vision models: " + (", ".join(s.brain.vision_models()[:3]) if s.brain and s.brain.vision_models() else "none configured"),
    }

    def update_skills_tree(self):
        self.skills_tree.clear()
        for name, obj in self.skills.items():
            self.skills_tree.addTopLevelItem(self._skill_item(name, "Loaded", obj.__class__.__name__))
        if self.jarvis:
            self.skills_tree.addTopLevelItem(self._skill_item("decision", "Loaded", self.jarvis.decision.status))
            self.skills_tree.addTopLevelItem(self._skill_item("tools", "Loaded", f"{len(self.jarvis.tools)} tools for the AI"))

    @staticmethod
    def _skill_item(name, status, detail):
        item = QTreeWidgetItem([name, status, detail])
        item.setForeground(1, QColor(_SUCCESS if status == "Loaded" else _WARN))
        item.setToolTip(2, str(detail))
        return item

    def test_selected_skill(self):
        cur = self.skills_tree.currentItem()
        if cur:
            self._test_skill(cur)

    def _test_skill(self, item):
        name = item.text(0)
        obj = self.skills.get(name)
        probe = self._SKILL_PROBES.get(name)
        if obj is None or probe is None:
            return
        item.setText(1, "Testing…")

        def run():
            try:
                result = probe(obj)
                low = str(result).lower()
                ok = not any(w in low for w in ("error", "could not", "couldn't", "unable", "unavailable",
                                                "not available", "none configured", "failed"))
                return f"{'✅' if ok else '⚠️'} {name}: {result}"
            except Exception as e:
                return f"❌ {name}: {e}"
        self._run_task(f"Test {name}", run, kind="task")
        item.setText(1, "Queued")
        item.setForeground(1, QColor(_WARN))

    def test_all_skills(self):
        for i in range(self.skills_tree.topLevelItemCount()):
            self._test_skill(self.skills_tree.topLevelItem(i))

    # ── System tab ────────────────────────────────────────────────────────────

    def refresh_system_info(self):
        self.refresh_gauges()
        if not self.jarvis:
            return
        monitor = self.jarvis.system_monitor

        def run():
            return monitor.get_system_info() if monitor else self.jarvis.system_control.get_system_status()

        # Short and read-only: run on a plain thread so it never waits behind the queue.
        # The result goes back through a signal (QTimer/widgets must not be used from this thread).
        def worker():
            try:
                text = run()
            except Exception as e:
                text = f"Error: {e}"
            self._bridge.system_info_ready.emit(str(text))
        threading.Thread(target=worker, daemon=True).start()

    def refresh_gauges(self, stats=None):
        """Update the CPU / RAM / disk / battery tiles; a failing sensor shows '—'."""
        if not hasattr(self, "gauges"):
            return
        try:
            stats = stats if stats is not None else read_system_stats()
        except Exception:
            log.exception("system stats failed")
            stats = {}
        for key, tile in self.gauges.items():
            value, detail = stats.get(key, (None, "Unavailable"))
            tile.set_stat(value, detail)

    def test_voice(self):
        if self.voice_engine:
            threading.Thread(target=lambda: self.voice_engine.speak("Voice test successful. JARVIS is ready."),
                             daemon=True).start()

    def show_about(self):
        QMessageBox.about(self, "About JARVIS",
                          "JARVIS AI Assistant 3.0\n\n"
                          "Local decision model (Laya) · Gemini / OpenRouter / Ollama\n"
                          "Voice · Screen vision · Windows control\n\n"
                          f"Settings and data: {Config.USER_DIR}")

    # ── Conversation ─────────────────────────────────────────────────────────

    def append_text(self, speaker: str, text: str, ambient: bool = False):
        """Add a message to the conversation; returns its row widget (None for ambient ones)."""
        text = "" if text is None else str(text)
        spk = str(speaker).upper()
        kind = None
        if spk == "JARVIS" and text.startswith("Error:"):
            kind = "error"
        row = self.chat.add_message(speaker, text, ambient=ambient, kind=kind)
        if not ambient and (spk == "ERROR" or kind == "error"):
            self.set_jarvis_state("error", text)
            self.activity.add_recent(text, "error")
        return row

    # ── Automation tab ────────────────────────────────────────────────────────

    def _auto_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.automation_log.append(f"[{ts}] {msg}")

    def _on_queue_changed(self, labels):
        self.task_queue_list.clear()
        for label in labels:
            self.task_queue_list.addItem(label[:80])
        paused = " (PAUSED)" if self.worker and self.worker.paused else ""
        self._queue_label.setText(f"TASK QUEUE — {len(labels)} waiting{paused}")

    def take_screenshot_and_analyze(self):
        if self.jarvis and self.jarvis.screen_automation:
            self.append_text("You", "What's on my screen?")
            self._run_task("Describe screen", lambda: self.jarvis.screen_automation.describe_screen(), kind="task")

    def take_screenshot_only(self):
        if self.jarvis and self.jarvis.screen_automation:
            self._run_task("Screenshot", lambda: f"Screenshot saved to {self.jarvis.screen_automation.take_screenshot()}")

    def analyze_current_screen(self):
        if self.jarvis and self.jarvis.screen_automation:
            self._run_task("Describe screen", lambda: self.jarvis.screen_automation.describe_screen())

    def execute_visual_task(self):
        task = self.visual_task_input.text().strip()
        if not task or not (self.jarvis and self.jarvis.screen_automation):
            return
        self.visual_task_input.clear()
        self._run_task(f"Click: {task}", lambda: self.jarvis.screen_automation.find_and_click_element(task)["message"])

    def discover_applications(self):
        if self.jarvis and self.jarvis.app_control:
            self._run_task("Discover apps", self.jarvis.app_control.discover_applications)

    def launch_application_dialog(self):
        app_name, ok = QInputDialog.getText(self, "Launch Application", "Application name:")
        if ok and app_name.strip() and self.jarvis and self.jarvis.app_control:
            name = app_name.strip()
            self._run_task(f"Launch {name}", lambda: self.jarvis.app_control.launch_app_by_name(name))

    def execute_complex_task(self):
        task = self.complex_task_input.toPlainText().strip()
        if not task or not self.jarvis:
            return
        self.complex_task_input.clear()
        self._run_task(task, lambda: self.jarvis.process_command(task, use_voice=False), kind="task")

    def plan_task_steps(self):
        task = self.complex_task_input.toPlainText().strip()
        if not task or not self.jarvis:
            return
        plan = self.jarvis.command_processor.plan(task, classify=self.jarvis._classify_command_intent)
        self._auto_log(plan.describe() + "\n(Plan only — nothing was executed. Use 'Add to Queue' to run it.)")

    def pause_task_queue(self):
        if self.worker:
            self.worker.pause()
            self._auto_log("Queue paused — the current task finishes, nothing new starts.")

    def resume_task_queue(self):
        if self.worker:
            self.worker.resume()
            self._auto_log("Queue resumed.")

    def clear_task_queue(self):
        if self.worker:
            self.worker.clear_tasks()
            self._auto_log("Queue cleared.")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def quit_app(self):
        """Really close (the tray's Quit), even when closing normally only hides the window."""
        self._quitting = True
        self.close()

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        if self.hide_on_close and not self._quitting:
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
            return
        self._closing = True
        self._speak_poll.stop()
        self._settle_timer.stop()
        self.voice_chat_active = False
        self._voice_session += 1
        for holder in list(self._pending_confirms):   # a worker waiting for an answer gets "No" now
            holder["answer"] = False
            holder["event"].set()
        if self.voice_chat_worker:
            self._retire_thread(self.voice_chat_worker, 2000)
            self.voice_chat_worker = None
        if self._live_listener:
            try:
                self._live_listener.stop()
            except Exception:
                log.exception("live voice stop failed")
            self._live_listener = None
        try:
            self.stop_conversation()
        except Exception:
            log.exception("conversation shutdown failed")
        try:
            self.stop_buddy()
            if self._buddy_overlay is not None:
                self._buddy_overlay.close()
        except Exception:
            log.exception("buddy shutdown failed")
        if self.jarvis:
            self.jarvis.exit_callback = None
            self.jarvis.stop_current_task()
        if self.worker:
            self.worker.stop()
            if not self.worker.wait(4000):
                log.warning("Worker still busy at exit; leaving it to finish in the background.")
        if self.jarvis:
            try:
                self.jarvis.shutdown()
            except Exception:
                log.exception("shutdown failed")
        try:
            from core.ollama_manager import OllamaManager
            OllamaManager.get().stop()
        except Exception:
            log.exception("Ollama stop failed")
        if self._browser_win is not None:
            self._browser_win.close()
        self._closed = True
        event.accept()

    def threads_still_running(self) -> bool:
        """True if a QThread is still busy after close (it would abort the process when destroyed)."""
        threads = [self.worker, self.voice_chat_worker] + list(self._retired_threads)
        return any(t is not None and t.isRunning() for t in threads)


def main():
    setup_logging()
    if WEBENGINE_AVAILABLE:
        # QtWebEngine needs this before the QApplication exists.
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS AI Assistant")
    app.setApplicationVersion("3.0")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    code = app.exec()
    if win.threads_still_running():
        # A command is still blocked (e.g. a long network call). Destroying its QThread would
        # abort the process, and waiting could hang: flush logs and leave immediately.
        import logging
        logging.shutdown()
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        os._exit(code)
    sys.exit(code)


if __name__ == "__main__":
    main()
