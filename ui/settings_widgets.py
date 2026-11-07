"""Building blocks shared by the Settings dialog and the welcome stepper.

    SecretEdit    masked QLineEdit with an eye action to show / hide the text
    Chip          small rounded status chip ("● SET", "● LAYA READY")
    KeyCaps       renders a hotkey label ("Hold Ctrl + Alt") as [Ctrl] + [Alt]
    SettingRow    title + description on the left, the control on the right; searchable
    SettingCard   HudPanel holding rows separated by hairlines
    NavButton     one entry of the settings nav rail (icon + label, glowing when active)
    SliderSpin    a slider bound to an existing (Double)SpinBox, which stays the source of truth
    PageHeader    big HUD title + one-line subtitle
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QSizePolicy, QSlider, QVBoxLayout, QWidget)

from ui import theme
from ui.widgets import HudPanel

CONTROL_WIDTH = 260          # every text/combo control on a settings row is exactly this wide


def mix(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t))


# ── masked key field ─────────────────────────────────────────────────────────
class SecretEdit(QLineEdit):
    """A password-style QLineEdit with a trailing eye action that reveals the text."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setEchoMode(QLineEdit.Password)
        self.eye = QAction(theme.icon("eye", 16, color=theme.MUTED), "Show", self)
        self.eye.setCheckable(True)
        self.eye.setToolTip("Show key")
        self.eye.toggled.connect(self.set_revealed)
        self.addAction(self.eye, QLineEdit.TrailingPosition)

    def revealed(self) -> bool:
        return self.echoMode() == QLineEdit.Normal

    def set_revealed(self, on: bool):
        self.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self.eye.setIcon(theme.icon("eye", 16, color=theme.ACCENT if on else theme.MUTED))
        self.eye.setToolTip("Hide key" if on else "Show key")
        if self.eye.isChecked() != on:
            self.eye.blockSignals(True)
            self.eye.setChecked(on)
            self.eye.blockSignals(False)

    def toggle_revealed(self):
        self.set_revealed(not self.revealed())


# ── combo with a drawn chevron ───────────────────────────────────────────────
class HudCombo(QComboBox):
    """QComboBox whose drop-down arrow is a crisp painted chevron (QSS arrows need image files)."""

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = theme.ACCENT if (self.hasFocus() or self.underMouse()) else theme.MUTED
        if not self.isEnabled():
            col = theme.FAINT
        pen = QPen(QColor(col), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 17, self.height() / 2
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])
        p.end()


# ── status chip ──────────────────────────────────────────────────────────────
class Chip(QWidget):
    """``● TEXT`` in a rounded, tinted capsule. ``set(text, color)``."""

    def __init__(self, text: str = "", color: str = theme.MUTED, parent=None, dot: bool = True, max_width: int = 260):
        super().__init__(parent)
        self._text, self._color, self._dot, self._max = text, color, dot, max_width
        self.setToolTip(text)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def text(self) -> str:
        return self._text

    def color(self) -> str:
        return self._color

    def set(self, text: str, color: str = None):
        self._text = text
        self.setToolTip(text)
        if color:
            self._color = color
        self.setFixedWidth(self.sizeHint().width())
        self.update()

    def sizeHint(self):
        w = QFontMetrics(theme.hud_font(7.5)).horizontalAdvance(self._text.upper())
        return QSize(min(self._max, w + (30 if self._dot else 18)), 22)

    def showEvent(self, e):
        self.setFixedWidth(self.sizeHint().width())
        super().showEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.qcolor(self._color, 0.45), 1))
        p.setBrush(theme.qcolor(self._color, 0.10))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        x = 9
        if self._dot:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._color))
            p.drawEllipse(QPointF(12, r.center().y()), 3, 3)
            x = 21
        p.setFont(theme.hud_font(7.5))
        p.setPen(QColor(self._color))
        f = theme.hud_font(7.5)
        text = QFontMetrics(f).elidedText(self._text.upper(), Qt.ElideRight, int(r.width() - x - 8))
        p.drawText(r.adjusted(x, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


# ── keycaps ──────────────────────────────────────────────────────────────────
def hotkey_keys(label: str) -> list:
    """'Hold Ctrl + Alt' → ['Ctrl', 'Alt']; 'F8' → ['F8']."""
    text = (label or "").strip()
    for prefix in ("Hold ", "Press ", "hold ", "press "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    parts = [p.strip() for p in text.replace("+", " + ").split(" + ")]
    return [p for p in (x.strip() for x in parts) if p]


class KeyCaps(QWidget):
    """Draws a hotkey as keyboard keys: [Ctrl] + [Alt]."""

    def __init__(self, label: str = "", parent=None, size: float = 8.5, align=Qt.AlignLeft):
        super().__init__(parent)
        self._size = size
        self._align = align
        self._keys = []
        self.set_label(label)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def keys(self) -> list:
        return list(self._keys)

    def set_label(self, label: str):
        self._keys = hotkey_keys(label)
        self.setMinimumWidth(self.sizeHint().width())
        self.setFixedHeight(self.sizeHint().height())
        self.updateGeometry()
        self.update()

    def _font(self):
        return theme.hud_font(self._size)

    def _metrics(self):
        fm = QFontMetrics(self._font())
        h = int(fm.height() + 12)
        widths = [max(h, fm.horizontalAdvance(k) + 18) for k in self._keys]
        return fm, h, widths, fm.horizontalAdvance("+") + 12

    def sizeHint(self):
        _fm, h, widths, plus = self._metrics()
        return QSize(sum(widths) + plus * max(0, len(widths) - 1) + 2, h + 4)

    def paintEvent(self, _e):
        if not self._keys:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _fm, h, widths, plus = self._metrics()
        total = sum(widths) + plus * (len(widths) - 1)
        x = 1.0
        if self._align & Qt.AlignRight:
            x = self.width() - total - 1
        elif self._align & Qt.AlignHCenter:
            x = (self.width() - total) / 2
        y = (self.height() - h - 3) / 2
        p.setFont(self._font())
        for i, (key, w) in enumerate(zip(self._keys, widths)):
            body = QRectF(x, y, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#02060A"))                    # the key's "side" (3D edge)
            p.drawRoundedRect(body.translated(0, 3), 6, 6)
            g = QLinearGradient(body.topLeft(), body.bottomLeft())
            g.setColorAt(0, QColor(theme.CARD_HI))
            g.setColorAt(1, QColor(theme.CARD))
            p.setBrush(g)
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.55), 1))
            p.drawRoundedRect(body, 6, 6)
            p.setPen(QColor(theme.ACCENT))
            p.drawText(body, Qt.AlignCenter, key)
            x += w
            if i < len(widths) - 1:
                p.setPen(QColor(theme.MUTED))
                p.drawText(QRectF(x, y, plus, h), Qt.AlignCenter, "+")
                x += plus
        p.end()


# ── rows / cards ─────────────────────────────────────────────────────────────
class SettingRow(QFrame):
    """One setting: title and description on the left, control(s) on the right.

    ``stacked=True`` puts the control under the text, full width (API keys, long paths).
    ``keywords`` add extra search terms; ``matches(query)`` tells the search box whether this row fits.
    """

    def __init__(self, title: str, description: str = "", control=None, stacked: bool = False,
                 keywords: str = "", trailing=None, below=None, keys=(), parent=None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        self.title = title
        self.description = description
        self.keywords = keywords
        self.control = control
        self._highlight = False
        self._modified = False
        self.keys = tuple(keys)              # the .env keys this row edits (for "modified" markers)
        self.page = -1
        self.setAttribute(Qt.WA_StyledBackground, False)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("rowTitle")
        self.title_label.setStyleSheet(f"color: {theme.TEXT}; font-size: 13.5px; font-weight: 600;")
        self.desc_label = QLabel(description)
        self.desc_label.setObjectName("rowDesc")
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        self.desc_label.setVisible(bool(description))
        self.desc_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        text = QVBoxLayout()
        text.setSpacing(3)
        text.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.title_label)
        if trailing is not None:
            head.addWidget(trailing)
        head.addStretch(1)
        text.addLayout(head)
        text.addWidget(self.desc_label)
        if below is not None:
            text.addSpacing(4)
            text.addWidget(below, 0, Qt.AlignLeft)

        if stacked:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(14, 12, 14, 12)
            outer.setSpacing(9)
            outer.addLayout(text)
            if control is not None:
                if isinstance(control, QWidget):
                    outer.addWidget(control)
                else:
                    outer.addLayout(control)
        else:
            outer = QHBoxLayout(self)
            outer.setContentsMargins(14, 12, 14, 12)
            outer.setSpacing(18)
            outer.addLayout(text, 1)
            if control is not None:
                if isinstance(control, QWidget):
                    outer.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
                else:
                    outer.addLayout(control)

    # search
    def haystack(self) -> str:
        return " ".join((self.title, self.description, self.keywords)).lower()

    def matches(self, query: str) -> bool:
        words = [w for w in (query or "").lower().split() if w]
        hay = self.haystack()
        return all(w in hay for w in words)

    def set_highlight(self, on: bool):
        if on != self._highlight:
            self._highlight = on
            self.update()

    def highlighted(self) -> bool:
        return self._highlight

    def set_modified(self, on: bool):
        if on != self._modified:
            self._modified = on
            self.title_label.setToolTip("Changed — not saved yet" if on else "")
            self.update()

    def modified(self) -> bool:
        return self._modified

    def paintEvent(self, e):
        if self._modified:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.WARN))
            y = self.title_label.geometry().center().y() + 1
            p.drawEllipse(QPointF(6, y), 2.6, 2.6)
            p.end()
        if self._highlight:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.35), 1))
            p.setBrush(theme.qcolor(theme.ACCENT, 0.07))
            p.drawRoundedRect(r, 8, 8)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 8, 3, r.height() - 16), 1.5, 1.5)
            p.end()
        super().paintEvent(e)


class SettingCard(HudPanel):
    """A HudPanel of SettingRows with hairline separators. ``add(row)``; ``note(text)`` adds a footnote."""

    def __init__(self, caption: str = "", parent=None):
        super().__init__(caption, parent)
        self.rows = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(6, 30 if caption else 8, 6, 8)
        self._lay.setSpacing(0)

    def add(self, row: SettingRow) -> SettingRow:
        if self.rows:
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background: {theme.BORDER_SOFT}; margin: 0 14px;")
            line.setObjectName("rowLine")
            self._lay.addWidget(line)
            row._line = line
        else:
            row._line = None
        self.rows.append(row)
        self._lay.addWidget(row)
        return row

    def note(self, text: str, icon_name: str = "sparkle", color: str = None, widget=None) -> QWidget:
        box = QFrame()
        box.setObjectName("cardNote")
        box.setStyleSheet(f"QFrame#cardNote {{ background: {theme.qcolor(color or theme.ACCENT, 0.05).name(QColor.HexArgb)};"
                          f" border: 1px solid {theme.qcolor(color or theme.ACCENT, 0.18).name(QColor.HexArgb)};"
                          f" border-radius: 8px; }}")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(theme.icon_pixmap(icon_name, 16, color or theme.ACCENT))
        ic.setFixedSize(16, 16)
        lay.addWidget(ic, 0, Qt.AlignTop)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.RichText)
        lab.setStyleSheet(f"color: {theme.TEXT_2}; font-size: 12px; background: transparent; border: none;")
        lay.addWidget(lab, 1)
        if widget is not None:
            lay.addWidget(widget, 0, Qt.AlignVCenter)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(10, 6, 10, 4)
        wl.addWidget(box)
        self._lay.addWidget(wrap)
        wrap.note_label = lab
        return wrap

    def update_visibility(self, searching: bool = False):
        """Hide separators next to hidden rows, footnotes while searching, and the card when it is empty."""
        first = True
        for row in self.rows:
            visible = not row.isHidden()
            if row._line is not None:
                row._line.setVisible(visible and not first)
            if visible:
                first = False
        for i in range(self._lay.count()):
            w = self._lay.itemAt(i).widget()
            if w is not None and hasattr(w, "note_label"):
                w.setVisible(not searching)
        self.setVisible(not first or not self.rows)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, icon_name: str = None, parent=None, trailing=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        if icon_name:
            badge = _IconBadge(icon_name, 40)
            lay.addWidget(badge, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.title = QLabel(title.upper())
        f = theme.hud_font(17)
        f.setLetterSpacing(QFont.PercentageSpacing, 118)
        self.title.setFont(f)
        self.title.setStyleSheet(f"color: {theme.TEXT};")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet(f"color: {theme.MUTED}; font-size: 12.5px;")
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        lay.addLayout(col, 1)
        if trailing is not None:
            lay.addWidget(trailing, 0, Qt.AlignTop | Qt.AlignRight)


class _IconBadge(QWidget):
    """A glowing hexagon-ish ring with an icon inside — page headers and onboarding cards."""

    def __init__(self, icon_name: str, size: int = 40, color: str = theme.ACCENT, parent=None):
        super().__init__(parent)
        self._icon, self._color = icon_name, color
        self.setFixedSize(size, size)

    def set_color(self, color: str):
        self._color = color
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        r = QRectF(1, 1, s - 2, s - 2)
        p.setPen(QPen(theme.qcolor(self._color, 0.55), 1.2))
        p.setBrush(theme.qcolor(self._color, 0.08))
        p.drawRoundedRect(r, s * 0.28, s * 0.28)
        isz = int(s * 0.5)
        p.drawPixmap(int((s - isz) / 2), int((s - isz) / 2), theme.icon_pixmap(self._icon, isz, self._color))
        p.end()


IconBadge = _IconBadge


# ── nav rail ─────────────────────────────────────────────────────────────────
class NavButton(QAbstractButton):
    """Nav rail entry. Checkable; active = cyan bar + glow. ``set_badge(n)`` shows search hits."""

    def __init__(self, icon_name: str, text: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self.setFocusPolicy(Qt.TabFocus)
        self._badge = None
        self._dim = False
        self._hover = False

    def set_badge(self, count):
        self._badge = count
        self._dim = count == 0
        self.update()

    def badge(self):
        return self._badge

    def dimmed(self) -> bool:
        return self._dim

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def sizeHint(self):
        return QSize(180, 40)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        if on:
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, theme.qcolor(theme.ACCENT, 0.16))
            g.setColorAt(1, theme.qcolor(theme.ACCENT, 0.02))
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.30), 1))
            p.setBrush(g)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(r.left() + 1, r.top() + 10, 3, r.height() - 20), 1.5, 1.5)
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qcolor(theme.CARD, 0.9))
            p.drawRoundedRect(r, 8, 8)
        if self.hasFocus():
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.6), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 7, 7)
        color = theme.ACCENT if on else (theme.FAINT if self._dim else (theme.TEXT if self._hover else theme.TEXT_2))
        p.drawPixmap(14, int(r.center().y() - 9), theme.icon_pixmap(self.icon_name, 18, color))
        f = theme.text_font(10, QFont.DemiBold if on else QFont.Medium)
        p.setFont(f)
        p.setPen(QColor(color))
        text_r = r.adjusted(42, 0, -10, 0)
        if self._badge:
            txt = str(self._badge)
            bf = theme.hud_font(7.5)
            bw = QFontMetrics(bf).horizontalAdvance(txt) + 12
            badge = QRectF(r.right() - bw - 10, r.center().y() - 9, bw, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qcolor(theme.ACCENT, 0.9 if on else 0.22))
            p.drawRoundedRect(badge, 9, 9)
            p.setFont(bf)
            p.setPen(QColor("#00121A" if on else theme.ACCENT))
            p.drawText(badge, Qt.AlignCenter, txt)
            p.setFont(f)
            text_r.setRight(badge.left() - 6)
        p.setPen(QColor(color))
        p.drawText(text_r, Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(self.text(), Qt.ElideRight, int(text_r.width())))
        p.end()


# ── slider bound to a spin box ───────────────────────────────────────────────
class SliderSpin(QWidget):
    """A slider next to a compact spin box. The spin box stays the real value (tests / _values read it)."""

    changed = Signal()

    def __init__(self, spin, scale: float = 1.0, parent=None, value_width: int = 64):
        super().__init__(parent)
        self.spin = spin
        self._scale = scale
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(round(spin.minimum() * scale)), int(round(spin.maximum() * scale)))
        step = spin.singleStep() * scale
        self.slider.setSingleStep(max(1, int(round(step))))
        self.slider.setPageStep(max(1, int(round(step * 2))))
        self.slider.setCursor(Qt.PointingHandCursor)
        self._sync_from_spin()
        spin.setFixedWidth(value_width)
        spin.setAlignment(Qt.AlignCenter)
        spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.slider.valueChanged.connect(self._sync_to_spin)
        spin.valueChanged.connect(self._sync_from_spin)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self.slider, 1)
        lay.addWidget(spin)

    def _sync_from_spin(self, *_):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(self.spin.value() * self._scale)))
        self.slider.blockSignals(False)

    def _sync_to_spin(self, v):
        value = v / self._scale
        if abs(value - self.spin.value()) * self._scale >= 0.5:
            self.spin.setValue(value if isinstance(self.spin, QDoubleSpinBox) else int(value))
        self.changed.emit()


def sized(widget, width: int = CONTROL_WIDTH):
    """Controls share one width so both edges of every control column line up."""
    widget.setFixedWidth(width)
    return widget


def hbox(*widgets, spacing: int = 8, stretch_first: bool = False) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for i, x in enumerate(widgets):
        if x is None:
            lay.addStretch(1)
        elif isinstance(x, QWidget):
            lay.addWidget(x, 1 if (stretch_first and i == 0) else 0)
        else:
            lay.addLayout(x)
    return w
