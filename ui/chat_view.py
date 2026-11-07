"""The dashboard conversation: a scrolling list of message widgets.

    ChatView           the whole thing (hero + messages + typing indicator + "↓ Latest" pill).
                       Stands in for the old QTextEdit transcript: ``toPlainText()`` / ``clear()``.
    JarvisMessage      left, Markdown (fenced code on a dark plate), orb avatar, copy on hover
    UserMessage        right-aligned bubble tinted with theme.USER
    SystemMessage      a subtle centred caption line
    ErrorMessage       red-bordered card with an icon
    ActionMessage      compact "⚡ open chrome   L2   DONE 1.2s" row (live voice / buddy)
    TypingIndicator    three pulsing dots + a scanning line while JARVIS works
    HeroView           the empty-conversation greeting with a big orb and suggestion cards

Every row lays its children out by hand and reports ``heightForWidth`` so text wraps
at any width (QScrollArea honours height-for-width of its widget's layout).
"""
from __future__ import annotations

import math
import re
import time
from datetime import datetime

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPalette,
                           QPen, QTextCharFormat, QTextCursor, QTextDocument, QTextOption)
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QTextBrowser,
                               QVBoxLayout, QWidget)

from ui import theme
from ui.dash_widgets import SuggestionCard
from ui.widgets import ArcOrb, IconButton

COLUMN_MAX = 860          # readable line length for the conversation column
SIDE = 22                 # gutter at each side of the column
AVATAR = 30
GAP = 12                  # avatar → card


def _mono_families():
    return ["Cascadia Code", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"]


def _column(w: int):
    cw = max(120, min(w - 2 * SIDE, COLUMN_MAX))
    return int((w - cw) / 2), int(cw)


# ── markdown helpers ─────────────────────────────────────────────────────────
_FENCE = re.compile(r"```[ \t]*([\w+#.-]*)[^\n]*\n(.*?)(?:\n?```[ \t]*(?=\n|$)|\Z)", re.S)


def split_markdown(text: str):
    """[('md', text) | ('code', lang, code), ...] — fenced code blocks become their own segments."""
    segs, pos = [], 0
    for m in _FENCE.finditer(text):
        before = text[pos:m.start()]
        if before.strip():
            segs.append(("md", before.strip("\n")))
        segs.append(("code", m.group(1) or "", m.group(2).rstrip("\n")))
        pos = m.end()
    rest = text[pos:]
    if rest.strip() or not segs:
        segs.append(("md", rest.strip("\n")))
    return segs


def _hard_breaks(md: str) -> str:
    """JARVIS replies are often plain text: keep single newlines as line breaks."""
    lines = md.split("\n")
    out = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line.strip() and nxt.strip() and not line.lstrip().startswith("|") and not line.endswith("  "):
            line += "  "
        out.append(line)
    return "\n".join(out)


def _style_document(doc: QTextDocument):
    """Inline code on a dark chip, links in cyan."""
    ranges = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                fmt = frag.charFormat()
                if fmt.isAnchor():
                    ranges.append((frag.position(), frag.length(), "link"))
                elif fmt.fontFixedPitch():
                    ranges.append((frag.position(), frag.length(), "code"))
            it += 1
        block = block.next()
    for pos, length, kind in ranges:
        cur = QTextCursor(doc)
        cur.setPosition(pos)
        cur.setPosition(pos + length, QTextCursor.KeepAnchor)
        f = QTextCharFormat()
        if kind == "link":
            f.setForeground(QColor(theme.ACCENT))
            f.setFontUnderline(True)
        else:
            f.setForeground(QColor("#8FF3FF"))
            f.setBackground(QColor("#0E2536"))
            f.setFontFamilies(_mono_families())
        cur.mergeCharFormat(f)


class AutoText(QTextBrowser):
    """Read-only rich text whose height follows its width (no scroll bars).

    A private clone of the document does the measuring, so asking for the height at some
    other width never disturbs what is on screen.
    """

    def __init__(self, parent=None, mono: bool = False, color: str = None, point_size: float = 10.5):
        super().__init__(parent)
        self.setObjectName("autoText")
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(True)
        self.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setViewportMargins(0, 0, 0, 0)
        self.setContentsMargins(0, 0, 0, 0)
        self.viewport().setAutoFillBackground(False)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        color = color or theme.TEXT
        font = theme.text_font(point_size)
        if mono:
            font.setFamilies(_mono_families())
            font.setPointSizeF(point_size)
            font.setStyleHint(font.StyleHint.Monospace)
        self.setFont(font)
        pal = self.palette()
        pal.setColor(QPalette.Text, QColor(color))
        pal.setColor(QPalette.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.Link, QColor(theme.ACCENT))
        pal.setColor(QPalette.Highlight, QColor(theme.ACCENT_DIM))
        pal.setColor(QPalette.HighlightedText, QColor("#001018"))
        self.setPalette(pal)
        self.setStyleSheet(f"QTextBrowser#autoText {{ background: transparent; border: none; padding: 0; margin: 0;"
                           f" color: {color}; selection-background-color: {theme.ACCENT_DIM}; }}")
        self.document().setDocumentMargin(0)
        self._measure = None
        self._raw = ""

    def wheelEvent(self, e):           # never scrolls itself: let the conversation scroll
        e.ignore()

    def set_content(self, text: str, markdown: bool = True):
        self._raw = text
        if markdown:
            self.setMarkdown(_hard_breaks(text))
            _style_document(self.document())
        else:
            self.setPlainText(text)
        self.document().setDocumentMargin(0)
        self._measure = self.document().clone(self)
        self._measure.setDocumentMargin(0)
        self._measure.setDefaultFont(self.font())
        opt = self._measure.defaultTextOption()
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self._measure.setDefaultTextOption(opt)

    def raw(self) -> str:
        return self._raw

    def _doc(self):
        return self._measure if self._measure is not None else self.document()

    def text_height(self, width: int) -> int:
        doc = self._doc()
        doc.setTextWidth(max(10, width))
        return int(math.ceil(doc.size().height())) + 1

    def ideal_width(self, max_width: int) -> int:
        doc = self._doc()
        doc.setTextWidth(max(10, max_width))
        return min(max_width, int(math.ceil(doc.idealWidth())) + 2)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self.text_height(w)

    def sizeHint(self):
        w = self.width() if self.width() > 20 else 400
        return QSize(w, self.text_height(w))

    def minimumSizeHint(self):
        return QSize(40, 16)


class CodeBlock(QWidget):
    """A fenced code block on a darker plate, with its language and a copy button."""
    HEADER = 28
    PAD = 12

    def __init__(self, lang: str, code: str, parent=None):
        super().__init__(parent)
        self.lang = (lang or "code").upper()
        self.code = code
        self.text = AutoText(self, mono=True, color="#BFEFFF", point_size=9.5)
        self.text.set_content(code, markdown=False)
        self.copy_btn = IconButton("copy", "Copy code", size=24, icon_size=13, parent=self)
        self.copy_btn.clicked.connect(self._copy)

    def _copy(self):
        QGuiApplication.clipboard().setText(self.code)
        self.copy_btn.set_icon("check")
        QTimer.singleShot(1200, lambda: self.copy_btn.set_icon("copy"))

    def ideal_width(self, max_width):
        return max_width

    def text_height(self, width):
        return self.HEADER + self.PAD + self.text.text_height(width - 2 * self.PAD) + self.PAD - 4

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self.text_height(w)

    def resizeEvent(self, e):
        w = self.width()
        self.text.setGeometry(self.PAD, self.HEADER + self.PAD - 2, w - 2 * self.PAD, self.text.text_height(w - 2 * self.PAD))
        self.copy_btn.move(w - 30, 2)
        super().resizeEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.setBrush(QColor("#03070B"))
        p.drawRoundedRect(r, 9, 9)
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.drawLine(QPointF(r.left() + 1, self.HEADER), QPointF(r.right() - 1, self.HEADER))
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qcolor(theme.ACCENT, 0.8))
        p.drawEllipse(QPointF(r.left() + 14, self.HEADER / 2), 2.5, 2.5)
        p.setFont(theme.hud_font(7.5))
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(r.left() + 24, 0, 200, self.HEADER), Qt.AlignVCenter | Qt.AlignLeft, self.lang)
        p.end()


def _avatar_pixmap(size=AVATAR):
    from PySide6.QtGui import QPixmap
    dpr = 2.0
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.fill(Qt.transparent)
    pix.setDevicePixelRatio(dpr)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(1, 1, size - 2, size - 2)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor("#0C2232"))
    g.setColorAt(1, QColor(theme.PANEL))
    p.setBrush(g)
    p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.55), 1.2))
    p.drawEllipse(r)
    p.translate(size * 0.14, size * 0.14)
    theme.draw_logo(p, int(size * 0.72), background=False)
    p.end()
    return pix


_AVATAR_CACHE = {}


def avatar_pixmap(size=AVATAR):
    if size not in _AVATAR_CACHE:
        _AVATAR_CACHE[size] = _avatar_pixmap(size)
    return _AVATAR_CACHE[size]


# ── rows ─────────────────────────────────────────────────────────────────────
class _Row(QWidget):
    """Base row: manual layout through ``_layout(width, apply)``; cached height-for-width."""
    kind = "row"
    TOP, BOTTOM = 6, 6

    def __init__(self, speaker: str, text: str, parent=None):
        super().__init__(parent)
        self.speaker = speaker
        self.raw_text = str(text)
        self.stamp = datetime.now().strftime("%H:%M:%S")
        self._hfw = {}
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def plain_text(self) -> str:
        return f"{self.speaker.upper()}  {self.stamp}\n{self.raw_text}"

    def _layout(self, w: int, apply: bool) -> int:          # pragma: no cover - overridden
        return 40

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        if w not in self._hfw:
            if len(self._hfw) > 16:
                self._hfw.clear()
            self._hfw[w] = self._layout(w, False)
        return self._hfw[w]

    def sizeHint(self):
        w = self.width() if self.width() > 50 else 700
        return QSize(w, self.heightForWidth(w))

    def minimumSizeHint(self):
        return QSize(160, 20)

    def invalidate(self):
        self._hfw.clear()
        self.updateGeometry()
        self._layout(self.width(), True)
        self.update()

    def resizeEvent(self, e):
        self._layout(self.width(), True)
        super().resizeEvent(e)


class _CardRow(_Row):
    """Shared by JARVIS and error messages: a card at the right of the avatar lane."""
    PAD_X, PAD_Y, HEADER = 16, 12, 16

    def __init__(self, speaker, text, parent=None, markdown=True, color=None):
        super().__init__(speaker, text, parent)
        self.segments = []
        if markdown:
            for seg in split_markdown(self.raw_text):
                if seg[0] == "code":
                    self.segments.append(CodeBlock(seg[1], seg[2], self))
                else:
                    t = AutoText(self, color=color)
                    t.set_content(seg[1], markdown=True)
                    self.segments.append(t)
        else:
            t = AutoText(self, color=color)
            t.set_content(self.raw_text, markdown=False)
            self.segments.append(t)
        self._card = QRectF()
        self.copy_btn = IconButton("copy", "Copy message", size=24, icon_size=13, parent=self)
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.hide()

    def _copy(self):
        QGuiApplication.clipboard().setText(self.raw_text)
        self.copy_btn.set_icon("check")
        QTimer.singleShot(1200, lambda: self.copy_btn.set_icon("copy"))

    def enterEvent(self, e):
        self.copy_btn.show()
        self.copy_btn.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.copy_btn.hide()
        super().leaveEvent(e)

    def _layout(self, w, apply):
        x0, cw = _column(w)
        card_x = x0 + AVATAR + GAP
        max_card = cw - AVATAR - GAP
        inner_max = max(60, max_card - 2 * self.PAD_X)
        ideal = max([s.ideal_width(inner_max) for s in self.segments] + [150])
        card_w = min(max_card, ideal + 2 * self.PAD_X)
        inner = card_w - 2 * self.PAD_X
        y = self.TOP + self.PAD_Y + self.HEADER + 6
        for i, seg in enumerate(self.segments):
            h = seg.text_height(inner)
            if apply:
                seg.setGeometry(int(card_x + self.PAD_X), int(y), int(inner), int(h))
            y += h + (10 if i < len(self.segments) - 1 else 0)
        card_h = y + self.PAD_Y - self.TOP
        if apply:
            self._card = QRectF(card_x, self.TOP, card_w, card_h)
            self.copy_btn.move(int(card_x + card_w - 30), int(self.TOP + 6))
        return int(self.TOP + card_h + self.BOTTOM)


class JarvisMessage(_CardRow):
    kind = "jarvis"

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x0, _ = _column(self.width())
        p.drawPixmap(int(x0), int(self.TOP + 2), avatar_pixmap())
        r = self._card.adjusted(0.5, 0.5, -0.5, -0.5)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, theme.qcolor(theme.CARD, 0.92))
        g.setColorAt(1.0, theme.qcolor(theme.PANEL, 0.88))
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, g)
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.drawPath(path)
        # cyan accent on the top-left edge
        p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.75), 1.4))
        p.drawLine(QPointF(r.left() + 14, r.top() + 0.5), QPointF(r.left() + 44, r.top() + 0.5))
        p.setFont(theme.hud_font(7.8))
        p.setPen(QColor(theme.ACCENT))
        name = self.speaker.upper() if self.speaker.upper() != "JARVIS" else "J.A.R.V.I.S"
        fm = QFontMetrics(p.font())
        p.drawText(QRectF(r.left() + self.PAD_X, r.top() + self.PAD_Y - 2, 200, self.HEADER), Qt.AlignVCenter, name)
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(r.left() + self.PAD_X + fm.horizontalAdvance(name) + 10, r.top() + self.PAD_Y - 2, 120,
                          self.HEADER), Qt.AlignVCenter, self.stamp[:5])
        p.end()


class ErrorMessage(_CardRow):
    kind = "error"

    def __init__(self, speaker, text, parent=None):
        super().__init__(speaker, text, parent, markdown=False, color="#FFC2CD")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x0, _ = _column(self.width())
        # warning glyph in the avatar lane
        c = QPointF(x0 + AVATAR / 2, self.TOP + 2 + AVATAR / 2)
        p.setPen(QPen(theme.qcolor(theme.ERROR, 0.8), 1.3))
        p.setBrush(theme.qcolor(theme.ERROR, 0.12))
        p.drawEllipse(c, AVATAR / 2 - 1, AVATAR / 2 - 1)
        p.setPen(QPen(QColor(theme.ERROR), 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x(), c.y() - 7), QPointF(c.x(), c.y() + 2))
        p.drawPoint(QPointF(c.x(), c.y() + 6.5))
        r = self._card.adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, theme.qcolor("#2A0A14", 0.85))
        p.setPen(QPen(theme.qcolor(theme.ERROR, 0.65), 1))
        p.drawPath(path)
        p.setFont(theme.hud_font(7.8))
        p.setPen(QColor(theme.ERROR))
        label = "ERROR" if self.speaker.upper() in ("ERROR", "JARVIS") else self.speaker.upper()
        fm = QFontMetrics(p.font())
        p.drawText(QRectF(r.left() + self.PAD_X, r.top() + self.PAD_Y - 2, 200, self.HEADER), Qt.AlignVCenter, label)
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(r.left() + self.PAD_X + fm.horizontalAdvance(label) + 10, r.top() + self.PAD_Y - 2, 120,
                          self.HEADER), Qt.AlignVCenter, self.stamp[:5])
        p.end()


class UserMessage(_Row):
    kind = "user"
    PAD_X, PAD_Y = 16, 10

    def __init__(self, speaker, text, parent=None):
        super().__init__(speaker, text, parent)
        self.body = AutoText(self, color=theme.TEXT)
        self.body.set_content(self.raw_text, markdown=False)
        self._bubble = QRectF()

    def _layout(self, w, apply):
        x0, cw = _column(w)
        max_w = max(140, int(cw * 0.74))
        inner_max = max_w - 2 * self.PAD_X
        inner = max(24, self.body.ideal_width(inner_max))
        bw = inner + 2 * self.PAD_X
        h = self.body.text_height(inner)
        bx = x0 + cw - bw
        bh = h + 2 * self.PAD_Y
        if apply:
            self._bubble = QRectF(bx, self.TOP, bw, bh)
            self.body.setGeometry(int(bx + self.PAD_X), int(self.TOP + self.PAD_Y), int(inner), int(h))
        return int(self.TOP + bh + 18 + self.BOTTOM - 4)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._bubble.adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        rad = 14.0
        path.addRoundedRect(r, rad, rad)
        corner = QPainterPath()                      # squarer bottom-right corner: "sent" tail
        corner.addRect(QRectF(r.right() - rad, r.bottom() - rad, rad, rad))
        path = path.united(corner)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, theme.qcolor(theme.USER, 0.22))
        g.setColorAt(1.0, theme.qcolor(theme.USER, 0.12))
        p.fillPath(path, g)
        p.setPen(QPen(theme.qcolor(theme.USER, 0.45), 1))
        p.drawPath(path)
        p.setFont(theme.hud_font(7.5))
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(r.left() - 100, r.bottom() + 3, r.width() + 100, 14), Qt.AlignRight | Qt.AlignVCenter,
                   f"YOU · {self.stamp[:5]}")
        p.end()


class SystemMessage(_Row):
    kind = "system"
    TOP, BOTTOM = 8, 8

    def _font(self):
        return theme.text_font(9)

    def _text_rect_h(self, width):
        fm = QFontMetrics(self._font())
        return fm.boundingRect(0, 0, int(width), 10000, Qt.TextWordWrap | Qt.AlignHCenter, self.raw_text).height()

    def _layout(self, w, apply):
        _, cw = _column(w)
        tw = min(cw - 120, 620)
        return int(self.TOP + self._text_rect_h(tw) + self.BOTTOM)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x0, cw = _column(self.width())
        tw = min(cw - 120, 620)
        fm = QFontMetrics(self._font())
        br = fm.boundingRect(0, 0, int(tw), 10000, Qt.TextWordWrap | Qt.AlignHCenter, self.raw_text)
        tx = x0 + (cw - tw) / 2
        rect = QRectF(tx, self.TOP, tw, br.height())
        p.setFont(self._font())
        p.setPen(QColor(theme.MUTED))
        p.drawText(rect, Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop, self.raw_text)
        # hairlines either side of a one-line caption
        if br.height() <= fm.height() + 2:
            half = br.width() / 2 + 14
            cx = x0 + cw / 2
            y = self.TOP + fm.height() / 2 + 0.5
            for a, b in ((cx - half - 70, cx - half), (cx + half, cx + half + 70)):
                g = QLinearGradient(QPointF(a, y), QPointF(b, y))
                lo, hi = theme.qcolor(theme.BORDER, 0.0), theme.qcolor(theme.BORDER, 1.0)
                g.setColorAt(0.0, lo if a < cx else hi)
                g.setColorAt(1.0, hi if a < cx else lo)
                p.setPen(QPen(g, 1))
                p.drawLine(QPointF(a, y), QPointF(b, y))
        p.end()


class ActionMessage(_Row):
    """⚡ one step JARVIS is doing. ``set_status('running'|'done'|'failed'|'skipped', seconds)``."""
    kind = "action"
    TOP, BOTTOM = 3, 3
    H = 36
    _LANE = re.compile(r"\s*·\s*lane\s+(\d+)\s*$")

    def __init__(self, speaker, text, parent=None):
        super().__init__(speaker, text, parent)
        shown = self.raw_text.lstrip("▶").strip()
        m = self._LANE.search(shown)
        self.lane = int(m.group(1)) if m else None
        self.label = self._LANE.sub("", shown)
        self.status = "dispatched"
        self.seconds = None
        self._started = time.monotonic()
        self.setToolTip(shown)

    def set_status(self, status: str, seconds: float = None):
        self.status = status or self.status
        if seconds is None and status in ("done", "failed", "skipped", "stopped"):
            seconds = time.monotonic() - self._started
        if status == "running":
            self._started = time.monotonic()
        self.seconds = seconds
        self.update()

    def _layout(self, w, apply):
        return self.TOP + self.H + self.BOTTOM

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x0, cw = _column(self.width())
        r = QRectF(x0 + AVATAR + GAP, self.TOP, cw - AVATAR - GAP, self.H).adjusted(0.5, 0.5, -0.5, -0.5)
        col = {"done": theme.SUCCESS, "failed": theme.ERROR, "skipped": theme.MUTED, "stopped": theme.MUTED,
               "running": theme.ACCENT_2}.get(self.status, theme.ACCENT_2)
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        p.fillPath(path, theme.qcolor(theme.ACCENT_2, 0.05))
        p.setPen(QPen(theme.qcolor(theme.ACCENT_2, 0.25), 1))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qcolor(col, 0.9))
        p.drawRoundedRect(QRectF(r.left(), r.top() + 8, 2.5, r.height() - 16), 1, 1)
        p.drawPixmap(int(r.left() + 12), int(r.center().y() - 8), theme.icon_pixmap("bolt", 16, theme.ACCENT_2))
        # status chip (right)
        status = self.status.upper()
        if self.seconds is not None and self.status != "running":
            status += f"  {self.seconds:.1f}s"
        p.setFont(theme.hud_font(7.5))
        fm = QFontMetrics(p.font())
        sw = fm.horizontalAdvance(status) + 18
        chip = QRectF(r.right() - sw - 8, r.center().y() - 10, sw, 20)
        p.setPen(QPen(theme.qcolor(col, 0.5), 1))
        p.setBrush(theme.qcolor(col, 0.10))
        p.drawRoundedRect(chip, 10, 10)
        p.setPen(QColor(col))
        p.drawText(chip, Qt.AlignCenter, status)
        right = chip.left() - 8
        if self.lane:
            lane = f"L{self.lane}"
            lw = fm.horizontalAdvance(lane) + 12
            badge = QRectF(right - lw, r.center().y() - 9, lw, 18)
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.45), 1))
            p.setBrush(theme.qcolor(theme.ACCENT, 0.08))
            p.drawRoundedRect(badge, 4, 4)
            p.setPen(QColor(theme.ACCENT))
            p.drawText(badge, Qt.AlignCenter, lane)
            right = badge.left() - 8
        p.setFont(theme.text_font(10))
        fm = QFontMetrics(p.font())
        tx = r.left() + 36
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(tx, r.top(), right - tx, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self.label, Qt.ElideRight, int(max(10, right - tx))))
        p.end()


class TypingIndicator(QWidget):
    """Three pulsing dots and a scanning line: JARVIS is on it."""
    H = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = "Thinking"
        self.color = theme.STATE_COLORS["thinking"]
        self.setFixedHeight(self.H)
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self.hide()

    def set_label(self, text: str, color: str = None):
        self.label = text or "Thinking"
        if color:
            self.color = color
        self.update()

    def showEvent(self, e):
        self._t0 = time.monotonic()
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x0, cw = _column(self.width())
        t = time.monotonic() - self._t0
        p.drawPixmap(int(x0), 8, avatar_pixmap())
        pill = QRectF(x0 + AVATAR + GAP, 6, 0, 34)
        p.setFont(theme.hud_font(8))
        fm = QFontMetrics(p.font())
        text = self.label.upper()
        width = min(cw - AVATAR - GAP, 76 + fm.horizontalAdvance(text) + 18)
        pill.setWidth(width)
        path = QPainterPath()
        path.addRoundedRect(pill, 17, 17)
        p.fillPath(path, theme.qcolor(theme.CARD, 0.9))
        p.setPen(QPen(theme.qcolor(self.color, 0.35), 1))
        p.drawPath(path)
        # scanning highlight sweeping across the pill
        sweep = (t * 0.7) % 1.0
        sx = pill.left() + sweep * pill.width()
        g = QLinearGradient(QPointF(sx - 40, 0), QPointF(sx + 40, 0))
        g.setColorAt(0.0, theme.qcolor(self.color, 0.0))
        g.setColorAt(0.5, theme.qcolor(self.color, 0.16))
        g.setColorAt(1.0, theme.qcolor(self.color, 0.0))
        p.save()
        p.setClipPath(path)
        p.fillRect(pill, g)
        p.setPen(QPen(theme.qcolor(self.color, 0.7), 1))
        p.drawLine(QPointF(sx - 30, pill.bottom() - 1), QPointF(sx + 30, pill.bottom() - 1))
        p.restore()
        for i in range(3):
            phase = (t * 2.4 - i * 0.35)
            a = 0.25 + 0.75 * max(0.0, math.sin(phase * math.pi) if (phase % 2) < 1 else 0.0)
            lift = 3 * max(0.0, math.sin(phase * math.pi)) if (phase % 2) < 1 else 0
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qcolor(self.color, a))
            p.drawEllipse(QPointF(pill.left() + 22 + i * 13, pill.center().y() - lift), 3.6, 3.6)
        p.setPen(QColor(theme.TEXT_2))
        p.drawText(QRectF(pill.left() + 68, pill.top(), pill.width() - 76, pill.height()), Qt.AlignVCenter,
                   fm.elidedText(text, Qt.ElideRight, int(pill.width() - 80)))
        p.end()


# ── hero ─────────────────────────────────────────────────────────────────────
SUGGESTIONS = (
    ("globe", "Weather", "What's the weather today?", "what's the weather today"),
    ("eye", "Read my screen", "What's on my screen right now?", "what's on my screen"),
    ("pulse", "System status", "How is my PC doing?", "system status"),
    ("clock", "Reminders", "What are my reminders?", "list reminders"),
    ("bolt", "Automate", "Open Notepad and type hello", "open notepad and type hello"),
    ("sparkle", "Capabilities", "What can you do?", "help"),
)


def greeting_for(hour: int, name: str = None) -> str:
    part = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening"
    return f"Good {part}, {name}" if name else f"Good {part}"


class HeroView(QWidget):
    suggestion = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SIDE, 12, SIDE, 12)
        lay.setSpacing(0)
        lay.addStretch(1)
        self.orb = ArcOrb(180)
        lay.addWidget(self.orb, 0, Qt.AlignHCenter)
        lay.addSpacing(18)
        self.title = QLabel(greeting_for(datetime.now().hour))
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(f"color: {theme.TEXT}; background: transparent; font-family: {theme.HUD_FONT};"
                                 " font-size: 30px; font-weight: 600; letter-spacing: 1px;")
        lay.addWidget(self.title)
        lay.addSpacing(8)
        self.subtitle = QLabel("Bringing systems online…")
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet(f"color: {theme.MUTED}; font-size: 14px; background: transparent;")
        lay.addWidget(self.subtitle)
        lay.addSpacing(28)
        self.cards_box = QWidget()
        self.cards_box.setMaximumWidth(820)
        self.cards_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.grid = QGridLayout(self.cards_box)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.cards = []
        for icon_name, title, example, command in SUGGESTIONS:
            card = SuggestionCard(icon_name, title, example, command)
            card.activated.connect(self.suggestion.emit)
            self.cards.append(card)
        self._cols = 0
        self._reflow(3)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self.cards_box, 100)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def set_compact(self, compact: bool):
        """Short windows: a smaller orb (and only four cards in two columns) so everything fits."""
        self._compact = compact
        size = 104 if compact else 180
        if self.orb.width() != size:
            self.orb.setFixedSize(size, size)
        self._apply_card_visibility()

    def _apply_card_visibility(self):
        few = getattr(self, "_compact", False) and self._cols < 3
        for i, c in enumerate(self.cards):
            c.setVisible(not few or i < 4)

    def _reflow(self, cols):
        if cols == self._cols:
            return
        self._cols = cols
        for c in self.cards:
            self.grid.removeWidget(c)
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols)
        for c in range(3):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        self._apply_card_visibility()

    def resizeEvent(self, e):
        avail = self.width() - 2 * SIDE
        self._reflow(3 if avail >= 700 else 2)
        super().resizeEvent(e)

    def set_text(self, title: str = None, subtitle: str = None):
        if title is not None:
            self.title.setText(title)
        if subtitle is not None:
            self.subtitle.setText(subtitle)

    def set_enabled_cards(self, on: bool):
        for c in self.cards:
            c.setEnabled(on)


# ── the view ─────────────────────────────────────────────────────────────────
_KINDS = {"YOU": UserMessage, "SYSTEM": SystemMessage, "ERROR": ErrorMessage, "ACTION": ActionMessage}


class ChatView(QWidget):
    """The conversation. ``add_message(speaker, text)`` returns the row widget it created."""

    suggestion = Signal(str)
    hero_visibility_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records = []            # every message in order (rows and ambient ones) for toPlainText()
        self.rows = []
        self._stick = True
        self._unseen = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("chatContent")
        self._lay = QVBoxLayout(self.content)
        self._lay.setContentsMargins(0, 18, 0, 18)
        self._lay.setSpacing(4)
        self.hero = HeroView()
        self.hero.suggestion.connect(self.suggestion.emit)
        self._lay.addWidget(self.hero)
        self.typing = TypingIndicator()
        self._lay.addWidget(self.typing)
        self._lay.addStretch(1)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)
        self.jump_pill = QPushButton("↓  Latest", self)
        self.jump_pill.setObjectName("jumpPill")
        self.jump_pill.setCursor(Qt.PointingHandCursor)
        self.jump_pill.setStyleSheet(f"""
            QPushButton#jumpPill {{ background: {theme.CARD_HI}; color: {theme.ACCENT};
                border: 1px solid {theme.ACCENT_DIM}; border-radius: 15px; padding: 5px 16px;
                font-family: {theme.HUD_FONT}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
            QPushButton#jumpPill:hover {{ background: #12293B; border-color: {theme.ACCENT}; }}""")
        self.jump_pill.clicked.connect(self.scroll_to_bottom)
        self.jump_pill.hide()
        self.scroll.viewport().installEventFilter(self)
        bar = self.scroll.verticalScrollBar()
        bar.valueChanged.connect(self._on_scrolled)
        bar.rangeChanged.connect(self._on_range)
        self._fit_hero()

    # transcript compatibility ------------------------------------------------
    def toPlainText(self) -> str:
        return "\n\n".join(r["plain"] if isinstance(r, dict) else r.plain_text() for r in self._records)

    def clear(self):
        for row in self.rows:
            self._lay.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.rows = []
        self._records = []
        self._unseen = 0
        self.jump_pill.hide()
        self._stick = True
        self._update_hero()

    # messages ----------------------------------------------------------------
    def add_message(self, speaker: str, text: str, ambient: bool = False, kind: str = None):
        """Add one message. ``ambient`` ones are kept in the plain-text transcript but not drawn."""
        speaker = str(speaker)
        text = "" if text is None else str(text)
        if ambient:
            stamp = datetime.now().strftime("%H:%M:%S")
            self._records.append({"plain": f"{speaker.upper()}  {stamp}\n{text}"})
            return None
        cls = {"user": UserMessage, "system": SystemMessage, "error": ErrorMessage, "action": ActionMessage,
               "jarvis": JarvisMessage}.get(kind) or _KINDS.get(speaker.upper(), JarvisMessage)
        row = cls(speaker, text)
        self.rows.append(row)
        self._records.append(row)
        self._lay.insertWidget(self._lay.indexOf(self.typing), row)
        if cls is UserMessage:
            self._stick = True           # sending always brings you back to the latest
        elif not self._stick:
            self._unseen += 1
            self._place_pill()
            self.jump_pill.show()
            self.jump_pill.raise_()
        self._update_hero()
        if self._stick:
            QTimer.singleShot(0, self._follow)
        return row

    def message_count(self, include_system: bool = True) -> int:
        return sum(1 for r in self.rows if include_system or r.kind != "system")

    # typing indicator ----------------------------------------------------------
    def set_typing(self, on: bool, label: str = "Thinking", color: str = None):
        self.typing.set_label(label, color)
        if on == self.typing.isVisible():
            return
        self.typing.setVisible(on)
        if on and self._stick:
            QTimer.singleShot(0, self._follow)

    @property
    def typing_visible(self) -> bool:
        return not self.typing.isHidden()

    # hero ----------------------------------------------------------------------
    @property
    def hero_visible(self) -> bool:
        return not self.hero.isHidden()

    def _update_hero(self):
        show = not any(r.kind != "system" for r in self.rows)
        if show != (not self.hero.isHidden()):
            self.hero.setVisible(show)
            self.hero_visibility_changed.emit(show)
        self._fit_hero()

    def _fit_hero(self):
        if self.hero.isHidden():
            return
        vh = self.scroll.viewport().height()
        self.hero.set_compact(vh < 540)
        others = sum(r.sizeHint().height() + 4 for r in self.rows)
        self.hero.setMinimumHeight(max(0, vh - 36 - others))

    # scrolling -----------------------------------------------------------------
    def is_at_bottom(self) -> bool:
        bar = self.scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - 24

    def scroll_to_bottom(self):
        self._stick = True
        self._unseen = 0
        self.jump_pill.hide()
        self._follow()

    def _follow(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_scrolled(self, _value):
        self._stick = self.is_at_bottom()
        if self._stick:
            self._unseen = 0
            self.jump_pill.hide()

    def _on_range(self, _lo, hi):
        if self._stick:
            self.scroll.verticalScrollBar().setValue(hi)

    def _place_pill(self):
        self.jump_pill.adjustSize()
        pw, ph = self.jump_pill.width(), self.jump_pill.height()
        self.jump_pill.move(int((self.width() - pw) / 2), int(self.height() - ph - 14))

    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport() and event.type() == QEvent.Resize:
            self._fit_hero()
        return super().eventFilter(obj, event)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_pill()
