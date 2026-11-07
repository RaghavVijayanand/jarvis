"""First-run welcome: pick a brain, hotkeys, voice and startup — then JARVIS lives in the tray.

A four-step HUD stepper (Welcome → Brain → Voice & keys → Launch) built as a QDialog:
``exec()`` returns truthy when the user presses "Start JARVIS", falsy on Cancel / Esc.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut, QTextOption
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from core.config import Config, save_setting
from ui import theme
from ui.settings_widgets import (Chip, HudCombo, IconBadge, KeyCaps, SecretEdit, SettingCard, SettingRow, hbox,
                                 sized)
from ui.widgets import ArcOrb, HudPanel, ToggleSwitch, paint_grid

STEPS = ("Welcome", "Brain", "Voice & keys", "Launch")

STYLE = f"""
QDialog#welcome {{ background: {theme.BG}; }}
QLabel#heroTitle {{ color: {theme.TEXT}; }}
QLabel#sub {{ color: {theme.MUTED}; font-size: 13px; }}
QLabel#hint {{ color: {theme.MUTED}; font-size: 12px; }}
QComboBox {{ padding: 6px 30px 6px 10px; min-height: 20px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: none; border: none; width: 0; height: 0; margin: 0; }}
QLineEdit {{ min-height: 22px; padding: 7px 10px; }}
QPushButton#primary {{ padding: 9px 22px; font-size: 13px; }}
QPushButton#ghost, QPushButton#secondary {{ padding: 9px 18px; }}
"""

BRAINS = (
    ("gemini", "sparkle", "Google Gemini", "Free key. Chats, reasons and sees your screen.", True),
    ("openrouter", "globe", "OpenRouter", "One key, hundreds of models — free ones included.", False),
    ("ollama", "chip", "Ollama", "Fully local and private. Runs on your PC.", False),
    ("skip", "clock", "Decide later", "Offline commands work now. Add a brain any time.", False),
)
HINTS = {
    "gemini": "Get a free key at <b>aistudio.google.com</b> — it takes about a minute.",
    "openrouter": "Create a key at <b>openrouter.ai/keys</b>. Free models need no credit.",
    "ollama": "Install Ollama from <b>ollama.com</b>; JARVIS starts it for you.",
    "skip": "Commands like “open Spotify” or “volume 30” work offline right away.",
}


# ── pieces ───────────────────────────────────────────────────────────────────
class StepIndicator(QWidget):
    """●━━○━━○━━○ with labels. ``set_current(i)``; clicking a finished step emits ``picked(i)``."""

    picked = Signal(int)

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.labels = list(labels)
        self.current = 0
        self.setFixedHeight(54)
        self.setMinimumWidth(360)

    def set_current(self, i: int):
        self.current = i
        self.update()

    def _centers(self):
        n = len(self.labels)
        pad = 50
        span = (self.width() - 2 * pad) / max(1, n - 1)
        return [QPointF(pad + i * span, 17) for i in range(n)]

    def mouseReleaseEvent(self, e):
        for i, c in enumerate(self._centers()):
            if i < self.current and abs(e.position().x() - c.x()) < 40:
                self.picked.emit(i)
                return
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cs = self._centers()
        for i in range(len(cs) - 1):
            a, b = cs[i], cs[i + 1]
            done = i < self.current
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.8) if done else QColor(theme.BORDER), 2 if done else 1))
            p.drawLine(QPointF(a.x() + 14, a.y()), QPointF(b.x() - 14, b.y()))
        for i, (c, label) in enumerate(zip(cs, self.labels)):
            done, now = i < self.current, i == self.current
            if now:
                p.setPen(Qt.NoPen)
                p.setBrush(theme.qcolor(theme.ACCENT, 0.16))
                p.drawEllipse(c, 16, 16)
            p.setPen(QPen(QColor(theme.ACCENT if (done or now) else theme.FAINT), 1.5))
            p.setBrush(QColor(theme.ACCENT) if done else QColor(theme.BG))
            p.drawEllipse(c, 11, 11)
            if done:
                p.drawPixmap(int(c.x() - 8), int(c.y() - 8), theme.icon_pixmap("check", 16, "#00121A"))
            else:
                p.setFont(theme.hud_font(8.5))
                p.setPen(QColor(theme.ACCENT if now else theme.MUTED))
                p.drawText(QRectF(c.x() - 11, c.y() - 11, 22, 22), Qt.AlignCenter, str(i + 1))
            p.setFont(theme.hud_font(7.5))
            p.setPen(QColor(theme.TEXT if now else (theme.TEXT_2 if done else theme.FAINT)))
            p.drawText(QRectF(c.x() - 60, c.y() + 17, 120, 16), Qt.AlignCenter, label.upper())
        p.end()


class BrainCard(QRadioButton):
    """A large selectable card (icon, title, one-line description, optional badge). Still a QRadioButton."""

    def __init__(self, icon_name: str, title: str, description: str, badge: str = "", parent=None):
        super().__init__(title, parent)
        self.icon_name, self.title, self.description, self.badge = icon_name, title, description, badge
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(98)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hover = False

    def sizeHint(self):
        return QSize(280, 100)

    def minimumSizeHint(self):
        return QSize(220, 98)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 9, -1, -1)          # 8px on top: room for the badge tab
        on = self.isChecked()
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qcolor(theme.ACCENT, 0.06))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 13, 13)
        p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.85) if on else
                      QColor(theme.BORDER if self._hover else theme.BORDER_SOFT), 1.3 if on else 1))
        p.setBrush(theme.qcolor(theme.CARD_HI if (on or self._hover) else theme.CARD, 0.95))
        p.drawRoundedRect(r, 12, 12)
        if self.hasFocus():
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.5), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 9, 9)
        col = theme.ACCENT if on else theme.TEXT_2
        # icon tile
        tile = QRectF(r.left() + 14, r.top() + 16, 40, 40)
        p.setPen(QPen(theme.qcolor(col, 0.5), 1))
        p.setBrush(theme.qcolor(col, 0.10 if on else 0.04))
        p.drawRoundedRect(tile, 10, 10)
        p.drawPixmap(int(tile.left() + 9), int(tile.top() + 9), theme.icon_pixmap(self.icon_name, 22, col))
        # radio dot (top-right)
        dot = QPointF(r.right() - 20, r.top() + 22)
        p.setPen(QPen(QColor(theme.ACCENT if on else theme.FAINT), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(dot, 8, 8)
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawEllipse(dot, 4.2, 4.2)
        # title + badge
        x = tile.right() + 14
        tf = theme.text_font(11, QFont.DemiBold)
        p.setFont(tf)
        p.setPen(QColor(theme.TEXT))
        tw = QFontMetrics(tf).horizontalAdvance(self.title)
        p.drawText(QRectF(x, r.top() + 13, tw + 4, 24), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        if self.badge:                                         # a tab sitting on the card's top edge
            bf = theme.hud_font(6.8)
            bw = QFontMetrics(bf).horizontalAdvance(self.badge.upper()) + 30
            badge = QRectF(r.right() - bw - 40, r.top() - 8, bw, 17)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.BG))
            p.drawRoundedRect(badge.adjusted(-3, 0, 3, 0), 8.5, 8.5)
            p.setPen(QPen(theme.qcolor(theme.ACCENT_2, 0.75), 1))
            p.setBrush(theme.qcolor(theme.ACCENT_2, 0.16))
            p.drawRoundedRect(badge, 8.5, 8.5)
            p.drawPixmap(int(badge.left() + 7), int(badge.top() + 3), theme.icon_pixmap("sparkle", 11, theme.ACCENT_2))
            p.setFont(bf)
            p.setPen(QColor(theme.ACCENT_2))
            p.drawText(badge.adjusted(16, 0, -2, 0), Qt.AlignCenter, self.badge.upper())
        # description (wrapped)
        p.setFont(theme.text_font(9))
        p.setPen(QColor(theme.MUTED))
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WordWrap)
        p.drawText(QRectF(x, r.top() + 39, r.right() - x - 16, r.height() - 44), self.description, opt)
        p.end()


class _Backdrop(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        paint_grid(p, self.rect(), spacing=32)
        p.end()


def _title(text: str, size: float = 20) -> QLabel:
    lab = QLabel(text.upper())
    f = theme.hud_font(size)
    f.setLetterSpacing(QFont.PercentageSpacing, 118)
    lab.setFont(f)
    lab.setObjectName("heroTitle")
    return lab


def _sub(text: str, center: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("sub")
    lab.setWordWrap(True)
    if center:
        lab.setAlignment(Qt.AlignHCenter)
    return lab


def _page_layout(title: str, subtitle: str, icon_name: str):
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(40, 18, 40, 10)
    lay.setSpacing(14)
    head = QHBoxLayout()
    head.setSpacing(14)
    head.addWidget(IconBadge(icon_name, 42), 0, Qt.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(3)
    col.addWidget(_title(title, 16))
    col.addWidget(_sub(subtitle))
    head.addLayout(col, 1)
    lay.addLayout(head)
    lay.addSpacing(4)
    return page, lay


# ── the stepper ──────────────────────────────────────────────────────────────
class WelcomeWizard(QDialog):
    stepChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("welcome")
        self.setWindowTitle("Welcome to JARVIS")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)
        self.resize(820, 640)
        self.setMinimumSize(700, 560)
        self.setStyleSheet(STYLE)
        from core.buddy import HOTKEYS
        from core.hotkeys import COMMAND_BAR_HOTKEYS
        self._buddy_labels, self._bar_labels = dict(HOTKEYS), dict(COMMAND_BAR_HOTKEYS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.backdrop = _Backdrop()
        root.addWidget(self.backdrop)
        body = QVBoxLayout(self.backdrop)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # header: brand + steps
        header = QHBoxLayout()
        header.setContentsMargins(28, 18, 28, 4)
        header.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(24))
        logo.setFixedSize(24, 24)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        name = QLabel("JARVIS")
        name.setFont(theme.hud_font(11))
        tag = QLabel("FIRST-RUN SETUP")
        tag.setFont(theme.hud_font(7))
        tag.setStyleSheet(f"color: {theme.ACCENT};")
        brand.addWidget(name)
        brand.addWidget(tag)
        header.addWidget(logo, 0, Qt.AlignVCenter)
        header.addLayout(brand)
        header.addSpacing(18)
        self.steps = StepIndicator(STEPS)
        self.steps.picked.connect(self.go_to)
        header.addWidget(self.steps, 1)
        body.addLayout(header)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        for build in (self._welcome, self._brain, self._voice, self._startup):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(build())
            self.stack.addWidget(scroll)

        # footer
        foot = QFrame()
        foot.setObjectName("wfoot")
        foot.setStyleSheet(f"QFrame#wfoot {{ background: {theme.qcolor(theme.BG_2, 0.88).name(QColor.HexArgb)};"
                           f" border-top: 1px solid {theme.BORDER_SOFT}; }}")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(24, 12, 24, 12)
        fl.setSpacing(10)
        self.cancel_button = QPushButton("Skip setup")
        self.cancel_button.setObjectName("ghost")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        self.step_label = QLabel()
        self.step_label.setFont(theme.hud_font(8))
        self.step_label.setStyleSheet(f"color: {theme.FAINT};")
        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("secondary")
        self.back_button.setAutoDefault(False)
        self.back_button.clicked.connect(self.back)
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("primary")
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self.next_step)
        fl.addWidget(self.cancel_button)
        fl.addStretch(1)
        fl.addWidget(self.step_label)
        fl.addSpacing(8)
        fl.addWidget(self.back_button)
        fl.addWidget(self.next_button)
        body.addWidget(foot)
        QShortcut(QKeySequence(Qt.ALT | Qt.Key_Left), self, activated=self.back)
        self.go_to(0)

    # ── pages ────────────────────────────────────────────────────────────────
    def _welcome(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(40, 4, 40, 12)
        lay.setSpacing(6)
        self.orb = ArcOrb(150)
        self.orb.set_state("speaking")
        lay.addWidget(self.orb, 0, Qt.AlignHCenter)
        lay.addSpacing(4)
        title = _title("Hi, I'm JARVIS.", 22)
        title.setAlignment(Qt.AlignHCenter)
        lay.addWidget(title)
        sub = _sub("I live next to your cursor. Ask about anything on your screen and I'll point at it — or tell "
                   "me what to do and I'll do it: open apps, play music, set alarms, type, click, and run "
                   "multi-step jobs while you're still talking.", center=True)
        sub.setContentsMargins(40, 0, 40, 0)
        lay.addWidget(sub)
        lay.addSpacing(14)
        tips = QHBoxLayout()
        tips.setSpacing(12)
        buddy = self._buddy_labels.get(Config.BUDDY_HOTKEY, "Hold Ctrl + Alt")
        bar = self._bar_labels.get(Config.COMMAND_BAR_HOTKEY, "Ctrl + Shift + Space")
        for caps, text in ((KeyCaps(buddy), "Hold and talk — ask “where is…” or “how do I…”"),
                           (KeyCaps(bar), "Opens the command bar for typing"),
                           (None, "I stay in the system tray. Click the ring any time.")):
            tips.addWidget(self._tip(caps, text), 1)
        lay.addLayout(tips)
        lay.addStretch(1)
        return page

    @staticmethod
    def _tip(caps, text):
        panel = HudPanel("", brackets=True)
        panel.setMinimumHeight(92)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 14, 14, 12)
        pl.setSpacing(8)
        if caps is None:
            caps = QLabel()
            caps.setPixmap(theme.logo_pixmap(28))
            caps.setFixedHeight(30)
        pl.addWidget(caps, 0, Qt.AlignLeft)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color: {theme.TEXT_2}; font-size: 12px;")
        pl.addWidget(lab)
        pl.addStretch(1)
        return panel

    def _brain(self):
        page, lay = _page_layout("Choose my brain",
                                 "Commands like “open Spotify” work offline without any of these. Conversation "
                                 "and seeing your screen need a language model.", "brain")
        self.brain_group = QButtonGroup(page)
        self.brain_group.setExclusive(True)
        grid = QGridLayout()
        grid.setSpacing(12)
        cards = []
        for i, (key, icon_name, title, desc, rec) in enumerate(BRAINS):
            card = BrainCard(icon_name, title, desc, "Recommended" if rec else "")
            card.brain = key
            self.brain_group.addButton(card, i)
            grid.addWidget(card, i // 2, i % 2)
            cards.append(card)
        self.opt_gemini, self.opt_openrouter, self.opt_ollama, self.opt_skip = cards
        self.brain_cards = cards
        lay.addLayout(grid)
        lay.addSpacing(4)

        self.key_panel = HudPanel("API key")
        kl = QVBoxLayout(self.key_panel)
        kl.setContentsMargins(16, 30, 16, 14)
        kl.setSpacing(8)
        self.key = SecretEdit()
        self.key.setPlaceholderText("Paste your API key")
        self.get_key = QPushButton("Get a free key")
        self.get_key.setAutoDefault(False)
        self.get_key.setIcon(theme.icon("key", 15))
        self.get_key.clicked.connect(self._open_key_page)
        self.key_state = Chip()
        kl.addWidget(hbox(self.key, self.get_key, spacing=10, stretch_first=True))
        self.key_hint = QLabel()
        self.key_hint.setObjectName("hint")
        self.key_hint.setTextFormat(Qt.RichText)
        self.key_hint.setWordWrap(True)
        kl.addWidget(hbox(self.key_hint, self.key_state, spacing=10, stretch_first=True))
        lay.addWidget(self.key_panel)
        lay.addStretch(1)

        if Config.GEMINI_API_KEY:
            self.opt_gemini.setChecked(True)
            self.key.setText(Config.GEMINI_API_KEY)
        elif Config.OPENROUTER_API_KEY:
            self.opt_openrouter.setChecked(True)
            self.key.setText(Config.OPENROUTER_API_KEY)
        else:
            self.opt_gemini.setChecked(True)
        self.brain_group.idToggled.connect(lambda *_: self._sync_key())
        self.key.textChanged.connect(lambda *_: self._sync_key())
        self._sync_key()
        return page

    def _voice(self):
        page, lay = _page_layout("Voice and hotkeys", "You can change all of this later in Settings.", "mic")
        card = SettingCard("Cursor buddy")
        self.buddy = ToggleSwitch(Config.BUDDY_ENABLED)
        card.add(SettingRow("Cursor buddy", "Hold a hotkey, ask about the screen, let go.", self.buddy))
        self.buddy_key = HudCombo()
        for value, label in self._buddy_labels.items():
            self.buddy_key.addItem(label, value)
        self.buddy_key.setCurrentIndex(max(0, self.buddy_key.findData(Config.BUDDY_HOTKEY)))
        self.buddy_caps = KeyCaps(self.buddy_key.currentText())
        self.buddy_key.currentTextChanged.connect(self.buddy_caps.set_label)
        card.add(SettingRow("Buddy hotkey", "Hold to talk, release to send.", sized(self.buddy_key, 240),
                            below=self.buddy_caps))
        self.buddy.toggled.connect(self.buddy_key.setEnabled)
        self.buddy_key.setEnabled(self.buddy.isChecked())
        lay.addWidget(card)

        card = SettingCard("Typing and listening")
        self.bar_key = HudCombo()
        for value, label in self._bar_labels.items():
            self.bar_key.addItem(label, value)
        self.bar_key.setCurrentIndex(max(0, self.bar_key.findData(Config.COMMAND_BAR_HOTKEY)))
        self.bar_caps = KeyCaps(self.bar_key.currentText())
        self.bar_key.currentTextChanged.connect(self.bar_caps.set_label)
        card.add(SettingRow("Command bar hotkey", "Press anywhere to type a request.", sized(self.bar_key, 240),
                            below=self.bar_caps))
        self.live = ToggleSwitch(Config.LIVE_VOICE)
        card.add(SettingRow("Live voice", "Start acting while I'm still talking. Downloads a 1 GB offline speech "
                            "model the first time.", self.live))
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _startup(self):
        page, lay = _page_layout("Ready when you are",
                                 "JARVIS runs quietly in the system tray, next to the clock.", "power")
        self.summary = SettingCard("Your setup")
        self.summary_rows = {}
        for key, icon_name, label in (("brain", "brain", "Brain"), ("buddy", "cursor", "Cursor buddy"),
                                      ("bar", "keyboard", "Command bar"), ("live", "wave", "Live voice")):
            self.summary.add(self._summary_row(key, icon_name, label))
        lay.addWidget(self.summary)
        card = SettingCard("")
        from core import autostart
        self.startup = ToggleSwitch(autostart.is_enabled() or not Config.ONBOARDED)
        card.add(SettingRow("Start JARVIS when I sign in to Windows", "Waits in the tray — no window pops up.",
                            self.startup))
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _summary_row(self, key, icon_name, label):
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(14, 7, 14, 7)
        rl.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(theme.icon_pixmap(icon_name, 18, theme.ACCENT))
        ic.setFixedSize(18, 18)
        name = QLabel(label)
        name.setStyleSheet(f"color: {theme.TEXT_2}; font-size: 13px;")
        name.setFixedWidth(130)
        value = QLabel()
        value.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;")
        caps = KeyCaps("")
        chip = Chip()
        rl.addWidget(ic)
        rl.addWidget(name)
        rl.addWidget(value)
        rl.addWidget(caps)
        rl.addStretch(1)
        rl.addWidget(chip)
        self.summary_rows[key] = (value, caps, chip)
        # SettingCard.add expects a SettingRow-like object; wrap it
        wrapper = SettingRow("", "", row, stacked=True)
        wrapper.title_label.hide()
        wrapper.layout().setContentsMargins(0, 0, 0, 0)
        wrapper.layout().setSpacing(0)
        return wrapper

    # ── navigation ───────────────────────────────────────────────────────────
    def step_count(self) -> int:
        return self.stack.count()

    def current_step(self) -> int:
        return self.stack.currentIndex()

    def go_to(self, i: int):
        i = max(0, min(i, self.stack.count() - 1))
        self.stack.setCurrentIndex(i)
        self.steps.set_current(i)
        last = i == self.stack.count() - 1
        self.back_button.setVisible(i > 0)
        self.next_button.setText("Start JARVIS" if last else "Next")
        self.next_button.setIcon(theme.icon("power" if last else "play", 15, color="#00121A", active="#00121A",
                                            checked="#00121A"))
        self.step_label.setText(f"STEP {i + 1} OF {self.stack.count()}")
        self.orb.set_state("speaking" if i == 0 else "idle")
        if last:
            self._refresh_summary()
        self.stepChanged.emit(i)

    def next_step(self):
        if self.current_step() >= self.stack.count() - 1:
            self.accept()
        else:
            self.go_to(self.current_step() + 1)

    def back(self):
        if self.current_step() > 0:
            self.go_to(self.current_step() - 1)

    # ── helpers ──────────────────────────────────────────────────────────────
    def selected_brain(self) -> str:
        for card in self.brain_cards:
            if card.isChecked():
                return card.brain
        return "skip"

    def _sync_key(self):
        needs_key = self.opt_gemini.isChecked() or self.opt_openrouter.isChecked()
        self.key.setEnabled(needs_key)
        self.get_key.setEnabled(needs_key or self.opt_ollama.isChecked())
        self.get_key.setText("Get Ollama" if self.opt_ollama.isChecked() else "Get a free key")
        self.get_key.setIcon(theme.icon("download" if self.opt_ollama.isChecked() else "key", 15))
        brain = self.selected_brain()
        self.key_hint.setText(HINTS[brain])
        self.key.setPlaceholderText({"gemini": "Paste your Gemini key (AIza…)",
                                     "openrouter": "Paste your OpenRouter key (sk-or-…)"}.get(brain, "No key needed"))
        if needs_key:
            has = bool(self.key.text().strip())
            self.key_state.set("Key added" if has else "Optional", theme.SUCCESS if has else theme.MUTED)
            self.key_state.show()
        else:
            self.key_state.hide()

    def _open_key_page(self):
        url = ("https://ollama.com/download" if self.opt_ollama.isChecked() else
               "https://openrouter.ai/keys" if self.opt_openrouter.isChecked() else
               "https://aistudio.google.com/apikey")
        webbrowser.open(url)

    def _refresh_summary(self):
        brain = self.selected_brain()
        title = {c.brain: c.title for c in self.brain_cards}[brain]
        has_key = bool(self.key.text().strip())
        value, caps, chip = self.summary_rows["brain"]
        value.setText(title)
        caps.hide()
        if brain in ("gemini", "openrouter"):
            chip.set("Key added" if has_key else "No key yet", theme.SUCCESS if has_key else theme.WARN)
        elif brain == "ollama":
            chip.set("Local", theme.ACCENT)
        else:
            chip.set("Offline only", theme.MUTED)
        value, caps, chip = self.summary_rows["buddy"]
        on = self.buddy.isChecked()
        value.setText("" if on else "Off")
        value.setVisible(not on)
        caps.set_label(self.buddy_key.currentText() if on else "")
        caps.setVisible(on)
        chip.set("Hold" if on else "Disabled", theme.ACCENT if on else theme.MUTED)
        value, caps, chip = self.summary_rows["bar"]
        value.hide()
        caps.set_label(self.bar_key.currentText())
        chip.set("Press", theme.ACCENT)
        value, caps, chip = self.summary_rows["live"]
        caps.hide()
        on = self.live.isChecked()
        value.setText("On" if on else "Off")
        chip.set("1 GB download" if on else "Standard", theme.WARN if on else theme.MUTED)

    def values(self) -> dict:
        v = {"JARVIS_BUDDY": "1" if self.buddy.isChecked() else "0",
             "JARVIS_BUDDY_HOTKEY": self.buddy_key.currentData(),
             "JARVIS_COMMAND_BAR_HOTKEY": self.bar_key.currentData(),
             "JARVIS_LIVE_VOICE": "1" if self.live.isChecked() else "0",
             "JARVIS_ONBOARDED": "1"}
        key = self.key.text().strip()
        if self.opt_gemini.isChecked() and key:
            v["GEMINI_API_KEY"] = key
        elif self.opt_openrouter.isChecked() and key:
            v["OPENROUTER_API_KEY"] = key
        elif self.opt_ollama.isChecked():
            v["JARVIS_OLLAMA_AUTOSTART"] = "1"
        return v

    def save(self) -> list:
        """Write the choices; returns messages worth showing (e.g. startup errors)."""
        notes = []
        for k, value in self.values().items():
            save_setting(k, value)
        from core import autostart
        if self.startup.isChecked() != autostart.is_enabled():
            msg = autostart.set_enabled(self.startup.isChecked())
            if msg.startswith("Couldn't"):
                notes.append(msg)
        return notes


def run_onboarding(parent=None) -> bool:
    """Show the welcome once. True when the user finished it (settings saved)."""
    wizard = WelcomeWizard(parent)
    if not wizard.exec():
        save_setting("JARVIS_ONBOARDED", "1")        # don't nag; Settings has everything
        return False
    wizard.save()
    return True
