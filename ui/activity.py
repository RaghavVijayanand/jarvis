"""The dashboard's right-hand ACTIVITY panel: what JARVIS is doing, right now and lately.

    ActivityPanel.set_state(state, detail)        current state card (orb + label + elapsed)
    ActivityPanel.on_live_event(kind, info)       live-voice / executor events → timeline
    ActivityPanel.on_buddy_event(kind, info)      cursor-buddy events → recent
    ActivityPanel.task_started(label) / task_finished(ok, reply)   the command worker
    ActivityPanel.add_recent(text, kind)

Timeline rows show queued / running / done / failed / skipped / stopped with lane
badges (L1, L2 … once a request runs steps in parallel) and durations.
"""
from __future__ import annotations

import math
import time
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ui import theme
from ui.widgets import ArcOrb, Caption, HudPanel, IconButton

STATUS_COLORS = {
    "queued": theme.MUTED, "running": theme.ACCENT_2, "done": theme.SUCCESS, "failed": theme.ERROR,
    "skipped": theme.FAINT, "stopped": theme.FAINT,
}
FINAL = ("done", "failed", "skipped", "stopped")


class StepRow(QWidget):
    H = 48

    def __init__(self, text: str, lane: int = 0, status: str = "queued", parent=None):
        super().__init__(parent)
        self.text = text or "…"
        self.lane = lane or 0
        self.status = status
        self.reply = ""
        self.show_lane = False
        self.started = time.monotonic() if status == "running" else None
        self.seconds = None
        self.setFixedHeight(self.H)
        self.setToolTip(self.text)

    def update_step(self, status: str = None, reply: str = None, text: str = None):
        if text:
            self.text = text
            self.setToolTip(text)
        if status:
            if status == "running" and self.status != "running":
                self.started = time.monotonic()
            if status in FINAL and self.status not in FINAL:
                self.seconds = (time.monotonic() - self.started) if self.started else None
            self.status = status
        if reply is not None:
            self.reply = str(reply)
            self.setToolTip(f"{self.text}\n→ {self.reply}" if self.reply else self.text)
        self.update()

    def duration_text(self) -> str:
        if self.status == "running" and self.started:
            return f"{time.monotonic() - self.started:.1f}s"
        if self.seconds is not None:
            return f"{self.seconds:.1f}s"
        return ""

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        col = QColor(STATUS_COLORS.get(self.status, theme.MUTED))
        cx, cy = 16, 17
        # rail line joining the steps
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.drawLine(QPointF(cx, 0), QPointF(cx, cy - 8))
        p.drawLine(QPointF(cx, cy + 8), QPointF(cx, h))
        s = self.status
        if s == "running":
            a = (time.monotonic() * 360) % 360
            p.setPen(QPen(theme.qcolor(col.name(), 0.25), 2))
            p.drawEllipse(QPointF(cx, cy), 6.5, 6.5)
            pen = QPen(col, 2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(cx - 6.5, cy - 6.5, 13, 13), int(-a * 16), 100 * 16)
        elif s == "done":
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qcolor(col.name(), 0.18))
            p.drawEllipse(QPointF(cx, cy), 8, 8)
            p.drawPixmap(cx - 6, cy - 6, theme.icon_pixmap("check", 12, col.name()))
        elif s == "failed":
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qcolor(col.name(), 0.18))
            p.drawEllipse(QPointF(cx, cy), 8, 8)
            p.drawPixmap(cx - 6, cy - 6, theme.icon_pixmap("close", 12, col.name()))
        elif s in ("skipped", "stopped"):
            p.setPen(QPen(col, 1.6))
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            p.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
        else:
            p.setPen(QPen(col, 1.4, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 6, 6)
        # right side: lane badge + duration
        right = w - 6
        p.setFont(theme.hud_font(7))
        fm = QFontMetrics(p.font())
        if self.show_lane:
            lane = f"L{self.lane + 1}"
            lw = fm.horizontalAdvance(lane) + 10
            badge = QRectF(right - lw, cy - 8, lw, 16)
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.45), 1))
            p.setBrush(theme.qcolor(theme.ACCENT, 0.08))
            p.drawRoundedRect(badge, 4, 4)
            p.setPen(QColor(theme.ACCENT))
            p.drawText(badge, Qt.AlignCenter, lane)
            right = badge.left() - 6
        dur = self.duration_text()
        if dur:
            p.setPen(QColor(theme.MUTED))
            dw = fm.horizontalAdvance(dur) + 2
            p.drawText(QRectF(right - dw, cy - 8, dw, 16), Qt.AlignRight | Qt.AlignVCenter, dur)
            right -= dw + 6
        tx = 32
        p.setFont(theme.text_font(9.5))
        fm = QFontMetrics(p.font())
        p.setPen(QColor(theme.TEXT if s != "skipped" else theme.MUTED))
        p.drawText(QRectF(tx, cy - 9, right - tx, 18), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self.text, Qt.ElideRight, int(max(10, right - tx))))
        sub = self.reply.split("\n", 1)[0] if self.reply else s.upper() if s != "done" else ""
        if sub:
            p.setFont(theme.text_font(8.5))
            fm = QFontMetrics(p.font())
            p.setPen(QColor(STATUS_COLORS.get(s, theme.MUTED) if s in ("failed",) else theme.MUTED))
            p.drawText(QRectF(tx, cy + 8, w - tx - 8, 16), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(sub, Qt.ElideRight, int(w - tx - 8)))
        p.end()


class GroupHeader(QWidget):
    H = 26

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.stamp = datetime.now().strftime("%H:%M")
        self.setFixedHeight(self.H)
        self.setToolTip(title)

    def set_title(self, title):
        self.title = title
        self.setToolTip(title)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(theme.hud_font(7.5))
        fm = QFontMetrics(p.font())
        p.setPen(QColor(theme.FAINT))
        sw = fm.horizontalAdvance(self.stamp) + 4
        p.drawText(QRectF(self.width() - sw - 4, 6, sw, 16), Qt.AlignRight | Qt.AlignVCenter, self.stamp)
        p.setPen(QColor(theme.ACCENT_DIM))
        title = fm.elidedText(self.title.upper(), Qt.ElideRight, int(self.width() - sw - 20))
        p.drawText(QRectF(8, 6, self.width() - sw - 16, 16), Qt.AlignLeft | Qt.AlignVCenter, title)
        p.end()


class RecentRow(QWidget):
    H = 24
    ICONS = {"voice": "mic", "buddy": "eye", "task": "bolt", "error": "close", "info": "pulse", "chat": "chat"}

    def __init__(self, text, kind="info", parent=None):
        super().__init__(parent)
        self.text, self.kind = text, kind
        self.stamp = datetime.now().strftime("%H:%M")
        self.setFixedHeight(self.H)
        self.setToolTip(text)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = theme.ERROR if self.kind == "error" else theme.ACCENT_DIM
        p.drawPixmap(4, 5, theme.icon_pixmap(self.ICONS.get(self.kind, "pulse"), 14, color))
        p.setFont(theme.hud_font(7))
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(self.width() - 40, 0, 36, self.H), Qt.AlignRight | Qt.AlignVCenter, self.stamp)
        p.setFont(theme.text_font(9))
        fm = QFontMetrics(p.font())
        p.setPen(QColor(theme.TEXT_2))
        p.drawText(QRectF(26, 0, self.width() - 70, self.H), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self.text, Qt.ElideRight, int(self.width() - 70)))
        p.end()


class _StateCard(HudPanel):
    def __init__(self):
        super().__init__("Current state", glow=True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 30, 14, 14)
        lay.setSpacing(12)
        self.orb = ArcOrb(58)
        lay.addWidget(self.orb, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.label = QLabel(theme.STATE_LABELS["offline"].upper())
        self.label.setWordWrap(True)
        col.addWidget(self.label)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color: {theme.TEXT_2}; font-size: 12px; background: transparent;")
        col.addWidget(self.detail)
        self.elapsed = QLabel("")
        self.elapsed.setStyleSheet(f"color: {theme.FAINT}; background: transparent; font-family: {theme.HUD_FONT};"
                                   " font-size: 10px; letter-spacing: 1px;")
        col.addWidget(self.elapsed)
        lay.addLayout(col, 1)


class ActivityPanel(QFrame):
    collapse_requested = Signal()
    MAX_ROWS = 80

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("activityPanel")
        self.setFixedWidth(304)
        self.state = "offline"
        self.detail = ""
        self._since = time.monotonic()
        self.steps = {}                 # key → StepRow
        self.rows = []                  # timeline widgets in order
        self._group = None              # (GroupHeader, lanes set) of the open request
        self._group_n = 0
        self._task_n = 0
        self._task_key = None
        self.recent = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 14, 14, 12)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 0, 0)
        title = Caption("Activity", color=theme.TEXT_2)
        title.setStyleSheet(f"color: {theme.TEXT_2}; background: transparent; font-family: {theme.HUD_FONT};"
                            " font-size: 12px; font-weight: 600; letter-spacing: 3px;")
        head.addWidget(title)
        head.addStretch()
        self.btn_collapse = IconButton("close", "Hide the activity panel", size=26, icon_size=13)
        self.btn_collapse.clicked.connect(self.collapse_requested.emit)
        head.addWidget(self.btn_collapse)
        lay.addLayout(head)

        self.state_card = _StateCard()
        lay.addWidget(self.state_card)

        self.timeline_card = HudPanel("Timeline")
        tl = QVBoxLayout(self.timeline_card)
        tl.setContentsMargins(8, 30, 8, 10)
        tl.setSpacing(0)
        self.btn_clear = IconButton("trash", "Clear the timeline", size=24, icon_size=12, parent=self.timeline_card)
        self.btn_clear.clicked.connect(self.clear_timeline)
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setFrameShape(QFrame.NoFrame)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tl_content = QWidget()
        self._tl = QVBoxLayout(self._tl_content)
        self._tl.setContentsMargins(0, 0, 4, 0)
        self._tl.setSpacing(0)
        self.empty = QLabel("Nothing yet. Steps JARVIS runs — typed, spoken or queued — show up here live.")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color: {theme.FAINT}; font-size: 12px; padding: 18px 10px; background: transparent;")
        self._tl.addWidget(self.empty)
        self._tl.addStretch(1)
        self.timeline_scroll.setWidget(self._tl_content)
        tl.addWidget(self.timeline_scroll)
        lay.addWidget(self.timeline_card, 3)

        self.recent_card = HudPanel("Recent")
        rl = QVBoxLayout(self.recent_card)
        rl.setContentsMargins(10, 30, 10, 10)
        rl.setSpacing(0)
        self._recent_lay = rl
        self.recent_empty = QLabel("No recent events.")
        self.recent_empty.setStyleSheet(f"color: {theme.FAINT}; font-size: 12px; padding: 4px 6px; background: transparent;")
        rl.addWidget(self.recent_empty)
        rl.addStretch(1)
        self.recent_card.setMinimumHeight(118)
        lay.addWidget(self.recent_card, 1)

        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self.set_state("offline", "Starting up")

    # painting: a glass column with a bright left edge
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.qcolor(theme.BG_2, 0.78))
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        p.drawLine(0, 0, 0, self.height())
        p.end()
        super().paintEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.btn_clear.move(self.timeline_card.width() - 32, 4)

    def showEvent(self, e):
        self._tick.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._tick.stop()
        super().hideEvent(e)

    def _on_tick(self):
        secs = int(time.monotonic() - self._since)
        if self.state in ("idle", "offline"):
            self.state_card.elapsed.setText("")
        else:
            self.state_card.elapsed.setText(f"FOR {secs // 60:02d}:{secs % 60:02d}")
        for row in self.steps.values():
            if row.status == "running":
                row.update()

    # state ----------------------------------------------------------------------
    def set_state(self, state: str, detail: str = ""):
        if state != self.state:
            self._since = time.monotonic()
        self.state, self.detail = state, detail or ""
        color = theme.STATE_COLORS.get(state, theme.ACCENT)
        card = self.state_card
        card.orb.set_state(state)
        card.label.setText(theme.STATE_LABELS.get(state, state).upper())
        card.label.setStyleSheet(f"color: {color}; background: transparent; font-family: {theme.HUD_FONT};"
                                 " font-size: 15px; font-weight: 600; letter-spacing: 1px;")
        card.detail.setText(self.detail if len(self.detail) < 140 else self.detail[:137] + "…")
        card.detail.setVisible(bool(self.detail))
        self._on_tick()

    def set_level(self, level: float):
        self.state_card.orb.set_level(level)

    # timeline -------------------------------------------------------------------
    def _add_row(self, widget):
        self.empty.hide()
        self._tl.insertWidget(self._tl.count() - 1, widget)
        self.rows.append(widget)
        while len(self.rows) > self.MAX_ROWS:
            old = self.rows.pop(0)
            for k, v in list(self.steps.items()):
                if v is old:
                    del self.steps[k]
            self._tl.removeWidget(old)
            old.deleteLater()
        QTimer.singleShot(0, lambda: self.timeline_scroll.verticalScrollBar().setValue(
            self.timeline_scroll.verticalScrollBar().maximum()))

    def begin_group(self, title: str):
        self._group_n += 1
        header = GroupHeader(title)
        self._add_row(header)
        self._group = {"id": self._group_n, "header": header, "lanes": set(), "rows": []}
        return self._group_n

    def end_group(self, title: str = None):
        if self._group and title:
            self._group["header"].set_title(title)
        self._group = None

    def _ensure_group(self, title="Live voice"):
        if self._group is None:
            self.begin_group(title)
        return self._group

    def upsert_step(self, index, text=None, lane=0, status="queued", reply=None):
        group = self._ensure_group()
        key = (group["id"], index)
        row = self.steps.get(key)
        if row is None:
            row = StepRow(text or "…", lane or 0, status or "queued")
            self.steps[key] = row
            group["rows"].append(row)
            self._add_row(row)
        row.update_step(status, reply, text)
        group["lanes"].add(lane or 0)
        multi = len(group["lanes"]) > 1
        for r in group["rows"]:
            if r.show_lane != multi:
                r.show_lane = multi
                r.update()
        return row

    def clear_timeline(self):
        for w in self.rows:
            self._tl.removeWidget(w)
            w.deleteLater()
        self.rows, self.steps, self._group = [], {}, None
        self.empty.show()

    # recent ---------------------------------------------------------------------
    def add_recent(self, text: str, kind: str = "info"):
        text = " ".join(str(text).split())
        if not text:
            return
        self.recent_empty.hide()
        row = RecentRow(text, kind)
        self._recent_lay.insertWidget(1, row)
        self.recent.insert(0, row)
        while len(self.recent) > 6:
            old = self.recent.pop()
            self._recent_lay.removeWidget(old)
            old.deleteLater()

    # event sources --------------------------------------------------------------
    def on_live_event(self, kind: str, info):
        info = info if isinstance(info, dict) else {}
        try:
            idx = info.get("index")
            if kind == "heard":
                group = self._ensure_group()
                group["header"].set_title(f"“{info.get('text', '')}”")
            elif kind in ("dispatched", "step_queued") and idx is not None:
                exists = idx in self._open_keys()
                self.upsert_step(idx, info.get("text"), info.get("lane") or 0, None if exists else "queued")
            elif kind == "step_started" and idx is not None:
                self.upsert_step(idx, info.get("text"), info.get("lane") or 0, "running")
            elif kind == "step_done" and idx is not None:
                status = info.get("status") or "done"
                self.upsert_step(idx, info.get("text"), info.get("lane") or 0, status, info.get("reply", ""))
            elif kind == "deferred":
                self.add_recent(f"Will answer after you finish: {info.get('text', '')}", "voice")
            elif kind == "ask":
                self.add_recent(f"Asked: {info.get('question', '')}", "voice")
            elif kind == "utterance_done":
                heard = info.get("heard")
                self.end_group(f"“{heard}”" if heard else None)
                if info.get("summary"):
                    self.add_recent(info["summary"], "voice")
        except Exception:                   # a malformed event must never break the dashboard
            pass

    def _open_keys(self):
        if not self._group:
            return set()
        gid = self._group["id"]
        return {k[1] for k in self.steps if k[0] == gid}

    def on_buddy_event(self, kind: str, info):
        info = info if isinstance(info, dict) else {}
        if kind == "heard":
            self.add_recent(f"Buddy heard: {info.get('text', '')}", "buddy")
        elif kind == "answer" and info.get("text"):
            self.add_recent(f"Buddy: {info['text']}", "buddy")
        elif kind == "point":
            n = len(info.get("points") or [])
            self.add_recent(f"Buddy pointed at {n} place{'s' if n != 1 else ''}", "buddy")
        elif kind == "error":
            self.add_recent(info.get("message", "Buddy error"), "error")

    def task_started(self, label: str):
        self._task_n += 1
        self._group = None
        self.begin_group("Request")
        self._task_key = self._task_n
        self.upsert_step(("task", self._task_n), label, 0, "running")

    def task_finished(self, ok: bool = True, reply: str = ""):
        if self._task_key is None:
            return
        group_row = None
        for (gid, idx), row in self.steps.items():
            if idx == ("task", self._task_key):
                group_row = row
        if group_row is not None:
            group_row.update_step("done" if ok else "failed", reply or "")
            self.add_recent(group_row.text, "task" if ok else "error")
        self._task_key = None
        self._group = None
