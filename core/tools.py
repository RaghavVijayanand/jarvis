"""The single tool system JARVIS exposes to language models (audit UC 3.3 / 11.2).

Every action a model may take is registered here once, with a JSON schema and
the skill method that performs it. The same registry serves OpenRouter,
Gemini and Ollama function calling, so there is exactly one execution path.
Tools marked ``confirm=True`` never run without an explicit "yes" from the
user (via ``JARVIS.confirm``), whatever the model says.
"""
from __future__ import annotations

import json
import re
import string
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.logging_setup import get_logger

log = get_logger("jarvis.tools")

# Always offered to small local models (see ToolRegistry.relevant): the everyday desktop actions.
CORE_TOOLS = ("open_app_or_website", "window_action", "list_windows", "type_text", "press_keys", "close_app",
              "media_control", "now_playing", "set_volume", "change_volume", "get_time", "get_weather", "web_search",
              "set_reminder", "set_alarm", "remember_fact", "describe_screen", "take_screenshot",
              "set_clipboard", "get_clipboard", "read_file", "create_file", "list_files", "get_system_status")
# Tools whose output is text from outside JARVIS's control (web pages, mail, files, the screen).
# Any of it can carry instructions ("press Win+R and type ..."), i.e. prompt injection.
UNTRUSTED_OUTPUT = frozenset({
    "web_search", "read_email", "list_recent_emails", "list_upcoming_events", "read_file", "read_pdf_text",
    "read_docx_text", "search_file_contents", "search_indexed_files", "screen_text", "ocr_image",
    "describe_screen", "get_clipboard", "list_clipboard_history", "list_windows"})
# Tools that act on the PC or can carry data out. Normally they run straight away; once the
# current turn has read untrusted text they need a "yes", so injected text can't drive them.
GATED_AFTER_UNTRUSTED = frozenset({
    "open_app_or_website", "type_text", "press_keys", "click_on_screen", "set_clipboard", "create_file",
    "rename_file", "create_archive", "extract_archive", "draft_email", "remember_fact", "ping_host",
    "check_port", "copy_from_clipboard_history", "window_action"})

_SECRET_ARG = re.compile(r"pass(word|phrase)?|secret|token|api_?key|pin$", re.I)


def _shown(key: str, value: Any) -> str:
    """An argument as it may appear on screen or in the tool log: secrets are masked."""
    if value in (None, ""):
        return ""
    return "••••••" if _SECRET_ARG.search(str(key)) else str(value)


_STOPWORDS = {"the", "and", "for", "you", "can", "could", "please", "with", "that", "this", "what", "from",
              "into", "about", "your", "have", "want", "just", "like", "make", "get", "how", "are", "its"}


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    confirm: bool = False
    confirm_text: str = ""

    def schema(self) -> Dict[str, Any]:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}


def params(required: Optional[List[str]] = None, **props: Any) -> Dict[str, Any]:
    """Small helper: params(required=['city'], city=('string', 'City name'))."""
    properties = {}
    for name, spec in props.items():
        kind, desc = spec[0], spec[1]
        entry: Dict[str, Any] = {"type": kind, "description": desc}
        if len(spec) > 2:
            entry["enum"] = list(spec[2])
        properties[name] = entry
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


class ToolRegistry:
    def __init__(self, confirm: Optional[Callable[[str], bool]] = None):
        self._tools: Dict[str, Tool] = {}
        self._confirm = confirm
        self.log: List[Dict[str, Any]] = []   # recent executions (for UI / debugging)
        self._turn = threading.local()        # per-thread: did this turn read untrusted text?

    def begin_turn(self) -> None:
        """Call once per user request, before the model's tool loop."""
        self._turn.tainted = False

    def set_confirm(self, fn: Optional[Callable[[str], bool]]) -> None:
        self._confirm = fn

    def register(self, tool: Tool) -> None:
        old = self._tools.get(tool.name)
        if old is not None and old.confirm and not tool.confirm:
            # A plugin re-using a built-in's name must not shed its "yes" requirement.
            log.warning("Tool %s re-registered without confirmation; keeping confirmation on", tool.name)
            tool.confirm, tool.confirm_text = True, tool.confirm_text or old.confirm_text
        self._tools[tool.name] = tool

    def add(self, name: str, description: str, func: Callable[..., Any],
            parameters: Optional[Dict[str, Any]] = None, confirm: bool = False,
            confirm_text: str = "") -> None:
        self.register(Tool(name, description, func,
                           parameters or {"type": "object", "properties": {}},
                           confirm, confirm_text))

    def names(self) -> List[str]:
        return list(self._tools)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def schemas(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if names is None:
            return [tool.schema() for tool in self._tools.values()]
        return [self._tools[n].schema() for n in names if n in self._tools]

    def relevant(self, text: str, limit: int = 30) -> List[str]:
        """A small local model can't take ~110 tool schemas (~8k tokens) and still see the
        conversation: the everyday tools, plus the ones whose name or description shares words
        with the request."""
        words = {w.rstrip("s") for w in re.findall(r"[a-z]{3,}", (text or "").lower())} - _STOPWORDS
        scored = []
        for name, tool in self._tools.items():
            if name in CORE_TOOLS:
                continue
            hay = {w.rstrip("s") for w in re.findall(r"[a-z]{3,}", f"{name.replace('_', ' ')} {tool.description}".lower())}
            score = len(words & hay)
            if score:
                scored.append((-score, name))
        scored.sort()
        chosen = [n for n in CORE_TOOLS if n in self._tools] + [n for _, n in scored]
        return chosen[:limit]

    @staticmethod
    def parse_arguments(raw: Any) -> Dict[str, Any]:
        if raw is None or raw == "":
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return value if isinstance(value, dict) else {}
        return {}

    def execute(self, name: str, arguments: Any) -> str:
        """Run a tool and return a string observation for the model. Never raises."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'."
        args = self.parse_arguments(arguments)
        allowed = tool.parameters.get("properties", {})
        # Drop unknown keys a model may hallucinate; check required ones.
        args = {k: v for k, v in args.items() if k in allowed}
        missing = [k for k in tool.parameters.get("required", []) if args.get(k) in (None, "")]
        if missing:
            return f"Error: missing required argument(s) for {name}: {', '.join(missing)}."
        tainted = getattr(self._turn, "tainted", False)
        if tool.confirm or (tainted and name in GATED_AFTER_UNTRUSTED):
            question = self._question(tool, args)
            if not tool.confirm:
                question = ("After reading outside content (web, email, a file or the screen), the AI wants to "
                            f"run {name} {self._describe(args)}. Allow it?")
            approved = bool(self._confirm and self._confirm(question))
            if not approved:
                self._record(name, args, "declined")
                return "The user declined this action. Do not retry it; tell the user it was not done."
        try:
            result = tool.func(**args)
        except TypeError as exc:
            log.warning("Tool %s bad arguments %s: %s", name, args, exc)
            return f"Error: invalid arguments for {name}: {exc}"
        except Exception as exc:
            log.exception("Tool %s failed", name)
            return f"Error while running {name}: {exc}"
        text = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
        if name in UNTRUSTED_OUTPUT:
            self._turn.tainted = True
        self._record(name, args, text)
        return text[:6000]

    @staticmethod
    def _describe(args: Dict[str, Any]) -> str:
        return ", ".join(f"{k}={_shown(k, v)[:200]!r}" for k, v in args.items()) or "(no arguments)"

    def _question(self, tool: Tool, args: Dict[str, Any]) -> str:
        """The confirmation text, always naming every argument so nothing material is hidden."""
        if not tool.confirm_text:
            return f"Allow JARVIS to run '{tool.name}' with {self._describe(args)}?"
        try:
            shown = {f for _, f, _, _ in string.Formatter().parse(tool.confirm_text) if f}
            question = tool.confirm_text.format_map({k: _shown(k, args.get(k, "")) for k in shown})
        except (IndexError, ValueError, AttributeError):
            return f"{tool.confirm_text} ({self._describe(args)})"
        rest = {k: v for k, v in args.items() if k not in shown and v not in (None, "")}
        return f"{question} ({self._describe(rest)})" if rest else question

    def _record(self, name: str, args: Dict[str, Any], result: str) -> None:
        self.log.append({"tool": name, "args": {k: _shown(k, v) for k, v in args.items()}, "result": result[:300]})
        del self.log[:-50]
