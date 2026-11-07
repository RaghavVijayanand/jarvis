"""Settings dialog — every user setting in one place (audit UC 5.5).

A two-pane HUD dialog: a nav rail with a search box on the left, one page per
topic on the right (each a stack of HudPanel cards made of SettingRows), and a
footer with Cancel / Save changes. Save is enabled only when something changed.

Values are written to the per-user .env (see core/config.py) and take effect
after ``Config.reload()``, which the main window calls when the dialog closes.
Only keys whose value changed since the dialog opened are written.
"""
import os
import re
import threading
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QFontMetrics, QKeySequence, QPainter, QPen,
                           QShortcut)
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDoubleSpinBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from core.config import Config, get_location_preference, save_location_preference, save_setting
from ui import theme
from ui.settings_widgets import (Chip, HudCombo, KeyCaps, NavButton, PageHeader, SecretEdit, SettingCard,
                                 SettingRow, SliderSpin, hbox, sized)
from ui.widgets import ArcOrb, ToggleSwitch, paint_grid

# (page title, nav icon, subtitle)
PAGES = (
    ("AI Models", "sparkle", "The language models JARVIS talks and sees with. One free key is enough."),
    ("Decisions", "brain", "How JARVIS decides which skill handles a request — locally, in milliseconds."),
    ("Voice", "mic", "How JARVIS speaks, listens and wakes up."),
    ("Buddy & Hotkeys", "keyboard", "The cursor helper, global shortcuts and starting with Windows."),
    ("Safety", "shield", "What JARVIS may do on its own, and how it sees your screen."),
    ("Location", "globe", "Where you are, for weather and local answers."),
    ("About", "chip", "Version, where your data lives, and help."),
)

KEY_LINKS = {"gemini": "https://aistudio.google.com/apikey", "openrouter": "https://openrouter.ai/keys"}
NAV_WIDTH = 224

# row title → the .env keys it edits ("startup" is the registry autostart entry)
ROW_KEYS = {
    "Google Gemini": ("GEMINI_API_KEY",), "OpenRouter": ("OPENROUTER_API_KEY",),
    "Default model": ("JARVIS_DEFAULT_MODEL",), "Request timeout": ("JARVIS_REQUEST_TIMEOUT",),
    "Engine": ("JARVIS_DECISION_ENGINE",), "Laya checkpoint": ("JARVIS_LAYA_MODEL",),
    "Confidence threshold": ("JARVIS_DECISION_THRESHOLD",), "Speech engine": ("JARVIS_TTS_ENGINE",),
    "Neural voice": ("JARVIS_VOICE",), "Offline voice rate": ("JARVIS_VOICE_RATE",),
    "Offline voice volume": ("JARVIS_VOICE_VOLUME",), "Wake word": ("JARVIS_WAKE_WORD",),
    "Live voice": ("JARVIS_LIVE_VOICE",), "Act on commands": ("JARVIS_ACT_MODE",),
    "Live speech model": ("JARVIS_VOSK_MODEL_NAME",), "Vosk model folder": ("JARVIS_VOSK_MODEL",),
    "Buddy mode": ("JARVIS_BUDDY",), "Buddy hotkey": ("JARVIS_BUDDY_HOTKEY",),
    "Command bar hotkey": ("JARVIS_COMMAND_BAR_HOTKEY",), "Start with Windows": ("startup",),
    "Ask before taking control": ("JARVIS_CONFIRM_ACTIONS",), "Safe mode": ("JARVIS_SAFE_MODE",),
    "Vision provider": ("JARVIS_VISION_PROVIDER",), "Vision model": ("JARVIS_VISION_MODEL",),
    "Start Ollama with JARVIS": ("JARVIS_OLLAMA_AUTOSTART",), "Ollama vision model": ("OLLAMA_VISION_MODEL",),
    "City": ("JARVIS_LOCATION",),
}

STYLE = f"""
QDialog#settings {{ background: {theme.BG}; }}
QLineEdit#navSearch {{ background: {theme.INPUT}; border: 1px solid {theme.BORDER_SOFT}; border-radius: 9px;
    padding: 7px 8px; font-size: 12.5px; }}
QLineEdit#navSearch:focus {{ border-color: {theme.ACCENT_DIM}; }}
QComboBox {{ padding: 6px 30px 6px 10px; min-height: 20px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: none; border: none; width: 0; height: 0; margin: 0; }}
QComboBox QAbstractItemView {{ min-width: 240px; }}
QLineEdit, QSpinBox, QDoubleSpinBox {{ min-height: 20px; padding: 6px 10px; }}
QPushButton#link {{ background: transparent; border: none; color: {theme.ACCENT}; padding: 4px 2px; font-size: 12px; }}
QPushButton#link:hover {{ color: #7CF4FF; text-decoration: underline; background: transparent; }}
QPushButton#small {{ padding: 5px 12px; font-size: 12px; }}
QPushButton#primary {{ padding: 8px 20px; }}
QPushButton#primary:disabled {{ background: {theme.CARD}; color: {theme.FAINT}; border: 1px solid {theme.BORDER_SOFT}; }}
QPushButton#ghost {{ padding: 8px 16px; }}
QLabel#footerPath {{ color: {theme.FAINT}; font-size: 11.5px; }}
QLabel#dirty {{ color: {theme.WARN}; font-size: 11.5px; }}
QLabel#emptySearch {{ color: {theme.MUTED}; font-size: 13px; }}
"""


def _secret(value: str) -> QLineEdit:
    return SecretEdit(value)


def _combo(options, current):
    box = HudCombo()
    for value, label in options:
        box.addItem(label, value)
    idx = box.findData(current)
    if idx < 0 and current:
        # A value set by hand in .env that isn't in the list: show it and keep it,
        # instead of silently replacing it with the first option on OK.
        box.addItem(str(current), current)
        idx = box.count() - 1
    box.setCurrentIndex(max(0, idx))
    return box


def app_version() -> str:
    """The version app.py sets with ``setApplicationVersion("…")``."""
    try:
        text = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
        m = re.search(r"setApplicationVersion\(\s*['\"]([^'\"]+)['\"]", text)
        if m:
            return m.group(1)
    except OSError:
        pass
    from PySide6.QtWidgets import QApplication
    return (QApplication.instance() and QApplication.instance().applicationVersion()) or "dev"


def decision_color(status: str) -> str:
    s = (status or "").lower()
    if "ready" in s:
        return theme.SUCCESS
    if "fail" in s or "error" in s:
        return theme.ERROR
    if "loading" in s:
        return theme.STATE_COLORS["thinking"]
    if "rules" in s:
        return theme.ACCENT
    return theme.MUTED


def _check_key(provider: str, key: str) -> tuple:
    """(ok, message). Runs in a worker thread — never on the UI thread."""
    import requests
    try:
        if provider == "gemini":
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                             params={"key": key, "pageSize": 1}, timeout=8)
        else:
            r = requests.get("https://openrouter.ai/api/v1/auth/key",
                             headers={"Authorization": f"Bearer {key}"}, timeout=8)
    except Exception as exc:                        # noqa: BLE001 - network errors are reported, not raised
        return False, f"No connection ({type(exc).__name__})"
    if r.status_code == 200:
        return True, "Key works"
    if r.status_code in (400, 401, 403):
        return False, "Key rejected"
    return False, f"HTTP {r.status_code}"


class _KeyTester(QObject):
    done = Signal(str, bool, str)             # provider, ok, message

    def start(self, provider: str, key: str):
        threading.Thread(target=self._run, args=(provider, key), daemon=True, name=f"key-test-{provider}").start()

    def _run(self, provider: str, key: str):
        ok, message = _check_key(provider, key)
        try:
            self.done.emit(provider, ok, message)      # queued to the UI thread
        except RuntimeError:                            # the dialog closed meanwhile
            pass


class _Rail(QFrame):
    """The left column: a slightly deeper glass strip with a hairline on its right edge."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.qcolor(theme.BG_2, 0.94))
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.end()
        super().paintEvent(e)


class _Content(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        paint_grid(p, self.rect(), spacing=32)
        p.end()


class _Pipeline(QWidget):
    """Laya → rules → AI model, drawn as three HUD nodes joined by arrows."""
    STEPS = (("brain", "Laya", "local · milliseconds"), ("list", "Rules", "known phrasings"),
             ("sparkle", "AI model", "everything else"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(92)

    def paintEvent(self, _e):
        from PySide6.QtCore import QPointF, QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.STEPS)
        gap = 34
        pad = 16
        w = (self.width() - 2 * pad - gap * (n - 1)) / n
        h = 62
        y = (self.height() - h) / 2
        for i, (ic, title, sub) in enumerate(self.STEPS):
            x = pad + i * (w + gap)
            r = QRectF(x, y, w, h)
            col = theme.ACCENT if i == 0 else theme.TEXT_2
            p.setPen(QPen(theme.qcolor(col, 0.45 if i == 0 else 0.25), 1))
            p.setBrush(theme.qcolor(theme.ACCENT, 0.07 if i == 0 else 0.02))
            p.drawRoundedRect(r, 9, 9)
            p.drawPixmap(int(x + 14), int(y + h / 2 - 11), theme.icon_pixmap(ic, 22, col))
            p.setFont(theme.hud_font(9.5))
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(x + 46, y + 11, w - 52, 20), Qt.AlignLeft | Qt.AlignVCenter, title.upper())
            p.setFont(theme.text_font(8.5))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(x + 46, y + 31, w - 52, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(sub, Qt.ElideRight, int(w - 52)))
            if i < n - 1:
                ax, ay = x + w + 6, y + h / 2
                p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.6), 1.4))
                p.drawLine(QPointF(ax, ay), QPointF(ax + gap - 12, ay))
                p.drawLine(QPointF(ax + gap - 12, ay), QPointF(ax + gap - 17, ay - 4))
                p.drawLine(QPointF(ax + gap - 12, ay), QPointF(ax + gap - 17, ay + 4))
        p.end()


class SettingsDialog(QDialog):
    def __init__(self, parent=None, decision=None):
        super().__init__(parent)
        self.setObjectName("settings")
        self.setWindowTitle("JARVIS Settings")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)
        self.resize(920, 640)
        self.setMinimumSize(760, 520)
        self.setStyleSheet(STYLE)
        self.rows = []                       # every SettingRow, in page order
        self.cards = []
        self.pages = []                      # (scroll area, [cards])
        self.key_status = {}                 # provider → Chip
        self.test_buttons = {}
        self._tester = _KeyTester(self)
        self._tester.done.connect(self._on_key_tested)
        self._decision = decision

        self._build_controls()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self._build_rail())
        self.content = _Content()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)
        cl.addWidget(self._build_footer())
        body.addWidget(self.content, 1)
        root.addLayout(body)

        for builder in (self._page_ai, self._page_decisions, self._page_voice, self._page_buddy, self._page_safety,
                        self._page_location, self._page_about):
            builder()
        self.set_page(0)

        # Snapshot of what the widgets showed on open: OK only writes what the user changed,
        # so opening and confirming never rewrites (clamps, reformats or pins defaults in) .env.
        self._initial = self._values()
        self._connect_dirty()
        self._update_dirty()
        QShortcut(QKeySequence.Find, self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))

    # ── controls (the public attributes) ─────────────────────────────────────
    def _build_controls(self):
        self.gemini_edit = _secret(Config.GEMINI_API_KEY)
        self.gemini_edit.setPlaceholderText("Paste a Gemini key (starts with AIza…)")
        self.openrouter_edit = _secret(Config.OPENROUTER_API_KEY)
        self.openrouter_edit.setPlaceholderText("Paste an OpenRouter key (sk-or-…)")
        self.default_model = QLineEdit(Config.DEFAULT_MODEL)
        self.default_model.setPlaceholderText("Automatic")
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 300)
        self.timeout.setValue(Config.REQUEST_TIMEOUT)
        self.timeout.setSuffix(" s")

        self.engine = _combo([("laya", "Laya — local decision model"), ("rules", "Rules only — no download")],
                             Config.DECISION_ENGINE)
        self.laya_model = _combo([("english", "English (0.8 GB)"), ("multilingual", "Multilingual (0.65 GB)")],
                                 Config.LAYA_MODEL)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.05, 0.95)
        self.threshold.setSingleStep(0.05)
        self.threshold.setValue(Config.DECISION_THRESHOLD)

        self.tts = _combo([("edge", "Neural voice (online)"), ("sapi", "Windows voice (offline)")],
                          Config.TTS_ENGINE)
        self.voice_name = QLineEdit(Config.EDGE_TTS_VOICE)
        self.voice_name.setPlaceholderText("e.g. en-GB-RyanNeural")
        self.rate = QSpinBox()
        self.rate.setRange(80, 320)
        self.rate.setValue(Config.VOICE_RATE)
        self.rate.setSuffix(" wpm")
        self.volume = QDoubleSpinBox()
        self.volume.setRange(0.0, 1.0)
        self.volume.setSingleStep(0.1)
        self.volume.setValue(Config.VOICE_VOLUME)
        self.wake_word = QLineEdit(Config.WAKE_WORD)
        self.wake_word.setPlaceholderText("jarvis")
        self.vosk = QLineEdit(Config.VOSK_MODEL_PATH)
        self.vosk.setPlaceholderText("Download automatically")
        self.live_voice = ToggleSwitch(Config.LIVE_VOICE)
        self.act_mode = _combo([("clause", "When each command is clear"),
                                ("pause", "At each short pause")], Config.ACT_MODE)
        self.stt_model = _combo([("vosk-model-en-in-0.5", "Indian English — large (1 GB)"),
                                 ("vosk-model-small-en-in-0.4", "Indian English — small (36 MB)"),
                                 ("vosk-model-en-us-0.22-lgraph", "US English — medium (128 MB)"),
                                 ("vosk-model-small-en-us-0.15", "US English — small (40 MB)")], Config.VOSK_MODEL_NAME)

        from core.buddy import HOTKEYS
        from core.hotkeys import COMMAND_BAR_HOTKEYS
        self.buddy = ToggleSwitch(Config.BUDDY_ENABLED)
        self.buddy_hotkey = _combo(list(HOTKEYS.items()), Config.BUDDY_HOTKEY)
        self.bar_hotkey = _combo(list(COMMAND_BAR_HOTKEYS.items()), Config.COMMAND_BAR_HOTKEY)
        from core import autostart
        self.startup = ToggleSwitch(autostart.is_enabled())
        self._startup_initial = self.startup.isChecked()

        self.confirm = ToggleSwitch(Config.AUTOMATION_CONFIRMATION_REQUIRED)
        self.safe_mode = ToggleSwitch(Config.AUTOMATION_SAFE_MODE)
        self.vision_provider = _combo([("auto", "Automatic"), ("gemini", "Gemini"), ("openrouter", "OpenRouter"),
                                       ("ollama", "Ollama (local)")], Config.AUTOMATION_VISION_PROVIDER)
        self.vision_model = QLineEdit(Config.AUTOMATION_VISION_MODEL)
        self.vision_model.setPlaceholderText("Provider default")
        self.ollama_autostart = ToggleSwitch(Config.OLLAMA_AUTOSTART)
        self.ollama_vision = QLineEdit(Config.OLLAMA_VISION_MODEL)
        self.ollama_vision.setPlaceholderText("e.g. qwen2.5vl:3b")

        self.location_edit = QLineEdit(get_location_preference())
        self.location_edit.setPlaceholderText("Auto-detect")

        for w in (self.default_model, self.timeout, self.engine, self.laya_model, self.tts, self.voice_name, self.rate,
                  self.wake_word, self.act_mode, self.stt_model, self.buddy_hotkey, self.bar_hotkey,
                  self.vision_provider, self.vision_model, self.ollama_vision, self.location_edit):
            sized(w)

    # ── layout pieces ─────────────────────────────────────────────────────────
    def _build_rail(self):
        rail = _Rail()
        rail.setFixedWidth(NAV_WIDTH)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(26))
        logo.setFixedSize(26, 26)
        brand.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel("JARVIS")
        name.setFont(theme.hud_font(12))
        name.setStyleSheet(f"color: {theme.TEXT};")
        sub = QLabel("SETTINGS")
        sub.setFont(theme.hud_font(7.5))
        sub.setStyleSheet(f"color: {theme.ACCENT};")
        col.addWidget(name)
        col.addWidget(sub)
        brand.addLayout(col)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(14)

        self.search = QLineEdit()
        self.search.setObjectName("navSearch")
        self.search.setPlaceholderText("Search settings")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(QAction(theme.icon("search", 16, color=theme.MUTED), "", self.search),
                              QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self.apply_search)
        self.search.returnPressed.connect(self._next_match_page)
        lay.addWidget(self.search)
        lay.addSpacing(12)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav = []
        for i, (title, icon_name, _sub) in enumerate(PAGES):
            b = NavButton(icon_name, title)
            b.clicked.connect(lambda _=False, i=i: self.set_page(i))
            self.nav_group.addButton(b, i)
            self.nav.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        hint = QLabel("Ctrl+F to search · Esc to close")
        hint.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return rail

    def _build_footer(self):
        bar = QFrame()
        bar.setObjectName("footer")
        bar.setStyleSheet(f"QFrame#footer {{ background: {theme.qcolor(theme.BG_2, 0.9).name(QColor.HexArgb)};"
                          f" border-top: 1px solid {theme.BORDER_SOFT}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 12, 20, 12)
        lay.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.env_path = os.path.join(str(Config.USER_DIR), ".env")
        self.path_label = QLabel()
        self.path_label.setObjectName("footerPath")
        self.path_label.setToolTip(self.env_path)
        self.path_label.setMinimumWidth(80)
        self.path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName("dirty")
        col.addWidget(self.dirty_label)
        col.addWidget(self.path_label)
        lay.addLayout(col, 1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("ghost")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("Save changes")
        self.save_button.setObjectName("primary")
        self.save_button.setDefault(True)
        self.save_button.setIcon(theme.icon("check", 16, color="#00121A", active="#00121A", checked="#00121A"))
        self.save_button.clicked.connect(self.accept)
        lay.addWidget(self.cancel_button)
        lay.addWidget(self.save_button)
        return bar

    def _page(self, index: int, trailing=None):
        title, icon_name, subtitle = PAGES[index]
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(30, 26, 26, 24)
        lay.setSpacing(16)
        lay.addWidget(PageHeader(title, subtitle, icon_name, trailing=trailing))
        lay.addSpacing(2)
        scroll.setWidget(inner)
        scroll._lay = inner.layout()
        scroll._cards = []
        empty = QLabel("No settings on this page match your search.")
        empty.setObjectName("emptySearch")
        empty.setAlignment(Qt.AlignCenter)
        empty.hide()
        lay.addWidget(empty)
        scroll._empty = empty
        self.stack.addWidget(scroll)
        self.pages.append(scroll)
        return scroll

    def _card(self, page, caption: str) -> SettingCard:
        card = SettingCard(caption)
        page._lay.addWidget(card)
        page._cards.append(card)
        self.cards.append(card)
        return card

    def _row(self, card, title, description="", control=None, **kw) -> SettingRow:
        kw.setdefault("keys", ROW_KEYS.get(title, ()))
        row = SettingRow(title, description, control, **kw)
        row.page = self.stack.count() - 1
        card.add(row)
        self.rows.append(row)
        return row

    @staticmethod
    def _finish(page):
        page._lay.addStretch(1)

    # ── pages ────────────────────────────────────────────────────────────────
    def _key_field(self, provider: str, edit: QLineEdit):
        chip = Chip()
        self.key_status[provider] = chip
        get = QPushButton("Get a key")
        get.setObjectName("link")
        get.setAutoDefault(False)
        get.setCursor(Qt.PointingHandCursor)
        get.clicked.connect(lambda: webbrowser.open(KEY_LINKS[provider]))
        test = QPushButton("Test")
        test.setObjectName("small")
        test.setAutoDefault(False)
        test.setToolTip("Send one tiny request to check the key")
        test.clicked.connect(lambda: self.test_key(provider))
        self.test_buttons[provider] = test
        edit.textChanged.connect(lambda *_: self._refresh_key_status(provider))
        self._refresh_key_status(provider)
        return chip, hbox(edit, test, get, spacing=8, stretch_first=True)

    def _page_ai(self):
        page = self._page(0)
        card = self._card(page, "API keys")
        chip, field = self._key_field("gemini", self.gemini_edit)
        self._row(card, "Google Gemini", "Free key from Google AI Studio. Chat, reasoning and seeing your screen.",
                  field, stacked=True, trailing=chip, keywords="api key gemini google aistudio secret")
        chip, field = self._key_field("openrouter", self.openrouter_edit)
        self._row(card, "OpenRouter", "One key for hundreds of models, including free ones.",
                  field, stacked=True, trailing=chip, keywords="api key openrouter secret models")
        card.note("No key? Install <b>Ollama</b> (ollama.com) and JARVIS uses local models, fully offline.",
                  "chip")
        card = self._card(page, "Model")
        self._row(card, "Default model", "Leave empty to let JARVIS pick. e.g. gemini-flash or ollama:llama3.2",
                  self.default_model, keywords="model llm default gemini ollama")
        self._row(card, "Request timeout", "How long to wait for a model before giving up.", self.timeout,
                  keywords="timeout seconds wait slow")
        self._finish(page)

    def _page_decisions(self):
        status = self._decision.status if self._decision is not None else "not started"
        self.decision_chip = Chip(status, decision_color(status))
        page = self._page(1, trailing=self.decision_chip)
        card = self._card(page, "Decision engine")
        self._row(card, "Engine", "Laya picks the right skill for each request fully offline.", self.engine,
                  keywords="laya rules decision engine intent")
        self._row(card, "Laya checkpoint", "English, or multilingual for 100+ languages. Downloaded once.",
                  self.laya_model,
                  keywords="laya model language multilingual english download")
        self.threshold_slider = SliderSpin(self.threshold, scale=100)
        sized(self.threshold_slider)
        self._row(card, "Confidence threshold", "Below this, JARVIS falls back to rules and the AI model.",
                  self.threshold_slider, keywords="confidence threshold laya fallback")
        card.note("Laya never sends your request to a cloud model. Needs <b>pip install laya</b>.", "brain")
        flow = SettingCard("How a request is routed")
        flow._lay.addWidget(_Pipeline())
        page._lay.addWidget(flow)
        page._cards.append(flow)
        self._finish(page)

    def _page_voice(self):
        page = self._page(2)
        card = self._card(page, "Speaking")
        self._row(card, "Speech engine", "Neural voices sound natural; the Windows voice works offline.", self.tts,
                  keywords="tts speech engine voice edge sapi")
        self._row(card, "Neural voice", "An edge-tts voice name, e.g. en-IN-PrabhatNeural.", self.voice_name,
                  keywords="voice neural edge name accent")
        self._row(card, "Offline voice rate", "Speaking speed of the Windows voice.", self.rate,
                  keywords="rate speed words per minute sapi")
        self.volume_slider = SliderSpin(self.volume, scale=100)
        sized(self.volume_slider)
        self._row(card, "Offline voice volume", "Loudness of the Windows voice.", self.volume_slider,
                  keywords="volume loudness sapi")
        card = self._card(page, "Listening")
        self._row(card, "Wake word", "Say it to get JARVIS's attention.", self.wake_word,
                  keywords="wake word hotword name listen")
        self._row(card, "Live voice", "Act while you're still speaking. Offline, with Vosk.", self.live_voice,
                  keywords="live voice streaming vosk realtime")
        self._row(card, "Act on commands", "When live voice runs a command.", self.act_mode,
                  keywords="act mode clause pause live")
        self._row(card, "Live speech model", "Offline recognition model, downloaded on first use.", self.stt_model,
                  keywords="stt speech recognition vosk model language")
        browse = QPushButton()
        browse.setIcon(theme.icon("folder", 16))
        browse.setToolTip("Choose a Vosk model folder")
        browse.setFixedSize(36, 34)
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse_vosk)
        self.vosk.setMinimumWidth(150)
        vosk_box = sized(hbox(self.vosk, browse, spacing=6, stretch_first=True))
        self._row(card, "Vosk model folder", "Use a model you already have instead of downloading.", vosk_box,
                  keywords="vosk folder path model offline")
        self._finish(page)

    def _page_buddy(self):
        page = self._page(3)
        card = self._card(page, "Cursor buddy")
        self._row(card, "Buddy mode", "A helper next to the cursor: hold the hotkey anywhere and ask.", self.buddy,
                  keywords="buddy cursor overlay helper")
        self.buddy_caps = KeyCaps(self.buddy_hotkey.currentText())
        self.buddy_hotkey.currentTextChanged.connect(self.buddy_caps.set_label)
        self._row(card, "Buddy hotkey", "Hold to talk, release to send.", self.buddy_hotkey, below=self.buddy_caps,
                  keywords="hotkey shortcut hold buddy key")
        card = self._card(page, "Command bar")
        self.bar_caps = KeyCaps(self.bar_hotkey.currentText())
        self.bar_hotkey.currentTextChanged.connect(self.bar_caps.set_label)
        self._row(card, "Command bar hotkey", "Press anywhere to type a request.", self.bar_hotkey,
                  below=self.bar_caps, keywords="hotkey shortcut command bar type key")
        card = self._card(page, "Startup")
        self._row(card, "Start with Windows", "Launch JARVIS quietly in the tray when you sign in.", self.startup,
                  keywords="startup autostart boot login sign in tray windows")
        self._finish(page)

    def _page_safety(self):
        page = self._page(4)
        card = self._card(page, "Automation")
        self._row(card, "Ask before taking control", "Confirm before JARVIS moves your mouse or types.", self.confirm,
                  keywords="confirm automation mouse keyboard control ask")
        self._row(card, "Safe mode", "Confirm risky clicks such as Delete, Send or Pay.", self.safe_mode,
                  keywords="safe mode risky click delete send pay")
        card.note("Shutdown, restart, deleting files and closing apps <b>always</b> ask first.", "shield",
                  theme.SUCCESS)
        card = self._card(page, "Screen vision")
        self._row(card, "Vision provider", "Which model looks at your screen.", self.vision_provider,
                  keywords="vision provider screen see gemini openrouter ollama")
        self._row(card, "Vision model", "Optional model name from the model list.", self.vision_model,
                  keywords="vision model screen")
        card = self._card(page, "Local models (Ollama)")
        self._row(card, "Start Ollama with JARVIS", "Keep local models ready in the background.",
                  self.ollama_autostart, keywords="ollama autostart local start")
        self._row(card, "Ollama vision model", "Local model used to see the screen.", self.ollama_vision,
                  keywords="ollama vision model local screen")
        self._finish(page)

    def _page_location(self):
        page = self._page(5)
        card = self._card(page, "Your location")
        self._row(card, "City", "Leave empty to auto-detect from your connection.", self.location_edit,
                  keywords="location city country weather place")
        self.auto_detect_button = QPushButton("Use auto-detect")
        self.auto_detect_button.setObjectName("small")
        self.auto_detect_button.setAutoDefault(False)
        self.auto_detect_button.clicked.connect(self.location_edit.clear)
        self.location_note = card.note("", "globe", widget=self.auto_detect_button)
        self.location_edit.textChanged.connect(self._refresh_location_note)
        self._refresh_location_note()
        card = self._card(page, "Privacy")
        card.note("Your location is stored only in your settings file on this PC. It is sent along with requests "
                  "to the AI model you chose, and to the weather service when you ask for the forecast.", "shield",
                  theme.SUCCESS)
        self._finish(page)

    def _page_about(self):
        page = self._page(6)
        hero = SettingCard("")
        hero.glow = True
        hl = QHBoxLayout()
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(22)
        self.orb = ArcOrb(120)
        hl.addWidget(self.orb)
        col = QVBoxLayout()
        col.setSpacing(4)
        name = QLabel("J.A.R.V.I.S.")
        f = theme.hud_font(22)
        f.setLetterSpacing(QFont.PercentageSpacing, 125)
        name.setFont(f)
        name.setStyleSheet(f"color: {theme.TEXT};")
        self.version = app_version()
        self.version_label = QLabel(f"Version {self.version}")
        self.version_label.setFont(theme.hud_font(9))
        self.version_label.setStyleSheet(f"color: {theme.ACCENT};")
        blurb = QLabel("Just A Rather Very Intelligent System — your desktop assistant for Windows.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet(f"color: {theme.MUTED}; font-size: 12.5px;")
        col.addStretch(1)
        col.addWidget(name)
        col.addWidget(self.version_label)
        col.addSpacing(4)
        col.addWidget(blurb)
        col.addStretch(1)
        hl.addLayout(col, 1)
        hero._lay.addLayout(hl)
        page._lay.addWidget(hero)
        page._cards.append(hero)

        card = self._card(page, "Your data")
        self.data_dir = str(Config.USER_DIR)
        open_btn = QPushButton("Open folder")
        open_btn.setObjectName("small")
        open_btn.setIcon(theme.icon("folder", 15))
        open_btn.setAutoDefault(False)
        open_btn.clicked.connect(self.open_data_folder)
        path = QLabel(self.data_dir)
        path.setStyleSheet(f"color: {theme.TEXT_2}; font-family: {theme.MONO}; font-size: 11.5px;")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setWordWrap(True)
        self._row(card, "Data folder", "Settings, memory, logs and downloaded models live here.",
                  hbox(path, open_btn, spacing=10, stretch_first=True), stacked=True,
                  keywords="data folder path appdata logs memory env")
        card = self._card(page, "Help")
        links = QWidget()
        ll = QHBoxLayout(links)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        root = Path(__file__).resolve().parent.parent
        for label, fname, ic in (("User guide", "USERGUIDE.md", "list"), ("Setup guide", "SETUP_GUIDE.md", "gear"),
                                 ("Read me", "README.md", "sparkle")):
            b = QPushButton(label)
            b.setIcon(theme.icon(ic, 15))
            b.setObjectName("chip")
            b.setAutoDefault(False)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, p=root / fname: self.open_url(QUrl.fromLocalFile(str(p))))
            ll.addWidget(b)
        ll.addStretch(1)
        self._row(card, "Documentation", "How to talk to JARVIS, set it up and fix problems.", links, stacked=True,
                  keywords="help docs documentation guide readme")
        self._finish(page)

    # ── behaviour ────────────────────────────────────────────────────────────
    def set_page(self, index: int):
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        self.nav[index].setChecked(True)

    def current_page(self) -> int:
        return self.stack.currentIndex()

    def apply_search(self, text: str = None):
        """Filter rows on every page; jump to the first page with hits and highlight them."""
        query = (self.search.text() if text is None else text).strip()
        counts = [0] * len(self.pages)
        for row in self.rows:
            hit = bool(query) and row.matches(query)
            row.setHidden(bool(query) and not hit)
            row.set_highlight(hit)
            if hit:
                counts[row.page] += 1
        for page in self.pages:
            for card in page._cards:
                if card.rows:
                    card.update_visibility(searching=bool(query))
                else:
                    card.setVisible(not query)
        for i, (btn, page) in enumerate(zip(self.nav, self.pages)):
            btn.set_badge(counts[i] if query else None)
            page._empty.setVisible(bool(query) and counts[i] == 0)
        if query and counts[self.current_page()] == 0 and any(counts):
            self.set_page(next(i for i, c in enumerate(counts) if c))
        if query:
            first = next((r for r in self.rows if r.page == self.current_page() and r.highlighted()), None)
            if first is not None:
                QTimer.singleShot(0, lambda: self.pages[first.page].ensureWidgetVisible(first, 0, 40))
        return counts

    def matching_rows(self):
        return [r for r in self.rows if r.highlighted()]

    def _next_match_page(self):
        counts = [b.badge() or 0 for b in self.nav]
        if not any(counts):
            return
        n = len(counts)
        for step in range(1, n + 1):
            i = (self.current_page() + step) % n
            if counts[i]:
                self.set_page(i)
                return

    def _connect_dirty(self):
        for w in (self.gemini_edit, self.openrouter_edit, self.default_model, self.voice_name, self.wake_word,
                  self.vosk, self.vision_model, self.ollama_vision, self.location_edit):
            w.textChanged.connect(self._update_dirty)
        for w in (self.timeout, self.threshold, self.rate, self.volume):
            w.valueChanged.connect(self._update_dirty)
        for w in (self.engine, self.laya_model, self.tts, self.act_mode, self.stt_model, self.buddy_hotkey,
                  self.bar_hotkey, self.vision_provider):
            w.currentIndexChanged.connect(self._update_dirty)
        for w in (self.live_voice, self.buddy, self.startup, self.confirm, self.safe_mode, self.ollama_autostart):
            w.toggled.connect(self._update_dirty)

    def changed_keys(self) -> list:
        initial = getattr(self, "_initial", None)
        if initial is None:
            return []
        keys = [k for k, v in self._values().items() if initial.get(k) != v]
        if self.startup.isChecked() != self._startup_initial:
            keys.append("startup")
        return keys

    def is_dirty(self) -> bool:
        return bool(self.changed_keys())

    def _update_dirty(self, *_):
        changed = set(self.changed_keys())
        n = len(changed)
        for row in self.rows:
            row.set_modified(bool(changed.intersection(row.keys)))
        self.save_button.setEnabled(n > 0)
        self.dirty_label.setText(f"● {n} unsaved change{'s' if n != 1 else ''}" if n else "")
        self.dirty_label.setVisible(bool(n))
        self._elide_path()

    def _elide_path(self):
        fm = QFontMetrics(self.path_label.font())
        width = max(80, self.path_label.width() or 300)
        self.path_label.setText(fm.elidedText(f"Saved to {self.env_path}", Qt.ElideMiddle, width))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide_path()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._elide_path)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.search.hasFocus() and self.search.text():
            self.search.clear()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.search.hasFocus():
            return                                   # Enter in search jumps to results, never saves
        super().keyPressEvent(e)

    def _refresh_key_status(self, provider: str):
        edit = self.gemini_edit if provider == "gemini" else self.openrouter_edit
        has = bool(edit.text().strip())
        self.key_status[provider].set("Set" if has else "Not set", theme.SUCCESS if has else theme.MUTED)
        self.key_status[provider].setToolTip("")
        if provider in self.test_buttons:
            self.test_buttons[provider].setEnabled(has)

    def test_key(self, provider: str):
        edit = self.gemini_edit if provider == "gemini" else self.openrouter_edit
        key = edit.text().strip()
        if not key:
            return
        self.key_status[provider].set("Testing…", theme.STATE_COLORS["thinking"])
        self.test_buttons[provider].setEnabled(False)
        self._tester.start(provider, key)

    def _on_key_tested(self, provider: str, ok: bool, message: str):
        try:
            self.key_status[provider].set(message, theme.SUCCESS if ok else theme.ERROR)
            self.test_buttons[provider].setEnabled(True)
        except RuntimeError:                      # dialog already closed
            pass

    def _refresh_location_note(self, *_):
        text = self.location_edit.text().strip()
        self.auto_detect_button.setVisible(bool(text))
        self.location_note.note_label.setText(
            f"JARVIS will use <b>{text}</b> for weather and share it with the AI as context." if text else
            "JARVIS will <b>auto-detect</b> your city from your connection for weather and local answers.")

    def _browse_vosk(self):
        folder = QFileDialog.getExistingDirectory(self, "Vosk model folder", self.vosk.text() or str(Config.USER_DIR))
        if folder:
            self.vosk.setText(folder)

    @staticmethod
    def open_url(url: QUrl):
        QDesktopServices.openUrl(url)

    def open_data_folder(self):
        os.makedirs(self.data_dir, exist_ok=True)
        self.open_url(QUrl.fromLocalFile(self.data_dir))

    # ── values / saving ──────────────────────────────────────────────────────
    def get_values(self):
        return (self.openrouter_edit.text().strip(), self.gemini_edit.text().strip(),
                self.location_edit.text().strip())

    def _values(self):
        return {
            "GEMINI_API_KEY": self.gemini_edit.text(),
            "OPENROUTER_API_KEY": self.openrouter_edit.text(),
            "JARVIS_DEFAULT_MODEL": self.default_model.text(),
            "JARVIS_REQUEST_TIMEOUT": self.timeout.value(),
            "JARVIS_DECISION_ENGINE": self.engine.currentData(),
            "JARVIS_LAYA_MODEL": self.laya_model.currentData(),
            "JARVIS_DECISION_THRESHOLD": f"{self.threshold.value():.2f}",
            "JARVIS_TTS_ENGINE": self.tts.currentData(),
            "JARVIS_VOICE": self.voice_name.text(),
            "JARVIS_VOICE_RATE": self.rate.value(),
            "JARVIS_VOICE_VOLUME": f"{self.volume.value():.2f}",
            "JARVIS_WAKE_WORD": self.wake_word.text().lower(),
            "JARVIS_VOSK_MODEL": self.vosk.text(),
            "JARVIS_LIVE_VOICE": "1" if self.live_voice.isChecked() else "0",
            "JARVIS_BUDDY": "1" if self.buddy.isChecked() else "0",
            "JARVIS_BUDDY_HOTKEY": self.buddy_hotkey.currentData(),
            "JARVIS_COMMAND_BAR_HOTKEY": self.bar_hotkey.currentData(),
            "JARVIS_ACT_MODE": self.act_mode.currentData(),
            "JARVIS_VOSK_MODEL_NAME": self.stt_model.currentData(),
            "JARVIS_CONFIRM_ACTIONS": "1" if self.confirm.isChecked() else "0",
            "JARVIS_SAFE_MODE": "1" if self.safe_mode.isChecked() else "0",
            "JARVIS_VISION_PROVIDER": self.vision_provider.currentData(),
            "JARVIS_VISION_MODEL": self.vision_model.text(),
            "JARVIS_OLLAMA_AUTOSTART": "1" if self.ollama_autostart.isChecked() else "0",
            "OLLAMA_VISION_MODEL": self.ollama_vision.text(),
            "JARVIS_LOCATION": self.location_edit.text().strip(),
        }

    def accept(self):
        values = self._values()
        initial = getattr(self, "_initial", {})
        try:
            for key, value in values.items():
                if key in initial and initial[key] == value:
                    continue
                if key == "JARVIS_LOCATION":
                    save_location_preference(value or None)
                else:
                    save_setting(key, value)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Settings not saved", str(error))
            return
        if self.startup.isChecked() != self._startup_initial:      # lives in the registry, not .env
            from core import autostart
            message = autostart.set_enabled(self.startup.isChecked())
            if message.startswith("Couldn't"):
                QMessageBox.warning(self, "Startup setting", message)
        super().accept()
