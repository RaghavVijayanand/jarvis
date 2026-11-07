"""JARVIS scorecard: how well does it understand what people actually say, and how fast?

    python eval/scorecard.py                  # current default model, rules routing
    python eval/scorecard.py --model ollama:qwen3:8b --laya
    python eval/scorecard.py --only follow-up --verbose

Every turn runs through the real pipeline — casual-speech tidying, rules, compose,
follow-up detection, the language model with tools — but every skill is a
recorder on a simulated desktop, so nothing is opened, typed or closed for real.
A turn passes when the recorded actions (and, for questions, the reply) match
what a person would expect. Results go to eval/results/<time>.json.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

Action = Tuple[str, str]          # (kind, detail) e.g. ("open", "chrome"), ("volume_change", "10")
# Looking things up isn't "acting" when the turn was only a question.
READ_ONLY = ("utility_skill.", "weather", "search", "system_monitor.", "system_control.get", "memory.")


# ── Simulated desktop ────────────────────────────────────────────────────────

class Desktop:
    """Remembers which apps are 'open' and in front; every skill call is recorded as an action."""

    def __init__(self):
        self.open: List[str] = []
        self.front = "Desktop"
        self.actions: List[Action] = []

    def record(self, kind: str, detail="") -> None:
        self.actions.append((kind, str(detail)))

    def match(self, title: str) -> Optional[str]:
        t = (title or "").lower()
        return next((a for a in reversed(self.open) if a.lower() in t or t in a.lower()), None) if t else None


class Skill:
    """Stands in for any JARVIS skill object: known methods act on the Desktop, the rest are recorded."""

    def __init__(self, desk: Desktop, name: str):
        self._desk, self._name = desk, name

    # apps
    def launch_app_by_name(self, target, browser=None):
        text = re.sub(r"^(?:open|launch|start|go to|visit)\s+(?:the\s+)?", "", str(target).strip(), flags=re.I)
        app = re.split(r"\s+(?:and|to|then)\s+", text)[0].strip().rstrip(".").title() or "App"
        self._desk.record("open", text)
        if app not in self._desk.open:
            self._desk.open.append(app)
        self._desk.front = app
        return f"Opened {app}."

    def close_app_by_name(self, name):
        self._desk.record("close", name)
        app = self._desk.match(name)
        if app:
            self._desk.open.remove(app)
            self._desk.front = self._desk.open[-1] if self._desk.open else "Desktop"
        return f"Closed {name}."

    # windows
    def _find(self, title):
        app = self._desk.match(title)
        return [(1, app)] if app else []

    def window_action(self, title, action):
        app = self._desk.match(title)
        self._desk.record("close" if action == "close" else action, title)
        if not app:
            return f"No window matching '{title}'."
        if action == "close":
            self._desk.open.remove(app)
            self._desk.front = self._desk.open[-1] if self._desk.open else "Desktop"
            return f"Asked to close '{app}'."
        self._desk.front = app
        return f"Switched to '{app}'."

    def open_settings(self, page=""):
        self._desk.record("open", f"settings {page}".strip())
        return f"Opened Settings{' — ' + page if page else ''}."

    def type_text(self, text):
        self._desk.record("type", f"{self._desk.front}: {text}")
        return f"Typed {len(text)} character(s)."

    def set_clipboard(self, text):
        self._desk.record("clipboard", text[:40])
        return "Copied to the clipboard."

    def media(self, action):
        self._desk.record("media", action)
        return {"play_pause": "Toggled play/pause.", "next": "Skipped.", "previous": "Went back.",
                "stop": "Stopped."}.get(action, "Done.")

    def change_volume(self, delta):
        self._desk.record("volume_change", int(delta))
        return f"Volume {'up' if int(delta) > 0 else 'down'}."

    def set_volume(self, level):
        self._desk.record("volume_set", int(level))
        return f"Volume set to {level}%."

    def mute(self, on=True):
        self._desk.record("mute", on)
        return "Muted." if on else "Unmuted."

    def __getattr__(self, method):
        if method.startswith("__"):
            raise AttributeError(method)

        def call(*args, **kwargs):
            detail = " ".join(str(a) for a in list(args) + list(kwargs.values()))
            kind = {"task_scheduler": "schedule", "weather_skill": "weather", "web_skill": "search"}.get(
                self._name, f"{self._name}.{method}")
            self._desk.record(kind, detail)
            if kind == "schedule":
                return f"Reminder set: {detail}."
            if kind == "weather":
                return "It's 24°C and sunny in Pune."
            return "Done."
        return call


class FileSkill(Skill):
    """The file skill also parses commands itself ("create file x.txt"); in a dry run it passes on everything."""

    def __init__(self, desk: Desktop):
        super().__init__(desk, "file_skill")

    def route_command(self, text):
        return None


# ── Cases ────────────────────────────────────────────────────────────────────

@dataclass
class Turn:
    said: str
    expect: List[Tuple[str, str]] = field(default_factory=list)   # (kind, text that must appear in detail)
    quiet: bool = False                                           # no actions at all (chat / questions)
    reply: str = ""                                               # regex the reply must match
    check: Optional[Callable[[List[Action]], bool]] = None


@dataclass
class Case:
    category: str
    turns: List[Turn]
    setup: List[str] = field(default_factory=list)                # apps already open (front = last)


def up(acts):
    return any(k == "volume_change" and int(d) > 0 for k, d in acts)


def down(acts):
    return any(k == "volume_change" and int(d) < 0 for k, d in acts)


def T(said, *expect, **kw):
    return Turn(said, list(expect), **kw)


CASES: List[Case] = [
    # opening apps, said casually
    *[Case("open", [T(s, ("open", app))]) for s, app in [
        ("open chrome", "chrome"), ("start chrome", "chrome"), ("go to chrome", "chrome"),
        ("hi um can you like start chrome", "chrome"), ("chrome please", "chrome"),
        ("hey jarvis could you please fire up spotify for me", "spotify"), ("uh launch notepad real quick", "notepad"),
        ("can you get youtube up", "youtube"), ("pull the calculator up", "calc"), ("yo open whatsapp", "whatsapp"),
        ("please bring up file explorer", "explorer"), ("take me to youtube", "youtube"),
        ("i need the calculator", "calc"), ("could you open up word for me", "word"),
        ("open settings", "settings"), ("can i get notepad open", "notepad"),
    ]],
    # media and volume
    Case("media", [T("pause it", ("media", "play_pause"))]),
    Case("media", [T("resume the music", ("media", "play_pause"))]),
    Case("media", [T("skip this song", ("media", "next"))]),
    Case("media", [T("next one", ("media", "next"))]),
    Case("media", [T("go back to the previous track", ("media", "previous"))]),
    Case("media", [T("stop the music", ("media", "stop"))]),
    Case("media", [T("turn it up a bit", check=up)]),
    Case("media", [T("um so like turn the volume up a bit", check=up)]),
    Case("media", [T("make it quieter", check=down)]),
    Case("media", [T("set the volume to 30", ("volume_set", "30"))]),
    Case("media", [T("mute", ("mute", ""))]),
    Case("media", [T("play some lofi on youtube", ("open", "lofi"))]),
    Case("media", [T("i wanna listen to some jazz on spotify", ("open", "jazz"))]),
    # reminders / alarms
    Case("schedule", [T("remind me to call mom at 6", ("schedule", "mom"))]),
    Case("schedule", [T("could you maybe remind me to drink water in 20 minutes", ("schedule", "water"))]),
    Case("schedule", [T("set an alarm for 7 am", ("schedule", "7"))]),
    Case("schedule", [T("um, uh, wake me up at 6:30 tomorrow, thanks", ("schedule", "6"))]),
    # questions that must not act
    Case("chat", [T("how are you doing today", quiet=True)]),
    Case("chat", [T("what is world peace", quiet=True)]),
    Case("chat", [T("tell me a joke", quiet=True)]),
    Case("chat", [T("explain black holes in one sentence", quiet=True, reply=r"(?i)black hole")]),
    Case("chat", [T("what time is it", reply=r"\d{1,2}[:.]\d{2}|\b(?:am|pm)\b|o'clock")]),
    Case("chat", [T("thanks jarvis", quiet=True)]),
    # writing into apps
    Case("compose", [T("write a two line poem about rain in notepad", ("type", "notepad"))]),
    Case("compose", [T("open notepad", ("open", "notepad")),
                     T("write an essay about world peace and type it there", ("type", "notepad"))]),
    Case("compose", [T("draft a short email asking my boss for friday off in word", ("type", "word"))]),
    Case("compose", [T("type hello world", ("type", "hello world"))], setup=["Notepad"]),
    Case("compose", [T("type an email to my landlord about the broken tap", ("type", "notepad"))], setup=["Notepad"]),
    # follow-ups: context from earlier turns
    Case("follow-up", [T("open notepad", ("open", "notepad")), T("actually close that", ("close", "notepad"))]),
    Case("follow-up", [T("open spotify", ("open", "spotify")), T("close it", ("close", "spotify"))]),
    Case("follow-up", [T("open notepad", ("open", "notepad")),
                       T("write a haiku about coffee and put it there", ("type", "notepad")),
                       T("now close it", ("close", "notepad"))]),
    Case("follow-up", [T("play some lofi on youtube", ("open", "lofi")), T("pause it", ("media", "play_pause")),
                       T("ok resume it", ("media", "play_pause"))]),
    Case("follow-up", [T("open chrome", ("open", "chrome")), T("and also open spotify", ("open", "spotify"))]),
    Case("follow-up", [T("remind me to call mom at 6", ("schedule", "mom")),
                       T("actually make it 7 instead", ("schedule", "7"))]),
    Case("follow-up", [T("write a two line poem about rain in notepad", ("type", "notepad")),
                       T("what did i ask you to write?", quiet=True, reply=r"(?i)poem|rain")]),
    Case("follow-up", [T("open notepad", ("open", "notepad")), T("open chrome", ("open", "chrome")),
                       T("go back to notepad", ("focus", "notepad"))]),
    Case("follow-up", [T("what's the weather in pune", ("weather", "pune")),
                       T("what about mumbai", ("weather", "mumbai"))]),
    # several things at once
    Case("multi", [T("open chrome and spotify", ("open", "chrome"), ("open", "spotify"))]),
    Case("multi", [T("open notepad then type hello there", ("open", "notepad"), ("type", "hello"))]),
    Case("multi", [T("pause the music and turn the volume down", ("media", "play_pause"), check=down)]),
]


# ── Runner ───────────────────────────────────────────────────────────────────

def build_jarvis(desk: Desktop, model: Optional[str], laya: bool):
    import jarvis as jm
    from core.brain import MultiModelBrain
    from core.config import Config
    from core.decision import DecisionEngine
    from core.tools import ToolRegistry
    from skills.command_processor import CommandProcessor

    class J(jm.JARVIS):
        def __getattr__(self, name):                 # any skill JARVIS reaches for is a recorder
            if name.startswith("_") or name in ("buddy", "stream", "web_dashboard", "file_index", "watchers"):
                raise AttributeError(name)
            skill = Skill(desk, name)
            object.__setattr__(self, name, skill)
            return skill

    app = J.__new__(J)
    for attr, value in dict(is_sleeping=False, is_running=True, confirm_callback=None, notify_callback=None,
                            exit_callback=None, voice_output_enabled=False, _voice_mode=False, _console_mode=False,
                            _pending_actions=[], _last_decision=None, _active_session=None, stream=None,
                            screen_automation=None, buddy=None).items():
        setattr(app, attr, value)
    import threading
    app._stop_plan, app._input_lock = threading.Event(), threading.Lock()
    app.voice_engine = Skill(desk, "voice_engine")
    app.windows = Skill(desk, "windows")
    app.app_control = Skill(desk, "app_control")
    app.task_scheduler = Skill(desk, "task_scheduler")
    app.file_skill = FileSkill(desk)
    app.decision = DecisionEngine(engine="laya" if laya else "rules")
    if laya:
        app.decision.warm_up_async()
        while app.decision._loading or not app.decision.laya_ready:
            time.sleep(0.5)
            if not app.decision._loading and not app.decision.laya_ready:
                break
    app.command_processor = CommandProcessor(app)
    app.confirm = lambda question: True             # dry run: approve, the recorder does nothing anyway
    app._foreground_title = lambda: desk.front
    with contextlib.redirect_stdout(io.StringIO()):
        brain = MultiModelBrain()
    brain.memory = Skill(desk, "memory")
    brain.memory.get_context_string = lambda: ""
    brain.memory.extract_from_message = lambda m: None
    brain._save_history = lambda: None
    brain.conversation_history = []
    if model:
        brain.current_model = model
    tools = ToolRegistry(confirm=lambda q: True)
    app.brain = brain
    app.handlers.register_tools(tools)
    brain.tool_registry = tools
    brain.context_provider = app._desktop_context
    return app, brain, Config


def run_case(app, brain, desk: Desktop, case: Case, verbose: bool):
    brain.conversation_history.clear()
    app._last_app = None
    app._pending_actions = []
    desk.open, desk.front, desk.actions = list(case.setup), (case.setup[-1] if case.setup else "Desktop"), []
    results = []
    for turn in case.turns:
        desk.actions = []
        used_ai = {"yes": False}
        real_process, real_ask = brain.process_command, brain.ask_text

        def spy_process(*a, **k):
            used_ai["yes"] = True
            return real_process(*a, **k)

        def spy_ask(*a, **k):
            used_ai["yes"] = True
            return real_ask(*a, **k)
        brain.process_command, brain.ask_text = spy_process, spy_ask
        start = time.perf_counter()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                reply = str(app.process_command(turn.said, use_voice=False) or "")
                if re.search(r"Reply yes to confirm", reply):     # a safety question: answer it like the user
                    reply += " → yes → " + str(app.process_command("yes", use_voice=False) or "")
        except Exception as exc:
            reply = f"CRASH: {exc!r}"
        finally:
            brain.process_command, brain.ask_text = real_process, real_ask
        seconds = time.perf_counter() - start
        acts = list(desk.actions)
        problems = []
        for kind, text in turn.expect:
            if not any(k == kind and text.lower() in d.lower() for k, d in acts):
                problems.append(f"missing {kind}({text})")
        if turn.check and not turn.check(acts):
            problems.append("check failed")
        changes = [a for a in acts if not a[0].startswith(READ_ONLY)]
        if turn.quiet and changes:
            problems.append(f"acted on a question: {changes}")
        if turn.reply and not re.search(turn.reply, reply):
            problems.append(f"reply doesn't match /{turn.reply}/")
        if reply.startswith("CRASH"):
            problems.append(reply)
        result = {"category": case.category, "said": turn.said, "passed": not problems, "problems": problems,
                  "seconds": round(seconds, 2), "path": "ai" if used_ai["yes"] else "fast",
                  "actions": acts, "reply": reply[:300]}
        results.append(result)
        if verbose or problems:
            mark = "PASS" if not problems else "FAIL"
            print(f"  {mark} {seconds:5.1f}s {result['path']:4} {turn.said!r}")
            if problems:
                print(f"         {'; '.join(problems)}\n         actions={acts}\n         reply={reply[:140]!r}")
    return results


def summarize(results, model, laya):
    def pct(rows):
        return f"{100 * sum(r['passed'] for r in rows) / len(rows):.0f}%" if rows else "-"

    def lat(rows):
        s = sorted(r["seconds"] for r in rows)
        if not s:
            return "-"
        p90 = s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]
        return f"median {statistics.median(s):.1f}s · p90 {p90:.1f}s"
    print(f"\nModel: {model} · routing: {'laya + rules' if laya else 'rules'} · {len(results)} turns")
    print(f"  overall      {pct(results):>5}   {lat(results)}")
    for cat in sorted({r['category'] for r in results}):
        rows = [r for r in results if r["category"] == cat]
        print(f"  {cat:12} {pct(rows):>5}   ({len(rows)} turns)  {lat(rows)}")
    for path in ("fast", "ai"):
        rows = [r for r in results if r["path"] == path]
        print(f"  path {path:7} {pct(rows):>5}   ({len(rows)} turns)  {lat(rows)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="e.g. ollama:qwen3:8b (default: JARVIS's configured model)")
    parser.add_argument("--laya", action="store_true", help="route with Laya too (loads it first, ~1 min)")
    parser.add_argument("--only", help="run one category")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.disable(logging.WARNING)
    desk = Desktop()
    app, brain, _ = build_jarvis(desk, args.model, args.laya)
    model = brain.current_model
    print(f"Scoring {model} …")
    results = []
    for case in CASES:
        if args.only and case.category != args.only:
            continue
        results += run_case(app, brain, desk, case, args.verbose)
    summarize(results, model, args.laya)
    out = ROOT / "eval" / "results" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": model, "laya": args.laya, "results": results}, indent=1, default=str),
                   encoding="utf-8")
    print(f"\nDetails: {out}")


if __name__ == "__main__":
    main()
