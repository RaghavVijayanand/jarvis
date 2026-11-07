"""Dashboard-only widgets built on the HUD design system (ui/theme.py, ui/widgets.py).

    NavButton        rail button: icon + tiny caption, cyan glow + left indicator when active
    OrbButton        round button (send / mic / camera / stop); ``primary`` fills it cyan,
                     a checked button glows and breathes in its accent colour
    SuggestionCard   clickable "try this" card on the empty-chat hero
    Gauge            circular HUD gauge (value 0..100 or None → "—")
    StatTile         a HudPanel holding a Gauge and a detail line
    ReflowGrid       lays its cards out in N columns chosen from the available width
    FlowLayout       buttons that wrap onto the next line when the card gets narrow
    read_system_stats()  CPU / RAM / disk / battery from psutil; any failure → None
"""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QGridLayout, QLabel, QLayout, QSizePolicy, QVBoxLayout, QWidget

from ui import theme
from ui.widgets import HudPanel


def _alpha(color, a):
    return theme.qcolor(color, a)


# ── navigation rail ──────────────────────────────────────────────────────────
class NavButton(QAbstractButton):
    def __init__(self, icon_name: str, label: str, checkable: bool = True, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setText(label)
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(label)
        self.setFixedSize(76, 62)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def sizeHint(self):
        return QSize(76, 62)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect())
        if on:
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0.0, _alpha(theme.ACCENT, 0.16))
            g.setColorAt(1.0, _alpha(theme.ACCENT, 0.0))
            p.fillRect(r.adjusted(0, 4, 0, -4), g)
            glow = QRectF(0, 12, 8, r.height() - 24)
            p.setPen(Qt.NoPen)
            p.setBrush(_alpha(theme.ACCENT, 0.18))
            p.drawRoundedRect(glow, 3, 3)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(0, 16, 3, r.height() - 32), 1.5, 1.5)
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(_alpha(theme.CARD, 0.9))
            p.drawRoundedRect(r.adjusted(8, 4, -8, -4), 10, 10)
        color = theme.ACCENT if on else theme.TEXT if self._hover else theme.MUTED
        pix = theme.icon_pixmap(self.icon_name, 22, color)
        p.drawPixmap(int((r.width() - 22) / 2), 11, pix)
        p.setFont(theme.hud_font(7.2))
        p.setPen(QColor(color))
        p.drawText(QRectF(0, 38, r.width(), 16), Qt.AlignCenter, self.text().upper())
        p.end()


# ── round buttons ────────────────────────────────────────────────────────────
class OrbButton(QAbstractButton):
    """Round icon button. Checkable ones glow (and slowly breathe) in ``accent`` while checked."""

    def __init__(self, icon_name: str, tooltip: str = "", diameter: int = 40, icon_size: int = 18,
                 primary: bool = False, checkable: bool = False, accent: str = None, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.primary = primary
        self.accent = accent or theme.ACCENT
        self._icon_size = icon_size
        self._hover = False
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(diameter, diameter)
        if tooltip:
            self.setToolTip(tooltip)
        self._pulse = QTimer(self)
        self._pulse.setInterval(40)
        self._pulse.timeout.connect(self.update)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, on):
        if on and self.isVisible():
            self._pulse.start()
        else:
            self._pulse.stop()
        self.update()

    def showEvent(self, e):
        if self.isChecked():
            self._pulse.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._pulse.stop()
        super().hideEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def sizeHint(self):
        return self.size()

    def set_icon(self, name: str):
        self.icon_name = name
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        c = r.center()
        enabled = self.isEnabled()
        if self.primary:
            base = QColor(theme.ACCENT if enabled else theme.FAINT)
            if self._hover and enabled:
                base = QColor("#5CF0FF")
            g = QRadialGradient(QPointF(c.x(), r.top()), r.height())
            g.setColorAt(0.0, base.lighter(118))
            g.setColorAt(1.0, base)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(r)
            icon_color = "#00121A"
        elif self.isChecked():
            t = time.monotonic()
            breathe = 0.5 + 0.5 * math.sin(t * 3.2)
            for k, a in ((5, 0.10), (2.5, 0.18)):
                p.setPen(Qt.NoPen)
                p.setBrush(_alpha(self.accent, a * (0.6 + 0.8 * breathe)))
                p.drawEllipse(r.adjusted(-k + 3, -k + 3, k - 3, k - 3))
            p.setBrush(_alpha(self.accent, 0.16))
            p.setPen(QPen(_alpha(self.accent, 0.9), 1.4))
            p.drawEllipse(r.adjusted(2, 2, -2, -2))
            icon_color = self.accent
        else:
            p.setBrush(QColor(theme.CARD_HI if self._hover and enabled else theme.CARD))
            border = self.accent if self._hover and enabled else theme.BORDER
            p.setPen(QPen(_alpha(border, 0.8 if self._hover else 1.0), 1))
            p.drawEllipse(r.adjusted(1, 1, -1, -1))
            tinted = not self.isCheckable() and self.accent != theme.ACCENT
            icon_color = (self.accent if self._hover or tinted else theme.TEXT_2) if enabled else theme.FAINT
            if tinted and enabled:
                p.setPen(QPen(_alpha(self.accent, 0.55), 1))
                p.setBrush(_alpha(self.accent, 0.08))
                p.drawEllipse(r.adjusted(1, 1, -1, -1))
        s = self._icon_size
        pix = theme.icon_pixmap(self.icon_name, s, icon_color)
        p.drawPixmap(int(c.x() - s / 2), int(c.y() - s / 2), pix)
        p.end()


# ── hero suggestion card ─────────────────────────────────────────────────────
class SuggestionCard(QAbstractButton):
    activated = Signal(str)

    def __init__(self, icon_name: str, title: str, example: str, command: str, parent=None):
        super().__init__(parent)
        self.icon_name, self.title, self.example, self.command = icon_name, title, example, command
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(example)
        self.setMinimumSize(180, 70)
        self.setFixedHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hover = False
        self.clicked.connect(lambda: self.activated.emit(self.command))

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def sizeHint(self):
        return QSize(240, 70)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hot = self._hover and self.isEnabled()
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, _alpha(theme.CARD_HI if hot else theme.CARD, 0.95))
        g.setColorAt(1.0, _alpha(theme.PANEL, 0.92))
        p.setBrush(g)
        p.setPen(QPen(_alpha(theme.ACCENT_DIM if hot else theme.BORDER_SOFT, 1.0), 1))
        p.drawRoundedRect(r, 12, 12)
        if hot:
            p.setPen(QPen(_alpha(theme.ACCENT, 0.8), 1.4))
            L = 10
            for (ax, ay, bx, by, cx, cy) in ((r.left() + 1, r.top() + L, r.left() + 1, r.top() + 1, r.left() + L, r.top() + 1),
                                             (r.right() - L, r.bottom() - 1, r.right() - 1, r.bottom() - 1,
                                              r.right() - 1, r.bottom() - L)):
                path = QPainterPath(QPointF(ax, ay))
                path.lineTo(QPointF(bx, by))
                path.lineTo(QPointF(cx, cy))
                p.drawPath(path)
        # icon plate
        plate = QRectF(r.left() + 14, r.center().y() - 18, 36, 36)
        p.setPen(QPen(_alpha(theme.ACCENT, 0.35 if hot else 0.2), 1))
        p.setBrush(_alpha(theme.ACCENT, 0.10 if hot else 0.06))
        p.drawRoundedRect(plate, 10, 10)
        p.drawPixmap(int(plate.center().x() - 10), int(plate.center().y() - 10),
                     theme.icon_pixmap(self.icon_name, 20, theme.ACCENT if self.isEnabled() else theme.FAINT))
        tx = plate.right() + 14
        tw = r.right() - tx - 12
        p.setFont(theme.text_font(10.5, QFont.DemiBold))
        p.setPen(QColor(theme.TEXT if self.isEnabled() else theme.MUTED))
        fm = QFontMetrics(p.font())
        p.drawText(QRectF(tx, r.top() + 14, tw, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(self.title, Qt.ElideRight, int(tw)))
        p.setFont(theme.text_font(9.5))
        fm = QFontMetrics(p.font())
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(tx, r.top() + 36, tw, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(self.example, Qt.ElideRight, int(tw)))
        p.end()


# ── gauges ───────────────────────────────────────────────────────────────────
def gauge_color(value):
    if value is None:
        return theme.FAINT
    return theme.ERROR if value >= 90 else theme.WARN if value >= 75 else theme.ACCENT


class Gauge(QWidget):
    """Circular 270° gauge. ``set_value(None)`` shows an em dash (sensor unavailable)."""

    def __init__(self, caption: str = "", size: int = 118, parent=None, invert: bool = False):
        super().__init__(parent)
        self.caption = caption.upper()
        self.invert = invert           # battery: low is bad
        self._value = None
        self._shown = 0.0
        self.setFixedSize(size, size)
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._step)

    @property
    def value(self):
        return self._value

    def text(self) -> str:
        return "—" if self._value is None else f"{self._value:.0f}%"

    def set_value(self, value):
        try:
            value = None if value is None else max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            value = None
        self._value = value
        if self.isVisible():
            self._anim.start()
        else:
            self._shown = value or 0.0
        self.update()

    def _step(self):
        target = self._value or 0.0
        self._shown += (target - self._shown) * 0.18
        if abs(target - self._shown) < 0.2:
            self._shown = target
            self._anim.stop()
        self.update()

    def _color(self):
        v = self._value
        if v is not None and self.invert:
            v = 100 - v
        return gauge_color(v)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        R = s / 2 - 8
        rect = QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R)
        col = self._color()
        # ticks
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        for i in range(28):
            a = math.radians(225 - i * 270 / 27)
            r1, r2 = R + 4, R + 7 if i % 3 == 0 else R + 5.5
            p.drawLine(QPointF(c.x() + r1 * math.cos(a), c.y() - r1 * math.sin(a)),
                       QPointF(c.x() + r2 * math.cos(a), c.y() - r2 * math.sin(a)))
        track = QPen(QColor(theme.BORDER_SOFT), 7)
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.drawArc(rect, 225 * 16, -270 * 16)
        if self._value is not None and self._shown > 0.3:
            span = 270 * self._shown / 100.0
            glow = QPen(_alpha(col, 0.18), 13)
            glow.setCapStyle(Qt.RoundCap)
            p.setPen(glow)
            p.drawArc(rect, 225 * 16, int(-span * 16))
            pen = QPen(QColor(col), 7)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 225 * 16, int(-span * 16))
        inner = R - 14
        p.setPen(QPen(_alpha(col, 0.25), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, inner, inner)
        f = theme.hud_font(max(11.0, s / 7.2))
        p.setFont(f)
        p.setPen(QColor(theme.TEXT if self._value is not None else theme.MUTED))
        p.drawText(QRectF(c.x() - R, c.y() - 16, 2 * R, 26), Qt.AlignCenter, self.text())
        p.setFont(theme.hud_font(7.5))
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(c.x() - R, c.y() + 10, 2 * R, 16), Qt.AlignCenter, self.caption)
        p.end()


class StatTile(HudPanel):
    """A gauge with a caption and one detail line (e.g. '6.1 / 15.8 GB')."""

    def __init__(self, caption: str, icon_name: str, invert: bool = False, parent=None):
        super().__init__(caption, parent=parent)
        self.icon_name = icon_name
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 30, 14, 14)
        lay.setSpacing(6)
        self.gauge = Gauge(caption, 120, invert=invert)
        lay.addWidget(self.gauge, 0, Qt.AlignHCenter)
        self.detail = QLabel("—")
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color: {theme.TEXT_2}; font-size: 12px; background: transparent;")
        lay.addWidget(self.detail)
        self.setMinimumHeight(206)

    def set_stat(self, value, detail: str = ""):
        self.gauge.set_value(value)
        self.detail.setText(detail or ("Unavailable" if value is None else ""))

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.drawPixmap(self.width() - 30, 8, theme.icon_pixmap(self.icon_name, 16, theme.ACCENT_DIM))
        p.end()


def _fmt_gb(n):
    return f"{n / (1024 ** 3):.1f}"


def read_system_stats(ps=None) -> dict:
    """{'cpu'|'ram'|'disk'|'battery': (percent or None, detail text)} — never raises."""
    if ps is None:
        try:
            import psutil as ps
        except Exception:
            ps = None
    out = {"cpu": (None, "psutil unavailable"), "ram": (None, "psutil unavailable"),
           "disk": (None, "psutil unavailable"), "battery": (None, "No battery")}
    if ps is None:
        return out
    try:
        pct = ps.cpu_percent(interval=None)
        try:
            cores = ps.cpu_count(logical=True)
        except Exception:
            cores = None
        out["cpu"] = (float(pct), f"{cores} logical cores" if cores else "")
    except Exception:
        out["cpu"] = (None, "Unavailable")
    try:
        vm = ps.virtual_memory()
        out["ram"] = (float(vm.percent), f"{_fmt_gb(vm.used)} / {_fmt_gb(vm.total)} GB")
    except Exception:
        out["ram"] = (None, "Unavailable")
    try:
        root = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
        du = ps.disk_usage(root)
        out["disk"] = (float(du.percent), f"{root}  {_fmt_gb(du.used)} / {_fmt_gb(du.total)} GB")
    except Exception:
        out["disk"] = (None, "Unavailable")
    try:
        bat = ps.sensors_battery() if hasattr(ps, "sensors_battery") else None
        if bat is None:
            out["battery"] = (None, "No battery · mains power")
        else:
            plugged = "Charging" if bat.power_plugged else "On battery"
            left = ""
            secs = getattr(bat, "secsleft", None)
            if isinstance(secs, (int, float)) and 0 < secs < 10 ** 6 and not bat.power_plugged:
                left = f" · {int(secs // 3600)}h {int(secs % 3600 // 60)}m left"
            out["battery"] = (float(bat.percent), plugged + left)
    except Exception:
        out["battery"] = (None, "Unavailable")
    return out


# ── responsive grid ──────────────────────────────────────────────────────────
class ReflowGrid(QWidget):
    """Cards in a grid whose column count follows the width: ``breakpoints=[(min_width, cols), ...]``."""

    def __init__(self, breakpoints, spacing: int = 14, parent=None):
        super().__init__(parent)
        self.breakpoints = sorted(breakpoints, reverse=True)
        self._items = []
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)
        # the column count follows our width, so our width must not follow the columns' minimums
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def add(self, widget, stretch: int = 0):
        self._items.append((widget, stretch))
        self._reflow(force=True)

    @property
    def columns(self) -> int:
        return self._cols

    def _cols_for(self, width):
        for min_w, cols in self.breakpoints:
            if width >= min_w:
                return cols
        return 1

    def _reflow(self, force=False):
        cols = self._cols_for(self.width() if self.width() > 0 else 10 ** 5)
        if cols == self._cols and not force:
            return
        self._cols = cols
        for w, _ in self._items:
            self._grid.removeWidget(w)
        for c in range(8):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        for r in range(40):
            self._grid.setRowStretch(r, 0)
        row = 0
        for i, (w, stretch) in enumerate(self._items):
            row, col = divmod(i, cols)
            self._grid.addWidget(w, row, col)
            if stretch:
                self._grid.setRowStretch(row, stretch)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reflow()


# ── chrome: rail, header, glass input bar ────────────────────────────────────
class RailFrame(QWidget):
    """The slim left navigation rail."""

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        g = QLinearGradient(QPointF(0, 0), QPointF(r.width(), 0))
        g.setColorAt(0.0, _alpha(theme.BG_2, 0.98))
        g.setColorAt(1.0, _alpha(theme.PANEL, 0.90))
        p.fillRect(r, g)
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.drawLine(r.right(), 0, r.right(), r.bottom())
        p.end()


class HeaderBar(QWidget):
    """Top HUD strip: a hairline with a bright cyan segment under the wordmark."""

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, _alpha(theme.BG_2, 0.72))
        y = r.bottom()
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.drawLine(0, y, r.right(), y)
        g = QLinearGradient(QPointF(0, y), QPointF(360, y))
        g.setColorAt(0.0, _alpha(theme.ACCENT, 0.0))
        g.setColorAt(0.25, _alpha(theme.ACCENT, 0.85))
        g.setColorAt(1.0, _alpha(theme.ACCENT, 0.0))
        p.setPen(QPen(g, 1.2))
        p.drawLine(QPointF(0, y), QPointF(360, y))
        p.end()


class GlassFrame(QWidget):
    """Rounded glass container; ``focused`` brightens the border (the chat input bar)."""

    def __init__(self, parent=None, radius: int = 20):
        super().__init__(parent)
        self.radius = radius
        self.focused = False

    def set_focused(self, on: bool):
        self.focused = on
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self.focused:
            p.setPen(QPen(_alpha(theme.ACCENT, 0.10), 4))
            p.drawRoundedRect(r, self.radius, self.radius)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, _alpha("#0D1A27", 0.97))
        g.setColorAt(1.0, _alpha(theme.PANEL, 0.97))
        p.setBrush(g)
        p.setPen(QPen(_alpha(theme.ACCENT_DIM if self.focused else theme.BORDER, 1.0), 1))
        p.drawRoundedRect(r, self.radius, self.radius)
        hl = QLinearGradient(QPointF(r.left(), r.top()), QPointF(r.right(), r.top()))
        hl.setColorAt(0.0, _alpha(theme.ACCENT, 0.0))
        hl.setColorAt(0.5, _alpha(theme.ACCENT, 0.35 if self.focused else 0.18))
        hl.setColorAt(1.0, _alpha(theme.ACCENT, 0.0))
        p.setPen(QPen(hl, 1))
        p.drawLine(QPointF(r.left() + self.radius, r.top() + 0.5), QPointF(r.right() - self.radius, r.top() + 0.5))
        p.end()


class LiveCaption(QLabel):
    """The live-voice transcript line; its strip hides itself whenever the text is empty."""

    def __init__(self, strip: QWidget = None, parent=None):
        super().__init__(parent)
        self.strip = strip

    def setText(self, text):
        super().setText(text or "")
        if self.strip is not None:
            self.strip.setVisible(bool(text))


class FlowLayout(QLayout):
    """Left-to-right items that wrap onto new lines (height-for-width aware)."""

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, False)

    def sizeHint(self):
        w = sum(i.sizeHint().width() for i in self._items) + self._spacing * max(0, len(self._items) - 1)
        h = max([i.sizeHint().height() for i in self._items] + [0])
        return QSize(w, h)

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x = rect.x()
                y += line + self._spacing
                line = 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()
