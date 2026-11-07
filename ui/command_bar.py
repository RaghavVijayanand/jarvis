"""The floating command bar: press the hotkey anywhere, type, press Enter.

    ╭─ ─────────────────────────────────────────────── ─╮   ← glass HUD card, cyan hairline,
    │ (◉)  Ask JARVIS or tell it what to do…      🎤  ⤢ │     corner brackets, soft glow
    │      ⌕ Where is…?   ▶ Play lo-fi   ⏲ Remind me …  │   ← suggestion chips when empty
    │   › open spotify                                  │   ← what you typed (dim)
    │ ▎ Opened **Spotify**.                         ⧉   │   ← reply card (Markdown, copy)
    │ [Enter] run · [↑] history · [Esc] close  ● WORKING │   ← keycap hints + status
    ╰─ ─────────────────────────────────────────────── ─╯

The orb on the left is JARVIS's state at a glance (``set_state``): it spins
blue while thinking, rings green while listening, glows amber while acting.
A scan line sweeps the top edge while a request is running.

It never runs commands itself: ``submitted`` goes to the dashboard's command
worker, and ``show_result`` receives the reply, so typed, spoken and bar
requests share one queue, one history and one set of confirmations.
"""
from __future__ import annotations

import html
import time
from typing import List, Optional

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRect,
                            QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QGuiApplication, QKeyEvent, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ui import theme
from ui.bar_markdown import to_html
from ui.widgets import ArcOrb, IconButton

# (chip label, what it runs)
SUGGESTIONS = [("Where is…?", "where is the settings button"), ("Play lo-fi", "open youtube and play lo-fi music"),
               ("Remind me in 20 min", "remind me to stretch in 20 minutes"), ("What's on screen?", "what's on my screen"),
               ("Volume 30", "set volume to 30")]
CHIP_ICONS = ["search", "play", "clock", "eye", "speaker"]
MAX_RESULTS = 6
RESULTS_MAX_HEIGHT = 340

GLOW = 18                        # transparent margin around the card for the outer glow
RADIUS = 14

STATUS_TEXT = {"idle": "", "listening": "Listening…", "thinking": "Working…", "acting": "Working…",
               "speaking": "Speaking…", "error": "Something went wrong", "offline": "Starting up…"}


def _brackets(p: QPainter, r: QRectF, length: float = 14, inset: float = 0.0):
    """Four HUD corner brackets on ``r``."""
    x0, y0, x1, y1 = r.left() + inset, r.top() + inset, r.right() - inset, r.bottom() - inset
    for ax, ay, bx, by, cx, cy in ((x0, y0 + length, x0, y0, x0 + length, y0),
                                   (x1 - length, y0, x1, y0, x1, y0 + length),
                                   (x0, y1 - length, x0, y1, x0 + length, y1),
                                   (x1 - length, y1, x1, y1, x1, y1 - length)):
        path = QPainterPath(QPointF(ax, ay))
        path.lineTo(QPointF(bx, by))
        path.lineTo(QPointF(cx, cy))
        p.drawPath(path)


# ── the orb (kept under the old ``logo`` name) ───────────────────────────────
class _BarOrb(ArcOrb):
    """The bar's small arc reactor. ``set_busy`` is kept for older callers."""

    def __init__(self, size: int = 36, parent=None):
        super().__init__(size, parent)
        self.busy = False

    def set_busy(self, busy: bool):
        self.busy = bool(busy)
        self.set_state("thinking" if busy else "idle")


# ── the glass card ───────────────────────────────────────────────────────────
class _Card(QWidget):
    """Paints the glass, the hairline, the corner brackets and — while busy — a scan line on the top edge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("barCard")
        self.color = QColor(theme.ACCENT)
        self._scanning = False
        self._scan_since = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._scan_tick)

    @property
    def scanning(self) -> bool:
        return self._scanning

    def set_scanning(self, on: bool):
        on = bool(on)
        if on == self._scanning:
            return
        self._scanning = on
        if on:
            self._scan_since = time.monotonic()
            if self.isVisible():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def showEvent(self, event):
        if self._scanning:
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _scan_tick(self):
        self.update(0, 0, self.width(), 6)          # only the top edge animates

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # glass: a faint vertical sheen over a deep panel
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, theme.qcolor("#0C1A28", 0.97))
        g.setColorAt(0.35, theme.qcolor(theme.PANEL, 0.97))
        g.setColorAt(1.0, theme.qcolor("#050A11", 0.98))
        p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.30), 1))
        p.setBrush(g)
        p.drawRoundedRect(r, RADIUS, RADIUS)
        # inner highlight on the top edge
        hl = QLinearGradient(r.topLeft(), r.topRight())
        hl.setColorAt(0.0, theme.qcolor(theme.ACCENT, 0.0))
        hl.setColorAt(0.5, theme.qcolor(theme.ACCENT, 0.45))
        hl.setColorAt(1.0, theme.qcolor(theme.ACCENT, 0.0))
        p.setPen(QPen(hl, 1))
        p.drawLine(QPointF(r.left() + RADIUS * 2, r.top() + 1), QPointF(r.right() - RADIUS * 2, r.top() + 1))
        # corner brackets
        pen = QPen(theme.qcolor(theme.ACCENT, 0.85), 1.6)
        pen.setCapStyle(Qt.SquareCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        _brackets(p, r, 16, 4)
        # scan line while busy: a bright comet travelling along the top border
        if self._scanning:
            t = (time.monotonic() - self._scan_since) % 1.6 / 1.6
            span = r.width() * 0.28
            x = r.left() - span + (r.width() + span) * t
            col = self.color
            comet = QLinearGradient(QPointF(x, 0), QPointF(x + span, 0))
            comet.setColorAt(0.0, theme.qcolor(col.name(), 0.0))
            comet.setColorAt(0.85, theme.qcolor(col.name(), 0.95))
            comet.setColorAt(1.0, theme.qcolor("#FFFFFF", 0.0))
            p.save()
            p.setClipRect(QRectF(r.left() + RADIUS, r.top() - 1, r.width() - 2 * RADIUS, 5))
            p.setPen(QPen(comet, 2))
            p.drawLine(QPointF(x, r.top() + 0.5), QPointF(x + span, r.top() + 0.5))
            glow = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.top() + 5))
            glow.setColorAt(0.0, theme.qcolor(col.name(), 0.25))
            glow.setColorAt(1.0, theme.qcolor(col.name(), 0.0))
            p.fillRect(QRectF(x + span * 0.4, r.top(), span * 0.6, 5), glow)
            p.restore()
        p.end()


# ── result cards ─────────────────────────────────────────────────────────────
class _RichLabel(QLabel):
    """A QLabel that shows rendered Markdown but whose ``text()`` is the original source."""

    def __init__(self, source: str, parent=None):
        super().__init__(parent)
        self.source = source
        self.setTextFormat(Qt.RichText)
        super().setText(to_html(source))

    def text(self):                                     # noqa: D401 - Qt-style accessor
        return self.source

    def html(self) -> str:
        return super().text()


class _YouLabel(QLabel):
    """"› what you typed": dim text with a cyan chevron; ``text()`` stays the plain line."""

    def __init__(self, source: str, parent=None):
        super().__init__(parent)
        self.source = source
        self.setTextFormat(Qt.RichText)
        body = source[2:] if source.startswith("› ") else source
        super().setText(f"<span style=\"color:{theme.ACCENT_DIM};\">›</span>&nbsp; {html.escape(body)}")

    def text(self):                                     # noqa: D401 - Qt-style accessor
        return self.source


class ResultCard(QFrame):
    """One line of the conversation: ``kind`` is "you", "reply" or "error"; ``label.text()`` is the text."""

    def __init__(self, text: str, kind: str = "reply", parent=None):
        super().__init__(parent)
        self.setObjectName("resultCard")
        self.setProperty("kind", kind)
        self.kind = kind
        self.source = text
        layout = QVBoxLayout(self)
        if kind == "you":
            layout.setContentsMargins(14, 6, 12, 0)
            label = _YouLabel(text, self)
            label.setObjectName("resultYou")
        elif kind == "reply":
            layout.setContentsMargins(16, 9, 34, 10)
            label = _RichLabel(text, self)
            label.setObjectName("resultText")
            label.setOpenExternalLinks(True)
        else:
            layout.setContentsMargins(16, 9, 34, 10)
            label = QLabel(text, self)
            label.setObjectName("resultError")
            label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        layout.addWidget(label)
        self.label = label
        self.btn_copy = None
        if kind != "you":
            self.btn_copy = IconButton("copy", tooltip="Copy", size=24, icon_size=14, parent=self)
            self.btn_copy.clicked.connect(self.copy)
            self.btn_copy.hide()
        self.setMouseTracking(True)

    def copy(self):
        QApplication.clipboard().setText(self.source)
        if self.btn_copy is not None:
            self.btn_copy.set_icon("check")
            self.btn_copy.setToolTip("Copied")
            QTimer.singleShot(1400, self._copy_reset)

    def _copy_reset(self):
        try:
            self.btn_copy.set_icon("copy")
            self.btn_copy.setToolTip("Copy")
        except RuntimeError:                              # card already deleted
            pass

    def resizeEvent(self, event):
        if self.btn_copy is not None:
            self.btn_copy.move(self.width() - self.btn_copy.width() - 6, 6)
        super().resizeEvent(event)

    def enterEvent(self, event):
        if self.btn_copy is not None:
            self.btn_copy.show()
            self.btn_copy.raise_()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.btn_copy is not None:
            self.btn_copy.hide()
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        if self.kind == "you":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        accent = theme.ERROR if self.kind == "error" else theme.ACCENT
        hover = self.underMouse()
        bg = theme.qcolor("#2A0A14", 0.55) if self.kind == "error" else theme.qcolor(
            theme.CARD_HI if hover else theme.CARD, 0.85)
        p.setPen(QPen(theme.qcolor(accent, 0.30 if self.kind == "error" else (0.28 if hover else 0.14)), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 8, 8)
        # the accent bar on the left edge
        bar = QRectF(r.left() + 1, r.top() + 8, 2.5, max(4.0, r.height() - 16))
        g = QLinearGradient(bar.topLeft(), bar.bottomLeft())
        g.setColorAt(0.0, theme.qcolor(accent, 1.0))
        g.setColorAt(1.0, theme.qcolor(accent, 0.25))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(bar, 1.2, 1.2)
        p.end()


class _EdgeFade(QWidget):
    """A soft fade over the top/bottom edge of the results when there is more to scroll."""

    def __init__(self, parent, top: bool):
        super().__init__(parent)
        self.top = top
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedHeight(18)
        self.hide()

    def paintEvent(self, _event):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        solid, clear = theme.qcolor(theme.PANEL, 0.96), theme.qcolor(theme.PANEL, 0.0)
        g.setColorAt(0.0, solid if self.top else clear)
        g.setColorAt(1.0, clear if self.top else solid)
        p.fillRect(self.rect(), g)
        p.end()


# ── keycaps for the footer ───────────────────────────────────────────────────
def _keycap(text: str, parent=None) -> QLabel:
    cap = QLabel(text, parent)
    cap.setObjectName("keycap")
    cap.setAlignment(Qt.AlignCenter)
    cap.setFixedHeight(18)                           # never stretch with the footer row
    cap.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return cap


class _StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.color = QColor(theme.FAINT)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qcolor(self.color.name(), 0.25))
        p.drawEllipse(QPointF(5, 5), 5, 5)
        p.setBrush(self.color)
        p.drawEllipse(QPointF(5, 5), 2.6, 2.6)
        p.end()


def _stylesheet() -> str:
    return theme.app_stylesheet() + f"""
QLineEdit#barInput {{
    background: transparent; border: none; padding: 4px 2px; font-size: 18px; color: {theme.TEXT};
    selection-background-color: {theme.ACCENT_DIM};
}}
QLineEdit#barInput:focus {{ background: transparent; border: none; }}
QPushButton#barChip {{
    background: rgba(11, 22, 34, 200); border: 1px solid {theme.BORDER_SOFT}; border-radius: 13px;
    padding: 4px 10px 4px 8px; color: {theme.TEXT_2}; font-size: 12px; text-align: left;
}}
QPushButton#barChip:hover {{ border-color: {theme.ACCENT_DIM}; color: {theme.ACCENT}; background: rgba(0, 229, 255, 18); }}
QPushButton#barChip:pressed {{ background: rgba(0, 229, 255, 34); }}
QLabel#resultYou {{ color: {theme.MUTED}; font-size: 13px; }}
QLabel#resultText {{ color: {theme.TEXT}; font-size: 13px; }}
QLabel#resultError {{ color: #FFC2CD; font-size: 13px; }}
QLabel#keycap {{
    color: {theme.TEXT_2}; background: {theme.INPUT}; border: 1px solid {theme.BORDER};
    border-bottom: 2px solid {theme.BORDER}; border-radius: 4px; padding: 0px 5px;
    font-family: {theme.MONO}; font-size: 10px; min-width: 12px;
}}
QLabel#barHint {{ color: {theme.FAINT}; font-size: 11px; }}
QLabel#barStatus {{ font-family: {theme.HUD_FONT}; font-size: 10px; letter-spacing: 2px; font-weight: 600; }}
QFrame#barRule {{ background: {theme.BORDER_SOFT}; max-height: 1px; min-height: 1px; border: none; }}
"""


class CommandBar(QWidget):
    submitted = Signal(str)           # the user pressed Enter
    mic_toggled = Signal(bool)        # 🎤: live voice on/off (the dashboard owns voice)
    open_dashboard = Signal()

    WIDTH = 700

    def __init__(self, hotkey_label: str = ""):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("commandBar")
        self.setWindowTitle("JARVIS")
        self.setStyleSheet(_stylesheet())
        self.history: List[str] = []
        self._history_pos: Optional[int] = None
        self._pending = 0
        self._state = "idle"
        self._mic = False
        self._glow_cache = None
        self._anim = None
        self._build(hotkey_label)
        self.setFixedWidth(self.WIDTH + 2 * GLOW)
        self._apply_state()

    # ── layout ───────────────────────────────────────────────────────────────
    def _build(self, hotkey_label: str):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(GLOW, GLOW, GLOW, GLOW)
        self.card = _Card(self)
        outer.addWidget(self.card)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(16, 14, 14, 10)
        v.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.orb = _BarOrb(36, self.card)
        self.orb.setToolTip("JARVIS")
        self.logo = self.orb                         # older name
        row.addWidget(self.orb)
        row.addSpacing(4)
        self.input = QLineEdit(self.card)
        self.input.setObjectName("barInput")
        self.input.setPlaceholderText("Ask JARVIS or tell it what to do…")
        self.input.returnPressed.connect(self._submit)
        self.input.installEventFilter(self)
        row.addWidget(self.input, 1)
        self.btn_mic = IconButton("mic", tooltip="Live voice — talk instead of typing", size=34, icon_size=18,
                                  checkable=True, parent=self.card, accent=theme.STATE_COLORS["listening"])
        self.btn_mic.clicked.connect(self._mic_clicked)
        row.addWidget(self.btn_mic)
        self.btn_expand = IconButton("expand", tooltip="Open the JARVIS dashboard", size=34, icon_size=16,
                                     parent=self.card)
        self.btn_expand.clicked.connect(self._open_dashboard)
        row.addWidget(self.btn_expand)
        v.addLayout(row)

        self.chips = QWidget(self.card)
        chips = QHBoxLayout(self.chips)
        chips.setContentsMargins(46, 0, 0, 2)
        chips.setSpacing(5)
        for (label, command), icon_name in zip(SUGGESTIONS, CHIP_ICONS + ["sparkle"] * len(SUGGESTIONS)):
            chip = QPushButton(label, self.chips)
            chip.setObjectName("barChip")
            chip.setIcon(theme.icon(icon_name, 12, color=theme.ACCENT_DIM))
            chip.setIconSize(QSize(12, 12))
            chip.setToolTip(command)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, t=command: self.run(t))
            chips.addWidget(chip)
        chips.addStretch()
        v.addWidget(self.chips)

        self.scroll = QScrollArea(self.card)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.results = QWidget()
        self.results_layout = QVBoxLayout(self.results)
        self.results_layout.setContentsMargins(0, 0, 6, 0)
        self.results_layout.setSpacing(6)
        self.results_layout.addStretch()
        self.scroll.setWidget(self.results)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.scroll.hide()
        v.addWidget(self.scroll)
        self._fade_top = _EdgeFade(self.scroll, top=True)
        self._fade_bottom = _EdgeFade(self.scroll, top=False)
        bar = self.scroll.verticalScrollBar()
        bar.valueChanged.connect(self._update_fades)
        bar.rangeChanged.connect(self._update_fades)

        rule = QFrame(self.card)
        rule.setObjectName("barRule")
        v.addWidget(rule)

        foot = QHBoxLayout()
        foot.setSpacing(5)
        foot.setContentsMargins(2, 0, 2, 0)
        self.hint = QWidget(self.card)
        hints = QHBoxLayout(self.hint)
        hints.setContentsMargins(0, 0, 0, 0)
        hints.setSpacing(5)
        items = [("Enter", "run"), ("↑", "history"), ("Esc", "close")]
        for i, (key, what) in enumerate(items):
            if i:
                sep = QLabel("·", self.hint)
                sep.setObjectName("barHint")
                hints.addWidget(sep)
            hints.addWidget(_keycap(key, self.hint))
            word = QLabel(what, self.hint)
            word.setObjectName("barHint")
            hints.addWidget(word)
        if hotkey_label:
            sep = QLabel("·", self.hint)
            sep.setObjectName("barHint")
            hints.addWidget(sep)
            hints.addWidget(_keycap(hotkey_label, self.hint))
            word = QLabel("anywhere", self.hint)
            word.setObjectName("barHint")
            hints.addWidget(word)
        self.hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        foot.addWidget(self.hint, 0, Qt.AlignVCenter)
        foot.addStretch()
        self.status_dot = _StatusDot(self.card)
        foot.addWidget(self.status_dot)
        self.status = QLabel("", self.card)
        self.status.setObjectName("barStatus")
        foot.addWidget(self.status)
        v.addLayout(foot)

    def _update_fades(self, *_):
        bar = self.scroll.verticalScrollBar()
        w = self.scroll.viewport().width()
        self._fade_top.setGeometry(0, 0, w, self._fade_top.height())
        self._fade_bottom.setGeometry(0, self.scroll.height() - self._fade_bottom.height(), w,
                                      self._fade_bottom.height())
        self._fade_top.setVisible(bar.value() > bar.minimum())
        self._fade_bottom.setVisible(bar.value() < bar.maximum())
        self._fade_top.raise_()
        self._fade_bottom.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_fades()

    # ── glow (painted on the translucent window around the card) ────────────
    def paintEvent(self, _event):
        size = self.size()
        key = (size.width(), size.height(), self.orb_color().name())
        if self._glow_cache is None or self._glow_cache[0] != key:
            self._glow_cache = (key, self._render_glow(size, self.orb_color()))
        p = QPainter(self)
        p.drawPixmap(0, 0, self._glow_cache[1])
        p.end()

    def _render_glow(self, size, col: QColor) -> QPixmap:
        pix = QPixmap(size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(GLOW, GLOW, size.width() - 2 * GLOW, size.height() - 2 * GLOW)
        p.setBrush(Qt.NoBrush)
        steps = GLOW
        for i in range(steps, 0, -1):
            k = 1 - i / steps
            # dark drop shadow (offset down) + a whisper of the state colour
            p.setPen(QPen(QColor(0, 0, 0, int(70 * k * k)), 2))
            p.drawRoundedRect(card.adjusted(-i + 2, -i + 6, i - 2, i + 2), RADIUS + i, RADIUS + i)
            p.setPen(QPen(theme.qcolor(col.name(), 0.07 * k ** 3), 2))
            p.drawRoundedRect(card.adjusted(-i, -i, i, i), RADIUS + i, RADIUS + i)
        p.end()
        return pix

    def orb_color(self) -> QColor:
        return QColor(theme.STATE_COLORS.get(self.display_state(), theme.ACCENT))

    # ── state ────────────────────────────────────────────────────────────────
    @property
    def state(self) -> str:
        return self._state

    def display_state(self) -> str:
        """What the orb shows: the live-voice mic turns an idle bar into "listening"."""
        if self._state == "idle" and self._mic:
            return "listening"
        return self._state

    def set_state(self, state: str):
        """Reflect JARVIS's state (a ``theme.STATE_COLORS`` key) in the orb, scan line and status."""
        self._state = state if state in theme.STATE_COLORS else "idle"
        self._apply_state()

    def _apply_state(self):
        shown = self.display_state()
        col = QColor(theme.STATE_COLORS.get(shown, theme.ACCENT))
        self.orb.set_state(shown)
        self.orb.busy = self._state in ("thinking", "acting")
        self.orb.setToolTip(f"JARVIS — {theme.STATE_LABELS.get(shown, shown)}")
        self.card.color = col
        self.card.set_scanning(self._state in ("thinking", "acting"))
        self.status.setText(STATUS_TEXT.get(shown, ""))
        self.status.setStyleSheet(f"color: {col.name()};")
        self.status_dot.color = col
        self.status_dot.setVisible(bool(self.status.text()))
        self.status_dot.update()
        self.update()

    def set_busy(self, busy: bool):
        self.set_state("thinking" if busy else "idle")

    def set_mic(self, on: bool):
        self._mic = bool(on)
        self.btn_mic.setChecked(self._mic)
        self._apply_state()

    def _mic_clicked(self, on):
        self._mic = bool(on)
        self._apply_state()
        self.mic_toggled.emit(bool(on))

    # ── showing ──────────────────────────────────────────────────────────────
    def summon(self):
        """Show centred on the screen with the cursor, focused and ready to type."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)
        self.adjustSize()
        x = area.x() + (area.width() - self.width()) // 2
        y = area.y() + int(area.height() * 0.18)
        if self._anim is not None:
            self._anim.stop()
        self.move(x, y - 14)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self._bring_to_front()
        self.input.setFocus()
        self.input.selectAll()
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"windowOpacity", group)
        fade.setDuration(170)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(220)
        slide.setStartValue(QPoint(x, y - 14))
        slide.setEndValue(QPoint(x, y))
        slide.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(fade)
        group.addAnimation(slide)
        group.start()
        self._anim = group

    def _bring_to_front(self):
        """Windows refuses focus to a background app unless the foreground lock is released."""
        try:
            import sys
            if sys.platform == "win32":
                from skills.windows_control import WindowsControl
                WindowsControl()._force_foreground(int(self.winId()))
        except Exception:
            pass

    def toggle(self):
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.summon()

    def _open_dashboard(self):
        self.hide()
        self.open_dashboard.emit()

    # ── input ────────────────────────────────────────────────────────────────
    def run(self, text: str):
        self.input.setText(text)
        self._submit()

    def _submit(self):
        text = self.input.text().strip()
        if not text:
            return
        if not self.history or self.history[-1] != text:
            self.history.append(text)
        self._history_pos = None
        self.input.clear()
        self._add_card(text, "you")
        self._pending += 1
        self.set_busy(True)
        self.submitted.emit(text)

    def show_result(self, text: str, error: bool = False):
        """A reply for something typed here (the dashboard routes it back)."""
        self._pending = max(0, self._pending - 1)
        self._add_card(text or "Done.", "error" if error else "reply")
        if not self._pending:
            self.set_busy(False)

    def owns_reply(self) -> bool:
        return self._pending > 0

    def _add_card(self, text: str, kind: str):
        card = ResultCard(("› " + text) if kind == "you" else text, kind, self.results)
        self.results_layout.insertWidget(self.results_layout.count() - 1, card)
        cards = [self.results_layout.itemAt(i).widget() for i in range(self.results_layout.count() - 1)]
        for old in cards[:-MAX_RESULTS * 2]:
            self.results_layout.removeWidget(old)
            old.deleteLater()
        self.chips.hide()
        self.scroll.show()
        self._fit_results()
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def _fit_results(self):
        # wrapped labels: measure at the real width, not the (much narrower) default sizeHint
        width = self.WIDTH - 30 - 6
        spacing = self.results_layout.spacing()
        content = 0
        for i in range(self.results_layout.count() - 1):
            w = self.results_layout.itemAt(i).widget()
            h = w.heightForWidth(width) if w.hasHeightForWidth() else -1
            content += (h if h > 0 else w.sizeHint().height()) + spacing
        self.scroll.setFixedHeight(min(RESULTS_MAX_HEIGHT, max(40, content)))
        self.adjustSize()

    def clear_results(self):
        while self.results_layout.count() > 1:
            w = self.results_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.scroll.hide()
        self.chips.show()
        self.adjustSize()

    def eventFilter(self, obj, event):
        if obj is self.input and isinstance(event, QKeyEvent) and event.type() == QKeyEvent.KeyPress:
            if event.key() == Qt.Key_Up and self.history:
                self._history_pos = (len(self.history) if self._history_pos is None else self._history_pos) - 1
                self._history_pos = max(0, self._history_pos)
                self.input.setText(self.history[self._history_pos])
                return True
            if event.key() == Qt.Key_Down and self._history_pos is not None:
                self._history_pos += 1
                if self._history_pos >= len(self.history):
                    self._history_pos = None
                    self.input.clear()
                else:
                    self.input.setText(self.history[self._history_pos])
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        if event.key() == Qt.Key_L and event.modifiers() & Qt.ControlModifier:
            self.clear_results()
            return
        super().keyPressEvent(event)
