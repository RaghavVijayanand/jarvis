"""Step executor with parallel lanes.

One ``ExecutionSession`` runs the steps of one request. Steps can be submitted
all at once (typed commands) or one by one while the user is still speaking
(core/streaming.py). Each lane is a worker thread that runs its steps in
order; lanes run concurrently. A failed step skips the rest of its lane only.

    session = executor.session(on_event=print)
    session.submit("open chrome")                     # lane 0
    session.submit("go to youtube and play x")        # lane 0, after chrome
    session.submit("open the alarm", parallel=True)   # lane 1, runs now
    results = session.close_and_wait()
"""
from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from core.logging_setup import get_logger

log = get_logger("jarvis.executor")

RunStep = Callable[[str, dict], str]
Settle = Callable[[str, str, dict], None]
EventFn = Callable[[str, dict], None]
_MAX_WAIT = 3600.0


@dataclass
class StepRecord:
    index: int
    lane: int
    text: str
    kind: str = "command"          # command | wait
    seconds: float = 0.0
    status: str = "queued"         # queued | running | done | failed | skipped | stopped
    reply: str = ""
    started: float = 0.0
    finished: float = 0.0


def _failed(reply) -> bool:
    # Skills report failure as "Error creating file: …", "Couldn't open …", "Failed to open URL: …" —
    # a later step in the lane must not run on top of any of them.
    return bool(getattr(reply, "is_error", False)) or str(reply).startswith(
        ("Step failed", "I couldn't", "Error", "Something went wrong", "Couldn't", "Could not", "Failed",
         "That failed"))


class _Lane:
    def __init__(self, session: "ExecutionSession", lane_id: int):
        self.session = session
        self.id = lane_id
        self.queue: "queue.Queue[Optional[StepRecord]]" = queue.Queue()
        self.context: Dict = {"browser": None, "lane": lane_id}
        self.failed = False
        self.thread = threading.Thread(target=self._run, name=f"Lane{lane_id}", daemon=True)
        self.thread.start()

    def _run(self):
        while True:
            step = self.queue.get()
            if step is None:
                return
            try:
                self._run_one(step)
            except Exception as exc:        # never let the lane die: its other steps would stay
                log.exception("lane %s crashed on: %s", self.id, step.text)   # "queued" and wait() hang
                step.status, step.reply, self.failed = "failed", f"Step failed: {exc}", True
                self.session._emit("step_done", step)

    def _run_one(self, step: StepRecord):
        s = self.session
        if s.stopped.is_set():
            step.status, step.reply = "stopped", "Stopped."
            s._emit("step_done", step)
            return
        if self.failed:
            step.status, step.reply = "skipped", "Skipped because an earlier step failed."
            s._emit("step_done", step)
            return
        step.status, step.started = "running", time.time()
        s._emit("step_started", step)
        if step.kind == "wait":
            interrupted = s.stopped.wait(step.seconds)
            reply = "Stopped." if interrupted else f"Waited {step.seconds:g} seconds."
        else:
            try:
                reply = s.run_step(step.text, self.context) or "Done."
            except Exception as exc:
                log.exception("step failed: %s", step.text)
                reply = f"Step failed: {exc}"
            if s.settle:
                try:
                    s.settle(step.text, str(reply), self.context)
                except Exception:
                    log.exception("settle failed")
        step.reply, step.finished = str(reply), time.time()
        if step.kind == "wait" and s.stopped.is_set():
            step.status = "stopped"
        elif step.kind != "wait" and _failed(reply):
            step.status, self.failed = "failed", True
        else:
            step.status = "done"
        s._emit("step_done", step)


class ExecutionSession:
    def __init__(self, run_step: RunStep, settle: Optional[Settle] = None, on_event: Optional[EventFn] = None):
        self.run_step = run_step
        self.settle = settle
        self.on_event = on_event
        self.steps: List[StepRecord] = []
        self.lanes: Dict[int, _Lane] = {}
        self.current_lane = 0
        self.stopped = threading.Event()
        self._lock = threading.Lock()
        self._closed = False
        self._inflight = 0            # submits that reserved a step but haven't queued it yet
        self._sentinels_sent = False

    def _emit(self, kind: str, step: StepRecord):
        if self.on_event:
            try:
                self.on_event(kind, {"index": step.index, "lane": step.lane, "text": step.text,
                                     "status": step.status, "reply": step.reply})
            except Exception:
                log.exception("event callback failed")

    def submit(self, text: str, parallel: bool = False, kind: str = "command", seconds: float = 0.0) -> StepRecord:
        try:            # Event.wait() raises on nan / huge values (OverflowError past time_t)
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = 0.0
        seconds = min(max(seconds, 0.0), _MAX_WAIT) if math.isfinite(seconds) else 0.0
        with self._lock:
            if self._closed:
                raise RuntimeError("session closed")
            if parallel and self.steps:
                self.current_lane = max(self.lanes) + 1 if self.lanes else 0
            lane = self.lanes.get(self.current_lane)
            if lane is None:
                lane = self.lanes[self.current_lane] = _Lane(self, self.current_lane)
            step = StepRecord(len(self.steps), self.current_lane, text, kind, seconds)
            self.steps.append(step)
            self._inflight += 1
        try:
            self._emit("step_queued", step)
            lane.queue.put(step)
        finally:
            with self._lock:
                self._inflight -= 1
                if self._closed:
                    # close() ran while this step was on its way; end the lanes only after it is queued,
                    # otherwise the lane would exit first and the step would stay "queued" forever.
                    self._end_lanes_locked()
        return step

    def _end_lanes_locked(self):
        if self._inflight or self._sentinels_sent:
            return
        self._sentinels_sent = True
        for lane in self.lanes.values():
            lane.queue.put(None)

    def stop(self):
        self.stopped.set()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._end_lanes_locked()

    def wait(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.time() + timeout
        with self._lock:
            lanes = list(self.lanes.values())
        for lane in lanes:
            remaining = None if deadline is None else max(0.0, deadline - time.time())
            lane.thread.join(remaining)
            if lane.thread.is_alive():
                return False
        return True

    def close_and_wait(self, timeout: Optional[float] = None) -> List[str]:
        self.close()
        self.wait(timeout)
        return [s.reply or "Not run." for s in self.steps]

    @property
    def busy(self) -> bool:
        return any(s.status in ("queued", "running") for s in self.steps)
