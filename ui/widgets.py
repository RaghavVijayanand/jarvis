"""Reusable HUD widgets shared by every JARVIS surface.

    ArcOrb        the animated arc-reactor orb: idle / listening / thinking / acting / speaking / error
    ToggleSwitch  an animated on/off switch (a checkable QAbstractButton — use it like a QCheckBox)
    IconButton    a flat icon button with a HUD hover glow; optional text; checkable
    HudPanel      a glass panel with corner brackets and an optional caption
    StatusPill    coloured dot + label ("● LISTENING")
    Caption       small uppercase letter-spaced label
    paint_grid    the faint HUD grid + vignette used behind the dashboard

Everything animates from one shared 60 fps clock that only runs while an
animated widget is visible, so an idle JARVIS in the tray costs nothing.
"""
from __future__ import annotations

import math
import time
import weakref
from typing import Optional

from PySide6.QtCore import (Property, QEasingCurve, QObject, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QConicalGradient, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QSizePolicy, QToolButton, QWidget

from ui import theme

STATES = ("idle", "listening", "thinking", "acting", "speaking", "error", "offline")


# ── shared animation clock ───────────────────────────────────────────────────
class _Clock(QObject):
    """One QTimer drives every animated widget; it stops when none is visible."""
    _instance = None

    def __init__(self):
        super().__init__()
        self._widgets = weakref.WeakSet()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = _Clock()
        return cls._instance

    def add(self, widget):
        self._widgets.add(widget)
        if not self._timer.isActive():
            self._timer.start()

    def remove(self, widget):
        self._widgets.discard(widget)
        if not self._widgets:
            self._timer.stop()

    def _tick(self):
        alive = False
        for w in list(self._widgets):
            try:
                if w.isVisible():
                    alive = True
                    w.update()
            except RuntimeError:            # C++ object already deleted
                self._widgets.discard(w)
        if not alive:
            self._timer.stop()

    @property
    def running(self) -> bool:
        return self._timer.isActive()


class _Animated:
    """Mixin: hooks the widget into the shared clock while it is shown."""

    def showEvent(self, event):
        _Clock.get().add(self)
        super().showEvent(event)

    def hideEvent(self, event):
        _Clock.get().remove(self)
        super().hideEvent(event)


# ── the orb ──────────────────────────────────────────────────────────────────
class ArcOrb(_Animated, QWidget):
    """JARVIS's face. ``set_state()`` switches the animation; ``set_level()`` feeds mic loudness (0..1)."""

    clicked = Signal()

    def __init__(self, size: int = 160, parent=None, interactive: bool = False):
        super().__init__(parent)
        self._state = "idle"
        self._since = time.monotonic()
        self._level = 0.0
        self._level_smooth = 0.0
        self._color = QColor(theme.STATE_COLORS["idle"])
        self._from_color = QColor(self._color)
        self._to_color = QColor(self._color)
        self.interactive = interactive
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground)
        if interactive:
            self.setCursor(Qt.PointingHandCursor)

    # API
    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str):
        state = state if state in STATES else "idle"
        if state == self._state:
            return
        self._from_color = self._current_color()
        self._to_color = QColor(theme.STATE_COLORS[state])
        self._state = state
        self._since = time.monotonic()
        self.update()

    def set_level(self, level: float):
        self._level = max(0.0, min(1.0, float(level)))

    def sizeHint(self):
        return QSize(self.width(), self.height())

    def mouseReleaseEvent(self, event):
        if self.interactive and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    # painting
    def _current_color(self) -> QColor:
        t = min(1.0, (time.monotonic() - self._since) / 0.35)
        a, b = self._from_color, self._to_color
        return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                      int(a.blue() + (b.blue() - a.blue()) * t))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = time.monotonic()
        t = now - self._since
        s = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        R = s / 2 - 2
        col = self._current_color()
        state = self._state
        self._level_smooth += (self._level - self._level_smooth) * 0.25
        speed = {"thinking": 3.0, "acting": 1.8, "listening": 1.2, "speaking": 1.0}.get(state, 0.35)
        if state == "offline":
            speed = 0.15
        base = now * speed

        # outer glow
        breathe = 0.5 + 0.5 * math.sin(now * (2.2 if state == "speaking" else 1.2))
        glow = QRadialGradient(c, R)
        g0 = QColor(col)
        g0.setAlphaF(0.20 + 0.10 * breathe + 0.25 * self._level_smooth)
        glow.setColorAt(0.0, g0)
        glow.setColorAt(0.55, theme.qcolor(col.name(), 0.06))
        glow.setColorAt(1.0, theme.qcolor(col.name(), 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, R, R)

        # outer tick ring (slow)
        p.save()
        p.translate(c)
        p.rotate(math.degrees(base * 0.25) % 360)
        for i in range(72):
            major = i % 6 == 0
            p.setPen(QPen(theme.qcolor(col.name(), 0.55 if major else 0.22), 1.2 if major else 0.8))
            r1 = R * (0.86 if major else 0.89)
            a = i * math.tau / 72
            p.drawLine(QPointF(r1 * math.cos(a), r1 * math.sin(a)), QPointF(R * 0.93 * math.cos(a), R * 0.93 * math.sin(a)))
        p.restore()

        # segmented ring (counter-rotating)
        seg_r = R * 0.74
        p.save()
        p.translate(c)
        p.rotate(-math.degrees(base * 0.6) % 360)
        pen = QPen(theme.qcolor(col.name(), 0.85), max(2.0, s * 0.03))
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        segments = 3 if state in ("thinking", "acting") else 6
        span = 360 / segments
        rect = QRectF(-seg_r, -seg_r, 2 * seg_r, 2 * seg_r)
        for i in range(segments):
            gap = 14 if segments == 6 else 40
            length = span - gap
            if state == "thinking":
                length *= 0.5 + 0.5 * abs(math.sin(now * 3 + i))
            p.drawArc(rect, int((i * span) * 16), int(length * 16))
        p.restore()

        # thin inner ring + state specific layer
        inner_r = R * 0.56
        p.setPen(QPen(theme.qcolor(col.name(), 0.35), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, inner_r, inner_r)

        if state == "listening":
            lvl = self._level_smooth
            for k in range(3):
                phase = (now * 1.3 + k / 3) % 1.0
                rr = inner_r * (0.9 + 0.55 * phase) * (1 + 0.25 * lvl)
                p.setPen(QPen(theme.qcolor(col.name(), (1 - phase) * (0.35 + 0.6 * lvl)), 1.6))
                p.drawEllipse(c, rr, rr)
        elif state == "speaking":
            path = QPainterPath()
            n = 96
            for i in range(n + 1):
                a = i * math.tau / n
                wob = 0.06 * math.sin(a * 6 + now * 7) * (0.6 + 0.4 * math.sin(now * 3))
                wob += 0.035 * math.sin(a * 11 - now * 9)
                rr = inner_r * (0.98 + wob)
                pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QPen(theme.qcolor(col.name(), 0.9), 1.6))
            p.drawPath(path)
        elif state == "acting":
            for k in range(3):
                a = now * 2.4 + k * math.tau / 3
                pt = QPointF(c.x() + seg_r * math.cos(a), c.y() + seg_r * math.sin(a))
                p.setPen(Qt.NoPen)
                p.setBrush(theme.qcolor(theme.ACCENT_2, 0.95))
                p.drawEllipse(pt, s * 0.022, s * 0.022)
        elif state == "thinking":
            cone = QConicalGradient(c, -math.degrees(now * 4) % 360)
            cone.setColorAt(0.0, theme.qcolor(col.name(), 0.55))
            cone.setColorAt(0.25, theme.qcolor(col.name(), 0.0))
            cone.setColorAt(1.0, theme.qcolor(col.name(), 0.0))
            p.setPen(Qt.NoPen)
            p.setBrush(cone)
            p.drawEllipse(c, inner_r, inner_r)
        elif state == "error":
            p.setPen(QPen(theme.qcolor(theme.ERROR, 0.4 + 0.4 * breathe), 2))
            p.drawEllipse(c, inner_r * 1.1, inner_r * 1.1)

        # core
        core_r = R * (0.30 + 0.03 * breathe + 0.08 * self._level_smooth)
        core = QRadialGradient(c, core_r)
        core.setColorAt(0.0, QColor(255, 255, 255, 245))
        core.setColorAt(0.35, theme.qcolor(col.name(), 0.95))
        core.setColorAt(1.0, theme.qcolor(col.name(), 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(core)
        p.drawEllipse(c, core_r, core_r)
        # triangle-ish reactor spokes
        p.setPen(QPen(theme.qcolor("#FFFFFF", 0.35), 1))
        for k in range(3):
            a = -math.pi / 2 + k * math.tau / 3 + base * 0.2
            p.drawLine(QPointF(c.x() + core_r * 0.35 * math.cos(a), c.y() + core_r * 0.35 * math.sin(a)),
                       QPointF(c.x() + inner_r * 0.9 * math.cos(a), c.y() + inner_r * 0.9 * math.sin(a)))
        p.end()


# ── toggle switch ────────────────────────────────────────────────────────────
class ToggleSwitch(QAbstractButton):
    """Animated switch. Checkable; emits toggled(bool) like a QCheckBox."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._pos = 1.0 if checked else 0.0
        self.setChecked(checked)
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self):
        return self._pos

    def _set_knob(self, value):
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on):                       # keep the knob right when set programmatically
        super().setChecked(on)
        if not getattr(self, "_anim", None) or self._anim.state() != QPropertyAnimation.Running:
            self._pos = 1.0 if on else 0.0
            self.update()

    def sizeHint(self):
        return QSize(42, 24)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track = QRectF(1, 3, w - 2, h - 6)
        on = self._pos
        off_c, on_c = QColor(theme.INPUT), QColor(theme.ACCENT_DIM)
        mix = QColor(int(off_c.red() + (on_c.red() - off_c.red()) * on), int(off_c.green() + (on_c.green() - off_c.green()) * on),
                     int(off_c.blue() + (on_c.blue() - off_c.blue()) * on))
        p.setPen(QPen(QColor(theme.ACCENT if on > 0.5 else theme.BORDER), 1))
        p.setBrush(mix)
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        d = h - 8
        x = 4 + (w - d - 8) * on
        knob = QRectF(x, 4, d, d)
        if self.isEnabled():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT) if on > 0.5 else QColor(theme.TEXT_2))
        else:
            p.setBrush(QColor(theme.FAINT))
        p.drawEllipse(knob)
        p.end()


# ── icon button ──────────────────────────────────────────────────────────────
class IconButton(QToolButton):
    """Flat HUD icon button. ``IconButton("mic", tooltip="Voice", checkable=True)``; text optional."""

    def __init__(self, icon_name: str, tooltip: str = "", text: str = "", size: int = 36, icon_size: int = 18,
                 checkable: bool = False, parent=None, color: str = None, accent: str = None):
        super().__init__(parent)
        self.icon_name = icon_name
        self._accent = accent or theme.ACCENT
        self.setIcon(theme.icon(icon_name, icon_size, color=color, active=self._accent, checked=self._accent))
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        if tooltip:
            self.setToolTip(tooltip)
        if text:
            self.setText(text)
            self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.setMinimumHeight(size)
        else:
            self.setFixedSize(size, size)
        self.setObjectName("iconButton")
        self.setStyleSheet(f"""
            QToolButton#iconButton {{ background: transparent; border: 1px solid transparent; border-radius: 9px;
                color: {theme.TEXT_2}; padding: 0 {10 if text else 0}px; font-size: 12px; }}
            QToolButton#iconButton:hover {{ background: {theme.CARD}; border-color: {theme.BORDER_SOFT}; color: {self._accent}; }}
            QToolButton#iconButton:pressed {{ background: #0A2030; }}
            QToolButton#iconButton:checked {{ background: {theme.qcolor(self._accent, 0.12).name(QColor.HexArgb)};
                border-color: {theme.qcolor(self._accent, 0.55).name(QColor.HexArgb)}; color: {self._accent}; }}
            QToolButton#iconButton:disabled {{ color: {theme.FAINT}; }}
        """)

    def set_icon(self, icon_name: str, icon_size: int = None):
        size = icon_size or self.iconSize().width()
        self.icon_name = icon_name
        self.setIcon(theme.icon(icon_name, size, active=self._accent, checked=self._accent))


# ── HUD panel ────────────────────────────────────────────────────────────────
class HudPanel(QFrame):
    """A glass panel with cyan corner brackets. Put a layout in it like any QFrame."""

    def __init__(self, caption: str = "", parent=None, brackets: bool = True, glow: bool = False, radius: int = 12):
        super().__init__(parent)
        self.caption = caption.upper()
        self.brackets = brackets
        self.glow = glow
        self.radius = radius
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.setBrush(theme.qcolor(theme.PANEL, 0.92))
        p.drawRoundedRect(r, self.radius, self.radius)
        if self.glow:
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.18), 1))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), self.radius - 1, self.radius - 1)
        if self.brackets:
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.7), 1.4))
            L = 12
            x0, y0, x1, y1 = r.left() + 1, r.top() + 1, r.right() - 1, r.bottom() - 1
            for (ax, ay, bx, by, cx, cy) in ((x0, y0 + L, x0, y0, x0 + L, y0), (x1 - L, y0, x1, y0, x1, y0 + L),
                                             (x0, y1 - L, x0, y1, x0 + L, y1), (x1 - L, y1, x1, y1, x1, y1 - L)):
                path = QPainterPath(QPointF(ax, ay))
                path.lineTo(QPointF(bx, by))
                path.lineTo(QPointF(cx, cy))
                p.drawPath(path)
        if self.caption:
            p.setFont(theme.hud_font(8))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(r.left() + 16, r.top() + 8, r.width() - 32, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       self.caption)
        p.end()
        super().paintEvent(event)


# ── small labels ─────────────────────────────────────────────────────────────
class Caption(QLabel):
    """Uppercase, letter-spaced HUD caption."""

    def __init__(self, text: str = "", parent=None, color: str = None, size: float = 8.5):
        super().__init__(text.upper(), parent)
        self.setFont(theme.hud_font(size))
        self.setStyleSheet(f"color: {color or theme.MUTED}; background: transparent;")

    def setText(self, text):
        super().setText((text or "").upper())


class StatusPill(QWidget):
    """``● THINKING`` — the colour and label follow ``set_state()``; the dot pulses while busy."""

    def __init__(self, parent=None, state: str = "offline"):
        super().__init__(parent)
        self._state = state
        self._detail = ""
        self.setFixedHeight(26)
        self.setMinimumWidth(110)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    @property
    def state(self):
        return self._state

    def set_state(self, state: str, detail: str = ""):
        self._state = state if state in theme.STATE_COLORS else "idle"
        self._detail = detail
        busy = self._state in ("listening", "thinking", "acting", "speaking")
        if busy and not self._timer.isActive():
            self._timer.start(33)
        elif not busy:
            self._timer.stop()
        self.setToolTip(detail or theme.STATE_LABELS.get(self._state, ""))
        self.setMinimumWidth(self.sizeHint().width())
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        label = theme.STATE_LABELS.get(self._state, self._state).upper()
        return f"{label} · {self._detail}" if self._detail else label

    def sizeHint(self):
        from PySide6.QtGui import QFontMetrics
        return QSize(QFontMetrics(theme.hud_font(8.5)).horizontalAdvance(self.text()) + 40, 26)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(theme.STATE_COLORS.get(self._state, theme.ACCENT))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.qcolor(col.name(), 0.45), 1))
        p.setBrush(theme.qcolor(col.name(), 0.08))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 6) if self._timer.isActive() else 1.0
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qcolor(col.name(), 0.35 + 0.65 * pulse))
        p.drawEllipse(QPointF(14, r.center().y()), 4, 4)
        p.setFont(theme.hud_font(8.5))
        p.setPen(col)
        p.drawText(r.adjusted(26, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


# ── background ───────────────────────────────────────────────────────────────
def paint_grid(painter: QPainter, rect, spacing: int = 28, vignette: bool = True):
    """Faint HUD grid with a soft centre glow. Call from a widget's paintEvent before children draw."""
    painter.save()
    painter.fillRect(rect, QColor(theme.BG))
    pen = QPen(QColor(theme.GRID), 1)
    painter.setPen(pen)
    x = rect.left() - rect.left() % spacing
    while x < rect.right():
        painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
        x += spacing
    y = rect.top() - rect.top() % spacing
    while y < rect.bottom():
        painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        y += spacing
    if vignette:
        g = QRadialGradient(QPointF(rect.center()), max(rect.width(), rect.height()) * 0.65)
        g.setColorAt(0.0, theme.qcolor(theme.ACCENT, 0.05))
        g.setColorAt(0.6, theme.qcolor(theme.BG, 0.0))
        g.setColorAt(1.0, theme.qcolor("#000000", 0.55))
        painter.fillRect(rect, g)
    painter.restore()


class GridBackground(QWidget):
    """A plain container that paints the HUD grid behind its children."""

    def paintEvent(self, event):
        p = QPainter(self)
        paint_grid(p, self.rect())
        p.end()
