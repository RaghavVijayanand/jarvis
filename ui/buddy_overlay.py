"""The Clicky-style overlay: a small HUD companion that follows the cursor and points at things.

A frameless, see-through, always-on-top window covering the whole desktop. It
never takes mouse or keyboard input (clicks pass straight through), and on
Windows 10 2004+ it is excluded from screen capture, so JARVIS's own
screenshots never contain it.

States (driven by core.buddy.BuddyController events):
    idle       a tiny static arc reactor next to the cursor
    listening  green, rings expanding out of the core (the hotkey is held)
    thinking   blue, a segmented arc spinning around the core
    answer     cyan pulse + a glass HUD plate with the reply
    point      a dashed trajectory draws from the buddy to each target, a
               targeting reticle locks on (brackets rotate and close in) and a
               numbered label plate ("01  File menu") names it

Cheap by design: the 60 fps timer only calls ``update()`` while something is
animating (or the cursor moved), and — unless targets are on screen — only the
small region around the buddy and its bubble is repainted, never the whole
desktop-sized window. The timer stops entirely while the overlay is hidden.
"""
from __future__ import annotations

import math
import sys
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from ui import theme

ACCENT = QColor(theme.ACCENT)                 # JARVIS cyan
ACCENT_SOFT = theme.qcolor(theme.ACCENT, 0.28)
BUBBLE_BG = QColor(6, 12, 20, 238)
BUBBLE_FG = QColor(theme.TEXT)
SHADOW = QColor(2, 8, 14)                     # dark under-stroke: keeps the HUD legible on light apps

WDA_EXCLUDEFROMCAPTURE = 0x11

BUBBLE_MAX_WIDTH = 360
BUBBLE_MAX_LINES = 7


def exclude_from_capture(widget: QWidget) -> bool:
    """Hide the overlay from screenshots/screen sharing (Windows 10 2004+). Best effort."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


def physical_to_logical(x: int, y: int) -> QPoint:
    """Screen automation works in physical pixels of the primary screen; Qt paints in logical ones."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return QPoint(int(x), int(y))
    ratio = screen.devicePixelRatio() or 1.0
    geo = screen.geometry()
    return QPoint(geo.x() + int(round(x / ratio)), geo.y() + int(round(y / ratio)))


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _col(base, alpha: float) -> QColor:
    c = QColor(base)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _brackets(p: QPainter, c: QPointF, half: float, arm: float):
    """Four corner brackets around ``c`` (square of side 2*half)."""
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, y = c.x() + sx * half, c.y() + sy * half
        path = QPainterPath(QPointF(x, y - sy * arm))
        path.lineTo(QPointF(x, y))
        path.lineTo(QPointF(x - sx * arm, y))
        p.drawPath(path)


class BuddyOverlay(QWidget):
    POINT_SECONDS = 9.0
    BUBBLE_SECONDS = 7.0
    FLIGHT_SECONDS = 0.55
    STAGGER = 0.35               # each target launches a little after the previous one
    BUDDY_OFFSET = QPoint(22, 24)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.state = "idle"
        self.message = ""
        self.hint = ""
        self.tone = "answer"                  # what the bubble is: answer / error / heard / hint / listening
        self._message_until = 0.0
        self._message_since = 0.0
        self._points: List[Tuple[QPoint, str]] = []
        self._points_since = 0.0
        self._points_until = 0.0
        self._state_since = time.monotonic()
        self._cursor = QCursor.pos()
        self._excluded = False
        self._was_animating = False
        self._last_dirty = QRect()
        self._bubble_cache = None
        self._f_text = theme.text_font(10)
        self._f_caption = theme.hud_font(7)
        self._f_number = theme.hud_font(8.5)
        self._f_label = theme.text_font(9.5, QFont.DemiBold)
        self._cover_desktop()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # geometry
    def _cover_desktop(self):
        rect = QRect()
        for screen in QGuiApplication.screens():
            rect = rect.united(screen.geometry())
        if rect.isNull():
            rect = QRect(0, 0, 1280, 720)
        self.setGeometry(rect)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()
        if not self._excluded:
            self._excluded = exclude_from_capture(self)

    def hideEvent(self, event):
        self._timer.stop()                    # hidden: no ticking at all
        super().hideEvent(event)

    # state API (GUI thread only — the main window forwards controller events via a signal)
    def set_state(self, kind: str, info: Optional[dict] = None):
        info = info or {}
        now = time.monotonic()
        if kind == "point":
            self._points = [(physical_to_logical(x, y), label) for x, y, label in info.get("points", [])]
            self._points_since, self._points_until = now, now + self.POINT_SECONDS
            return self.update()
        if kind in ("answer", "error") or (kind == "idle" and info.get("message")):
            self._set_message(info.get("text") or info.get("message") or "", now, now + self.BUBBLE_SECONDS,
                              "error" if kind == "error" else "answer")
        if kind == "heard":
            self._set_message(f"“{info.get('text', '')}”", now, now + self.BUBBLE_SECONDS, "heard")
            return self.update()
        if kind == "idle" and info.get("hotkey"):
            self.hint = f"{info['hotkey']} and talk"
            self._set_message(f"Buddy is on — {self.hint}.", now, now + 4, "hint")
        if kind in ("listening", "thinking"):
            self._set_message("Listening…" if kind == "listening" else "", now, now + 30, kind)
            if kind == "listening":
                self._points = []
        self.state = "idle" if kind in ("answer", "error", "idle") else kind
        self._state_since = now
        self.update()

    def _set_message(self, text: str, now: float, until: float, tone: str):
        if text != self.message:
            self._message_since = now
        self.message = text
        self._message_until = until
        self.tone = tone

    def clear(self):
        self._points, self.message = [], ""
        self.update()

    # animation bookkeeping
    def animating(self, now: Optional[float] = None) -> bool:
        """True while something moves on its own (so the 60 fps repaint is needed)."""
        now = time.monotonic() if now is None else now
        return bool(self.state != "idle" or self._points or (self.message and now < self._message_until))

    def _tick(self):
        pos = QCursor.pos()
        now = time.monotonic()
        had_points = bool(self._points)
        if self._points and now > self._points_until:
            self._points = []
        busy = self.animating(now)
        # repaint while animating, when the cursor moves, and once more when an animation ends (to erase it)
        if pos != self._cursor or busy or self._was_animating or had_points != bool(self._points):
            self._cursor = pos
            self._repaint(now, full=had_points or bool(self._points))
        self._was_animating = busy

    def _repaint(self, now: float, full: bool = False):
        if full:
            self._last_dirty = QRect()
            self.update()
            return
        dirty = self._dirty_rect(now)
        self.update(dirty.united(self._last_dirty))
        self._last_dirty = dirty

    def _dirty_rect(self, now: float) -> QRect:
        c = self._buddy_center()
        rect = QRectF(c.x() - 36, c.y() - 36, 72, 72)
        if self.message and now < self._message_until:
            bubble = self._bubble_layout(c, self.message)[0]
            rect = rect.united(bubble.adjusted(-6, -6, 6, 6))
        return rect.toAlignedRect()

    # painting
    def _buddy_center(self) -> QPointF:
        local = self.mapFromGlobal(self._cursor)
        return QPointF(local.x() + self.BUDDY_OFFSET.x(), local.y() + self.BUDDY_OFFSET.y())

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = time.monotonic()
        center = self._buddy_center()
        self._paint_points(p, center, now)
        if self.message and now < self._message_until:
            self._paint_bubble(p, center, self.message, now)
        self._paint_buddy(p, center, now)
        p.end()

    def _mode(self, now: float) -> str:
        if self.state in ("listening", "thinking"):
            return self.state
        if self.message and now < self._message_until:
            return "error" if self.tone == "error" else "speaking"
        if self._points:
            return "speaking"
        return "idle"

    def _paint_buddy(self, p: QPainter, c: QPointF, now: float):
        """A tiny arc reactor: halo, ring, state layer, bright core."""
        mode = self._mode(now)
        col = QColor(theme.STATE_COLORS.get(mode, theme.ACCENT))
        t = now - self._state_since
        pulse = 0.5 + 0.5 * math.sin(now * 5.0)
        p.save()
        # halo
        halo = QRadialGradient(c, 18)
        halo.setColorAt(0.0, _col(col, 0.30 if mode != "idle" else 0.18))
        halo.setColorAt(1.0, _col(col, 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, 18, 18)
        backing = QRadialGradient(c, 15)
        backing.setColorAt(0.0, _col(SHADOW, 0.55))
        backing.setColorAt(0.75, _col(SHADOW, 0.40))
        backing.setColorAt(1.0, _col(SHADOW, 0.0))
        p.setBrush(backing)
        p.drawEllipse(c, 15, 15)
        p.setBrush(Qt.NoBrush)
        ring = QRectF(c.x() - 10, c.y() - 10, 20, 20)

        if mode == "listening":
            for k in range(3):
                phase = (t * 1.1 + k / 3) % 1.0
                r = 9 + 17 * phase
                p.setPen(QPen(_col(col, 0.75 * (1 - phase) ** 1.5), 1.4))
                p.drawEllipse(c, r, r)
            pen = QPen(_col(col, 0.9), 1.6)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            for k in range(4):
                p.drawArc(ring, int((k * 90 + 12 + now * 40) * 16), 66 * 16)
        elif mode == "thinking":
            pen = QPen(_col(col, 0.95), 2.2)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            big = QRectF(c.x() - 12.5, c.y() - 12.5, 25, 25)
            spin = -(now * 300) % 360
            for k in range(3):
                span = 50 + 30 * abs(math.sin(now * 3 + k))
                p.drawArc(big, int((spin + k * 120) * 16), int(span * 16))
            p.setPen(QPen(_col(col, 0.55), 1.2))
            small = QRectF(c.x() - 7.5, c.y() - 7.5, 15, 15)
            p.drawArc(small, int(((now * 420) % 360) * 16), 140 * 16)
        elif mode in ("speaking", "error"):
            phase = (now * 0.9) % 1.0
            r = 10 + 12 * phase
            p.setPen(QPen(_col(col, 0.6 * (1 - phase)), 1.2))
            p.drawEllipse(c, r, r)
            p.setPen(QPen(_col(col, 0.55 + 0.4 * pulse), 1.5))
            p.drawEllipse(c, 10, 10)
        else:                                   # idle: static, costs nothing
            pen = QPen(_col(col, 0.75), 1.4)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            for k in range(3):
                p.drawArc(ring, int((k * 120 + 30) * 16), 80 * 16)

        # reticle ticks
        p.setPen(QPen(_col(col, 0.55), 1))
        for k in range(4):
            a = k * math.pi / 2 + math.pi / 4
            p.drawLine(QPointF(c.x() + 13 * math.cos(a), c.y() + 13 * math.sin(a)),
                       QPointF(c.x() + 15.5 * math.cos(a), c.y() + 15.5 * math.sin(a)))
        # core
        core_r = 4.6 + (1.2 * pulse if mode in ("speaking", "listening") else 0.0)
        core = QRadialGradient(c, core_r + 2)
        core.setColorAt(0.0, QColor(255, 255, 255, 250))
        core.setColorAt(0.45, _col(col, 0.95))
        core.setColorAt(1.0, _col(col, 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(core)
        p.drawEllipse(c, core_r + 2, core_r + 2)
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawEllipse(c, 1.7, 1.7)
        p.restore()

    # ── the speech bubble ────────────────────────────────────────────────────
    def _caption(self) -> Tuple[str, QColor]:
        if self.tone == "error":
            return "ERROR", QColor(theme.ERROR)
        if self.tone == "heard":
            return "YOU SAID", QColor(theme.USER)
        if self.tone == "listening":
            return "LISTENING", QColor(theme.STATE_COLORS["listening"])
        return "JARVIS", QColor(theme.ACCENT)

    def _wrap(self, text: str, width: int) -> Tuple[str, int]:
        """Fit ``text`` in ``BUBBLE_MAX_LINES`` lines of ``width`` (eliding the end) → (text, height)."""
        metrics = QFontMetrics(self._f_text)
        max_h = metrics.lineSpacing() * BUBBLE_MAX_LINES
        bound = metrics.boundingRect(QRect(0, 0, width, 10000), Qt.TextWordWrap, text)
        if bound.height() <= max_h:
            return text, bound.height()
        lo, hi = 0, len(text)
        while lo < hi:                          # longest prefix that still fits
            mid = (lo + hi + 1) // 2
            candidate = text[:mid].rstrip() + "…"
            if metrics.boundingRect(QRect(0, 0, width, 10000), Qt.TextWordWrap, candidate).height() <= max_h:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…", max_h

    def _bubble_layout(self, c: QPointF, text: str):
        """(plate rect, text rect, wrapped text) for a bubble next to the buddy at ``c``."""
        key = (text, self.tone)
        if self._bubble_cache is None or self._bubble_cache[0] != key:
            if self.tone == "listening":             # a compact "● LISTENING ▮▮▮" plate
                self._bubble_cache = (key, 138, 26, text)
            else:
                self._bubble_cache = (key,) + self._measure_bubble(text)
        _, width, height, wrapped = self._bubble_cache
        area = QRectF(self.rect())
        x, y = c.x() + 24, c.y() + (-13 if self.tone == "listening" else 8)
        if x + width > area.right() - 8:
            x = c.x() - width - 24
        if y + height > area.bottom() - 8:
            y = c.y() - height - 8
        x = max(area.left() + 8, x)
        y = max(area.top() + 8, y)
        rect = QRectF(x, y, width, height)
        return rect, rect.adjusted(14, 26, -14, -12), wrapped

    def _measure_bubble(self, text: str):
        metrics = QFontMetrics(self._f_text)
        pad_x = 14
        width = int(min(BUBBLE_MAX_WIDTH, max(170, metrics.horizontalAdvance(text) + 2 * pad_x + 2)))
        wrapped, text_h = self._wrap(text, width - 2 * pad_x)
        height = 26 + text_h + 12
        return width, height, wrapped

    def _paint_bubble(self, p: QPainter, c: QPointF, text: str, now: float):
        rect, text_rect, wrapped = self._bubble_layout(c, text)
        caption, tone = self._caption()
        appear = _ease_out((now - self._message_since) / 0.22)
        fade = min(1.0, max(0.0, (self._message_until - now) / 0.4))
        alpha = appear * fade
        if alpha <= 0:
            return
        p.save()
        p.setOpacity(alpha)
        if self.tone == "listening":
            self._paint_listening_plate(p, rect, tone, now)
            p.restore()
            return
        offset = (1 - appear) * 6
        p.translate(-offset if rect.center().x() < c.x() else offset, 0)
        # leader line from the buddy to the plate's nearest corner
        corner = QPointF(rect.left() if rect.left() > c.x() else rect.right(),
                         rect.top() + 13 if rect.top() > c.y() - 20 else rect.bottom() - 13)
        ang = math.atan2(corner.y() - c.y(), corner.x() - c.x())
        p.setPen(QPen(_col(tone, 0.45), 1))
        p.drawLine(QPointF(c.x() + 17 * math.cos(ang), c.y() + 17 * math.sin(ang)), corner)
        # glass plate
        p.setPen(QPen(_col(tone, 0.32), 1))
        p.setBrush(BUBBLE_BG)
        p.drawRoundedRect(rect, 5, 5)
        head = QRectF(rect.left() + 1, rect.top() + 1, rect.width() - 2, 20)
        p.fillRect(head, _col(tone, 0.07))
        pen = QPen(_col(tone, 0.95), 1.5)
        pen.setCapStyle(Qt.SquareCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = rect.adjusted(-2, -2, 2, 2)
        for sx, sy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            x = r.right() if sx else r.left()
            y = r.bottom() if sy else r.top()
            dx, dy = (-8 if sx else 8), (-8 if sy else 8)
            path = QPainterPath(QPointF(x, y + dy))
            path.lineTo(QPointF(x, y))
            path.lineTo(QPointF(x + dx, y))
            p.drawPath(path)
        # caption row: ◆ JARVIS ───────────
        p.setPen(Qt.NoPen)
        p.setBrush(tone)
        d = QPointF(rect.left() + 16, rect.top() + 11)
        diamond = QPainterPath(QPointF(d.x(), d.y() - 3))
        for dx, dy in ((3, 0), (0, 3), (-3, 0)):
            diamond.lineTo(QPointF(d.x() + dx, d.y() + dy))
        diamond.closeSubpath()
        p.drawPath(diamond)
        p.setFont(self._f_caption)
        p.setPen(_col(tone, 0.95))
        cap_rect = QRectF(rect.left() + 24, rect.top() + 3, rect.width() - 36, 16)
        p.drawText(cap_rect, Qt.AlignLeft | Qt.AlignVCenter, caption)
        cap_w = QFontMetrics(self._f_caption).horizontalAdvance(caption)
        p.setPen(QPen(_col(tone, 0.22), 1))
        p.drawLine(QPointF(cap_rect.left() + cap_w + 8, rect.top() + 11), QPointF(rect.right() - 12, rect.top() + 11))
        # text
        p.setFont(self._f_text)
        p.setPen(BUBBLE_FG if self.tone != "heard" else QColor(theme.TEXT_2))
        p.drawText(text_rect, Qt.TextWordWrap, wrapped)
        p.restore()

    def _paint_listening_plate(self, p: QPainter, rect: QRectF, tone: QColor, now: float):
        p.setPen(QPen(_col(tone, 0.45), 1))
        p.setBrush(BUBBLE_BG)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        cy = rect.center().y()
        blink = 0.55 + 0.45 * math.sin(now * 6)
        p.setPen(Qt.NoPen)
        p.setBrush(_col(tone, blink))
        p.drawEllipse(QPointF(rect.left() + 13, cy), 3.2, 3.2)
        p.setFont(self._f_caption)
        p.setPen(tone)
        p.drawText(QRectF(rect.left() + 22, rect.top(), 70, rect.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   "LISTENING")
        # a little live-looking equaliser
        pen = QPen(_col(tone, 0.9), 2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        for i in range(5):
            h = 3 + 7 * abs(math.sin(now * (5.3 + i * 1.7) + i * 1.3))
            x = rect.right() - 40 + i * 6
            p.drawLine(QPointF(x, cy - h / 2), QPointF(x, cy + h / 2))

    # ── pointing ─────────────────────────────────────────────────────────────
    @staticmethod
    def _bezier(a: QPointF, ctrl: QPointF, b: QPointF, t: float) -> QPointF:
        u = 1 - t
        return QPointF(u * u * a.x() + 2 * u * t * ctrl.x() + t * t * b.x(),
                       u * u * a.y() + 2 * u * t * ctrl.y() + t * t * b.y())

    @staticmethod
    def _control(start: QPointF, target: QPointF) -> QPointF:
        mid = QPointF((start.x() + target.x()) / 2, (start.y() + target.y()) / 2)
        dx, dy = target.x() - start.x(), target.y() - start.y()
        dist = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / dist, dx / dist
        if ny > 0:                               # always bow upwards
            nx, ny = -nx, -ny
        bow = min(140.0, dist * 0.28)
        return QPointF(mid.x() + nx * bow, mid.y() + ny * bow)

    def _paint_points(self, p: QPainter, start: QPointF, now: float):
        if not self._points:
            return
        age = now - self._points_since
        fade = max(0.0, min(1.0, (self._points_until - now) / 1.2))
        area = QRectF(self.rect()).adjusted(-80, -80, 80, 80)
        for index, (target_global, label) in enumerate(self._points):
            target = QPointF(self.mapFromGlobal(target_global))
            local_age = age - index * self.STAGGER
            progress = max(0.0, min(1.0, local_age / self.FLIGHT_SECONDS))
            if progress <= 0:
                continue
            eased = _ease_out(progress)
            ctrl = self._control(start, target)
            landed = local_age - self.FLIGHT_SECONDS
            trail = fade * (1.0 if landed <= 0 else max(0.0, 1 - landed / 0.8))
            if trail > 0:
                self._paint_trajectory(p, start, ctrl, target, eased, trail, now)
            if progress >= 1 and area.contains(target):
                self._paint_reticle(p, target, index, landed, fade, now)
                self._paint_label(p, target, index + 1, label, landed, fade)

    def _paint_trajectory(self, p, start, ctrl, target, eased, alpha, now):
        steps = 32
        length = math.hypot(target.x() - start.x(), target.y() - start.y()) * 1.1 or 1.0
        t0 = min(0.3, 18.0 / length)            # leave the buddy itself clear
        if eased <= t0:
            return
        path = QPainterPath(self._bezier(start, ctrl, target, t0))
        tip = start
        for i in range(1, steps + 1):
            tip = self._bezier(start, ctrl, target, t0 + (eased - t0) * i / steps)
            path.lineTo(tip)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_col(SHADOW, 0.16 * alpha), 3.0, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(path)
        pen = QPen(_col(ACCENT, alpha), 1.8)
        pen.setDashPattern([4, 2.5])
        pen.setDashOffset(-now * 14)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawPath(path)
        # the comet at the head of the line (only while flying)
        if eased < 1:
            glow = QRadialGradient(tip, 10)
            glow.setColorAt(0.0, _col("#FFFFFF", 0.95 * alpha))
            glow.setColorAt(0.3, _col(ACCENT, 0.85 * alpha))
            glow.setColorAt(1.0, _col(ACCENT, 0.0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(tip, 10, 10)

    def _paint_reticle(self, p: QPainter, c: QPointF, index: int, landed: float, fade: float, now: float):
        k = _ease_out(landed / 0.45)
        if k <= 0 or fade <= 0:
            return
        col = ACCENT
        a = fade * k
        p.save()
        # landing flash
        if landed < 0.4:
            f = landed / 0.4
            p.setPen(QPen(_col(col, 0.8 * (1 - f) * fade), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, 6 + 34 * f, 6 + 34 * f)
        # a faint dark lens so the reticle reads on light apps too
        lens = QRadialGradient(c, 30)
        lens.setColorAt(0.0, _col(SHADOW, 0.0))
        lens.setColorAt(0.55, _col(SHADOW, 0.05 * a))
        lens.setColorAt(0.8, _col(SHADOW, 0.09 * a))
        lens.setColorAt(1.0, _col(SHADOW, 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(lens)
        p.drawEllipse(c, 30, 30)
        p.setBrush(Qt.NoBrush)

        def dual(width, alpha, draw, dash=False, shadow=0.45):
            p.setPen(QPen(_col(SHADOW, shadow * alpha), width + 2.0, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
            draw()
            pen = QPen(_col(col, alpha), width, Qt.SolidLine, Qt.SquareCap if not dash else Qt.FlatCap, Qt.MiterJoin)
            p.setPen(pen)
            draw()

        # rotating dashed outer ring
        ring = QRectF(c.x() - 24, c.y() - 24, 48, 48)
        spin = (now * 40 + index * 25) % 360

        def arcs():
            for s in range(8):
                p.drawArc(ring, int((spin + s * 45) * 16), 24 * 16)
        dual(1.2, 0.7 * a, arcs, dash=True, shadow=0.12)

        # crosshair ticks
        def ticks():
            for q in range(4):
                ang = q * math.pi / 2
                p.drawLine(QPointF(c.x() + 27 * math.cos(ang), c.y() + 27 * math.sin(ang)),
                           QPointF(c.x() + 34 * math.cos(ang), c.y() + 34 * math.sin(ang)))
        dual(1.4, 0.95 * a, ticks)

        # corner brackets: rotate 90° → 0° while closing in, then breathe
        half = 34 - 16 * k + (1.2 * math.sin(now * 4 + index) if k >= 1 else 0.0)
        p.save()
        p.translate(c)
        p.rotate(90 * (1 - k))
        dual(1.9, a, lambda: _brackets(p, QPointF(0, 0), half, 6))
        p.restore()
        # pulsing core
        phase = (now * 1.2 + index * 0.3) % 1.0
        p.setPen(QPen(_col(col, 0.8 * (1 - phase) * fade), 1.3))
        p.drawEllipse(c, 3 + 9 * phase, 3 + 9 * phase)
        p.setPen(Qt.NoPen)
        p.setBrush(_col(SHADOW, 0.35 * fade))
        p.drawEllipse(c, 4.6, 4.6)
        p.setBrush(_col(col, 0.9 * fade))
        p.drawEllipse(c, 3.4, 3.4)
        p.setBrush(_col("#FFFFFF", 0.95 * fade))
        p.drawEllipse(c, 1.8, 1.8)
        p.restore()

    def _label_rect(self, target: QPointF, number_w: float, label_w: float) -> Tuple[QRectF, bool]:
        w = number_w + (label_w + 22 if label_w else 12)
        h = 24.0
        x, y = target.x() + 44, target.y() - 40
        left = False
        if x + w > self.rect().right() - 6:
            x, left = target.x() - 44 - w, True
        if y < self.rect().top() + 6:
            y = target.y() + 16
        return QRectF(x, y, w, h), left

    def _paint_label(self, p: QPainter, target: QPointF, number: int, label: str, landed: float, fade: float):
        appear = _ease_out((landed - 0.15) / 0.3)
        alpha = appear * fade
        if alpha <= 0:
            return
        num = f"{number:02d}"
        fm_num = QFontMetrics(self._f_number)
        fm_label = QFontMetrics(self._f_label)
        label = fm_label.elidedText(label or "", Qt.ElideRight, 260)
        number_w = fm_num.horizontalAdvance(num) + 16
        label_w = fm_label.horizontalAdvance(label) if label else 0
        rect, left = self._label_rect(target, number_w, label_w)
        p.save()
        p.setOpacity(alpha)
        p.translate((1 - appear) * (8 if left else -8), 0)
        # elbow leader: reticle corner → plate
        above = rect.top() < target.y()
        anchor = QPointF(target.x() + (-15 if left else 15), target.y() + (-15 if above else 15))
        elbow_y = rect.center().y()
        elbow = QPointF(anchor.x() + (-10 if left else 10), elbow_y)
        edge = QPointF(rect.right() if left else rect.left(), elbow_y)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath(anchor)
        path.lineTo(elbow)
        path.lineTo(edge)
        p.setPen(QPen(_col(SHADOW, 0.4), 3))
        p.drawPath(path)
        p.setPen(QPen(_col(ACCENT, 0.85), 1.1))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(_col(ACCENT, 0.9))
        p.drawEllipse(anchor, 1.8, 1.8)
        # plate
        p.setPen(QPen(_col(ACCENT, 0.40), 1))
        p.setBrush(BUBBLE_BG)
        p.drawRoundedRect(rect, 4, 4)
        num_rect = QRectF(rect.left(), rect.top(), number_w, rect.height())
        p.setPen(Qt.NoPen)
        p.setBrush(_col(theme.ACCENT_2, 0.16))
        path = QPainterPath()
        path.addRoundedRect(num_rect.adjusted(1, 1, 0, -1), 3, 3)
        p.drawPath(path)
        p.setPen(QPen(_col(theme.ACCENT_2, 0.45), 1))
        if label:
            p.drawLine(QPointF(num_rect.right(), rect.top() + 5), QPointF(num_rect.right(), rect.bottom() - 5))
        p.setFont(self._f_number)
        p.setPen(QColor(theme.ACCENT_2))
        p.drawText(num_rect, Qt.AlignCenter, num)
        if label:
            p.setFont(self._f_label)
            p.setPen(BUBBLE_FG)
            p.drawText(QRectF(num_rect.right() + 10, rect.top(), label_w + 4, rect.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, label)
        p.restore()
