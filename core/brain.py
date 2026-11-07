"""Multi-provider language-model brain for JARVIS.

Providers
    * OpenRouter  — OpenAI-compatible chat completions.
    * Gemini      — Google's OpenAI-compatible endpoint (no extra SDK needed).
    * Ollama      — local models via ``/api/chat``.

All three support function calling through one ``ToolRegistry`` (core/tools.py).
Provider failures never masquerade as answers: they come back as a
``Reply`` with ``is_error=True``, are not stored in the conversation, and the
brain automatically fails over to the next usable model once (audit UC 3.5).
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.config import Config
from core.logging_setup import get_logger
from core.memory import MemoryManager

log = get_logger("jarvis.brain")

_PLAN_SYSTEM_PROMPT = (
    "You are a planner for a Windows desktop assistant. Break the user's request into "
    "an ordered list of separate, atomic instructions — each one a complete, standalone "
    "imperative command a simple rule-based router could act on by itself (e.g. 'open Chrome', "
    "'search for python tutorials', 'wait 10 seconds'). "
    "Respond with ONLY a numbered list, one instruction per line, nothing else — no preamble, "
    "no explanation. If the request is already a single atomic action, respond with just "
    "'1. <the request>'. Keep the original wording/details (names, numbers, times) intact."
)
_STEP_LINE = re.compile(r"^\s*\d+[.)]\s*(.+?)\s*$")

# Static fallbacks used until the live catalogs are fetched (or when offline).
# Gemini's "-latest" aliases track Google's current release, so they do not rot.
GEMINI_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "gemini-flash": {"model_id": "gemini-flash-latest", "description": "Gemini Flash (latest)"},
    "gemini-flash-lite": {"model_id": "gemini-flash-lite-latest", "description": "Gemini Flash-Lite (latest, fastest)"},
    "gemini-pro": {"model_id": "gemini-pro-latest", "description": "Gemini Pro (latest, strongest)"},
}
OPENROUTER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "openrouter-auto": {"model_id": "openrouter/auto", "description": "OpenRouter auto-router (paid credits)",
                        "supports_tools": True, "supports_vision": True},
}
MAX_TOOL_ROUNDS = 6


class ProviderError(Exception):
    """A provider call failed. ``retryable`` means another model may succeed."""

    def __init__(self, message: str, retryable: bool = True, status: Optional[int] = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class Reply(str):
    """A string reply that also says whether it is an error message."""

    is_error: bool = False
    model: str = ""

    def __new__(cls, text: str, is_error: bool = False, model: str = ""):
        obj = super().__new__(cls, text)
        obj.is_error = is_error
        obj.model = model
        return obj


def _as_dict(raw: Any) -> Dict[str, Any]:
    """Tool arguments as a dict (Ollama expects objects, not JSON strings)."""
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# A reply that reports an action as done ("has been opened", "I've turned up the volume").
_ACTION_STEMS = (r"open|clos|play|paus|resum|start|launch|turn|increas|decreas|rais|lower|set|chang|typ|sav|creat|"
                 r"delet|mov|renam|sent|send|mut|switch|focus|minimi|maximi|updat|schedul|remind|skipp|stopp")
_CLAIMS_ACTION = re.compile(
    rf"\b(?:has been|have been|is now|are now|i(?:'ve| have)|i just|now playing|done[.!]|successfully)\b.{{0,60}}?"
    rf"\b(?:{_ACTION_STEMS})|"
    # the terse style of JARVIS's own replies, which small models copy from the history: "Closed Notepad."
    rf"^\s*(?:{_ACTION_STEMS})\w*ed\b|^\s*(?:reminder|alarm|volume)\s+(?:set|updated|changed)", re.I)
_DID_NOT_ACT = "Sorry, I didn't manage to do that. Could you say it another way, or name the app?"
_NUDGE = ("You described doing that, but no tool was called, so nothing actually happened on the computer. "
          "If the request needs an action, call the right tool now. If it doesn't, answer without saying you did it.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MultiModelBrain:
    # Guards conversation_history and its file: the GUI and voice threads can
    # both call process_command. Class-level so instances built with __new__
    # (tests) still have it; kept separate from ``_lock`` because that one is
    # held across network calls during a catalog refresh.
    _history_lock = threading.RLock()

    def __init__(self):
        self.available_models: Dict[str, Dict[str, Any]] = {}
        self.current_model: Optional[str] = None
        self.conversation_history: List[Dict[str, Any]] = []
        self.memory = MemoryManager()
        self.tool_registry = None           # set by JARVIS.attach_tools()
        self.context_provider = None        # () -> str: what's on the desktop right now (set by JARVIS)
        self.last_error: str = ""
        self._lock = threading.RLock()
        self._history_file = Config.LOGS_DIR / "conversation_history.json"
        self._catalog_file = Config.CACHE_DIR / "model_catalog.json"
        self._catalog: Dict[str, Dict[str, Any]] = self._load_catalog()
        self._load_history()
        self._initialize_providers()
        self._set_default_model()

    # ── Catalog / providers ──────────────────────────────────────────────────

    def _load_catalog(self) -> Dict[str, Dict[str, Any]]:
        try:
            if self._catalog_file.exists():
                data = json.loads(self._catalog_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            log.warning("Model catalog cache unreadable: %s", exc)
        return {}

    def _save_catalog(self) -> None:
        try:
            self._catalog_file.parent.mkdir(parents=True, exist_ok=True)
            self._catalog_file.write_text(json.dumps(self._catalog, indent=1), encoding="utf-8")
        except Exception as exc:
            log.warning("Could not save model catalog: %s", exc)

    def refresh_catalog(self, timeout: float = 8.0) -> str:
        """Fetch live model lists (OpenRouter free models, Gemini models)."""
        import requests
        notes = []
        catalog = dict(self._catalog)
        if Config.OPENROUTER_API_KEY:
            try:
                resp = requests.get(f"{Config.OPENROUTER_BASE_URL}/models", timeout=timeout)
                resp.raise_for_status()
                free = {}
                for m in (resp.json() or {}).get("data", []):
                    mid = m.get("id", "") if isinstance(m, dict) else ""
                    if not mid or not self._openrouter_is_free(m):
                        continue
                    supported = m.get("supported_parameters") or []
                    modalities = (m.get("architecture") or {}).get("input_modalities") or []
                    free[mid] = {
                        "context_window": int(m.get("context_length") or 32768),
                        "supports_tools": "tools" in supported,
                        "supports_vision": "image" in modalities,
                        "description": (m.get("name") or mid) + " (free)",
                    }
                catalog["openrouter"] = free
                notes.append(f"OpenRouter: {len(free)} free models")
            except Exception as exc:
                notes.append(f"OpenRouter catalog unavailable ({exc})")
        if Config.GEMINI_API_KEY:
            try:
                resp = requests.get(f"{Config.GEMINI_OPENAI_BASE_URL}/models",
                                    headers={"Authorization": f"Bearer {Config.GEMINI_API_KEY}"},
                                    timeout=timeout)
                resp.raise_for_status()
                gem = {}
                for m in (resp.json() or {}).get("data", []):
                    mid = ((m.get("id") if isinstance(m, dict) else "") or "").replace("models/", "")
                    if mid.startswith("gemini") and not any(x in mid for x in ("embedding", "tts", "image", "live", "audio")):
                        gem[mid] = {"context_window": 1_000_000, "supports_tools": True,
                                    "supports_vision": True, "description": mid}
                catalog["gemini"] = gem
                notes.append(f"Gemini: {len(gem)} models")
            except Exception as exc:
                notes.append(f"Gemini catalog unavailable ({exc})")
        with self._lock:
            self._catalog = catalog
            self._save_catalog()
            self._initialize_providers()
            self._set_default_model()
        return "; ".join(notes) or "No cloud providers configured."

    @staticmethod
    def _openrouter_is_free(m: Dict[str, Any]) -> bool:
        """``:free`` variants, or models whose prompt and completion prices are both 0.

        OpenRouter prices are decimal strings; ``openrouter/auto`` reports "-1"
        (variable), which is not free.
        """
        if str(m.get("id", "")).endswith(":free"):
            return True
        pricing = m.get("pricing") or {}
        try:
            return (float(pricing.get("prompt")) == 0.0 and float(pricing.get("completion")) == 0.0)
        except (TypeError, ValueError):
            return False

    def refresh_catalog_async(self, on_done=None) -> None:
        def run():
            msg = self.refresh_catalog()
            log.info("Catalog refresh: %s", msg)
            if on_done:
                try:
                    on_done(msg)
                except Exception:
                    log.exception("catalog callback failed")
        threading.Thread(target=run, name="ModelCatalog", daemon=True).start()

    def _initialize_providers(self) -> None:
        """Rebuild ``available_models`` from keys, catalogs and local Ollama."""
        models: Dict[str, Dict[str, Any]] = {}
        local_only = getattr(Config, "LOCAL_ONLY", False)   # cloud models never registered: no fallback to them
        if getattr(Config, "OPENROUTER_API_KEY", "") and not local_only:
            for name, cfg in OPENROUTER_DEFAULTS.items():
                models[name] = {"provider": "openrouter", "context_window": 128000, **cfg}
            for mid, cfg in (self._catalog.get("openrouter") or {}).items():
                short = mid.split("/", 1)[-1].replace(":free", "") + " (free)"
                models[short] = {"provider": "openrouter", "model_id": mid, **cfg}
        if getattr(Config, "GEMINI_API_KEY", "") and not local_only:
            for name, cfg in GEMINI_DEFAULTS.items():
                models[name] = {"provider": "gemini", "context_window": 1_000_000,
                                "supports_tools": True, "supports_vision": True, **cfg}
            for mid, cfg in (self._catalog.get("gemini") or {}).items():
                if not any(m.get("model_id") == mid for m in models.values()):
                    models[mid] = {"provider": "gemini", "model_id": mid, **cfg}
        # Keep previously discovered local models until the next scan.
        for name, cfg in self.available_models.items():
            if cfg.get("provider") == "ollama":
                models[name] = cfg
        self.available_models = models
        self._check_local_models()

    def _check_local_models(self) -> List[str]:
        """Discover local Ollama models. Returns the names found."""
        from core.ollama_manager import VISION_MODEL_KEYWORDS
        found = []
        # Build a new dict and swap it in: other threads iterate available_models.
        models = dict(self.available_models)
        try:
            import requests
            resp = requests.get(f"{Config.OLLAMA_URL}/api/tags", timeout=2)
            if resp.status_code != 200:
                return found
            listed = resp.json().get("models", [])
            # A successful scan is authoritative: drop local models that were removed.
            models = {k: v for k, v in models.items() if v.get("provider") != "ollama"}
            for m in listed:
                name = m.get("name", "")
                if not name or "embed" in name.lower():
                    continue
                key = f"ollama:{name}"
                caps = self._ollama_capabilities(name)
                is_vision = "vision" in caps or any(kw in name.lower() for kw in VISION_MODEL_KEYWORDS)
                models[key] = {
                    # 16k: the system prompt + offered tools + history; 8k overflowed and dropped the history.
                    "provider": "ollama", "model_id": name, "context_window": 16384,
                    "supports_vision": is_vision, "supports_tools": "tools" in caps,
                    "supports_thinking": "thinking" in caps,
                    "description": f"Local — {name}" + (" [vision]" if is_vision else "")
                                   + (" [tools]" if "tools" in caps else ""),
                }
                found.append(key)
            self.available_models = models
        except Exception:
            pass  # Ollama not running or not installed — expected
        return found

    @staticmethod
    def _ollama_capabilities(name: str) -> List[str]:
        try:
            import requests
            resp = requests.post(f"{Config.OLLAMA_URL}/api/show", json={"model": name}, timeout=3)
            if resp.status_code == 200:
                return list(resp.json().get("capabilities") or [])
        except Exception:
            pass
        return []

    def _set_default_model(self) -> None:
        if self.current_model and self.current_model in self.available_models:
            return
        preferred = [Config.DEFAULT_MODEL] if getattr(Config, "DEFAULT_MODEL", "") else []
        preferred += ["gemini-flash", "gemini-flash-lite"]
        preferred += sorted((k for k, v in self.available_models.items()
                             if v.get("provider") == "openrouter" and v.get("supports_tools")
                             and k != "openrouter-auto"), key=lambda k: -self.available_models[k].get("context_window", 0))
        preferred += [k for k, v in self.available_models.items()
                      if v.get("provider") == "ollama" and v.get("supports_tools")]
        preferred += [k for k in self.available_models if k.startswith("ollama:")]
        preferred += ["openrouter-auto"]
        for name in preferred:
            if name in self.available_models:
                self.current_model = name
                return
        self.current_model = next(iter(self.available_models), None)

    def list_available_models(self) -> str:
        if not self.available_models:
            return "No models available. Add an API key in Settings or install Ollama."
        lines = []
        for name, cfg in self.available_models.items():
            flags = ",".join(f for f, on in (("tools", cfg.get("supports_tools")),
                                             ("vision", cfg.get("supports_vision"))) if on)
            marker = "▶ " if name == self.current_model else "  "
            lines.append(f"{marker}{name} ({cfg['provider']}{', ' + flags if flags else ''})")
        return "Available models:\n" + "\n".join(lines)

    def switch_model(self, model_name: str) -> str:
        name = (model_name or "").strip()
        if name not in self.available_models:
            matches = [k for k in self.available_models if name.lower() in k.lower()]
            if len(matches) != 1:
                return f"Model '{model_name}' is not available."
            name = matches[0]
        self.current_model = name
        self.picked_by_user = True             # a later Ollama start-up must not switch it back
        return f"Switched to '{name}'."

    def prefer_default_model(self) -> bool:
        """The configured default may only appear later (Ollama still starting when JARVIS did).
        Move to it then — unless the user has picked a model themselves since."""
        wanted = getattr(Config, "DEFAULT_MODEL", "")
        if wanted and wanted in self.available_models and self.current_model != wanted \
                and not getattr(self, "picked_by_user", False):
            self.current_model = wanted
            return True
        return False

    def get_model_info(self) -> Dict[str, Any]:
        if not self.current_model:
            return {"active": None}
        cfg = self.available_models.get(self.current_model, {})
        return {"active": self.current_model, "provider": cfg.get("provider"),
                "context_window": cfg.get("context_window"),
                "supports_vision": cfg.get("supports_vision"),
                "supports_tools": cfg.get("supports_tools"),
                "description": cfg.get("description")}

    # ── History ──────────────────────────────────────────────────────────────

    def _load_history(self) -> None:
        if not self._history_file.exists():
            return
        try:
            data = json.loads(self._history_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("history file is not a list")
            # Only well-formed chat turns: a hand-edited or truncated entry must
            # not crash every later request (msg["content"] is read directly).
            self.conversation_history = [
                m for m in data if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                and isinstance(m.get("content"), str)][-100:]
        except Exception as exc:
            log.warning("Conversation history unreadable, starting fresh: %s", exc)
            self.conversation_history = []

    def _save_history(self) -> None:
        with self._history_lock:
            try:
                self._history_file.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._history_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.conversation_history[-100:], indent=2, ensure_ascii=False),
                               encoding="utf-8")
                tmp.replace(self._history_file)
            except Exception as exc:
                log.warning("Could not save conversation history: %s", exc)

    def _append_turn(self, user_text: str, reply: str) -> None:
        """Atomically add one user/assistant pair, cap the history and persist it."""
        with self._history_lock:
            self.conversation_history.extend([
                {"role": "user", "content": str(user_text), "ts": _now()},
                {"role": "assistant", "content": str(reply), "ts": _now()},
            ])
            del self.conversation_history[:-100]
            self._save_history()

    def clear_history(self) -> str:
        with self._history_lock:
            self.conversation_history.clear()
            self._save_history()
        return "Conversation history cleared."

    @staticmethod
    def _history_budget(context_window) -> int:
        """Character budget for sent history (UC 10.2): context minus headroom, ~4 chars/token."""
        try:
            ctx = int(context_window or 0)
        except (TypeError, ValueError):
            ctx = 0
        ctx = ctx if ctx > 0 else 8192
        return max(128, ctx - 1024) * 4

    def _history_window(self, budget_chars: int) -> List[Dict]:
        """Newest-first prior turns that fit the character budget."""
        selected: List[Dict] = []
        remaining = max(0, budget_chars)
        with self._history_lock:
            recent = list(self.conversation_history[-30:])     # the budget below still caps it to the model
        for msg in reversed(recent):
            if msg.get("role") not in ("user", "assistant") or not isinstance(msg.get("content"), str):
                continue
            cost = len(msg["content"]) + 8
            if cost > remaining:
                break
            remaining -= cost
            selected.append(msg)
        selected.reverse()
        return selected

    def record_exchange(self, user_text: str, reply: str) -> None:
        """Store a turn handled outside the LLM (e.g. a skill answer) as context."""
        if not user_text or not reply or getattr(reply, "is_error", False):
            return
        self._append_turn(user_text, str(reply)[:4000])

    # ── Prompting ────────────────────────────────────────────────────────────

    def _get_system_prompt(self, with_tools: bool = False) -> str:
        memory_ctx = self.memory.get_context_string()
        now = datetime.now().strftime("%A %d %B %Y, %H:%M")
        prompt = (
            "You are JARVIS, a desktop AI assistant on the user's Windows PC, inspired by Tony Stark's JARVIS. "
            "You are precise, helpful and concise, with a dry British wit. "
            f"Current local time: {now}. {memory_ctx}"
        )
        if with_tools:
            prompt += (
                " You can act on the computer using the provided tools. Use a tool whenever the user asks "
                "you to do something rather than explain it; chain several tools for multi-step requests. "
                "Never claim an action succeeded unless a tool result says so. If a tool reports an error "
                "or the user declined, say so plainly. "
                "Every action needs its own tool call, every time — replies like \"Opened Notepad.\" earlier in "
                "the conversation were produced by tool calls, so never just write a reply like that. Never state "
                "live information (weather, time, news, what's playing) without calling the tool for it. "
                "Earlier turns in this conversation include actions JARVIS already took (\"Opened Notepad.\"). "
                "Resolve words like 'it', 'that', 'there' and 'again' from them and from the desktop state "
                "below, the way a person would. To put text into an app, first focus its window with "
                "window_action (opening it if needed), then call type_text with the full text."
            )
        provider = self.context_provider
        if provider is not None:
            try:
                state = str(provider() or "").strip()
            except Exception:
                log.exception("desktop context failed")
                state = ""
            if state:
                prompt += f"\n\nDesktop right now: {state}"
        return prompt

    def get_personality_response(self, context: str) -> str:
        hour = datetime.now().hour
        part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
        if context == "startup":
            return f"Good {part}. JARVIS online and at your service."
        return f"Good {part}. How may I help?"

    # ── Main entry ───────────────────────────────────────────────────────────

    def process_command(self, command: str, use_context: bool = True, skills=None,
                        image_path: str = None, use_tools: Optional[bool] = None,
                        system_prompt: Optional[str] = None, max_tokens: int = 1500,
                        temperature: float = 0.6) -> str:
        """Answer ``command`` with the current model.

        ``use_context=False`` marks an internal request (summaries, planning):
        it neither reads nor writes conversation history or user memory.
        Tools are offered for user-facing requests when a registry is attached.
        """
        if not self.current_model:
            return Reply("No model selected. Add an API key in Settings, install Ollama for "
                         "offline chat, then choose a model.", is_error=True)
        if use_context:
            try:
                self.memory.extract_from_message(command)
            except Exception:
                log.exception("memory extraction failed")
        if use_tools is None:
            use_tools = use_context and (self.tool_registry is not None or bool(skills))
        begin_turn = getattr(self.tool_registry, "begin_turn", None)
        if callable(begin_turn):
            begin_turn()
        tried: List[str] = []
        original = model = self.current_model
        last_exc: Optional[ProviderError] = None
        bad_providers: List[str] = []
        for _attempt in range(2):
            tried.append(model)
            cfg = self.available_models.get(model, {})
            try:
                reply = self._call_model(model, cfg, command, use_context, use_tools,
                                         image_path, system_prompt, max_tokens, temperature)
                self.last_error = ""
                if use_context:
                    self._append_turn(command, reply)
                if model != original:
                    reply = f"{reply}\n\n(Answered by {model} because {original} failed: {last_exc})"
                return Reply(reply, model=model)
            except ProviderError as exc:
                last_exc = exc
                log.warning("Model %s failed: %s", model, exc)
                if exc.status in (401, 403):
                    # A bad key fails the same way on every model of that provider.
                    bad_providers.append(cfg.get("provider"))
                nxt = (self._fallback_model(tried, need_vision=bool(image_path), skip_providers=bad_providers)
                       if exc.retryable else None)
                if not nxt:
                    break
                model = nxt
        self.last_error = str(last_exc)
        return Reply(f"I couldn't reach the AI model ({last_exc}). {self._error_hint(last_exc)}",
                     is_error=True, model=model)

    @staticmethod
    def _error_hint(exc: Optional[ProviderError]) -> str:
        status = getattr(exc, "status", None)
        if status in (401, 403):
            return "Check the API key in Settings, or pick another model."
        if status == 402:
            return "The account is out of credits; pick a free or local model."
        if status == 429:
            return "The model is rate-limited; wait a minute or pick another model."
        if status is not None and status >= 500:
            return "The provider is having trouble; try again shortly or pick another model."
        return "Check your connection or API key, or pick another model."

    def _fallback_model(self, tried: List[str], need_vision: bool = False,
                        skip_providers: Optional[List[str]] = None) -> Optional[str]:
        skip_providers = skip_providers or []
        for name, cfg in list(self.available_models.items()):
            if name in tried or name == "openrouter-auto":
                continue
            if cfg.get("provider") in skip_providers:
                continue
            if need_vision and not cfg.get("supports_vision"):
                continue
            return name
        return None

    def _call_model(self, model: str, cfg: Dict[str, Any], command: str, use_context: bool,
                    use_tools: bool, image_path: Optional[str], system_prompt: Optional[str],
                    max_tokens: int, temperature: float) -> str:
        provider = cfg.get("provider")
        tools_ok = bool(use_tools and cfg.get("supports_tools") and self.tool_registry is not None
                        and len(self.tool_registry))
        system = system_prompt or self._get_system_prompt(with_tools=tools_ok)
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        if use_context and self.conversation_history:
            # History gets what's left after everything else sent: an over-full prompt makes Ollama
            # drop its *start* — the system prompt and tool instructions — without any error.
            budget = (self._history_budget(cfg.get("context_window")) - len(system) - len(command)
                      - max(0, int(max_tokens or 0)) * 4 - self._tool_schema_chars(provider, tools_ok, command))
            for msg in self._history_window(budget):
                messages.append({"role": msg["role"], "content": msg["content"]})
        try:
            user_msg = self._user_message(provider, command, image_path)
        except OSError as exc:
            raise ProviderError(f"could not read image {image_path!r} ({exc.__class__.__name__})",
                                retryable=False) from exc
        messages.append(user_msg)
        if provider in ("openrouter", "gemini"):
            return self._chat_openai_compatible(provider, cfg, messages, tools_ok, max_tokens, temperature)
        if provider == "ollama":
            return self._chat_ollama(cfg, messages, tools_ok, max_tokens, temperature)
        raise ProviderError(f"Unsupported provider '{provider}'", retryable=True)

    def _tool_schema_chars(self, provider: str, tools_ok: bool, command: str) -> int:
        """Size of the tool schemas that will go with this request (Ollama gets the relevant subset)."""
        if not tools_ok:
            return 0
        try:
            relevant = getattr(self.tool_registry, "relevant", None)
            names = relevant(command) if provider == "ollama" and callable(relevant) else None
            return len(json.dumps(self.tool_registry.schemas(names)))
        except Exception:
            return 0

    @staticmethod
    def _user_message(provider: str, text: str, image_path: Optional[str]) -> Dict[str, Any]:
        if not image_path:
            return {"role": "user", "content": text}
        import base64
        import os
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        if provider == "ollama":
            return {"role": "user", "content": text, "images": [b64]}
        # Static map: mimetypes consults the Windows registry, which is unreliable.
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                ".gif": "image/gif"}.get(os.path.splitext(str(image_path))[1].lower(), "image/png")
        return {"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}

    # ── Provider calls ───────────────────────────────────────────────────────

    def _content_tool_call(self, content: Any) -> Optional[Dict[str, Any]]:
        """A tool call some models write as JSON text instead of ``tool_calls``.

        Only a whole-message JSON object naming a registered tool counts, e.g.
        ``{"name": "open_app", "arguments": {"app": "notepad"}}`` (optionally
        in a ``` fence); anything else is an ordinary answer.
        """
        if not isinstance(content, str) or self.tool_registry is None:
            return None
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        if not (text.startswith("{") and text.endswith("}")):
            return None
        try:
            obj = json.loads(text)
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        name = obj.get("name")
        args = obj.get("arguments", obj.get("parameters", {}))
        if not isinstance(name, str) or name not in self.tool_registry or not isinstance(args, (dict, str)):
            return None
        return {"name": name, "arguments": args}

    def _chat_openai_compatible(self, provider: str, cfg: Dict[str, Any], messages: List[Dict[str, Any]],
                                tools_ok: bool, max_tokens: int, temperature: float) -> str:
        import requests
        if provider == "openrouter":
            key, base = Config.OPENROUTER_API_KEY, Config.OPENROUTER_BASE_URL
            headers = {"HTTP-Referer": "https://github.com/RaghavVijayanand/jarvis", "X-Title": "JARVIS"}
        else:
            key, base = Config.GEMINI_API_KEY, Config.GEMINI_OPENAI_BASE_URL
            headers = {}
        if not key:
            raise ProviderError(f"{provider} API key not configured", retryable=True)
        headers.update({"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        body: Dict[str, Any] = {"model": cfg.get("model_id"), "messages": messages,
                                "max_tokens": max_tokens, "temperature": temperature}
        if tools_ok:
            body["tools"] = self.tool_registry.schemas()
            body["tool_choice"] = "auto"
        acted = False  # a tool ran: a failure now must not re-run the request elsewhere
        try:
            for _round in range(MAX_TOOL_ROUNDS + 1):
                if tools_ok and _round == MAX_TOOL_ROUNDS:
                    body["tool_choice"] = "none"   # last round: ask for a text answer
                try:
                    resp = requests.post(f"{base}/chat/completions", headers=headers, json=body,
                                         timeout=(5, Config.REQUEST_TIMEOUT))
                except requests.Timeout as exc:
                    raise ProviderError(f"{provider} timed out after {Config.REQUEST_TIMEOUT}s") from exc
                except requests.RequestException as exc:
                    raise ProviderError(f"network error: {exc.__class__.__name__}") from exc
                if resp.status_code != 200:
                    raise self._http_error(provider, resp)
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise ProviderError(f"{provider} returned an unreadable response") from exc
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    data = data[0]
                if not isinstance(data, dict):
                    raise ProviderError(f"{provider} returned an unreadable response")
                if data.get("error"):
                    err = data["error"]
                    raise ProviderError(f"{provider}: {err.get('message', err) if isinstance(err, dict) else err}")
                choices = data.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    raise ProviderError(f"{provider} returned no answer")
                if choices[0].get("error"):   # OpenRouter: mid-generation upstream failure
                    err = choices[0]["error"]
                    raise ProviderError(f"{provider}: {err.get('message', err) if isinstance(err, dict) else err}")
                message = choices[0].get("message") or {}
                calls = [c for c in (message.get("tool_calls") or []) if isinstance(c, dict)]
                content = message.get("content")
                if isinstance(content, list):  # some providers return content parts
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                if not calls and tools_ok and _round < MAX_TOOL_ROUNDS:
                    parsed = self._content_tool_call(content)
                    if parsed:
                        calls = [{"id": f"call_{_round}_0", "type": "function",
                                  "function": {"name": parsed["name"],
                                               "arguments": parsed["arguments"] if isinstance(parsed["arguments"], str)
                                               else json.dumps(parsed["arguments"])}}]
                        content = ""
                if calls and tools_ok and _round < MAX_TOOL_ROUNDS:
                    for i, call in enumerate(calls):
                        # Gemini's compat layer may omit ids; the tool result must reference the call.
                        if not call.get("id"):
                            call["id"] = f"call_{_round}_{i}"
                        call.setdefault("type", "function")
                    body["messages"].append({"role": "assistant", "content": content or "",
                                             "tool_calls": calls})
                    for call in calls:
                        fn = call.get("function") or {}
                        acted = True
                        result = self.tool_registry.execute(fn.get("name", ""), fn.get("arguments"))
                        tool_msg = {"role": "tool", "tool_call_id": call["id"], "content": result}
                        if provider == "gemini":
                            tool_msg["name"] = fn.get("name", "")
                        body["messages"].append(tool_msg)
                    continue
                content = (content or "").strip()
                if not content:
                    raise ProviderError(f"{provider} returned an empty answer")
                return content
            raise ProviderError("too many tool rounds", retryable=False)
        except ProviderError as exc:
            if acted:
                exc.retryable = False
            raise

    @staticmethod
    def _http_error(provider: str, resp) -> ProviderError:
        detail = ""
        try:
            data = resp.json()
            if isinstance(data, list) and data:   # Gemini's compat layer wraps errors in a list
                data = data[0]
            err = data.get("error", {}) if isinstance(data, dict) else {}
            detail = err.get("message", "") if isinstance(err, dict) else str(err)
        except Exception:
            detail = (resp.text or "")[:160]
        status = resp.status_code
        # Gemini reports a bad key as 400 INVALID_ARGUMENT "API key not valid".
        if status == 400 and "api key" in (detail or "").lower():
            status = 401
        meaning = {400: "bad request", 401: "invalid API key", 402: "out of credits",
                   403: "access denied", 404: "model not found", 408: "timeout",
                   429: "rate limited", 500: "server error", 502: "bad gateway",
                   503: "service unavailable", 504: "gateway timeout"}.get(status, "error")
        return ProviderError(f"{provider} {status} {meaning}{': ' + detail[:160] if detail else ''}",
                             retryable=status not in (400,), status=status)

    def _chat_ollama(self, cfg: Dict[str, Any], messages: List[Dict[str, Any]], tools_ok: bool,
                     max_tokens: int, temperature: float) -> str:
        import requests
        body: Dict[str, Any] = {
            "model": cfg.get("model_id", ""), "messages": messages, "stream": False,
            "options": {"num_ctx": cfg.get("context_window", 16384), "temperature": temperature,
                        "num_predict": max_tokens},
            "keep_alive": "30m",                  # stay loaded between turns of a conversation
        }
        if cfg.get("supports_thinking"):
            body["think"] = False                 # a spoken assistant can't wait for a reasoning trace
        if not body["model"]:
            raise ProviderError("Ollama model ID not set", retryable=True)
        if tools_ok:
            relevant = getattr(self.tool_registry, "relevant", None)
            if callable(relevant):
                recent = " ".join(str(m.get("content") or "") for m in messages[-3:] if m.get("role") != "system")
                body["tools"] = self.tool_registry.schemas(relevant(recent))
            else:
                body["tools"] = self.tool_registry.schemas()
        acted = nudged = False
        try:
            for _round in range(MAX_TOOL_ROUNDS + 1):
                if tools_ok and _round == MAX_TOOL_ROUNDS:
                    body.pop("tools", None)   # last round: no more tools, answer in text
                try:
                    resp = requests.post(f"{Config.OLLAMA_URL}/api/chat", json=body,
                                         timeout=(5, max(45, Config.REQUEST_TIMEOUT)))
                except requests.Timeout as exc:
                    raise ProviderError("Ollama timed out (the model may still be loading)") from exc
                except requests.RequestException as exc:
                    raise ProviderError(f"Ollama not reachable ({exc.__class__.__name__})") from exc
                if resp.status_code != 200:
                    try:
                        payload = resp.json()
                        detail = str(payload.get("error") or "") if isinstance(payload, dict) else ""
                        detail = detail or resp.text or ""
                    except Exception:
                        detail = resp.text or ""
                    raise ProviderError(f"Ollama {resp.status_code}: {detail[:160]}", status=resp.status_code)
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise ProviderError("Ollama returned an unreadable response") from exc
                if not isinstance(data, dict):
                    raise ProviderError("Ollama returned an unreadable response")
                if data.get("error"):
                    raise ProviderError(f"Ollama: {data['error']}")
                message = data.get("message") or {}
                calls = [c for c in (message.get("tool_calls") or []) if isinstance(c, dict)]
                content = message.get("content") or ""
                if not calls and tools_ok and _round < MAX_TOOL_ROUNDS:
                    parsed = self._content_tool_call(content)
                    if parsed:
                        args = _as_dict(parsed["arguments"])
                        calls = [{"function": {"name": parsed["name"], "arguments": args}}]
                        content = ""
                if calls and tools_ok and _round < MAX_TOOL_ROUNDS:
                    body["messages"].append({"role": "assistant", "content": content,
                                             "tool_calls": calls})
                    for call in calls:
                        fn = call.get("function") or {}
                        acted = True
                        result = self.tool_registry.execute(fn.get("name", ""), fn.get("arguments"))
                        body["messages"].append({"role": "tool", "content": result,
                                                 "tool_name": fn.get("name", "")})
                    continue
                content = content.strip()
                if not content:
                    raise ProviderError("Ollama returned an empty answer")
                if tools_ok and not acted and nudged and _CLAIMS_ACTION.search(content):
                    # Pushed back once and it still only *says* it acted: don't pass the claim on.
                    return _DID_NOT_ACT
                if tools_ok and not acted and not nudged and _round < MAX_TOOL_ROUNDS - 1 \
                        and _CLAIMS_ACTION.search(content):
                    # Small local models sometimes say "the volume has been increased" without calling a
                    # tool. Push back once: act for real, or don't claim it.
                    nudged = True
                    body["messages"].append({"role": "assistant", "content": content})
                    body["messages"].append({"role": "user", "content": _NUDGE})
                    continue
                return content
            raise ProviderError("too many tool rounds", retryable=False)
        except ProviderError as exc:
            if acted:
                exc.retryable = False
            raise

    # ── Vision ───────────────────────────────────────────────────────────────

    def vision_models(self) -> List[str]:
        """Vision-capable models in preference order (configured → current → others)."""
        pref = getattr(Config, "AUTOMATION_VISION_PROVIDER", "auto")
        wanted = getattr(Config, "AUTOMATION_VISION_MODEL", "")
        order = [wanted] if wanted else []
        order += [self.current_model] + list(self.available_models)
        out = []
        for name in order:
            cfg = self.available_models.get(name or "")
            if not cfg or name in out or not cfg.get("supports_vision"):
                continue
            if pref != "auto" and cfg.get("provider") != pref and name != wanted:
                continue
            out.append(name)
        return out

    def ask_vision(self, prompt: str, image_path: str, max_tokens: int = 900) -> str:
        """Ask a vision model about an image. Raises ProviderError when none can answer."""
        candidates = self.vision_models()
        if not candidates:
            raise ProviderError("No vision-capable model is available. Add a Gemini/OpenRouter key or "
                                "pull a local vision model (e.g. 'ollama pull qwen2.5vl:3b').", retryable=False)
        last: Optional[ProviderError] = None
        for name in candidates[:2]:
            try:
                return self._call_model(name, self.available_models[name], prompt, False, False, image_path,
                                        "You are a precise screen-reading assistant. Follow the requested "
                                        "output format exactly.", max_tokens, 0.1)
            except ProviderError as exc:
                last = exc
                log.warning("Vision model %s failed: %s", name, exc)
        raise last or ProviderError("vision failed")

    def ask_text(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1500,
                temperature: float = 0.2) -> str:
        """One-off text completion with no conversation history and no tool-calling —
        for things like generating a script, not chatting. Raises ProviderError when
        no model can answer."""
        candidates = ([self.current_model] if self.current_model else []) + list(self.available_models)
        seen: List[str] = []
        last: Optional[ProviderError] = None
        for name in candidates:
            if not name or name in seen or name not in self.available_models:
                continue
            seen.append(name)
            try:
                return self._call_model(name, self.available_models[name], prompt, False, False, None,
                                        system_prompt, max_tokens, temperature)
            except ProviderError as exc:
                last = exc
                log.warning("Text model %s failed: %s", name, exc)
        raise last or ProviderError("No AI model is available.", retryable=False)

    def plan_steps(self, command: str) -> List[str]:
        """Ask the model to break a compound request into an ordered list of atomic,
        standalone instructions — a fallback for the rare requests the fast regex
        splitter (skills/command_processor.py) doesn't manage to split, even though
        the decision engine flagged them as multi-step. Returns ``[command]``
        unchanged (nothing to add) if planning fails or the model doesn't cooperate;
        callers should treat a single-item result as "nothing to add"."""
        try:
            text = self.ask_text(command, system_prompt=_PLAN_SYSTEM_PROMPT, max_tokens=400, temperature=0.1)
        except Exception:
            log.exception("plan_steps failed")
            return [command]
        steps: List[str] = []
        for line in (text or "").splitlines():
            m = _STEP_LINE.match(line)
            if m:
                step = m.group(1).strip()
                if step:
                    steps.append(step)
        return steps if steps else [command]

    # ── Utilities ────────────────────────────────────────────────────────────

    def get_usage_stats(self) -> str:
        users = sum(1 for m in self.conversation_history if m.get("role") == "user")
        replies = sum(1 for m in self.conversation_history if m.get("role") == "assistant")
        return f"Turns: {users} user, {replies} assistant. Active model: {self.current_model or 'none'}."

    def benchmark_models(self, test_prompt: str = "In one sentence, what is a black hole?",
                         models: Optional[List[str]] = None, limit: int = 6) -> str:
        """Time a short, context-free prompt on each model (audit UC 3.8)."""
        names = models or list(self.available_models)[:limit]
        if not names:
            return "No models to benchmark."
        original = self.current_model
        rows = []
        try:
            for name in names:
                cfg = self.available_models.get(name)
                if not cfg:
                    continue
                start = time.perf_counter()
                try:
                    text = self._call_model(name, cfg, test_prompt, False, False, None,
                                            "Answer briefly.", 120, 0.2)
                    rows.append((name, time.perf_counter() - start, f"ok, {len(text)} chars"))
                except ProviderError as exc:
                    rows.append((name, time.perf_counter() - start, f"failed: {exc}"))
        finally:
            self.current_model = original
        rows.sort(key=lambda r: (not r[2].startswith("ok"), r[1]))
        lines = [f"{n:<32} {t:6.2f}s  {status}" for n, t, status in rows]
        return "Model benchmark (lower is faster):\n" + "\n".join(lines)
