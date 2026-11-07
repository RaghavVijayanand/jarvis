"""Compound-command planning and execution — sequential steps and parallel lanes.

"Open Chrome and go to YouTube and play Rick Roll and move to the next video,
simultaneously open the alarm, set the alarm for 10 am, after which open
settings and change the resolution to 720p" becomes:

    lane 1: open chrome → go to youtube and play rick roll → move to the next video
    lane 2: open the alarm → set the alarm for 10 am → open settings → change the resolution to 720p

* "then", "after which", "after that", "and <verb>" … continue the current lane (in order).
* "simultaneously", "at the same time", "meanwhile", "in parallel", "and also" start a new lane.
* "go to <site> and play/search X" stays one step.
Lanes run concurrently; steps inside a lane run in order and stop on failure.
Browser navigation after "open <browser>" in the same lane uses that browser.
The same splitter drives live voice (core/streaming.py): a clause is "closed"
as soon as the connector after it and the next word have been heard.
"""
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from core.logging_setup import get_logger

log = get_logger("jarvis.steps")

VERBS = (r"open|launch|start|close|quit|exit|type|write|save|create|make|search|google|play|pause|resume|stop|"
         r"go to|go|navigate to|visit|browse to|take|click|double click|press|hit|set|remind|turn|lock|show|tell|"
         r"send|check|find|rename|delete|copy|move|wait|mute|unmute|minimi[sz]e|maximi[sz]e|scroll|read|list|"
         r"what|remember|change|switch|adjust|increase|decrease|raise|lower|enable|disable|skip|next|shut ?down|"
         r"restart|put|mute|unmute|select|download|install|call|email|message|schedule|cancel")
_PAR = r"(?:and\s+)?(?:simultaneously|at the same time|meanwhile|in parallel|parallelly)(?:\s+and)?"
_SEQ = (r"(?:and\s+)?(?:then|after which|after that|afterwards|after this|followed by|once (?:that'?s|that is|it'?s) done)"
        r"(?:\s+and)?")
_CONNECTOR = re.compile(
    rf"\s*(?:,|;)?\s*\b(?P<par>{_PAR})\b\s*,?\s*"
    rf"|\s*(?:,|;)?\s*\b(?P<seq>{_SEQ})\b\s*,?\s*"
    rf"|\s*(?P<also>\band also\b)\s+(?=(?:{VERBS})\b)"
    rf"|\s*;\s*|\s*,\s*(?:and\s+)?(?=(?:{VERBS})\b)"
    rf"|\s+\band\b\s+(?=(?:{VERBS})\b)", re.I)
_QUESTION = re.compile(r"^(?:how|what|what's|whats|why|when|where|who|whom|which|is|are|can|could|would|should|do|does|"
                       r"did|explain|describe|tell me about|tell me how|give me)\b", re.I)
_STRONG_VERBS = r"open|launch|close|play|pause|set|turn|lock|mute|unmute|take|remind|start|go to|shut ?down|restart"
_AND_STRONG = re.compile(rf"\s+\band\b\s+(?=(?:{_STRONG_VERBS})\b)", re.I)
_SITE_NAV = re.compile(r"^(?:go to|open|visit|navigate to|browse to)\s+(?:the\s+)?(youtube(?: music)?|google|amazon|reddit|"
                       r"wikipedia|github|netflix|twitch|spotify web|[\w-]+\.\w{2,}\S*)(?:\s+website)?$", re.I)
_SITE_FOLLOW = re.compile(r"^(?:play|search(?: for)?|watch|find|look up|listen to|show me)\b", re.I)
_KEEP_WHOLE = re.compile(r"screen ?shot.*\b(?:tell|describe|what|analy[sz]e|explain|read)\b", re.I)
_WAIT = re.compile(r"^(?:wait|pause)(?: for)? (\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?)$", re.I)
_BROWSER = re.compile(r"^(?:open|launch|start)\s+(?:the\s+)?(?:google\s+)?(chrome|edge|microsoft edge|firefox|brave|opera)"
                      r"(?:\s+browser)?$", re.I)
_LEAD = re.compile(r"^(?:please|jarvis|hey jarvis|can you|could you|okay|ok)[,\s]+", re.I)


@dataclass
class Step:
    text: str
    kind: str = "command"      # "command" or "wait"
    seconds: float = 0.0
    intent: str = ""
    lane: int = 0


@dataclass
class Plan:
    original: str
    steps: List[Step] = field(default_factory=list)

    @property
    def lanes(self) -> Dict[int, List[Step]]:
        out: Dict[int, List[Step]] = {}
        for step in self.steps:
            out.setdefault(step.lane, []).append(step)
        return out

    def describe(self) -> str:
        lanes = self.lanes
        lines = [f"Plan for: {self.original}"]
        n = 0
        for lane, steps in lanes.items():
            if len(lanes) > 1:
                lines.append(f"Lane {lane + 1}" + (" (runs in parallel)" if lane else ""))
            for step in steps:
                n += 1
                label = f"wait {step.seconds:g} seconds" if step.kind == "wait" else step.text
                lines.append(f"  {n}. {label}" + (f"   [{step.intent}]" if step.intent else ""))
        return "\n".join(lines)


_STARTS_WITH_VERB = re.compile(rf"^(?:please\s+)?(?:{VERBS})\b", re.I)
_IMPLICIT = re.compile(
    r"\s+(?=(?:set|open|close|launch|start|play|change|turn|take|search|remind|lock|mute|unmute|type|press|show|"
    r"increase|decrease|switch|minimi[sz]e|maximi[sz]e)\s+(?:the|a|an|my|this|that|volume|brightness|alarm|"
    r"timer|reminder|screen|resolution|it|me)\b|go to\s)", re.I)


_LITERAL = re.compile(r"^(?:please\s+)?(?:type|write|say|dictate)\b", re.I)   # the rest is text, not commands
_INFINITIVE = re.compile(r"\b(?:to|how|want|wants|need|needs|and|or)\s*$", re.I)
_REMIND = re.compile(r"^(?:please\s+)?(?:remind me|set (?:a|an) reminder|add (?:a|an) reminder)\b", re.I)
_HAS_TIME = re.compile(r"\b(?:in \d+|at \d|at (?:noon|midnight)|tomorrow|tonight|today|every|on (?:mon|tue|wed|thu|fri|sat|sun))",
                       re.I)


def _implicit_split(clause: str) -> List[str]:
    """Split "open the alarm set the alarm for 10 am" at a second imperative verb."""
    if not _STARTS_WITH_VERB.match(clause) or _SITE_NAV.match(clause) or _LITERAL.match(clause) \
            or _REMIND.match(clause):
        return [clause]
    parts, start = [], 0
    for m in _IMPLICIT.finditer(clause):
        if m.start() - start < 4:          # need a real object between the verbs
            continue
        if _INFINITIVE.search(clause[start:m.start()]):
            continue                       # "search for how to open a jar": the verb is an object
        head = clause[start:m.start()].strip()
        if len(head.split()) >= 2:
            parts.append(head)
            start = m.end()
    parts.append(clause[start:].strip())
    return [p for p in parts if p]


_SITE_NAMES = ("youtube", "google", "github", "netflix", "reddit", "amazon", "spotify", "wikipedia",
               "twitch", "gmail", "whatsapp", "instagram", "facebook", "linkedin")
_SITE_SPOKEN = {"you tube": "youtube", "u tube": "youtube", "utube": "youtube", "git hub": "github",
                "net flix": "netflix", "what's app": "whatsapp", "whats app": "whatsapp", "g mail": "gmail",
                "linked in": "linkedin", "insta gram": "instagram"}
_NAV_BEFORE_SITE = re.compile(r"\b(?:go to|open|visit|navigate to|browse to|take me to|on|in|search)\s+(?:the\s+)?$", re.I)


def normalize_site_names(text: str) -> str:
    """Fix misheard / mistyped site names right after a navigation word.

    "go to the yputube and play …" → "go to the youtube and play …". Only a word
    that follows "go to / open / visit / on …" is touched, and only when it is
    one or two letters away from a known site, so ordinary words are left alone.
    """
    if not text:
        return text
    import difflib
    for spoken, site in _SITE_SPOKEN.items():
        text = re.sub(rf"\b{re.escape(spoken)}\b", site, text, flags=re.I)
    out, last = [], 0
    for m in re.finditer(r"[A-Za-z']+", text):
        word = m.group(0)
        low = word.lower()
        # Only the last few words before this one matter; searching the whole prefix made long
        # dictation quadratic (40 KB took seconds).
        if len(low) >= 5 and low not in _SITE_NAMES and \
                _NAV_BEFORE_SITE.search(text[max(0, m.start() - 40):m.start()]):
            best = difflib.get_close_matches(low, _SITE_NAMES, n=1, cutoff=0.8)
            if best and abs(len(best[0]) - len(low)) <= 2:
                out.append(text[last:m.start()])
                out.append(best[0])
                last = m.end()
    out.append(text[last:])
    return "".join(out)


def split_clauses(text: str) -> List[Tuple[str, str]]:
    """Split into [(link, clause)] where link is 'start', 'seq' or 'par'."""
    # Long space runs make the connector pattern's "\s*,?\s*" backtrack cubically (a pasted page froze the
    # worker); one space / one line break means the same to every rule below.
    text = re.sub(r"\s*\n\s*", "\n", re.sub(r"[^\S\n]+", " ", (text or "").strip()))
    text = normalize_site_names(_LEAD.sub("", text.rstrip(".!?")))
    # Speech arrives in pieces: drop a dangling connector at either end ("…and", "and then go…").
    text = re.sub(r"\s+(?:and then|and also|and|then|also|after which|after that|simultaneously|"
                  r"at the same time|meanwhile)$", "", text, flags=re.I)
    lead = re.match(r"^(?:and then|and|then|after which|after that|afterwards)\s+", text, re.I)
    if lead:
        text = text[lead.end():]
    if not text or re.fullmatch(r"(?:and|then|also|and then|and also)", text, re.I):
        return []                      # only a connector was heard ("and then")
    if _KEEP_WHOLE.search(text) and not _CONNECTOR.search(text.split(" and ", 1)[-1]):
        return [("start", text)]
    out: List[Tuple[str, str]] = []
    link, pos = "start", 0
    question = bool(_QUESTION.match(text))
    for m in _CONNECTOR.finditer(text):
        if question and not (m.group("par") or m.group("seq") or m.group("also")):
            # "how do I open a file and read it" is one question; only split before a clear command.
            if not _AND_STRONG.match(text, m.start()) and "," not in m.group(0) and ";" not in m.group(0):
                continue
        if not (m.group("par") or m.group("seq") or m.group("also")) and "," not in m.group(0) \
                and ";" not in m.group(0):
            current = text[pos:m.start()]
            if _REMIND.match(current.strip(" ,;")) and not _HAS_TIME.search(current):
                # "remind me to take the trash out and lock the door" is one reminder.
                continue
        clause = text[pos:m.start()].strip(" ,;")
        if clause:
            out.append((link, clause))
            link = "seq"
        link = "par" if m.group("par") or m.group("also") else "seq"
        pos = m.end()
    tail = text[pos:].strip(" ,;")
    if tail:
        out.append((link, tail))
    if lead and out and out[0][0] == "start":
        out[0] = ("seq", out[0][1])
    # Spoken commands often have no connector at all: "open the alarm set the alarm for 10 am".
    expanded: List[Tuple[str, str]] = []
    for link, clause in out:
        parts = [clause] if _QUESTION.match(clause) else _implicit_split(clause)
        expanded.append((link, parts[0]))
        expanded.extend(("seq", p) for p in parts[1:])
    out = expanded
    # Re-join "go to youtube" + "play X" into one browser action.
    merged: List[Tuple[str, str]] = []
    for link, clause in out:
        if merged and link == "seq" and _SITE_NAV.match(merged[-1][1]) and _SITE_FOLLOW.match(clause):
            merged[-1] = (merged[-1][0], f"{merged[-1][1]} and {clause}")
        else:
            merged.append((link, clause))
    return merged


class CommandProcessor:
    def __init__(self, jarvis_instance=None):
        self.jarvis = jarvis_instance

    @staticmethod
    def split_steps(command: str) -> List[str]:
        return [clause for _, clause in split_clauses(command)]

    def plan(self, command: str, classify: Optional[Callable[[str], str]] = None) -> Plan:
        plan = Plan(command)
        lane = 0
        for link, chunk in split_clauses(command):
            if link == "par" and plan.steps:
                lane = max(s.lane for s in plan.steps) + 1
            m = _WAIT.match(chunk)
            if m:
                seconds = float(m.group(1)) * (60 if m.group(2).lower().startswith("m") else 1)
                plan.steps.append(Step(chunk, "wait", min(seconds, 600), lane=lane))
                continue
            step = Step(chunk, lane=lane)
            if classify:
                try:
                    step.intent = classify(chunk)
                except Exception:
                    step.intent = ""
            plan.steps.append(step)
        return plan

    @staticmethod
    def is_browser_launch(text: str) -> Optional[str]:
        m = _BROWSER.match(text.strip())
        return m.group(1).lower() if m else None

    def execute(self, plan: Plan, run_step: Callable[[str, dict], str],
                should_stop: Optional[Callable[[], bool]] = None,
                on_progress: Optional[Callable[[int, int, str], None]] = None,
                settle: Optional[Callable[[str, str, dict], None]] = None,
                on_event=None) -> List[str]:
        """Run lanes concurrently (steps within a lane in order). Returns replies in plan order."""
        from core.executor import ExecutionSession
        total = len(plan.steps)

        def events(kind, info):
            if kind == "step_started" and on_progress:
                on_progress(info["index"] + 1, total, info["text"])
            if on_event:
                on_event(kind, info)

        default_settle = settle or (lambda text, reply, ctx: time.sleep(1.5) if self.is_browser_launch(text) else None)

        def step_runner(text, context):
            reply = run_step(text, context)
            browser = self.is_browser_launch(text)
            if browser:
                context["browser"] = browser
            return reply

        session = ExecutionSession(step_runner, default_settle, events)
        watcher = None
        if should_stop:
            def watch():
                while not session.stopped.is_set() and session.busy is not False:
                    if should_stop():
                        session.stop()
                        return
                    time.sleep(0.1)
            watcher = threading.Thread(target=watch, daemon=True)
        last_lane = 0
        for step in plan.steps:
            session.submit(step.text, parallel=step.lane != last_lane, kind=step.kind, seconds=step.seconds)
            last_lane = step.lane
        if watcher:
            watcher.start()
        results = session.close_and_wait()
        session.stopped.set()
        return results

    # Backwards-compatible name used by older code.
    def parse_complex_command(self, command: str):
        return [{"type": s.kind, "command": s.text, "seconds": s.seconds, "lane": s.lane}
                for s in self.plan(command).steps]
