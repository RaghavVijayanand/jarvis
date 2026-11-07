#!/usr/bin/env python3
"""
JARVIS — desktop AI assistant for Windows.

Pipeline for every message:
  1. lifecycle words (exit / sleep / wake) and pending confirmations;
  2. deterministic file syntax (create/read/rename … and overwrite prompts);
  3. local decision model (Laya, with rule fallback) picks an intent — no LLM call;
  4. compound requests are split into ordered steps and executed one by one;
  5. a skill handler answers; anything it can't handle goes to the language
     model, which can act through the single shared tool registry.
Destructive actions always need an explicit "yes".
"""

import os
import random
import re
import sys
import threading
import time
import weakref
from datetime import datetime

# Consoles that cannot encode Unicode (e.g. cp1252 when output is piped)
# must degrade to replacement characters instead of crashing the app.
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box

from core.config import Config
from core.logging_setup import setup_logging, get_logger
from core.decision import DecisionEngine, PERSONAL_FACT_QUESTION
from core.tools import ToolRegistry
from core.voice import VoiceEngine
from core.brain import MultiModelBrain

from skills.system_control import SystemControl
from skills.weather import WeatherSkill
from skills.web_search import WebSearchSkill
from skills.utility import UtilitySkill
from skills.file_manager import FileManagerSkill
from skills.automation import AutomationSkill
from skills.app_control import ApplicationControl
from skills.command_processor import CommandProcessor
from skills.task_scheduler import TaskScheduler
from skills.system_monitor import SystemMonitor
from skills.screen_automation import ScreenAutomationSkill
from skills.windows_control import WindowsControl
from skills.software_manager import SoftwareManager
from skills.system_admin import SystemAdmin
from skills.app_scripting import AppScripting
from skills.network_manager import NetworkManager
from skills.service_manager import ServiceManager
from skills.power_manager import PowerManager
from skills.productivity import ProductivitySkill
from skills.security_checks import SecurityChecks
from skills.window_layouts import WindowLayouts
from skills.outlook_manager import OutlookManager
from skills.watchers import WatcherManager
from skills.file_index import FileIndex
from skills.web_dashboard import WebDashboard

console = Console()
log = get_logger("jarvis")
_ORIGIN = threading.local()          # per-thread: is this command from live voice?

# Words that point back at the conversation ("type it there", "close that", "play it again").
_FOLLOW_UP = re.compile(
    r"\b(?:it|its|that|this|these|those|them|there|again|same|instead|another one|one more|the other one|"
    r"the previous one|the last one|undo|shorter|longer)\b|"
    r"^\s*(?:and|also|now|then|but|actually|ok so|okay so|what about|how about|continue|keep going|go on)\b",
    re.I)
# Fixed phrases where "it"/"this" refer to nothing earlier.
_IDIOMS = re.compile(r"what time is it|is it (?:going to|gonna)|how(?:'s| is) it going|what(?:'s| is) it like|"
                     r"(?:this|that) (?:morning|afternoon|evening|week|month|year|weekend)|this is|that's all",
                     re.I)
_FOLLOW_UP_WINDOW = 30 * 60          # seconds: older turns aren't "the conversation" any more
# "close it", "minimise that", "go back to it": the app is the one JARVIS opened last (or the one in front).
_APP_REFERENCE = re.compile(
    r"^(?P<verb>close|quit|exit|minimi[sz]e|maximi[sz]e|restore|focus|switch to|switch back to|go back to|"
    r"bring back|back to)\s+(?:it|that|this|that app|this app|that window|this window|that one|this one)"
    r"(?:\s+again)?$", re.I)
# "what about mumbai?" right after a weather question.
_WHAT_ABOUT = re.compile(r"^(?:and\s+)?(?:what|how)\s+about\s+(?:in\s+)?(?P<x>[a-z][a-z .'-]{1,40}?)\??$", re.I)

# Decision-model labels → handler categories.
INTENT_MAP = {
    "chat": "GENERAL", "time": "TIME", "math": "MATH", "weather": "WEATHER", "search": "SEARCH",
    "open": "APP", "media": "MEDIA", "system": "SYSTEM", "control": "CONTROL", "file": "FILE",
    "schedule": "SCHEDULE", "screen": "SCREEN_AUTOMATION", "memory": "MEMORY", "fun": "UTILITY",
    "software": "SOFTWARE", "appscript": "APPSCRIPT", "network": "NETWORK", "service": "SERVICE",
    "power": "POWER", "productivity": "PRODUCTIVITY", "security": "SECURITY", "layout": "LAYOUT",
    "email": "EMAIL", "watch": "WATCH", "fileindex": "FILEINDEX", "dashboard": "DASHBOARD", "plugins": "PLUGINS",
}

HELP_TEXT = """Here's what I can do:
• Chat & questions — anything; I remember facts you tell me ("remember that I like tea").
• Apps & web — "open Spotify", "close Chrome", "go to YouTube and play lo-fi", "open github.com".
• Media & volume — "pause", "next track", "volume 40", "mute", "what's playing".
• PC control — "lock my PC", "show desktop", "minimize Chrome", "open Bluetooth settings", "brightness 60".
• Power — "restart the computer", "shut down", "put the PC to sleep" (I always ask first).
• Files — "create file notes/todo.txt with content buy milk", "read file todo", "rename a.txt to b.txt".
• Time & reminders — "what time is it", "set an alarm for 7 am", "remind me to stretch in 20 minutes".
• Info — "weather in London", "search for Python 3.14 news", "CPU usage", "battery".
• Screen — "take a screenshot", "what's on my screen", "click the Save button", "type hello".
• Software — "install VLC", "uninstall notepad++", "update all apps", "is Python installed".
• Admin — registry, firewall rules and OS scheduled tasks, just ask in plain language (I'll confirm first).
• Blender — "model a chair in Blender" (I write the script with AI and run it — I'll confirm first).
• Services & processes — "what's using my CPU", "list services", "restart the spooler service".
• Power & startup — "list power plans", "switch power plan to balanced", "disable Spotify from startup".
• Productivity — "clipboard history", "what does my screen say", "read the pdf report.pdf".
• Security — "defender status", "bitlocker status", "check for windows updates" (I'll confirm before scanning/installing).
• Window layouts — "save the current layout as work", "restore layout work", "snap Chrome to left-half".
• Outlook — "list my recent emails", "what's on my calendar", "send an email to..." (I'll confirm before sending).
• Watchers — "tell me when setup.exe appears", "notify me if CPU stays above 90 for 2 minutes", "list watchers".
• File search — "index folder C:\\Docs", "search my files for Q3 budget", "file index status".
• Remote dashboard — "start the dashboard" gives you a link to control JARVIS from your phone on the same Wi-Fi.
• Plugins — "list plugins" shows what's loaded; drop a .py file in the plugins folder to add a capability.
• Multi-step — "open Notepad, type hello, then press ctrl+s".
• Models — "list models", "switch model gemini-flash", "benchmark models", "decision status".
• JARVIS itself — "sleep" / "wake up" pauses and resumes me; "exit" closes me.
Say "help" any time to see this again."""

_YES = re.compile(r"(yes|yeah|yep|yup|y|sure|confirm|do it|go ahead|ok do it|okay do it)"
                  r"(,?\s*(please|do it|go ahead|confirm))?")
_NO = re.compile(r"(no|nope|n|cancel|stop|don't|do not|never mind|nevermind)(,?\s*(thanks|thank you|cancel))?")
_CONFIRM_TTL = 120      # seconds a queued destructive action waits for its yes
# Plan lanes queue confirmations while the GUI worker, live voice and the web dashboard may each be
# answering: without one lock two simultaneous "yes" both pop, and the second approves an action
# nobody said yes to.
_PENDING_LOCK = threading.RLock()
_STOP_LOCK = threading.RLock()       # one global stop at a time (hotkey, button and voice can coincide)
_MAX_PLAN_STEPS = 25


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")
# "Stop everything" — only while something is in progress, so "stop" stays free for other uses
# when JARVIS is idle. Anything naming a target ("stop the music", "cancel shutdown") is not this.
_STOP_ALL = re.compile(r"(?:(?:hey\s+)?jarvis[,\s]+)?(?:stop|abort|cancel|halt)"
                       r"(?:\s+(?:it|that|this|everything|all|all tasks|the task|task|tasks|automation|now|"
                       r"what you'?re doing|what you are doing))?(?:[,\s]+(?:now|please|jarvis))*")


class _NullVoice:
    """Stand-in when the voice engine can't start: speaking and listening do nothing."""
    sr_available = False
    tts_available = False
    selected_mic_index = None

    def speak(self, *args, **kwargs):
        return None

    def listen_for_command(self, *args, **kwargs):
        return None

    def listen_for_wake_word(self, *args, **kwargs):
        return False

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class JARVIS:
    def __init__(self, show_banner: bool = True):
        setup_logging()
        if show_banner:
            self.display_startup_banner()
        console.print("[yellow]Initializing JARVIS systems...[/yellow]")

        # Callbacks the GUI (or CLI) can install.
        self.confirm_callback = None      # fn(question) -> bool, may block
        self.notify_callback = None       # fn(text) — show proactive messages
        self.exit_callback = None         # fn() — GUI closes itself
        self.voice_output_enabled = False  # GUI voice toggle (scheduler reminders honour it)
        self._voice_mode = False
        self._console_mode = False
        self._pending_actions = []           # destructive actions waiting for "yes" (oldest first)
        self._last_decision = None
        self._stop_plan = threading.Event()
        self._input_lock = threading.Lock()   # steps that press keys / move focus take turns
        self._active_session = None
        self._sessions = weakref.WeakSet()    # every live ExecutionSession (plans, live voice, queue)
        self._stop_hooks = []                 # UI callbacks the global stop also runs (e.g. close dialogs)
        self._stop_hotkey = None
        self._resolution_timer = None
        self.stream = None                    # live voice session (core/streaming.py) when active
        self._live_listener = None

        self.voice_engine = self._safe(lambda: VoiceEngine(), "Voice engine") or _NullVoice()

        try:
            self.decision = DecisionEngine(engine=Config.DECISION_ENGINE, model=Config.LAYA_MODEL,
                                           repo=Config.LAYA_REPO, threshold=Config.DECISION_THRESHOLD,
                                           on_status=lambda s: log.info("decision: %s", s))
        except Exception as e:
            log.exception("decision engine failed")
            console.print(f"[yellow]⚠️ Local decision model unavailable ({e}); using rules.[/yellow]")
            self.decision = DecisionEngine(engine="rules")

        try:
            self.brain = MultiModelBrain()
            n = len(self.brain.available_models)
            console.print(f"[green]🧠 AI initialized — {n} model(s) available[/green]")
            if not self.brain.current_model:
                console.print("[yellow]No AI model yet — add an API key in Settings or install Ollama.[/yellow]")
        except Exception as e:
            log.exception("brain failed")
            console.print(f"[red]AI brain failed to start: {e}[/red]")
            self.brain = None
        self.multi_brain = self.brain

        self.app_control = self._safe(lambda: ApplicationControl(), "Application control")
        self.system_control = SystemControl(app_control=self.app_control)
        self.windows = WindowsControl()
        self.weather_skill = WeatherSkill()
        self.web_skill = WebSearchSkill()
        self.utility_skill = UtilitySkill()
        self.file_skill = FileManagerSkill()
        self.automation_skill = self._safe(lambda: AutomationSkill(), "Automation")
        self.command_processor = CommandProcessor(self)
        self.system_monitor = self._safe(lambda: SystemMonitor(), "System monitor")
        self.screen_automation = self._safe(lambda: ScreenAutomationSkill(self), "Screen automation")
        self.task_scheduler = self._safe(lambda: TaskScheduler(self), "Task scheduler")
        self.software_manager = self._safe(lambda: SoftwareManager(), "Software manager")
        self.system_admin = self._safe(lambda: SystemAdmin(), "System admin")
        self.app_scripting = self._safe(lambda: AppScripting(self), "App scripting")
        self.network_manager = self._safe(lambda: NetworkManager(), "Network manager")
        self.service_manager = self._safe(lambda: ServiceManager(), "Service manager")
        self.power_manager = self._safe(lambda: PowerManager(), "Power manager")
        self.productivity = self._safe(lambda: ProductivitySkill(self), "Productivity extras")
        self.security_checks = self._safe(lambda: SecurityChecks(), "Security checks")
        self.window_layouts = self._safe(lambda: WindowLayouts(self.windows), "Window layouts")
        self.outlook = self._safe(lambda: OutlookManager(), "Outlook integration")
        self.watchers = self._safe(lambda: WatcherManager(self), "Watchers")
        self.file_index = self._safe(lambda: FileIndex(self.productivity), "File index")
        self.web_dashboard = self._safe(lambda: WebDashboard(self), "Web dashboard")

        self.is_running = False
        self.is_sleeping = False
        self.last_activity = time.time()

        self.skills = {name: obj for name, obj in (
            ("weather", self.weather_skill), ("web_search", self.web_skill), ("utility", self.utility_skill),
            ("file_manager", self.file_skill), ("system_monitor", self.system_monitor),
            ("automation", self.automation_skill), ("app_control", self.app_control),
            ("windows", self.windows), ("command_processor", self.command_processor),
            ("task_scheduler", self.task_scheduler), ("screen_automation", self.screen_automation),
            ("software_manager", self.software_manager), ("system_admin", self.system_admin),
            ("app_scripting", self.app_scripting), ("network_manager", self.network_manager),
            ("service_manager", self.service_manager), ("power_manager", self.power_manager),
            ("productivity", self.productivity), ("security_checks", self.security_checks),
            ("window_layouts", self.window_layouts), ("outlook", self.outlook), ("watchers", self.watchers),
            ("file_index", self.file_index), ("web_dashboard", self.web_dashboard),
        ) if obj is not None}

        self.tools = ToolRegistry(confirm=self.confirm)
        self._register_tools()
        if self.brain is not None:
            self.brain.tool_registry = self.tools
            self.brain.context_provider = self._desktop_context
            try:
                self.brain.memory.fact_detector = lambda msg: self.decision.yes_no(msg, PERSONAL_FACT_QUESTION)
                self.brain.refresh_catalog_async()
            except Exception:
                log.exception("brain setup failed")
        try:
            self.decision.warm_up_async()
        except Exception:
            log.exception("decision warm-up failed")
        console.print("[green]All systems initialized.[/green]")

    # ── Setup helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _safe(factory, label):
        try:
            obj = factory()
            console.print(f"[green]✅ {label} ready[/green]")
            return obj
        except Exception as e:
            log.exception("%s failed", label)
            console.print(f"[yellow]⚠️ {label} unavailable: {e}[/yellow]")
            return None

    def display_startup_banner(self):
        banner = Text("J.A.R.V.I.S.", style="bold cyan", justify="center")
        console.print(Panel(banner, title="[bold blue]JARVIS AI Assistant[/bold blue]",
                            subtitle="[italic]Just A Rather Very Intelligent System[/italic]",
                            border_style="blue", box=box.DOUBLE))
        console.print("[dim]Type 'help' to see what I can do.[/dim]")

    def install_signal_handlers(self):
        """CLI only: Ctrl+C / SIGTERM shut down cleanly (never installed by the GUI)."""
        import signal
        if threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        console.print(f"\n[yellow]Received signal {signum}. Shutting down JARVIS...[/yellow]")
        self.shutdown()
        raise SystemExit(0)

    # ── Interaction helpers ──────────────────────────────────────────────────

    def confirm(self, question: str) -> bool:
        """Ask the user to approve an action. Blocks the calling (worker) thread."""
        stream = getattr(self, "stream", None)
        # Only commands that came from live voice are confirmed out loud; a typed
        # command keeps using the dialog even while the microphone is live.
        if stream is not None and getattr(_ORIGIN, "voice", False):
            try:
                return bool(stream.ask_yes_no(question))
            except Exception:
                log.exception("live voice confirmation failed")
                return False
        callback = getattr(self, "confirm_callback", None)
        if callback:
            try:
                return bool(callback(question))
            except Exception:
                log.exception("confirm callback failed")
                return False
        if getattr(self, "_voice_mode", False):
            try:
                self.voice_engine.speak(question + " Say yes or no.")
                answer = self.voice_engine.listen_for_command(timeout=8) or ""
            except Exception:
                log.exception("voice confirmation failed")
                return False
            return bool(re.match(r"\s*(yes|yeah|yep|sure|do it|confirm|go ahead)\b", answer, re.I))
        if getattr(self, "_console_mode", False) and sys.stdin and sys.stdin.isatty():
            try:
                return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                return False
        return False

    def notify(self, text: str, speak: bool = False, speak_text: str = None) -> None:
        """Proactive message (alarms, reminders, background status)."""
        dashboard = getattr(self, "web_dashboard", None)
        if dashboard is not None:
            try:
                dashboard.on_notify(text)
            except Exception:
                log.exception("dashboard notify failed")
        callback = getattr(self, "notify_callback", None)
        if callback:
            try:
                callback(text)
            except Exception:
                log.exception("notify callback failed")
        else:
            console.print(f"[bold cyan]JARVIS:[/bold cyan] {text}")
        if speak and (self.voice_output_enabled or self._voice_mode or callback is None):
            try:
                self.voice_engine.speak(speak_text or text, summarize=True)
            except Exception:
                log.exception("notify speech failed")

    def _say(self, text, use_voice):
        """Print (CLI) and optionally speak a reply."""
        from rich.markup import escape
        if text is None:
            return
        console.print(f"[blue]JARVIS:[/blue] {escape(str(text))}")
        if use_voice:
            try:
                try:
                    self.voice_engine.speak(str(text), summarize=True)
                except TypeError:
                    self.voice_engine.speak(str(text))
            except Exception:
                log.exception("speech failed")

    def _ask_to_confirm(self, prompt: str, action, label: str = ""):
        """Destructive action: queue it and ask for a yes (works in text and voice, several can wait)."""
        with _PENDING_LOCK:
            if getattr(self, "_pending_actions", None) is None:
                self._pending_actions = []
            self._pending_actions.append({"prompt": prompt, "run": action, "created": time.monotonic(),
                                          "label": label})
        return f"{prompt} Reply yes to confirm, or no to cancel."

    @property
    def _pending_action(self):
        queue = getattr(self, "_pending_actions", None) or []
        return queue[0] if queue else None

    # ── Main entry ───────────────────────────────────────────────────────────

    def process_command(self, command, use_voice=True):
        """Process one user message and return the reply text."""
        if not command or not str(command).strip():
            return None
        original_command = str(command).strip()
        command = original_command.lower()
        bare = command.rstrip(".!? ")
        self.last_activity = time.time()
        console.print(f"[green]Processing command:[/green] {original_command}")

        if bare in {"goodbye", "exit", "quit", "shutdown jarvis", "bye jarvis", "goodbye jarvis", "exit jarvis",
                    "quit jarvis"}:
            response = "Goodbye. JARVIS systems shutting down."
            self._say(response, use_voice)
            try:
                self.shutdown()
            except Exception:
                log.exception("shutdown failed")
            return response
        if bare in {"sleep", "standby", "go to sleep", "jarvis sleep", "jarvis go to sleep"}:
            self.is_sleeping = True
            response = "Entering sleep mode. Say 'wake up' when you need me."
            self._say(response, use_voice)
            return response
        if bare in {"wake up", "wake", "jarvis wake up", "wake up jarvis", "hey jarvis wake up"}:
            self.is_sleeping = False
            response = "I'm awake and ready to assist."
            self._say(response, use_voice)
            return response
        if getattr(self, "is_sleeping", False):
            return "JARVIS is sleeping. Say 'wake up' to resume."

        brain = getattr(self, "brain", None)
        history = getattr(brain, "conversation_history", None)
        turns_before = len(history) if isinstance(history, list) else None
        try:
            response = self._route(original_command)
        except Exception as exc:
            log.exception("command failed: %s", original_command)
            response = f"Something went wrong handling that ({exc})."
        if turns_before is not None and response is not None and len(history) == turns_before:
            try:                       # every turn is context — plans, confirmations and quick commands too
                brain.record_exchange(original_command, response)
            except Exception:
                log.exception("recording the exchange failed")
        if response is None:
            response = "I'm not sure how to respond to that."
        elif not isinstance(response, str):
            response = str(response)
        self._say(response, use_voice)
        return response

    def _route(self, original_command):
        # The fast routes get casual speech tidied ("hi um can you like start chrome" → "start chrome");
        # the language model and the history always get exactly what was said.
        from core.natural import tidy
        # Several routing patterns backtrack on long space runs (3,000 spaces took 90 s in a search); no
        # real request needs more than a few in a row, so cap them before any routing regex sees the text.
        original_command = re.sub(r"(\s{8})\s+", r"\1", original_command)
        said, original_command = original_command, self._resolve_reference(tidy(original_command))
        command = original_command.lower().strip()
        bare = command.rstrip(".!? ")

        # 0. "stop" / "cancel that" / "abort" while something is in progress: the global stop.
        if _STOP_ALL.fullmatch(bare) and self.is_busy():
            return self.stop_everything()

        # 1. A pending destructive action waits for yes/no.
        is_yes = _YES.fullmatch(bare)
        is_no = _NO.fullmatch(bare)
        pending = None
        with _PENDING_LOCK:
            queue = getattr(self, "_pending_actions", None)
            if queue is None:
                queue = self._pending_actions = []
            now = time.monotonic()
            expired = [p for p in queue if now - p.get("created", now) > _CONFIRM_TTL]
            queue[:] = [p for p in queue if now - p.get("created", now) <= _CONFIRM_TTL]
            if queue and (is_yes or is_no):
                pending = queue.pop(0)          # claimed under the lock: exactly one answer per prompt
            elif queue:
                queue.clear()   # an unrelated request cancels anything still waiting
        if pending is not None:
            if is_yes:
                try:            # run outside the lock: the action may itself queue another confirmation
                    reply = str(pending["run"]())
                except Exception as exc:
                    log.exception("confirmed action failed")
                    reply = f"That failed: {exc}"
            else:
                reply = "Cancelled. Nothing was changed."
            with _PENDING_LOCK:
                if queue:
                    queue[0]["created"] = time.monotonic()   # its countdown starts when it is asked
                    reply += f" Next: {queue[0]['prompt']} Reply yes or no."
            return reply

        # 1a. "write an essay about X and type it there / in notepad": the AI writes, JARVIS types it in.
        compose = self._compose_request(original_command)
        if compose is not None:
            return compose

        # 1b. Follow-ups that lean on the conversation ("play it again", "make it shorter", "rename it
        # to notes.txt") go to the language model with the history, the desktop state and tools; every
        # fast route below only ever sees this one message. The common ones ("close it", "what about
        # mumbai") were already resolved into a plain command above, so they skip this.
        if original_command == tidy(said) and self._is_follow_up(said):
            return self._fallback_brain(said)

        # 2. File deletions need a yes; everything else in the file syntax is deterministic.
        processor = getattr(self, "command_processor", None)
        plan = processor.plan(original_command) if processor is not None else None
        file_skill = getattr(self, "file_skill", None)
        m = re.match(r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?file\s+(.+?)[.!?]*$", original_command, re.I)
        if file_skill and m and not (plan and len(plan.steps) > 1):
            target = m.group(1).strip().strip('"\'')
            return self._ask_to_confirm(f"Delete the file '{target}'?",
                                        lambda: file_skill.delete_file(target), "delete_file")
        if not m:
            response = file_skill.route_command(original_command) if file_skill else None
            if response is not None:
                return response

        # A bare yes/no with nothing waiting must not reach the model as a fresh request
        # ("stop" / "cancel" keep their own meaning below).
        answer = is_yes or re.fullmatch(r"(no|nope|n)(,?\s*(thanks|thank you))?", bare)
        if answer and expired:
            return "That confirmation expired, so nothing was changed. Please ask again."
        brain = getattr(self, "brain", None)
        if answer and not (brain is not None and getattr(brain, "current_model", None)):
            return "There's nothing waiting for your confirmation right now."

        # 3. Built-in meta commands.
        meta = self._meta_command(original_command, bare)
        if meta is not None:
            return meta

        # 4. Compound requests ("…and then…", "…simultaneously…") run as ordered / parallel steps.
        if plan is not None and len(plan.steps) > _MAX_PLAN_STEPS:
            # A pasted page can split into thousands of actions (and one thread per parallel lane).
            return (f"That splits into {len(plan.steps)} separate actions — more than the {_MAX_PLAN_STEPS} I'll "
                    "run in one go. Please break it into smaller requests.")
        if plan is not None and len(plan.steps) > 1:
            return self._run_plan(plan)

        # 4a. The regex splitter found nothing to split, but the decision engine still
        # flags this as multi-step (e.g. no explicit connector, or a construction the
        # splitter doesn't know) — ask the model to break it into steps as a fallback,
        # then run those through the same plan/execute machinery as a normal plan.
        if plan is not None and len(plan.steps) <= 1:
            llm_plan = self._llm_plan_fallback(said)
            if llm_plan is not None:
                return self._run_plan(llm_plan)

        # 4b. Buddy mode: "where's the export button?" gets pointed at on screen.
        buddy = getattr(self, "buddy", None)
        if buddy is not None:
            from core.buddy import is_guide_question
            if is_guide_question(original_command):
                return buddy.ask(said, speak=False).answer

        # 4c. Just an app's name ("notepad"): open it.
        from skills.app_control import _APP_ALIASES
        if bare in _APP_ALIASES and getattr(self, "app_control", None) is not None:
            response = self.app_control.launch_app_by_name(bare)
            self._remember_app(response)
            return response

        # 5. Decide (local model / rules; never an LLM call).
        intent = self._classify_command_intent(original_command)
        self._last_intent = intent
        decision = getattr(self, "_last_decision", None)
        try:
            console.print(f"[dim]Intent: {intent}"
                          + (f" ({decision.source}, {decision.confidence:.2f})" if decision else "") + "[/dim]")
        except Exception:
            pass

        response = self._handle_classified_command(original_command, intent, use_voice=False)
        if response is None:
            response = self._fallback_brain(said)
        else:
            self._remember_app(response)
            if getattr(self, "brain", None) is not None and not getattr(response, "is_error", False):
                try:
                    self.brain.record_exchange(said, response)
                except Exception:
                    pass
        return response

    # ── Conversation context ─────────────────────────────────────────────────

    def _is_follow_up(self, command):
        """Does this message lean on earlier turns? Only when a recent conversation exists and the
        current model can act through tools (otherwise the fast routes are still the better bet)."""
        brain = getattr(self, "brain", None)
        model = getattr(brain, "current_model", None) if brain is not None else None
        if not model:
            return False
        models = getattr(brain, "available_models", None)
        if not isinstance(models, dict) or not models.get(model, {}).get("supports_tools"):
            return False
        history = getattr(brain, "conversation_history", None)
        if not isinstance(history, list) or not history:
            return False
        try:
            last = datetime.fromisoformat(str(history[-1].get("ts")))
            if (datetime.now(last.tzinfo) - last).total_seconds() > _FOLLOW_UP_WINDOW:
                return False
        except (TypeError, ValueError, AttributeError):
            pass                                   # no timestamp: treat the history as recent
        text = _IDIOMS.sub(" ", command)
        if not _FOLLOW_UP.search(text):
            return False
        from core.decision import rule_decision
        from core.natural import tidy
        plain = rule_decision(tidy(command))
        if plain.source == "rules" and plain.intent == "media":
            return False                           # "pause it", "turn it up": "it" is whatever's playing
        if getattr(self, "buddy", None) is not None:
            from core.buddy import is_guide_question
            if is_guide_question(command):         # "where's the export button?" → buddy points
                return False
        return True

    def _resolve_reference(self, command):
        """Rewrite the everyday follow-ups into plain commands the fast routes handle reliably
        (a small local model often just *says* "Closed Notepad." without doing it)."""
        m = _APP_REFERENCE.match(command)
        if m:
            app = getattr(self, "_last_app", None)
            if not app:
                front = self._foreground_title()
                app = front if front and "jarvis" not in front.lower() else None
            if app:
                verb = m.group("verb").lower()
                if verb in ("focus", "switch back to", "go back to", "bring back", "back to"):
                    verb = "switch to"
                return f"{verb} {app}"
        m = _WHAT_ABOUT.match(command)
        if m and getattr(self, "_last_intent", None) == "WEATHER":
            return f"weather in {m.group('x').strip()}"
        return command

    def _desktop_context(self):
        """One line for the model's system prompt: what "there" and "it" most likely mean."""
        parts = []
        front = self._foreground_title()
        if front and "jarvis" not in front.lower():
            parts.append(f"the window in front is '{front}'")
        last = getattr(self, "_last_app", None)
        if last:
            parts.append(f"the app JARVIS opened most recently is {last}")
        return ("; ".join(parts) + ".") if parts else ""

    # ── Writing into apps ("…and type it there") ─────────────────────────────

    def _remember_app(self, reply):
        """'Opened Notepad.' → Notepad is where "type it there" goes next."""
        from core.compose import opened_app
        name = opened_app(str(reply)) if reply else None
        if name:
            self._last_app = name
        last = getattr(self, "_last_app", None)
        if last and re.match(r"^(?:Closed|Asked to close)\b", str(reply or "")) and last.lower() in str(reply).lower():
            self._last_app = None                  # "close it" twice shouldn't aim at an app that's gone

    def _compose_request(self, command):
        """Handle "write X and type it there / in <app>"; None when the request isn't one."""
        from core.compose import parse
        from skills.app_control import _APP_ALIASES
        last = getattr(self, "_last_app", None)
        request = parse(command, known_apps=list(_APP_ALIASES) + ([last] if last else []))
        if request is None:
            return None
        return self._compose_and_type(request, command)

    def _foreground_title(self):
        try:
            import win32gui
            return win32gui.GetWindowText(win32gui.GetForegroundWindow()) or ""
        except Exception:
            return ""

    def _compose_and_type(self, request, command):
        from core.compose import COMPOSE_SYSTEM_PROMPT
        brain = getattr(self, "brain", None)
        if brain is None or not getattr(brain, "current_model", None):
            return ("I need an AI model to write that. Pick one in Settings (an Ollama model works offline), "
                    "then ask again.")
        windows = self.windows
        target = request.app or (getattr(self, "_last_app", None) if request.here else None)
        if target:
            # Find (or open) the app before spending time writing, so a wrong name fails fast.
            if not windows._find(target):
                opened = self.app_control.launch_app_by_name(target)
                if not str(opened).startswith("Opened"):
                    return f"I couldn't open {target}: {opened}"
                self._remember_app(opened)
                deadline = time.time() + 8
                while not windows._find(target) and time.time() < deadline:
                    time.sleep(0.3)
        else:
            title = self._foreground_title()
            if not title or "jarvis" in title.lower():
                return ("Which app should I type it into? Open it first (say \"open notepad\"), "
                        "or say \"… in notepad\".")
            target = title
        try:
            text = brain.ask_text(request.prompt, system_prompt=COMPOSE_SYSTEM_PROMPT, max_tokens=2000,
                                  temperature=0.7)
        except Exception as exc:
            log.exception("compose failed")
            return f"I couldn't write that: {exc}"
        text = re.sub(r"^\s*#{1,6}\s*|\*\*|__", "", str(text or ""), flags=re.M).strip()
        if not text:
            return "The AI didn't write anything — try asking again."
        try:
            brain.record_exchange(command, text)        # "make it shorter" next has the essay to work with
        except Exception:
            pass
        focused = windows.window_action(target, "focus")
        if not focused.startswith("Switched"):
            windows.set_clipboard(text)
            return f"I wrote it, but couldn't switch to {target} ({focused}). It's on your clipboard — press Ctrl+V."
        time.sleep(0.5)
        lock = getattr(self, "_input_lock", None)
        if lock is not None:
            with lock:
                typed = windows.type_text(text)
        else:
            typed = windows.type_text(text)
        if not typed.startswith("Typed"):
            return f"I wrote it but couldn't type it: {typed}"
        name = request.app or getattr(self, "_last_app", None) or target
        return f"Done — wrote {len(text.split())} words and typed them into {name}."

    def _llm_plan_fallback(self, command):
        """When the regex splitter (skills/command_processor.py) finds nothing to
        split but the request still looks compound, ask the model to break it into
        steps. Returns None — meaning "nothing more to do than the regular
        single-command path" — when there's no model available, the decision engine
        doesn't think this is multi-step, or planning didn't produce more than one
        real step."""
        brain = getattr(self, "brain", None)
        if brain is None or not getattr(brain, "current_model", None):
            return None
        decision = self.decision.decide(command)
        self._last_decision = decision
        if not decision.is_multi_step:
            return None
        try:
            steps = brain.plan_steps(command)
        except Exception:
            log.exception("LLM plan fallback failed")
            return None
        if not isinstance(steps, (list, tuple)):
            return None
        steps = [s.strip() for s in steps if isinstance(s, str) and s.strip()]
        if len(steps) <= 1 or len(steps) > _MAX_PLAN_STEPS:
            return None
        from skills.command_processor import Plan, Step
        llm_plan = Plan(command)
        for text in steps:
            llm_plan.steps.append(Step(text, lane=0))
        return llm_plan

    def _classify_command_intent(self, command):
        """Map the local decision engine's answer to a handler category."""
        decision = self.decision.decide(command)
        self._last_decision = decision
        return INTENT_MAP.get(decision.intent, "GENERAL")

    # ── Multi-step execution ─────────────────────────────────────────────────

    _KEY_INTENTS = {"MEDIA", "SCREEN_AUTOMATION", "CONTROL"}   # send keys / change focus

    def _run_step(self, text, context):
        """Route and run one step of a plan. ``context`` is per-lane (browser, media state)."""
        from core.natural import tidy
        text = tidy(text)                           # live voice: "uh, open spotify" → "open spotify"
        intent = self._classify_command_intent(text)
        if intent == "APP" and context.get("browser") and re.search(
                r"^(?:go to|navigate to|visit|open|browse to|play)\b|\.\w{2,4}\b|\byoutube\b", text, re.I) \
                and not self.command_processor.is_browser_launch(text):
            return self.app_control.launch_app_by_name(text, browser=context["browser"])
        if intent == "MEDIA" and context.get("media_started"):
            # "…and move to the next video": wait until the video really plays.
            waited = time.time() - context.pop("media_started")
            if not self.windows.wait_for_playback(timeout=max(0.0, 12 - waited)) and waited < 6:
                time.sleep(6 - waited)
        lock = getattr(self, "_input_lock", None)
        if lock is not None and intent in self._KEY_INTENTS:
            with lock:
                reply = self._handle_classified_command(text, intent, use_voice=False)
        else:
            reply = self._handle_classified_command(text, intent, use_voice=False)
        return reply if reply is not None else self._fallback_brain(text)

    def _settle(self, text, reply, context):
        """Give the desktop time to catch up before the next step in the same lane."""
        self._remember_app(reply)
        browser = self.command_processor.is_browser_launch(text)
        if browser:
            context["browser"] = browser
            time.sleep(1.5)
        elif "watch?v=" in reply or "Playing:" in reply or "youtube.com/results" in reply:
            context["media_started"] = time.time()
        elif reply.startswith("Opened"):
            time.sleep(0.8)

    def new_execution_session(self, on_event=None, voice=False):
        """``voice=True``: steps come from live voice, so confirmations are asked out loud."""
        from core.executor import ExecutionSession
        if getattr(self, "_input_lock", None) is None:
            self._input_lock = threading.Lock()
        if getattr(self, "_stop_plan", None) is not None:
            self._stop_plan.clear()           # a stop only applies to work that was already running
        run_step = self._run_step
        if voice:
            def run_step(text, context, _run=self._run_step):
                _ORIGIN.voice = True
                try:
                    return _run(text, context)
                finally:
                    _ORIGIN.voice = False
        session = ExecutionSession(run_step, self._settle, on_event)
        self._active_session = session
        sessions = getattr(self, "_sessions", None)
        if sessions is None:
            sessions = self._sessions = weakref.WeakSet()
        sessions.add(session)
        return session

    def _run_plan(self, plan):
        def progress(kind, info):
            if kind == "step_started":
                console.print(f"[cyan]Step {info['index'] + 1}/{len(plan.steps)} (lane {info['lane'] + 1}):[/cyan] "
                              f"{info['text']}")
        with _PENDING_LOCK:
            before = {id(p) for p in (getattr(self, "_pending_actions", None) or [])}
        session = self.new_execution_session(progress)
        last_lane = 0
        for step in plan.steps:
            session.submit(step.text, parallel=step.lane != last_lane, kind=step.kind, seconds=step.seconds)
            last_lane = step.lane
        session.close_and_wait()
        self._order_plan_confirmations(session, before)
        return self.format_session(session)

    def _order_plan_confirmations(self, session, before):
        """Parallel lanes queue their yes/no prompts in whatever order they finish, but the reply lists
        them in step order — and "yes" answers the first one. Line the queue up with what was shown."""
        with _PENDING_LOCK:
            queue = getattr(self, "_pending_actions", None)
            if not queue:
                return
            def step_of(p):
                return next((s.index for s in session.steps if p["prompt"] and p["prompt"] in (s.reply or "")),
                            len(session.steps))
            old = [p for p in queue if id(p) in before]
            new = sorted((p for p in queue if id(p) not in before), key=step_of)
            now = time.monotonic()
            for p in new:
                p["created"] = now      # nobody has seen these prompts until the plan's reply arrives
            queue[:] = old + new

    @staticmethod
    def format_session(session):
        lanes = {s.lane for s in session.steps}
        head = f"Ran {len(session.steps)} steps" + (f" in {len(lanes)} parallel lanes" if len(lanes) > 1 else "") + ":"
        lines = [head]
        for s in session.steps:
            tag = f"[{s.lane + 1}] " if len(lanes) > 1 else ""
            lines.append(f"{s.index + 1}. {tag}{s.text} → {s.reply or s.status}")
        return "\n".join(lines)

    def _live_sessions(self):
        sessions = set(getattr(self, "_sessions", None) or ())
        active = getattr(self, "_active_session", None)
        if active is not None:
            sessions.add(active)
        return sessions

    def is_busy(self) -> bool:
        """Is anything in progress that the global stop would cut short?"""
        if any(getattr(s, "busy", False) for s in self._live_sessions()):
            return True
        screen = getattr(self, "screen_automation", None)
        if screen is not None and getattr(screen, "is_running", False) is True:
            return True
        if getattr(self, "_pending_actions", None):
            return True
        stream = getattr(self, "stream", None)
        if stream is not None and (getattr(stream, "_exec", None) is not None or getattr(stream, "_deferred", None)
                                   or getattr(stream, "_ask", None) is not None):
            return True
        return getattr(getattr(self, "voice_engine", None), "is_speaking", False) is True

    def add_stop_hook(self, hook) -> None:
        """``hook()`` runs on every global stop (from any thread) and returns how many open
        confirmations it cancelled — the GUI uses it to close its yes/no dialogs as "no"."""
        hooks = getattr(self, "_stop_hooks", None)
        if hooks is None:
            hooks = self._stop_hooks = []
        if hook not in hooks:
            hooks.append(hook)

    def stop_everything(self) -> str:
        """The global stop: cancel all work in progress, from any thread, any number of times.

        Plans and live-voice steps stop at the next step boundary (queued ones never start, waits
        end now), screen automation and speech stop, and every pending yes/no is answered "no".
        Scheduled reminders, alarms and watchers are the user's future plans and are left alone.
        """
        with _STOP_LOCK:
            running = queued = asks = 0
            plan_stop = getattr(self, "_stop_plan", None)
            if plan_stop is not None:
                plan_stop.set()
            for session in self._live_sessions():
                try:
                    counts = session.stop()
                except Exception:
                    log.exception("stopping a session failed")
                    continue
                if isinstance(counts, dict):
                    running += counts.get("running", 0)
                    queued += counts.get("queued", 0)
            stream = getattr(self, "stream", None)
            cancel = getattr(stream, "cancel_in_flight", None)
            if callable(cancel):
                try:
                    counts = cancel()
                    if isinstance(counts, dict):
                        running += counts.get("running", 0)
                        queued += counts.get("queued", 0)
                        asks += counts.get("asks", 0)
                except Exception:
                    log.exception("stopping live voice actions failed")
            with _PENDING_LOCK:
                pending = getattr(self, "_pending_actions", None) or []
                asks += len(pending)
                pending.clear()                       # cancelled, never approved
            for hook in list(getattr(self, "_stop_hooks", None) or ()):
                try:
                    asks += int(hook() or 0)
                except Exception:
                    log.exception("stop hook failed")
            automation = False
            screen = getattr(self, "screen_automation", None)
            if screen is not None:
                automation = getattr(screen, "is_running", False) is True
                try:
                    screen.stop_automation()
                except Exception:
                    log.exception("stopping screen automation failed")
            stop_speaking = getattr(getattr(self, "voice_engine", None), "stop_speaking", None)
            if callable(stop_speaking):
                try:
                    stop_speaking()
                except Exception:
                    log.exception("stopping speech failed")
        parts = []
        if running:
            parts.append(_plural(running, "running step"))
        if queued:
            parts.append(_plural(queued, "queued step"))
        if asks:
            parts.append(_plural(asks, "pending confirmation"))
        if automation:
            parts.append("screen automation")
        if not parts:
            return "Stopped. Nothing else was running."
        listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        return f"Stopped {listed}."

    @staticmethod
    def is_stop_request(text) -> bool:
        """"stop", "cancel that", "jarvis abort!" … (but not "stop the music")."""
        from core.natural import tidy
        raw = str(text or "").strip()
        return any(_STOP_ALL.fullmatch(t.lower().strip().rstrip(".!? ")) for t in (raw, tidy(raw)) if t)

    def stop_current_task(self):
        """Older name for the global stop (the GUI's Stop button, shutdown)."""
        return self.stop_everything()

    def _stop_from_hotkey(self):
        """Runs on the hotkey thread: stop, then say what happened wherever JARVIS shows messages."""
        summary = self.stop_everything()
        try:
            self.notify(summary)
        except Exception:
            log.exception("announcing the stop failed")

    def install_stop_hotkey(self) -> bool:
        """Register the global stop hotkey (Config.STOP_HOTKEY). Re-installing swaps the combo."""
        from core.hotkeys import TapHotkey
        current = getattr(self, "_stop_hotkey", None)
        if current is not None:
            if current.combo == Config.STOP_HOTKEY:
                return True
            current.stop()
        self._stop_hotkey = TapHotkey(Config.STOP_HOTKEY, self._stop_from_hotkey)
        if not self._stop_hotkey.start():
            self._stop_hotkey = None
            return False
        return True

    def remove_stop_hotkey(self) -> None:
        hotkey, self._stop_hotkey = getattr(self, "_stop_hotkey", None), None
        if hotkey is not None:
            hotkey.stop()

    # ── Meta commands ────────────────────────────────────────────────────────

    def _meta_command(self, original, bare):
        brain = getattr(self, "brain", None)
        if bare in ("help", "what can you do", "commands", "show commands", "capabilities"):
            return HELP_TEXT
        if bare in ("list models", "show models", "available models", "which models"):
            return brain.list_available_models() if brain else "The AI brain is offline."
        m = re.match(r"^(?:switch|change|use)(?: to)?(?: the)? model\s+(?:to\s+)?(.+)$|^use\s+(\S+)\s+model$", bare)
        offline = "The AI brain is offline."
        if m:
            return brain.switch_model((m.group(1) or m.group(2)).strip()) if brain else offline
        if bare in ("benchmark models", "benchmark", "test models"):
            return brain.benchmark_models() if brain else offline
        if bare in ("model stats", "usage stats", "model info"):
            return brain.get_usage_stats() if brain else offline
        if bare in ("clear history", "clear conversation", "forget this conversation") and brain:
            return brain.clear_history()
        if bare in ("decision status", "laya status", "router status"):
            d = self.decision
            return (f"{d.describe()}. Engine setting: {d.engine}, model: {d.model}, "
                    f"threshold: {d.threshold:.2f}.")
        if bare in ("refresh models", "update models", "scan models"):
            return brain.refresh_catalog() if brain else offline
        if _STOP_ALL.fullmatch(bare) and self.is_busy():
            return self.stop_everything()
        return None

    # ── Handlers ─────────────────────────────────────────────────────────────

    @property
    def handlers(self):
        """Per-domain intent handlers (handlers/); built on first use."""
        registry = self.__dict__.get("_handlers")
        if registry is None:
            from handlers import HandlerRegistry
            registry = self._handlers = HandlerRegistry(self)
        return registry

    def _handle_classified_command(self, command, intent, use_voice=True):
        """Handle a classified command and return the reply (None → language model)."""
        if intent == "EXIT":
            return self.process_command("exit", use_voice)
        return self.handlers.dispatch(command, intent)

    def _set_alarm(self, command, use_voice=True):
        return self.handlers["ScheduleHandler"].set_alarm(command)

    # ── Language model fallback ──────────────────────────────────────────────

    def _fallback_brain(self, command):
        """Send to the language model (with tools). Offline: explain what still works."""
        try:
            if getattr(self, "brain", None) is not None and self.brain.current_model:
                return self.brain.process_command(command, use_context=True)
        except Exception as exc:
            log.exception("brain failed")
            return f"The AI model failed: {exc}"
        return self._basic_fallback_processing(command)

    def _basic_fallback_processing(self, command):
        return ("I can't answer that without an AI model. Add an OpenRouter or Gemini key in Settings, or "
                "install Ollama for offline chat. Meanwhile I can still open apps, control media and volume, "
                "manage files, set alarms, check the weather and system status — say 'help' for examples.")

    # ── Tools for the language model ─────────────────────────────────────────

    def _register_tools(self):
        self.handlers.register_tools(self.tools)
        plugin_names = getattr(self.handlers, "plugin_names", None)
        if plugin_names:
            console.print(f"[cyan]🔌 Loaded {len(plugin_names)} plugin(s) from "
                          f"{self.handlers.plugin_dir}: {', '.join(plugin_names)}[/cyan]")

    # ── Run loops ────────────────────────────────────────────────────────────

    def run_text_mode(self, use_voice=False):
        self._console_mode = True
        console.print("[cyan]JARVIS text mode — type a command ('help' for ideas, 'exit' to quit).[/cyan]")
        console.print("[dim]'voice on' / 'voice off' toggles spoken replies.[/dim]")
        while self.is_running:
            try:
                command = input("\n[You]: ").strip()
                if not command:
                    continue
                low = command.lower()
                if low in ("voice on", "enable voice"):
                    use_voice = True
                    console.print("[blue]JARVIS:[/blue] Voice responses enabled.")
                    continue
                if low in ("voice off", "disable voice"):
                    use_voice = False
                    console.print("[blue]JARVIS:[/blue] Voice responses disabled.")
                    continue
                if low in ("exit", "quit", "goodbye"):
                    console.print("[blue]JARVIS:[/blue] Goodbye!")
                    break
                self.process_command(command, use_voice=use_voice)
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted.[/yellow]")
                break
            except EOFError:
                break
            except Exception as e:
                log.exception("text mode error")
                console.print(f"[red]Error: {e}[/red]")

    def run_text_mode_with_voice(self):
        self.run_text_mode(use_voice=True)

    def _welcome(self):
        try:
            return self.brain.get_personality_response("startup") if self.brain else "JARVIS online."
        except Exception:
            log.exception("welcome message failed")
            return "JARVIS online."

    def start(self, mode="text"):
        self.is_running = True
        try:
            self._report_missed_tasks()
        except Exception:
            log.exception("missed-task report failed")
        if self.install_stop_hotkey():          # CLI; the GUI installs it when its window is ready
            from core.hotkeys import STOP_HOTKEYS
            console.print(f"[dim]Press {STOP_HOTKEYS.get(Config.STOP_HOTKEY, Config.STOP_HOTKEY)} "
                          "anywhere to stop whatever I'm doing.[/dim]")
        welcome = self._welcome()
        if mode == "voice" and getattr(self.voice_engine, "sr_available", False):
            self.run_voice_mode()
        elif mode == "voice":
            console.print("[yellow]Speech recognition unavailable — text input with spoken replies.[/yellow]")
            self.voice_engine.speak(welcome)
            self.run_text_mode_with_voice()
        else:
            console.print(f"[blue]JARVIS:[/blue] {welcome}")
            self.run_text_mode()

    def _report_missed_tasks(self):
        scheduler = getattr(self, "task_scheduler", None)
        if scheduler is None:
            return
        warning = getattr(scheduler, "storage_warning", "")
        if isinstance(warning, str) and warning:
            scheduler.storage_warning = ""
            self.notify(warning)
        for task in scheduler.missed_tasks():
            when = (task.get("next_run") or "")[:16].replace("T", " ")
            what = re.sub(r"^(reminder|alarm):\s*", "", task.get("description", ""))
            self.notify(f"While I was offline you missed: {what or task.get('type')} ({when}).")

    def run_voice_mode(self):
        self._voice_mode = True
        if self._run_live_voice_cli():
            self._voice_mode = False
            return
        wake = Config.WAKE_WORD
        greeting = self._welcome()
        console.print(f"[cyan]🎤 Voice mode — say '{wake}' to wake me. Ctrl+C to quit.[/cyan]")
        self.voice_engine.speak(greeting)
        while self.is_running:
            try:
                if not self.voice_engine.listen_for_wake_word():
                    continue
                self.voice_engine.speak("Yes?")
                command = self.voice_engine.listen_for_command(timeout=8)
                if not command:
                    self.voice_engine.speak("I didn't catch that.")
                    continue
                if re.fullmatch(r"(goodbye|exit|quit|stop listening)( jarvis)?", command.strip().lower().rstrip(".!? ")):
                    self.voice_engine.speak("Goodbye!")
                    break
                self.process_command(command, use_voice=True)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.exception("voice loop error")
                console.print(f"[red]Voice mode error: {e}[/red]")
                time.sleep(1)
        self._voice_mode = False

    def start_live_voice(self, on_event=None, require_wake_word=False, on_status=None):
        """Start act-while-you-speak voice. Returns the listener (call .stop()) or None if unavailable."""
        from core import streaming
        if not (Config.LIVE_VOICE and streaming.vosk_available()):
            return None
        path = streaming.ensure_model(on_progress=on_status or (lambda m: self.notify(m)))
        if path is None:
            return None
        session = streaming.StreamingSession(self, on_event=on_event, act_mode=Config.ACT_MODE,
                                             require_wake_word=require_wake_word)
        listener = streaming.StreamingListener(session, self.voice_engine,
                                               device_index=self.voice_engine.selected_mic_index, model_path=path)
        self.stream = session
        self._live_listener = listener

        def run():
            try:
                listener.run()
            except ModuleNotFoundError as exc:
                from core.deps import missing_package_message
                log.exception("live voice failed")
                if on_status:
                    try:
                        on_status(missing_package_message(exc, "Live voice"))
                    except Exception:
                        pass
            except Exception as exc:
                log.exception("live voice failed")
                if on_status:
                    try:
                        on_status(f"Live voice stopped: {exc}")
                    except Exception:
                        pass
            finally:
                if getattr(self, "stream", None) is session:
                    self.stream = None
                if getattr(self, "_live_listener", None) is listener:
                    self._live_listener = None
        self._live_thread = threading.Thread(target=run, name="LiveVoice", daemon=True)
        self._live_thread.start()
        return listener

    def _run_live_voice_cli(self):
        """Terminal voice mode with live, act-while-speaking recognition."""
        done = threading.Event()

        def on_event(kind, info):
            if kind == "partial":
                console.print(f"[dim]… {info['text']}[/dim]", end="\r")
            elif kind == "dispatched":
                console.print(f"\n[cyan]▶ {info['text']}[/cyan]  [dim](lane {info['lane'] + 1})[/dim]")
            elif kind == "utterance_done":
                console.print(f"[blue]JARVIS:[/blue] {info['details']}")
                self.voice_engine.speak(info["summary"], summarize=True)

        listener = self.start_live_voice(on_event, require_wake_word=True, on_status=lambda m: console.print(m))
        if listener is None:
            return False
        console.print(f"[cyan]🎤 Live voice — say '{Config.WAKE_WORD} …' and keep talking; I act as you speak. "
                      f"Ctrl+C to quit.[/cyan]")
        thread = getattr(self, "_live_thread", None)
        try:
            # Also end when the listener dies (mic unplugged, model error), not only on exit.
            while self.is_running and (thread is None or thread.is_alive()) and not done.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass
        listener.stop()
        return True

    def get_time_greeting(self):
        hour = datetime.now().hour
        return "morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else "evening"

    def shutdown(self):
        """Stop background work. The caller (CLI loop or GUI) decides whether to exit."""
        console.print("[yellow]JARVIS shutting down...[/yellow]")
        self.is_running = False
        try:
            self.stop_current_task()
        except Exception:
            log.exception("stopping the current task failed")
        try:
            self.remove_stop_hotkey()
        except Exception:
            log.exception("removing the stop hotkey failed")
        listener = getattr(self, "_live_listener", None)
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                log.exception("stopping live voice failed")
            self._live_listener = None
        try:
            if getattr(self, "task_scheduler", None):
                self.task_scheduler.stop_scheduler()
        except Exception as e:
            log.warning("Scheduler shutdown: %s", e)
        for name, stop in (("clipboard history", lambda: self.productivity.clipboard_history.stop()),
                           ("watchers", lambda: self.watchers.stop()),
                           ("web dashboard", lambda: self.web_dashboard.running and self.web_dashboard.stop())):
            try:
                stop()
            except AttributeError:
                pass                # that skill failed to load
            except Exception:
                log.exception("stopping %s failed", name)
        callback = getattr(self, "exit_callback", None)
        if callback:
            try:
                callback()
            except Exception:
                log.exception("exit callback failed")


def main():
    try:
        jarvis = JARVIS()
        jarvis.install_signal_handlers()
        if len(sys.argv) > 1:
            first = sys.argv[1].lower()
            if first in ("voice", "text"):
                jarvis.start(first)
            else:
                command = " ".join(sys.argv[1:])
                jarvis._console_mode = True
                jarvis.process_command(command, use_voice=False)
                jarvis.shutdown()
        else:
            jarvis.start("text")
            jarvis.shutdown()
    except KeyboardInterrupt:
        console.print("\n[yellow]JARVIS interrupted.[/yellow]")
    except Exception as e:
        log.exception("startup failed")
        console.print(f"[red]Failed to start JARVIS: {e}[/red]")
        console.print("[yellow]Check that dependencies are installed: pip install -r requirements.txt[/yellow]")


if __name__ == "__main__":
    main()
