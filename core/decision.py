"""Fast local decision-making for JARVIS.

JARVIS used to spend a full LLM round-trip classifying every message before
doing anything (audit UC 2.1). This module replaces that with:

1. **Laya** — Convai Innovations' open (Apache-2.0) typed decision model. It
   answers *choice*, *score* and yes/no (*noul*) questions with calibrated
   probabilities in one forward pass (tens of milliseconds on CPU), fully
   offline, with no text generation. It is loaded in the background on first
   start (weights are downloaded once from Hugging Face, ~0.8 GB).
2. **Rules** — deterministic, high-precision regular expressions. They run
   instantly, need no dependencies, and are used when Laya is not installed,
   still loading, or unsure.

Nothing here generates text or extracts arguments; handlers still parse the
details (city, file name, time) themselves.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.decision")


def _prepare_hf_cache_env() -> None:
    """Point Hugging Face Hub (Laya's downloader) at a JARVIS-managed cache
    directory, so the ~0.8 GB model persists across app updates/reinstalls
    instead of re-downloading into a random per-user cache.

    A packaged build that pre-downloaded the model at build time ships it
    under an 'hf_cache' folder next to the executable (see build/jarvis.spec
    and build/build_installer.py's warm_up_laya step) — if that's present we
    use it directly and Laya works fully offline on first run. Otherwise we
    fall back to Config.MODELS_DIR, which still downloads once and reuses it
    after that. Either way, an HF_HOME the user already set in their
    environment is left alone.
    """
    if os.environ.get("HF_HOME"):
        return
    bundled = None
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "hf_cache"
    if bundled and bundled.is_dir():
        os.environ["HF_HOME"] = str(bundled)
        return
    try:
        cache_dir = Path(Config.MODELS_DIR) / "hf_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(cache_dir)
    except OSError:
        pass  # HF falls back to its own default cache location


_prepare_hf_cache_env()

# Intent label -> short description the decision model scores against.
# Keep these short: Laya's English checkpoint shares a 192-token budget
# across all option texts of a question.
INTENTS: Dict[str, str] = {
    "chat": "conversation, opinions or general questions",
    "time": "current time, date or day",
    "math": "calculation or unit conversion",
    "weather": "weather or forecast",
    "search": "web search, news or facts lookup",
    "open": "open or close an app or website",
    "media": "play, pause or skip media; volume",
    "system": "CPU, memory, disk, battery or network status",
    "control": "lock, sleep, restart or shut down PC; windows",
    "file": "create, read, rename, delete or list files",
    "schedule": "alarm, reminder, timer or schedule",
    "screen": "screenshot, look at screen, click or type",
    "memory": "remember or forget facts about the user",
    "fun": "joke, coin flip, dice or random number",
    "power": "power plans, or apps that start with Windows",
    "productivity": "clipboard history, OCR, or reading text from a PDF/Word document",
    "security": "antivirus/Defender status or scan, BitLocker, Windows Update",
    "layout": "window layouts, snapping windows, moving windows between monitors",
    "email": "reading, sending or drafting email; calendar/meetings",
    "watch": "watch for a file/download/process, or notify on sustained CPU/RAM usage",
    "fileindex": "index a folder for local file search, or search indexed files by keyword",
    "dashboard": "start/stop/check the local web dashboard for remote control over Wi-Fi",
    "plugins": "list installed/loaded JARVIS plugins",
}

_YES_NO = {
    "multi_step": "Does the user ask for two or more separate actions done in sequence?",
    "destructive": ("Would doing this delete data, close programs, or shut down, restart "
                    "or sleep the computer?"),
}

PERSONAL_FACT_QUESTION = (
    "Does the message state a lasting fact or preference about the user, such as "
    "their name, job, family, likes, dislikes or habits?"
)


@dataclass
class Decision:
    intent: str
    confidence: float
    source: str                      # "laya", "rules" or "default"
    probabilities: Dict[str, float] = field(default_factory=dict)
    multi_step: float = 0.0
    destructive: float = 0.0
    latency_ms: float = 0.0

    @property
    def is_multi_step(self) -> bool:
        return self.multi_step >= 0.5

    @property
    def is_destructive(self) -> bool:
        return self.destructive >= 0.5


# ── Deterministic rules ──────────────────────────────────────────────────────

_WORD_MATH = r"(?:plus|minus|times|multiplied by|divided by|over|squared|cubed|to the power of|square root|percent of|mod)"
_RULES: List[tuple] = [
    # (intent, confidence, compiled regex) — first match wins, so order matters.
    ("memory", 0.95, re.compile(
        r"^(?:please\s+)?(?:remember(?: that)?|note that|keep in mind(?: that)?|don'?t forget(?: that)?|"
        r"forget (?!this conversation|(?:the\s+)?wi-?fi\b)\S|what do you (?:know|remember) about me|my name is\s+\S|"
        r"what(?:'s|s| is) my name|who am i\b|show (?:me )?(?:my )?memor(?:y|ies))", re.I)),
    ("open", 0.95, re.compile(r"^(?:please\s+)?(?:open|launch|start|show)\s+(?:the\s+|my\s+)?(?:alarms?|clock|timer)"
                              r"(?:\s+app)?$", re.I)),
    ("schedule", 0.92, re.compile(
        r"\b(?:alarm|remind me|reminder|timer|wake me(?: up)?|schedule(?:d)? (?:a |an )?(?:task|reminder|check|backup)|"
        r"(?:list|show|cancel)(?: my)? (?:scheduled )?(?:tasks|reminders|alarms))\b", re.I)),
    ("productivity", 0.93, re.compile(
        r"\bclipboard history\b|"
        r"^(?:please\s+)?copy\s+(?:entry\s+)?\d+\s+from\s+(?:clipboard\s+)?history\b|"
        r"^(?:please\s+)?paste\s+history\s+item\s+\d+\b|"
        r"\b(?:ocr|extract text from|get text from)\s+(?:my |the )?(?:screen|image|picture|photo)\b|"
        r"\bwhat does (?:my |the )?screen say\b|"
        r"\bread\s+(?:the\s+)?text\s+(?:in|from|on)\s+(?:this |the |my )?(?:image|picture|photo|screen|pdf|docx?|"
        r"word document)\b|"
        r"\bread\s+(?:the\s+|this\s+)?(?:pdf|docx?|word document)\b", re.I)),
    ("plugins", 0.93, re.compile(
        r"^(?:please\s+)?(?:list|show)\s+plugins\b|\bplugin\s+status\b|"
        r"^(?:please\s+)?(?:what|which)\s+plugins\s+(?:are\s+)?(?:loaded|installed)\b", re.I)),
    ("dashboard", 0.93, re.compile(
        r"^(?:please\s+)?(?:start|enable|turn on|launch)\s+(?:the\s+)?(?:remote\s+|web\s+)*dashboard\b|"
        r"^(?:please\s+)?(?:stop|disable|turn off|shut down)\s+(?:the\s+)?(?:remote\s+|web\s+)*dashboard\b|"
        r"\bdashboard\s+status\b|\bis\s+the\s+dashboard\s+running\b", re.I)),
    ("fileindex", 0.93, re.compile(
        r"^(?:please\s+)?index\s+(?:the\s+)?folder\s+\S|"
        r"^(?:please\s+)?(?:remove|unindex)\s+(?:the\s+)?folder\s+.+\s+from\s+(?:the\s+)?index\b|"
        r"^(?:please\s+)?clear\s+(?:the\s+|my\s+)?file\s+index\b|"
        r"\bfile\s+index\s+status\b|\bhow\s+many\s+files\s+are\s+indexed\b|"
        r"^(?:please\s+)?search\s+(?:my\s+|indexed\s+)?files\s+for\s+\S|"
        r"^(?:please\s+)?find\s+(?:the\s+)?(?:file|document)\s+(?:about|where|that)\s+\S", re.I)),
    ("file", 0.9, re.compile(
        r"\b(?:create|make|new|write|save|read|open|show|rename|delete|remove|copy|move|list)\b.{0,40}?"
        r"(?:\bfile\b(?!\s+explorer)|\bfiles\b|\bfolder\b|\bdirectory\b|\bdocument\b|"
        r"\.(?:txt|md|py|json|csv|log|html|js)\b)", re.I)),       # "open file explorer" is an app
    ("screen", 0.9, re.compile(
        r"\b(?:screen ?shot|screen capture|capture (?:the |my )?screen|what(?:'s|s| is) on (?:my |the )?screen|"
        r"(?:look at|analy[sz]e|describe|read) (?:my |the )?screen|click(?: on)?\b|double[- ]?click|right[- ]?click|"
        r"scroll (?:up|down)|type (?:out |in )?[\"'“]|press (?:the )?(?:enter|escape|tab|key)|automate)\b|"
        r"^(?:please\s+)?(?:type|write out|press|hit)\s+\S", re.I)),
    ("time", 0.95, re.compile(
        r"\b(?:what(?:'s|s| is)? (?:the )?(?:time|date)(?: now| today| right now)?|what time is it|current (?:time|date)|"
        r"time (?:is it|now)|today'?s date|what day is (?:it|today)|what(?:'s|s| is) today)\b", re.I)),
    ("math", 0.95, re.compile(
        r"^\s*(?:what(?:'s|s| is)|calculate|compute|solve|evaluate|how much is)?\s*"
        r"[-+(]*\s*\d[\d\s.,+\-*/^()x×÷%]*[\d)!]\s*[?=]*\s*$", re.I)),
    ("math", 0.9, re.compile(
        rf"(?:\d\s*{_WORD_MATH}\s*\d|\d\s*%\s*of\s*\d|\b(?:calculate|compute|square root of|convert \d|how many \w+ (?:in|are in) (?:a |an |one |\d))\b)", re.I)),
    ("weather", 0.92, re.compile(
        r"\b(?:weather|temperature outside|forecast|is it (?:going to )?(?:rain|snow)|will it rain|humidity)\b", re.I)),
    ("service", 0.93, re.compile(
        r"\bwhat(?:'s|s| is)\s+(?:using|eating|hogging)\s+(?:my\s+)?(?:cpu|ram|memory)\b|"
        r"\btop processes?\b|\b(?:list|show)\s+(?:running\s+)?(?:windows\s+)?services\b|"
        r"\b(?:start|stop|restart)\s+(?:the\s+)?[\w .-]+?\s+service\b|"
        r"^(?:please\s+)?(?:is|check if)\s+.+\s+service\s+(?:running|status)\??$", re.I)),
    ("security", 0.93, re.compile(
        r"\b(?:defender|antivirus)\s+status\b|\bis\s+(?:windows\s+)?defender\s+(?:on|enabled|running)\b|"
        r"^(?:please\s+)?(?:start|run)\s+(?:a\s+)?(?:full\s+|quick\s+)?(?:defender|antivirus|virus)\s+scan\b|"
        r"\bbitlocker\s+status\b|\bis\s+bitlocker\s+(?:on|enabled)\b|"
        r"\bcheck\s+for\s+(?:windows\s+)?updates\b|\bany\s+(?:windows\s+)?updates\s+available\b|"
        r"\bwindows\s+update\s+status\b|"
        r"^(?:please\s+)?install\s+(?:the\s+)?(?:windows\s+)?updates\b", re.I)),
    ("email", 0.93, re.compile(
        r"^(?:please\s+)?(?:list|show)\s+(?:my\s+)?(?:recent\s+)?(?:unread\s+)?emails?\b|"
        r"^(?:please\s+)?read\s+(?:the\s+)?email\s+(?:about|from)\s+\S|"
        r"^(?:please\s+)?(?:send|draft)\s+(?:an\s+)?email\s+to\s+\S|"
        r"^(?:please\s+)?reply\s+to\s+(?:the\s+)?email\s+(?:about|from)\s+.+\s+(?:saying|with)\s+\S|"
        r"\b(?:upcoming|next)\s+(?:calendar\s+)?events?\b|\bwhat(?:'s|s| is) on my calendar\b|"
        r"\bmy\s+(?:meetings|schedule)(?:\s+(?:today|tomorrow|this week))?\b", re.I)),
    ("watch", 0.93, re.compile(
        r"^(?:please\s+)?(?:watch for|tell me when)\s+.+?(?:\s+to)?\s+(?:appears?|is created|exists)\b|"
        r"^(?:please\s+)?(?:tell me|notify me)\s+when\s+(?:the\s+)?download(?:ing)?\s+.+\s+"
        r"(?:finishes|completes|is done)\b|"
        r"^(?:please\s+)?(?:tell me|notify me)\s+when\s+.+\s+(?:closes|exits|ends|finishes)\b|"
        r"^(?:please\s+)?(?:notify|tell) me\s+if\s+(?:cpu|memory|ram)\s+(?:is\s+|stays\s+)?(?:above|over)\s+\d|"
        r"\blist\s+watchers\b|\bwhat\s+(?:are\s+)?(?:you\s+)?watching\b|"
        r"^(?:please\s+)?stop\s+watch(?:er|ing)\s+\S|"
        r"^(?:please\s+)?clear\s+(?:all\s+)?watchers\b", re.I)),
    ("layout", 0.93, re.compile(
        r"\blist\s+monitors?\b|"
        r"^(?:please\s+)?save\s+(?:the\s+)?(?:current\s+)?(?:window\s+)?layout\s+as\s+\S|"
        r"\blist\s+(?:window\s+)?layouts\b|\bshow\s+saved\s+layouts\b|"
        r"^(?:please\s+)?(?:restore|load)\s+(?:the\s+)?layout\s+\S|"
        r"^(?:please\s+)?delete\s+(?:the\s+)?layout\s+\S|"
        r"^(?:please\s+)?move\s+.+\s+to\s+monitor\s+\d+\b|"
        r"^(?:please\s+)?snap\s+.+\s+to\s+(?:the\s+)?[\w-]+\b", re.I)),
    ("power", 0.93, re.compile(
        r"\b(?:list|show)\s+power\s+plans?\b|"
        r"\b(?:what(?:'s|s| is)\s+(?:the\s+)?(?:active|current)\s+power\s+plan|"
        r"which power plan (?:is|am i)\s+(?:active|on|using))\b|"
        r"^(?:please\s+)?(?:switch|set|change)\s+(?:the\s+)?power\s+plan\s+to\s+\S|"
        r"\b(?:list|show)\s+startup\s+apps?\b|"
        r"^(?:please\s+)?(?:enable|disable)\s+.+\s+(?:at|on|from)\s+startup\b", re.I)),
    ("system", 0.9, re.compile(
        r"\b(?:cpu|processor usage|ram|memory usage|disk (?:usage|space)|storage|battery|ip address|network (?:info|status)|"
        r"running processes|process list|system (?:status|info|information|report|health)|uptime|hardware info)\b", re.I)),
    ("control", 0.92, re.compile(
        r"\b(?:lock (?:my |the )?(?:pc|computer|screen|laptop|workstation)|shut ?down (?:the |my )?(?:pc|computer|laptop)|"
        r"restart (?:the |my )?(?:pc|computer|laptop)|reboot|log ?off|sign out|hibernate|"
        r"(?:put )?(?:the |my )?(?:pc|computer|laptop) to sleep|sleep (?:the |my )?(?:pc|computer|laptop)|"
        r"brightness|(?:dim|brighten)(?: the)? (?:screen|display)|make (?:the )?(?:screen|display) (?:dimmer|brighter)|"
        r"minimi[sz]e|maximi[sz]e|show (?:the )?desktop|close (?:all|every) windows?|"
        r"^(?:please\s+)?(?:switch|go back|change) to (?:the )?[\w.+-]+(?: window)?$|"
        r"list (?:open )?windows|switch to (?:the )?\w+ window|"
        r"(?:bluetooth|wi-?fi|display|sound|network) settings|open settings|(?:screen |display )?resolution)\b|"
        r"\b(?:empty|clear|clean(?: out)?|wipe|delete|remove)\b.{0,30}?\brecycle bin\b|"
        r"\brecycle bin\b.{0,20}?\b(?:empty|clear|delet(?:e|ing)|remov(?:e|ing))\b", re.I)),
    ("network", 0.9, re.compile(
        r"\b(?:list|show|scan for)\s+(?:nearby\s+)?wi-?fi\s+networks\b|\bwhat wi-?fi networks?\b|"
        r"\b(?:connect to|join|forget|disconnect (?:from )?)\s*(?:the\s+)?wi-?fi\b|\bturn off wi-?fi\b|"
        r"\bwi-?fi status\b|\bcurrent wi-?fi\b|"
        r"^(?:please\s+)?ping\s+\S+|\bflush(?:ing)? (?:the )?dns\b|"
        r"\bnetwork config(?:uration)?\b|\b(?:list|show)\s+vpn\b|\bconnect to (?:the\s+)?vpn\b|"
        r"\bdisconnect (?:the\s+)?vpn\b", re.I)),
    ("appscript", 0.93, re.compile(
        r"\b(?:make|model|create|build|design|generate|render)\b.*\bin\s+blender\b|"
        r"\bblender\b.*\b(?:make|model|create|build|design|generate)\b.*\b(?:model|mesh|object|scene)\b|"
        r"^(?:please\s+)?(?:open\s+)?blender\s+and\s+(?:make|model|create|build)\b", re.I)),
    ("software", 0.92, re.compile(
        r"^(?:please\s+)?(?:install|uninstall)\s+(?!.*\b(?:file|files|folder|folders)\b).+$|"
        r"\b(?:upgrade|update)\s+(?:all\s+)?(?:my\s+)?(?:apps?|applications?|programs?|software|packages?)\b|"
        r"\bwinget\b|\bis\s+.+\s+installed\b|\bdo i have\s+.+\s+installed\b", re.I)),
    ("media", 0.9, re.compile(
        r"^(?:please\s+)?(?:pause|resume|unpause|stop)(?: it| this| that)?(?: the)?"
        r"(?: music| song| video| playback| media)?\s*$|"
        r"\b(?:next|previous|skip)(?: the| this| that)? (?:song|track|video)\b|^(?:skip (?:it|this|that)|next one)\s*$|"
        r"\b(?:un)?mute\b|"
        r"\b(?:volume|turn (?:it )?(?:up|down)|louder|quieter)\b|\bwhat(?:'s|s| is) playing\b", re.I)),
    ("open", 0.9, re.compile(
        r"^(?:please\s+)?(?:can you\s+)?(?:open|launch|start|run|close|quit|exit|kill|go to|navigate to|visit|"
        r"browse to|take me to|play)\s+\S", re.I)),
    ("open", 0.85, re.compile(r"\b(?:https?://|www\.)\S+|\b\w+\.(?:com|org|net|io|in|co|dev|ai)\b", re.I)),
    ("search", 0.9, re.compile(
        r"^(?:please\s+)?(?:search|google|look up|lookup|find (?:out|info|information)|search for|who is|who was|"
        r"what happened)\b|\b(?:news|headlines|wikipedia|wiki|latest)\b", re.I)),
    ("fun", 0.95, re.compile(
        r"\b(?:joke|flip a coin|coin (?:flip|toss)|toss a coin|roll (?:a |the |two |\d )?di(?:e|ce)|random number|"
        r"generate (?:a )?password)\b", re.I)),
]

_SEQUENCE = re.compile(r"\b(?:and then|then|after that|afterwards|followed by|next)\b|;|,\s*(?:and\s+)?(?=\w+\s)", re.I)
_ACTION_VERBS = (r"open|launch|start|close|type|write|save|create|search|play|go to|take|click|set|"
                 r"remind|turn|lock|show|tell|send|check|find|rename|delete|copy|move|wait")
_VERB_RE = re.compile(rf"(?:^|\b(?:and|then|,|;)\s+|^please\s+)(?:{_ACTION_VERBS})\b", re.I)
_DESTRUCTIVE = re.compile(
    r"\b(?:delete|remove|erase|wipe|format|kill|terminate|end task|close all|shut ?down|restart|reboot|"
    r"log ?off|sign out|hibernate|uninstall)\b|"
    r"\b(?:empty|clear|clean(?: out)?|wipe|delete|remove)\b.{0,30}?\brecycle bin\b|"
    r"\brecycle bin\b.{0,20}?\b(?:empty|clear|delet(?:e|ing)|remov(?:e|ing))\b", re.I)


def rule_decision(command: str) -> Decision:
    text = (command or "").strip()
    start = time.perf_counter()
    intent, conf = "chat", 0.4
    for name, confidence, pattern in _RULES:
        if pattern.search(text):
            intent, conf = name, confidence
            break
    multi = 0.0
    verbs = _VERB_RE.findall(text)
    if re.search(r"screen ?shot.*\b(?:tell|describe|what|analy[sz]e)\b", text, re.I) and not re.search(r"\bthen\b", text, re.I):
        verbs = verbs[:1]
    if len(verbs) >= 2:
        site_action = re.search(r"\b(?:go to|open|visit)\s+\S+\s+and\s+(?:play|search|watch|find|look up)\b", text, re.I)
        if _SEQUENCE.search(text) and not (site_action and not re.search(r"\bthen\b|;", text, re.I)):
            multi = 1.0
        elif re.search(r"\band\b", text, re.I) and not site_action:
            multi = 1.0
    destructive = 1.0 if _DESTRUCTIVE.search(text) else 0.0
    return Decision(intent=intent, confidence=conf, source="rules" if intent != "chat" or conf > 0.4 else "default",
                    multi_step=multi, destructive=destructive,
                    latency_ms=(time.perf_counter() - start) * 1000)


# ── Laya ─────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """Routes commands with Laya when available, rules otherwise."""

    def __init__(self, engine: str = "laya", model: str = "english",
                 repo: str = "convaiinnovations/laya", threshold: float = 0.45,
                 on_status: Optional[Callable[[str], None]] = None):
        self.engine = engine
        self.model = model
        self.repo = repo
        self.threshold = threshold
        self._on_status = on_status
        self._agent = None
        self._lock = threading.Lock()
        self._loading = False
        self._intent_mode = "described"     # falls back to "labels" if descriptions overflow
        self.status = "rules only" if engine != "laya" else "not loaded"
        self.last_error = ""

    # -- lifecycle ------------------------------------------------------------
    @property
    def laya_ready(self) -> bool:
        return self._agent is not None

    def set_status_callback(self, fn: Optional[Callable[[str], None]]) -> None:
        self._on_status = fn

    def _emit(self, status: str) -> None:
        self.status = status
        log.info("Decision engine: %s", status)
        if self._on_status:
            try:
                self._on_status(status)
            except Exception:  # never let a UI callback break loading
                log.exception("status callback failed")

    def warm_up_async(self) -> None:
        """Load Laya in a background thread (no-op if disabled or loaded)."""
        if self.engine != "laya" or self._agent is not None or self._loading:
            return
        self._loading = True
        threading.Thread(target=self._load, name="LayaLoader", daemon=True).start()

    def _load(self) -> None:
        try:
            self._emit("loading Laya decision model…")
            try:
                import laya  # noqa: F401  (heavy: torch + transformers)
            except ImportError:
                self.last_error = "laya package not installed"
                self._emit("rules only — install Laya with: pip install laya")
                return
            subfolder = "multilingual" if self.model == "multilingual" else None
            started = time.perf_counter()
            agent = laya.load(self.repo, subfolder=subfolder)
            # One tiny warm-up pass so the first real command is fast.
            agent.predict("hello", {"w": {"type": "noul", "instructions": "Is this a greeting?"}})
            with self._lock:
                self._agent = agent
            self._emit(f"Laya ready ({self.model}, {time.perf_counter() - started:.1f}s)")
        except Exception as exc:
            self.last_error = str(exc)
            log.exception("Laya failed to load")
            self._emit(f"rules only — Laya failed to load: {exc}")
        finally:
            self._loading = False

    def unload(self) -> None:
        with self._lock:
            self._agent = None
        self.status = "not loaded"

    # -- generic typed questions ---------------------------------------------
    def ask(self, state: Any, questions: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Run arbitrary Laya questions. Returns ``answers`` or None if unavailable."""
        agent = self._agent
        if agent is None:
            return None
        try:
            return agent.predict(state, questions).get("answers", {})
        except Exception as exc:
            log.warning("Laya question failed: %s", exc)
            return None

    def yes_no(self, state: Any, question: str) -> Optional[float]:
        answers = self.ask(state, {"q": {"type": "noul", "instructions": question}})
        if not answers:
            return None
        return float(answers["q"].get("noul", 0.0))

    # -- routing -------------------------------------------------------------
    def _intent_question(self) -> Dict[str, Any]:
        criteria: Any = dict(INTENTS) if self._intent_mode == "described" else list(INTENTS)
        return {"type": "choice",
                "instructions": "What does the user want JARVIS, a desktop assistant, to do?",
                "criteria": criteria}

    def _laya_decision(self, command: str) -> Optional[Decision]:
        agent = self._agent
        if agent is None:
            return None
        questions = {"intent": self._intent_question()}
        for key, text in _YES_NO.items():
            questions[key] = {"type": "noul", "instructions": text}
        start = time.perf_counter()
        try:
            answers = agent.predict(command, questions)["answers"]
        except ValueError as exc:
            if self._intent_mode == "described" and "head_max_len" in str(exc):
                self._intent_mode = "labels"
                return self._laya_decision(command)
            log.warning("Laya routing failed: %s", exc)
            return None
        except Exception as exc:
            log.warning("Laya routing failed: %s", exc)
            return None
        intent = answers["intent"]
        return Decision(
            intent=intent["choice"],
            confidence=float(intent.get("confidence", 0.0)),
            source="laya",
            probabilities=dict(intent.get("probabilities", {})),
            multi_step=float(answers["multi_step"].get("noul", 0.0)),
            destructive=float(answers["destructive"].get("noul", 0.0)),
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    def decide(self, command: str) -> Decision:
        """Pick an intent for ``command``. Never raises; never calls an LLM."""
        rules = rule_decision(command)
        model = self._laya_decision(command) if self.engine == "laya" else None
        if model is None:
            return rules
        # Rules only fire on precise patterns; trust them over an unsure model.
        rule_hit = rules.source == "rules"
        if rule_hit and rules.intent != model.intent and model.confidence < 0.8:
            chosen = rules
        elif model.confidence >= self.threshold:
            chosen = model
        elif rule_hit:
            chosen = rules
        else:
            chosen = Decision("chat", model.confidence, "laya", model.probabilities)
        # Safety flags: either signal is enough to be careful.
        chosen.multi_step = max(model.multi_step, rules.multi_step) if chosen is not rules else max(
            rules.multi_step, model.multi_step)
        chosen.destructive = max(model.destructive, rules.destructive)
        if chosen.source == "rules":
            chosen.probabilities = model.probabilities
        chosen.latency_ms = model.latency_ms + rules.latency_ms
        return chosen

    def describe(self) -> str:
        return f"Decision engine: {self.status}"
