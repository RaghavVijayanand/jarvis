"""The JARVIS HUD design system — one visual language for every surface.

Deep near-black glass, cyan light, amber for "doing something", thin lines,
corner brackets and uppercase letter-spaced captions. Everything (logo, icons,
the orb) is drawn in code: no image files, crisp at any DPI.

    colours     BG … ERROR, STATE_COLORS          (hex strings)
    fonts       FONT (text), HUD_FONT (captions), MONO (code)
    icons       icon(name, size=20, color=None) → QIcon     ICON_NAMES lists them
    logo        draw_logo(), logo_pixmap(), app_icon()
    stylesheet  app_stylesheet()                  (QSS for the whole app)
"""
from __future__ import annotations

import math

# ── palette ──────────────────────────────────────────────────────────────────
BG = "#04070C"            # window background
BG_2 = "#060B12"          # sidebars / deeper areas
SIDE = BG_2               # (older name)
PANEL = "#08101A"         # panels
CARD = "#0B1622"          # cards, bubbles
CARD_HI = "#0F1D2C"       # hovered card
INPUT = "#0A1520"         # inputs
BORDER = "#16324A"        # cyan-tinted hairlines
BORDER_SOFT = "#0E2131"
GRID = "#0B1824"          # background grid lines
ACCENT = "#00E5FF"        # JARVIS cyan
ACCENT_DIM = "#0A8FA8"
ACCENT_GLOW = "rgba(0, 229, 255, 38)"
ACCENT_2 = "#FFB547"      # amber: acting / attention
TEXT = "#DDF6FF"
TEXT_2 = "#A9C6D6"
MUTED = "#6F8BA0"
FAINT = "#3C5568"
SUCCESS = "#2EE59D"
WARN = "#FFB547"
ERROR = "#FF4D6D"
USER = "#7AA7FF"          # the user's own messages

# JARVIS's state → colour (orb, status pill, tray)
STATE_COLORS = {
    "idle": ACCENT,
    "listening": "#3DFFB0",
    "thinking": "#7AA7FF",
    "acting": ACCENT_2,
    "speaking": ACCENT,
    "error": ERROR,
    "offline": FAINT,
}
STATE_LABELS = {
    "idle": "Standing by", "listening": "Listening", "thinking": "Thinking", "acting": "Working",
    "speaking": "Speaking", "error": "Something went wrong", "offline": "Starting up",
}

FONT = '"Segoe UI Variable Text", "Segoe UI", "Inter", Arial, sans-serif'
HUD_FONT = '"Bahnschrift", "Segoe UI Semibold", "DejaVu Sans Condensed", "Segoe UI", sans-serif'
MONO = '"Cascadia Code", "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace'


def qcolor(value, alpha: float = None):
    from PySide6.QtGui import QColor
    c = QColor(value)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def hud_font(size: float = 9, bold: bool = True):
    """Captions: condensed, uppercase-friendly, letter-spaced."""
    from PySide6.QtGui import QFont
    f = QFont()
    f.setFamilies(["Bahnschrift", "Segoe UI Semibold", "DejaVu Sans Condensed", "Segoe UI"])
    f.setPointSizeF(size)
    f.setWeight(QFont.DemiBold if bold else QFont.Normal)
    f.setLetterSpacing(QFont.PercentageSpacing, 112)
    return f


def text_font(size: float = 10.5, weight=None):
    from PySide6.QtGui import QFont
    f = QFont()
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Arial"])
    f.setPointSizeF(size)
    if weight is not None:
        f.setWeight(weight)
    return f


# ── logo ─────────────────────────────────────────────────────────────────────
def draw_logo(painter, size: int, background: bool = True):
    """The JARVIS mark: a cyan ring with a gap and a dot — the same shape as the cursor buddy."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPen
    painter.setRenderHint(painter.RenderHint.Antialiasing)
    if background:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(BG))
        radius = size * 0.22
        painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    pen = QPen(QColor(ACCENT), max(1.5, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    m = size * 0.2
    painter.drawArc(QRectF(m, m, size - 2 * m, size - 2 * m), 60 * 16, 300 * 16)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(ACCENT))
    r = size * 0.11
    painter.drawEllipse(QRectF(size / 2 - r, size / 2 - r, 2 * r, 2 * r))


def app_icon(busy: bool = False):
    """A crisp multi-size QIcon (tray, taskbar, windows) — no image files needed."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        draw_logo(p, size)
        if busy:                                   # an amber dot: "working on it"
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT_2))
            d = size * 0.34
            p.drawEllipse(int(size - d), int(size - d), int(d), int(d))
        p.end()
        icon.addPixmap(pix)
    return icon


def logo_pixmap(size: int = 40, background: bool = False):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPixmap
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    draw_logo(p, size, background=background)
    p.end()
    return pix


# ── icon set (line icons on a 24-unit grid) ──────────────────────────────────
def _pt(x, y):
    from PySide6.QtCore import QPointF
    return QPointF(x, y)


def _path(points, close=False):
    from PySide6.QtGui import QPainterPath
    path = QPainterPath(_pt(*points[0]))
    for x, y in points[1:]:
        path.lineTo(_pt(x, y))
    if close:
        path.closeSubpath()
    return path


def _d_chat(p):
    from PySide6.QtCore import QRectF
    p.drawRoundedRect(QRectF(3.5, 4.5, 17, 12), 3.5, 3.5)
    p.drawPath(_path([(8, 16.5), (7, 20), (11.5, 16.5)]))


def _d_bolt(p):
    p.drawPath(_path([(13.5, 3), (5.5, 13.5), (11.5, 13.5), (10.5, 21), (18.5, 10.5), (12.5, 10.5)], close=True))


def _d_pulse(p):
    p.drawPath(_path([(3, 12.5), (7.5, 12.5), (9.5, 7), (13, 18), (15.5, 10), (17, 12.5), (21, 12.5)]))


def _d_brain(p):
    from PySide6.QtCore import QRectF
    p.drawArc(QRectF(4, 4, 9, 9), 60 * 16, 210 * 16)
    p.drawArc(QRectF(11, 4, 9, 9), -90 * 16, 210 * 16)
    p.drawArc(QRectF(4, 11, 9, 9), 90 * 16, 210 * 16)
    p.drawArc(QRectF(11, 11, 9, 9), -120 * 16, 210 * 16)
    p.drawLine(_pt(12, 5), _pt(12, 19))


def _d_gear(p):
    from PySide6.QtCore import QRectF
    p.drawEllipse(QRectF(9, 9, 6, 6))
    for i in range(8):
        a = i * math.pi / 4
        p.drawLine(_pt(12 + 6.2 * math.cos(a), 12 + 6.2 * math.sin(a)), _pt(12 + 8.6 * math.cos(a), 12 + 8.6 * math.sin(a)))
    p.drawEllipse(QRectF(5.8, 5.8, 12.4, 12.4))


def _d_mic(p):
    from PySide6.QtCore import QRectF
    p.drawRoundedRect(QRectF(9, 3.5, 6, 11), 3, 3)
    p.drawArc(QRectF(6, 7, 12, 11), 200 * 16, 140 * 16)
    p.drawLine(_pt(12, 18), _pt(12, 21))
    p.drawLine(_pt(8.5, 21), _pt(15.5, 21))


def _d_speaker(p):
    from PySide6.QtCore import QRectF
    p.drawPath(_path([(4, 9.5), (8, 9.5), (12.5, 5.5), (12.5, 18.5), (8, 14.5), (4, 14.5)], close=True))
    p.drawArc(QRectF(11, 8, 7, 8), -50 * 16, 100 * 16)
    p.drawArc(QRectF(11, 5, 10, 14), -50 * 16, 100 * 16)


def _d_speaker_off(p):
    p.drawPath(_path([(4, 9.5), (8, 9.5), (12.5, 5.5), (12.5, 18.5), (8, 14.5), (4, 14.5)], close=True))
    p.drawLine(_pt(15.5, 9.5), _pt(20.5, 14.5))
    p.drawLine(_pt(20.5, 9.5), _pt(15.5, 14.5))


def _d_eye(p):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath(_pt(2.5, 12))
    path.quadTo(_pt(12, 3), _pt(21.5, 12))
    path.quadTo(_pt(12, 21), _pt(2.5, 12))
    p.drawPath(path)
    p.drawEllipse(QRectF(9, 9, 6, 6))


def _d_cursor(p):
    p.drawPath(_path([(5, 3.5), (5, 18.5), (9.5, 14.5), (12.5, 20.5), (15, 19.3), (12, 13.5), (18, 13.5)], close=True))


def _d_stop(p):
    from PySide6.QtCore import QRectF
    p.drawRoundedRect(QRectF(6, 6, 12, 12), 2.5, 2.5)


def _d_send(p):
    p.drawPath(_path([(3.5, 11), (20.5, 4), (14, 20.5), (11, 13.5)], close=True))
    p.drawLine(_pt(11, 13.5), _pt(20.5, 4))


def _d_camera(p):
    from PySide6.QtCore import QRectF
    p.drawRoundedRect(QRectF(3, 7, 18, 12.5), 2.5, 2.5)
    p.drawPath(_path([(8, 7), (9.5, 4.5), (14.5, 4.5), (16, 7)]))
    p.drawEllipse(QRectF(8.5, 9.5, 7, 7))


def _d_plus(p):
    p.drawLine(_pt(12, 5), _pt(12, 19))
    p.drawLine(_pt(5, 12), _pt(19, 12))


def _d_close(p):
    p.drawLine(_pt(6, 6), _pt(18, 18))
    p.drawLine(_pt(18, 6), _pt(6, 18))


def _d_check(p):
    p.drawPath(_path([(5, 12.5), (10, 17.5), (19.5, 7)]))


def _d_copy(p):
    from PySide6.QtCore import QRectF
    p.drawRoundedRect(QRectF(8.5, 8.5, 11.5, 11.5), 2, 2)
    p.drawPath(_path([(15.5, 8.5), (15.5, 4), (4, 4), (4, 15.5), (8.5, 15.5)]))


def _d_expand(p):
    p.drawPath(_path([(4, 9), (4, 4), (9, 4)]))
    p.drawPath(_path([(15, 20), (20, 20), (20, 15)]))
    p.drawLine(_pt(4.5, 4.5), _pt(10, 10))
    p.drawLine(_pt(19.5, 19.5), _pt(14, 14))


def _d_trash(p):
    from PySide6.QtCore import QRectF
    p.drawLine(_pt(4, 6.5), _pt(20, 6.5))
    p.drawPath(_path([(9, 6.5), (9.5, 3.5), (14.5, 3.5), (15, 6.5)]))
    p.drawPath(_path([(6, 6.5), (7, 20.5), (17, 20.5), (18, 6.5)]))


def _d_search(p):
    from PySide6.QtCore import QRectF
    p.drawEllipse(QRectF(4, 4, 12, 12))
    p.drawLine(_pt(14.5, 14.5), _pt(20, 20))


def _d_sparkle(p):
    from PySide6.QtGui import QPainterPath
    path = QPainterPath(_pt(12, 3))
    for a, b in (((12.8, 11.2), (21, 12)), ((12.8, 12.8), (12, 21)), ((11.2, 12.8), (3, 12)), ((11.2, 11.2), (12, 3))):
        path.quadTo(_pt(*a), _pt(*b))
    p.drawPath(path)


def _d_clock(p):
    from PySide6.QtCore import QRectF
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
    p.drawPath(_path([(12, 7), (12, 12), (15.5, 14)]))


def _d_globe(p):
    from PySide6.QtCore import QRectF
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
    p.drawEllipse(QRectF(8, 3.5, 8, 17))
    p.drawLine(_pt(3.5, 12), _pt(20.5, 12))


def _d_key(p):
    from PySide6.QtCore import QRectF
    p.drawEllipse(QRectF(3.5, 8.5, 7, 7))
    p.drawPath(_path([(10.5, 12), (20.5, 12), (20.5, 15.5)]))
    p.drawLine(_pt(16.5, 12), _pt(16.5, 15))


def _d_keyboard(p):
    from PySide6.QtCore import QRectF
    p.drawRoundedRect(QRectF(2.5, 6.5, 19, 11), 2.5, 2.5)
    for x in (6.5, 10, 13.5, 17):
        p.drawPoint(_pt(x, 10))
    p.drawLine(_pt(7.5, 14), _pt(16.5, 14))


def _d_power(p):
    from PySide6.QtCore import QRectF
    p.drawArc(QRectF(4.5, 5, 15, 15), 120 * 16, 300 * 16)
    p.drawLine(_pt(12, 3), _pt(12, 11))


def _d_shield(p):
    from PySide6.QtGui import QPainterPath
    path = QPainterPath(_pt(12, 3))
    path.lineTo(_pt(19.5, 6))
    path.quadTo(_pt(19.5, 16), _pt(12, 21))
    path.quadTo(_pt(4.5, 16), _pt(4.5, 6))
    path.closeSubpath()
    p.drawPath(path)


def _d_sliders(p):
    from PySide6.QtCore import QRectF
    for y, x in ((6, 15), (12, 8), (18, 13)):
        p.drawLine(_pt(3.5, y), _pt(20.5, y))
        p.drawEllipse(QRectF(x - 2, y - 2, 4, 4))


def _d_user(p):
    from PySide6.QtCore import QRectF
    p.drawEllipse(QRectF(8, 3.5, 8, 8))
    p.drawArc(QRectF(4.5, 13.5, 15, 13), 0, 180 * 16)


def _d_folder(p):
    p.drawPath(_path([(3, 6.5), (9.5, 6.5), (11.5, 8.5), (21, 8.5), (21, 19), (3, 19)], close=True))


def _d_play(p):
    p.drawPath(_path([(8, 5), (19, 12), (8, 19)], close=True))


def _d_pause(p):
    p.drawLine(_pt(9, 5.5), _pt(9, 18.5))
    p.drawLine(_pt(15, 5.5), _pt(15, 18.5))


def _d_list(p):
    for y in (7, 12, 17):
        p.drawLine(_pt(9, y), _pt(20, y))
        p.drawPoint(_pt(4.5, y))


def _d_chip(p):
    from PySide6.QtCore import QRectF
    p.drawRoundedRect(QRectF(6.5, 6.5, 11, 11), 1.5, 1.5)
    for v in (9.5, 14.5):
        for a, b in (((v, 3), (v, 6.5)), ((v, 17.5), (v, 21)), ((3, v), (6.5, v)), ((17.5, v), (21, v))):
            p.drawLine(_pt(*a), _pt(*b))


def _d_download(p):
    p.drawLine(_pt(12, 3.5), _pt(12, 15))
    p.drawPath(_path([(7, 10.5), (12, 15.5), (17, 10.5)]))
    p.drawPath(_path([(4, 16), (4, 20), (20, 20), (20, 16)]))


def _d_refresh(p):
    from PySide6.QtCore import QRectF
    p.drawArc(QRectF(4.5, 4.5, 15, 15), 30 * 16, 290 * 16)
    p.drawPath(_path([(19.5, 3.5), (19.3, 8.3), (14.5, 8)]))


def _d_bell(p):
    from PySide6.QtGui import QPainterPath
    path = QPainterPath(_pt(5, 17))
    path.lineTo(_pt(19, 17))
    path.quadTo(_pt(17, 15), _pt(17, 10.5))
    path.quadTo(_pt(17, 5), _pt(12, 5))
    path.quadTo(_pt(7, 5), _pt(7, 10.5))
    path.quadTo(_pt(7, 15), _pt(5, 17))
    p.drawPath(path)
    p.drawLine(_pt(10.5, 20), _pt(13.5, 20))


def _d_wave(p):
    for x, h in ((5, 3), (8.5, 7), (12, 11), (15.5, 7), (19, 3)):
        p.drawLine(_pt(x, 12 - h / 2), _pt(x, 12 + h / 2))


def _d_home(p):
    p.drawPath(_path([(3.5, 11.5), (12, 4), (20.5, 11.5)]))
    p.drawPath(_path([(6, 9.5), (6, 20), (18, 20), (18, 9.5)]))


def _d_more(p):
    for x in (6, 12, 18):
        p.drawPoint(_pt(x, 12))


_DRAW = {
    "chat": _d_chat, "bolt": _d_bolt, "pulse": _d_pulse, "brain": _d_brain, "gear": _d_gear, "mic": _d_mic,
    "speaker": _d_speaker, "speaker_off": _d_speaker_off, "eye": _d_eye, "cursor": _d_cursor, "stop": _d_stop,
    "send": _d_send, "camera": _d_camera, "plus": _d_plus, "close": _d_close, "check": _d_check, "copy": _d_copy,
    "expand": _d_expand, "trash": _d_trash, "search": _d_search, "sparkle": _d_sparkle, "clock": _d_clock,
    "globe": _d_globe, "key": _d_key, "keyboard": _d_keyboard, "power": _d_power, "shield": _d_shield,
    "sliders": _d_sliders, "user": _d_user, "folder": _d_folder, "play": _d_play, "pause": _d_pause,
    "list": _d_list, "chip": _d_chip, "download": _d_download, "refresh": _d_refresh, "bell": _d_bell,
    "wave": _d_wave, "home": _d_home, "more": _d_more,
}
ICON_NAMES = tuple(sorted(_DRAW))
_ICON_CACHE = {}


def icon_pixmap(name: str, size: int = 20, color: str = None, dpr: float = 2.0):
    """One icon rendered at ``size`` logical px (``dpr`` × for HiDPI)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPen, QPixmap
    draw = _DRAW.get(name)
    if draw is None:
        raise KeyError(f"unknown icon {name!r}; known: {', '.join(ICON_NAMES)}")
    px = max(1, int(round(size * dpr)))
    pix = QPixmap(px, px)
    pix.fill(Qt.transparent)
    pix.setDevicePixelRatio(dpr)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    pen = QPen(qcolor(color or TEXT_2), 1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    draw(p)
    p.end()
    return pix


def icon(name: str, size: int = 20, color: str = None, active: str = None, checked: str = None):
    """A QIcon with normal / hover(active) / checked colours. Cached."""
    key = (name, size, color, active, checked)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    from PySide6.QtGui import QIcon
    ic = QIcon()
    normal, hot, on = color or TEXT_2, active or ACCENT, checked or ACCENT
    for mode, c in ((QIcon.Normal, normal), (QIcon.Active, hot), (QIcon.Selected, hot), (QIcon.Disabled, FAINT)):
        ic.addPixmap(icon_pixmap(name, size, c), mode, QIcon.Off)
        ic.addPixmap(icon_pixmap(name, size, on if mode != QIcon.Disabled else FAINT), mode, QIcon.On)
    _ICON_CACHE[key] = ic
    return ic


# kept for older callers
def mic_icon():
    return icon("mic")


def expand_icon():
    return icon("expand")


def _icon(draw, size: int = 32, color: str = MUTED):          # pragma: no cover - legacy helper
    return icon("more", size, color)


# ── stylesheet ───────────────────────────────────────────────────────────────
def app_stylesheet() -> str:
    """Base QSS for every JARVIS window. Surfaces add their own objectName rules on top."""
    return f"""
* {{ outline: none; }}
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: {FONT};
    font-size: 13px;
    selection-background-color: {ACCENT_DIM};
    selection-color: #001018;
}}
QMainWindow, QDialog, QWizard {{ background: {BG}; }}
QToolTip {{
    background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px 9px; border-radius: 6px;
}}
QLabel#caption, QLabel[hud="true"] {{
    color: {MUTED}; font-family: {HUD_FONT}; font-size: 10px; letter-spacing: 2px; font-weight: 600;
}}
QLabel#title {{ color: {TEXT}; font-family: {HUD_FONT}; font-size: 20px; letter-spacing: 1px; font-weight: 600; }}
QLabel#subtitle, QLabel#muted {{ color: {MUTED}; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {INPUT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    padding: 7px 10px;
    color: {TEXT};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {BORDER}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT_DIM};
    background: #0C1926;
}}
QLineEdit:disabled, QComboBox:disabled {{ color: {FAINT}; border-color: {BORDER_SOFT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {MUTED}; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; color: {TEXT}; padding: 4px;
    selection-background-color: {CARD_HI}; selection-color: {ACCENT}; outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}

QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    padding: 7px 14px;
    color: {TEXT_2};
    font-weight: 500;
}}
QPushButton:hover {{ border-color: {ACCENT_DIM}; color: {ACCENT}; background: {CARD_HI}; }}
QPushButton:pressed {{ background: #0A2030; }}
QPushButton:checked {{ border-color: {ACCENT}; color: {ACCENT}; background: rgba(0, 229, 255, 22); }}
QPushButton:disabled {{ color: {FAINT}; border-color: {BORDER_SOFT}; }}
QPushButton#primary, QPushButton:default {{
    background: {ACCENT}; color: #00121A; border: none; font-weight: 700;
}}
QPushButton#primary:hover, QPushButton:default:hover {{ background: #5CF0FF; color: #00121A; }}
QPushButton#danger {{ color: {ERROR}; border-color: rgba(255, 77, 109, 90); }}
QPushButton#danger:hover {{ background: rgba(255, 77, 109, 28); color: #FF8098; border-color: {ERROR}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {MUTED}; }}
QPushButton#ghost:hover {{ color: {ACCENT}; border-color: {BORDER_SOFT}; }}
QPushButton#chip {{
    background: {CARD}; border: 1px solid {BORDER_SOFT}; border-radius: 14px; padding: 5px 13px;
    color: {TEXT_2}; font-size: 12px;
}}
QPushButton#chip:hover {{ border-color: {ACCENT_DIM}; color: {ACCENT}; }}

QCheckBox, QRadioButton {{ spacing: 10px; color: {TEXT_2}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1.5px solid {FAINT}; background: {INPUT};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {ACCENT_DIM}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QListWidget, QTreeWidget, QTableWidget {{
    background: {PANEL}; border: 1px solid {BORDER_SOFT}; border-radius: 10px; padding: 4px;
    alternate-background-color: {CARD};
}}
QListWidget::item, QTreeWidget::item {{ padding: 7px 8px; border-radius: 6px; color: {TEXT_2}; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {CARD}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {CARD_HI}; color: {ACCENT}; }}
QHeaderView::section {{
    background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER_SOFT}; padding: 6px;
    font-family: {HUD_FONT}; font-size: 10px; letter-spacing: 1px;
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 1px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 1px 4px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 3px; min-width: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenuBar {{ background: {BG_2}; color: {MUTED}; border-bottom: 1px solid {BORDER_SOFT}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ color: {ACCENT}; background: {CARD}; }}
QMenu {{
    background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; border-radius: 10px;
}}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {CARD_HI}; color: {ACCENT}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; }}

QTabWidget::pane {{ border: 1px solid {BORDER_SOFT}; border-radius: 10px; top: -1px; background: {PANEL}; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 8px 16px; border: none; border-bottom: 2px solid transparent;
    font-family: {HUD_FONT}; letter-spacing: 1px;
}}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom-color: {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QProgressBar {{ background: {INPUT}; border: 1px solid {BORDER_SOFT}; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER_SOFT}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT_DIM}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QStatusBar {{ background: {BG_2}; color: {MUTED}; border-top: 1px solid {BORDER_SOFT}; }}
QStatusBar::item {{ border: none; }}
QMessageBox {{ background: {BG}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
"""


# The command bar (ui/command_bar.py) appends its own rules to the base sheet.
BAR_STYLESHEET = app_stylesheet()
