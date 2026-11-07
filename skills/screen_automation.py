"""Screen vision and mouse/keyboard automation.

* Screenshots are downscaled before being sent to a vision model, and the
  model's coordinates are mapped back to real screen coordinates using the
  measured ratio — correct on high-DPI and multi-resolution setups (UC 6.5).
* One shared instance per JARVIS; the emergency-stop hotkey is registered once
  (UC 6.1). Stop with **Ctrl+Alt+Esc** or by slamming the mouse into a corner.
* Unicode text is pasted, not typed key-by-key (UC 6.3).
* Confirmation goes through ``JARVIS.confirm`` so it reaches the GUI dialog or
  the console — never a hidden ``input()`` in a worker thread (UC 6.2).
* Task completion is judged by an explicit structured answer from the vision
  model, cross-checked by the local decision model and a screen-change check,
  not by keyword overlap (UC 6.4).
"""
from __future__ import annotations

import ast
import json
import os
import re
import threading
import time
import weakref
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.screen")

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.15
except Exception:  # pragma: no cover - headless test machines
    pyautogui = None

MODEL_IMAGE_WIDTH = 1366
RISKY_WORDS = re.compile(r"\b(delete|remove|uninstall|erase|format|send|submit|pay|purchase|buy|order|"
                         r"sign out|log ?out|shut ?down|restart|confirm|transfer|post|publish)\b", re.I)

_hotkey_lock = threading.Lock()
_hotkey_listener = None
_stop_callbacks: List[Any] = []   # weak references, so throw-away skill instances don't leak


def _fire_emergency_stop() -> None:
    with _hotkey_lock:
        refs = list(_stop_callbacks)
    for ref in refs:
        cb = ref() if isinstance(ref, (weakref.ref, weakref.WeakMethod)) else ref
        if cb is None:
            continue
        try:
            cb()
        except Exception:
            pass


def _install_emergency_stop(callback) -> None:
    """Register ``callback`` for the global Ctrl+Alt+Esc stop hotkey (listener created once)."""
    global _hotkey_listener
    with _hotkey_lock:
        try:
            ref = weakref.WeakMethod(callback)
        except TypeError:          # plain function / lambda
            ref = callback
        # drop dead references and avoid registering the same callback twice
        _stop_callbacks[:] = [r for r in _stop_callbacks
                              if not (isinstance(r, weakref.WeakMethod) and r() is None)]
        if not any((r() if isinstance(r, weakref.WeakMethod) else r) == callback for r in _stop_callbacks):
            _stop_callbacks.append(ref)
        if _hotkey_listener is not None:
            return
        try:
            from pynput import keyboard

            fire = _fire_emergency_stop
            _hotkey_listener = keyboard.GlobalHotKeys({"<ctrl>+<alt>+<esc>": fire})
            _hotkey_listener.daemon = True
            _hotkey_listener.start()
        except Exception as exc:
            log.warning("Emergency-stop hotkey unavailable: %s", exc)
            _hotkey_listener = False


_PY_LITERALS = {"true": "True", "false": "False", "null": "None"}


def _loose_literal(cand: str) -> Any:
    """Fallback for Python-style dicts ({'done': False} / {'done': false})."""
    fixed = re.sub(r"\b(true|false|null)\b", lambda m: _PY_LITERALS[m.group(1)], cand)
    for src in (cand, fixed):
        try:
            return ast.literal_eval(src)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
    return None


def _brace_span(text: str, start: int) -> Optional[str]:
    """Balanced {...} starting at ``start``, ignoring braces inside quoted strings."""
    depth, quote, escape = 0, None, False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first JSON object out of a model reply.

    Handles ```json fences, prose before/after, braces inside strings, a
    top-level list (first object wins) and Python-style single-quoted dicts.
    """
    if not text:
        return None
    if isinstance(text, dict):
        return text
    if isinstance(text, list):
        return next((v for v in text if isinstance(v, dict)), None)
    if not isinstance(text, str):
        text = str(text)
    fenced = re.search(r"```(?:json|JSON)?\s*(.*?)\s*```", text, re.S)
    sources = ([fenced.group(1)] if fenced else []) + [text]
    decoder = json.JSONDecoder()
    for src in sources:
        for m in re.finditer(r"[\[{]", src):
            try:
                value, _ = decoder.raw_decode(src, m.start())
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
            if isinstance(value, list):
                first = next((v for v in value if isinstance(v, dict)), None)
                if first is not None:
                    return first
        for m in re.finditer(r"\{", src):
            cand = _brace_span(src, m.start())
            value = _loose_literal(cand) if cand else None
            if isinstance(value, dict):
                return value
    return None


def _truthy(value: Any) -> bool:
    """Strict boolean for model fields: the string "false" must not count as true."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "y")
    return bool(value)


_KEY_ALIASES = {"control": "ctrl", "windows": "win", "window": "win", "cmd": "win", "super": "win",
                "escape": "esc", "del": "delete", "return": "enter", "pgup": "pageup", "pgdn": "pagedown",
                "page_up": "pageup", "page_down": "pagedown", "arrowup": "up", "arrowdown": "down",
                "arrowleft": "left", "arrowright": "right", "spacebar": "space", "option": "alt"}
_KIND_ALIASES = {"left_click": "click", "leftclick": "click", "tap": "click", "doubleclick": "double_click",
                 "rightclick": "right_click", "key": "press", "keypress": "press", "type_text": "type",
                 "write": "type", "sleep": "wait"}
RISKY_KEYS = {("alt", "f4"), ("ctrl", "w"), ("shift", "delete"), ("ctrl", "shift", "delete")}


class ScreenAutomationSkill:
    _state_lock = threading.Lock()   # guards is_running so two tasks can't drive the mouse at once

    def __init__(self, jarvis_instance=None):
        self.jarvis = jarvis_instance
        self.is_running = False
        self.emergency_stop = False
        self.current_task: Optional[str] = None
        self.automation_history: List[Dict[str, Any]] = []
        self.screenshot_dir = str(Config.SCREENSHOTS_DIR)
        os.makedirs(self.screenshot_dir, exist_ok=True)
        _install_emergency_stop(self.stop_automation)

    # ── Plumbing ─────────────────────────────────────────────────────────────

    @property
    def brain(self):
        return getattr(self.jarvis, "brain", None)

    def _confirm(self, question: str) -> bool:
        confirm = getattr(self.jarvis, "confirm", None)
        if callable(confirm):
            return bool(confirm(question))
        return False  # no way to ask → never act on something risky

    def _log(self, entry: Dict[str, Any]) -> None:
        entry["time"] = datetime.now().strftime("%H:%M:%S")
        self.automation_history.append(entry)
        del self.automation_history[:-200]

    def _require_gui(self):
        if pyautogui is None:
            raise RuntimeError("Screen control needs pyautogui on a desktop session.")

    # ── Screenshots & vision ─────────────────────────────────────────────────

    def take_screenshot(self, region=None) -> str:
        self._require_gui()
        path = os.path.join(self.screenshot_dir, f"screenshot_{datetime.now():%Y%m%d_%H%M%S_%f}.png")
        image = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
        image.save(path)
        self._prune_screenshots()
        return path

    def _prune_screenshots(self, keep: int = 40) -> None:
        try:
            files = sorted((os.path.join(self.screenshot_dir, f) for f in os.listdir(self.screenshot_dir)
                            if f.startswith("screenshot_")), key=os.path.getmtime)
            for old in files[:-keep]:
                os.remove(old)
        except OSError:
            pass

    def _model_image(self, path: str) -> Tuple[str, int, int]:
        """Downscaled JPEG copy for the model. Returns (path, width, height)."""
        from PIL import Image
        with Image.open(path) as img:
            img = img.convert("RGB")
            if img.width > MODEL_IMAGE_WIDTH:
                ratio = MODEL_IMAGE_WIDTH / img.width
                img = img.resize((MODEL_IMAGE_WIDTH, int(img.height * ratio)))
            out = os.path.splitext(path)[0] + "_model.jpg"
            img.save(out, "JPEG", quality=80)
            return out, img.width, img.height

    def _to_screen(self, x: float, y: float, img_w: int, img_h: int) -> Tuple[int, int]:
        screen_w, screen_h = pyautogui.size()
        sx = int(round(float(x) * screen_w / img_w))
        sy = int(round(float(y) * screen_h / img_h))
        # Stay one pixel inside the edges: an exact corner trips pyautogui's
        # fail-safe, which would abort the task as if the user had stopped it.
        return max(1, min(screen_w - 2, sx)), max(1, min(screen_h - 2, sy))

    @staticmethod
    def _point_from(data: Dict[str, Any], img_w: int, img_h: int) -> Optional[Tuple[float, float]]:
        """Accept {x,y}, {coordinates:[x,y]} or Gemini-style box_2d (0-1000, ymin,xmin,ymax,xmax)."""
        if "box_2d" in data and isinstance(data["box_2d"], list) and len(data["box_2d"]) == 4:
            ymin, xmin, ymax, xmax = [float(v) for v in data["box_2d"]]
            return (xmin + xmax) / 2 * img_w / 1000, (ymin + ymax) / 2 * img_h / 1000
        if "x" in data and "y" in data:
            return float(data["x"]), float(data["y"])
        coords = data.get("coordinates")
        if isinstance(coords, list) and len(coords) >= 2:
            return float(coords[0]), float(coords[1])
        return None

    def _ask_vision(self, prompt: str, image_path: str) -> str:
        brain = self.brain
        if brain is None or not hasattr(brain, "ask_vision"):
            raise RuntimeError("No AI brain available for screen vision.")
        return brain.ask_vision(prompt, image_path)

    def describe_screen(self, question: str = "") -> str:
        """Screenshot + plain-language answer about what is on screen."""
        try:
            shot = self.take_screenshot()
            img, _, _ = self._model_image(shot)
            prompt = (question.strip() or "Describe what is on this screen: the main window, what the user "
                      "appears to be doing, and anything that needs attention.") + " Be concise."
            answer = self._ask_vision(prompt, img)
            self._log({"action": "describe", "result": answer[:200]})
            return answer
        except Exception as exc:
            return f"I couldn't analyze the screen: {exc}"

    def _find_element(self, description: str, shot: str) -> Dict[str, Any]:
        img, w, h = self._model_image(shot)
        prompt = (
            f"This screenshot is {w}x{h} pixels. Find the UI element: \"{description}\".\n"
            "Reply with JSON only: {\"found\": true|false, \"x\": <center x in pixels>, "
            "\"y\": <center y in pixels>, \"label\": \"<visible text of the element>\", "
            "\"confidence\": <0..1>}"
        )
        data = extract_json(self._ask_vision(prompt, img)) or {}
        point = self._point_from(data, w, h) if _truthy(data.get("found", True)) else None
        if not point:
            return {"found": False, "label": data.get("label", ""), "confidence": 0.0}
        sx, sy = self._to_screen(point[0], point[1], w, h)
        confidence = data.get("confidence")
        return {"found": True, "coordinates": [sx, sy], "label": data.get("label") or description,
                # a reported confidence of 0 must stay 0 (``or 0.7`` used to turn it into 0.7)
                "confidence": 0.7 if confidence in (None, "") else float(confidence)}

    def find_and_click_element(self, element_description: str, button: str = "left",
                               double: bool = False) -> Dict[str, Any]:
        try:
            self._require_gui()
            shot = self.take_screenshot()
            info = self._find_element(element_description, shot)
            if not info["found"]:
                return {"success": False, "message": f"Could not find '{element_description}' on screen."}
            if info["confidence"] < Config.AUTOMATION_CONFIDENCE_THRESHOLD:
                return {"success": False, "confidence": info["confidence"],
                        "message": f"I'm not confident I found '{element_description}' "
                                   f"(confidence {info['confidence']:.2f}), so I didn't click."}
            label = info.get("label") or element_description
            if RISKY_WORDS.search(f"{element_description} {label}") and not self._confirm(
                    f"Click '{label}' on screen?"):
                return {"success": False, "message": f"Not clicking '{label}' — you declined."}
            x, y = info["coordinates"]
            pyautogui.click(x, y, clicks=2 if double else 1, button=button)
            self._log({"action": "click", "target": label, "at": [x, y]})
            return {"success": True, "coordinates": [x, y], "confidence": info["confidence"],
                    "message": f"Clicked '{label}' at ({x}, {y})."}
        except Exception as exc:
            return {"success": False, "message": f"Click failed: {exc}"}

    # ── Actions ──────────────────────────────────────────────────────────────

    def execute_action(self, action: Dict[str, Any], img_size: Tuple[int, int] = None) -> Tuple[bool, str]:
        """Run one action dict from the planner. Returns (ok, message)."""
        self._require_gui()
        if not getattr(self, "is_running", False):
            # a direct call (e.g. "press enter"): a stop pressed earlier while idle must not
            # make every later key press fail with "stopped"; a stop *during* it still works
            self.emergency_stop = False
        elif self.emergency_stop:
            return False, "stopped"
        if not isinstance(action, dict):
            return False, "invalid action"
        kind = re.sub(r"[\s-]+", "_", str(action.get("type", "")).strip().lower())
        kind = _KIND_ALIASES.get(kind, kind)
        target = str(action.get("target", "") or action.get("element_description", ""))
        keys = self._parse_keys(action) if kind in ("press", "hotkey") else []
        risky = RISKY_WORDS.search(f"{target} {action.get('text', '')}") or tuple(keys) in RISKY_KEYS
        if risky and not self._confirm(
                f"Automation wants to {kind} '{target or action.get('text', '') or '+'.join(keys)}'. Allow?"):
            return False, "declined by user"
        try:
            if kind in ("click", "double_click", "right_click"):
                if img_size:
                    point = self._point_from(action, *img_size)
                    if not point:
                        return False, "no coordinates"
                    x, y = self._to_screen(point[0], point[1], *img_size)
                else:
                    # screen coordinates given directly; never default to (0, 0) — that is a
                    # fail-safe corner and clicking it silently aborts the next action
                    point = self._point_from(action, 1, 1)
                    if not point:
                        return False, "no coordinates"
                    x, y = int(round(point[0])), int(round(point[1]))
                if self.emergency_stop:
                    return False, "stopped"
                pyautogui.click(x, y, clicks=2 if kind == "double_click" else 1,
                                button="right" if kind == "right_click" else "left")
                return True, f"{kind} at ({x},{y}) {target}"
            if kind == "type":
                text = str(action.get("text", ""))
                if text.isascii() and "\n" not in text:
                    # typed in small chunks so the emergency stop interrupts long text
                    for i in range(0, len(text), 16):
                        if self.emergency_stop:
                            return False, "stopped"
                        pyautogui.write(text[i:i + 16], interval=0.02)
                else:
                    windows = getattr(self.jarvis, "windows", None)
                    if windows is None or not hasattr(windows, "type_text"):
                        from skills.windows_control import WindowsControl
                        windows = WindowsControl()
                    outcome = windows.type_text(text)
                    if isinstance(outcome, str) and not outcome.startswith("Typed"):
                        return False, f"type failed: {outcome}"
                if action.get("enter") is True or str(action.get("enter")).lower() == "true":
                    if self.emergency_stop:
                        return False, "stopped"
                    pyautogui.press("enter")
                return True, f"typed {len(text)} chars"
            if kind in ("press", "hotkey"):
                if not keys:
                    return False, "no key"
                valid = getattr(pyautogui, "KEYBOARD_KEYS", None)
                if isinstance(valid, (list, tuple, set, frozenset)):
                    unknown = [k for k in keys if k not in valid]
                    if unknown:     # pyautogui silently ignores unknown key names
                        return False, "unknown key " + ", ".join(unknown)
                pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
                return True, "pressed " + "+".join(keys)
            if kind == "scroll":
                amount = abs(int(float(action.get("amount", 5))))
                pyautogui.scroll(amount * (120 if os.name == "nt" else 1) *
                                 (-1 if str(action.get("direction", "down")).lower() == "down" else 1))
                return True, f"scrolled {action.get('direction', 'down')}"
            if kind == "wait":
                if not self._sleep(min(10.0, max(0.0, float(action.get("seconds", 1))))):
                    return False, "stopped"
                return True, "waited"
            if kind == "open":
                app = getattr(self.jarvis, "app_control", None)
                if app is None:
                    return False, "app control unavailable"
                return True, app.launch_app_by_name(str(action.get("target", "")))
            return False, f"unknown action '{kind}'"
        except pyautogui.FailSafeException:
            self.stop_automation()
            return False, "fail-safe triggered (mouse in corner)"
        except Exception as exc:
            return False, f"{kind} failed: {exc}"

    @staticmethod
    def _parse_keys(action: Dict[str, Any]) -> List[str]:
        keys = action.get("keys") or action.get("key") or ""
        keys = keys if isinstance(keys, list) else re.split(r"\s*\+\s*", str(keys))
        keys = [str(k).strip().lower() for k in keys if str(k).strip()]
        return [_KEY_ALIASES.get(k, k) for k in keys]

    def _sleep(self, seconds: float) -> bool:
        """Interruptible sleep: returns False as soon as the emergency stop fires."""
        end = time.monotonic() + max(0.0, float(seconds or 0))
        while True:
            if self.emergency_stop:
                return False
            left = end - time.monotonic()
            if left <= 0:
                return True
            time.sleep(min(0.05, left))

    @staticmethod
    def _screen_changed(a: str, b: str) -> bool:
        try:
            from PIL import Image, ImageChops
            with Image.open(a) as ia, Image.open(b) as ib:
                if ia.size != ib.size:
                    return True
                diff = ImageChops.difference(ia.convert("L").resize((320, 180)),
                                             ib.convert("L").resize((320, 180)))
                return sum(1 for px in diff.getdata() if px > 24) > 150
        except Exception:
            return True

    def _goal_check(self, goal: str, reason: str) -> Optional[float]:
        decider = getattr(self.jarvis, "decision", None)
        if decider is None or not getattr(decider, "laya_ready", False):
            return None
        return decider.yes_no({"goal": goal, "screen_report": reason},
                              "Does the screen report say the goal has been fully completed?")

    def automate_task(self, goal: str, max_steps: int = None) -> Dict[str, Any]:
        """Observe → decide one action → act → verify, until done or stopped."""
        max_steps = max_steps or Config.AUTOMATION_MAX_STEPS
        result = {"goal": goal, "status": "running", "steps_completed": 0, "actions_taken": [],
                  "errors": [], "summary": ""}
        try:
            self._require_gui()
        except RuntimeError as exc:
            result.update(status="error", summary=str(exc))
            return result
        if Config.AUTOMATION_CONFIRMATION_REQUIRED and not self._confirm(
                f"Let JARVIS control your mouse and keyboard to: {goal}?\n"
                f"Press Ctrl+Alt+Esc or move the mouse to a screen corner to stop."):
            result.update(status="cancelled", summary="You declined, so I didn't touch anything.")
            return result
        with self._state_lock:
            if self.is_running:
                result.update(status="error", summary="Another screen automation is already running.")
                return result
            self.is_running, self.emergency_stop, self.current_task = True, False, goal
        history: List[str] = []
        stuck = bad_replies = 0
        previous_shot = None      # screenshot taken just before the last executed action
        try:
            for step in range(1, max_steps + 1):
                if self.emergency_stop:
                    result["status"] = "stopped"
                    break
                shot = self.take_screenshot()
                if previous_shot is not None:
                    stuck = 0 if self._screen_changed(previous_shot, shot) else stuck + 1
                    if stuck >= 2:
                        result["status"] = "stuck"
                        result["errors"].append("The screen stopped changing after my actions.")
                        break
                    previous_shot = None
                img, w, h = self._model_image(shot)
                prompt = (
                    f"You control a Windows PC to achieve this goal: \"{goal}\".\n"
                    f"The screenshot is {w}x{h} pixels. Actions so far: {history[-6:] or 'none'}.\n"
                    "Decide the SINGLE next action. Reply with JSON only:\n"
                    "{\"done\": true|false, \"reason\": \"what the screen shows / why\", "
                    "\"action\": {\"type\": \"click|double_click|right_click|type|press|scroll|wait|open\", "
                    "\"x\": <px>, \"y\": <px>, \"target\": \"element or app name\", \"text\": \"to type\", "
                    "\"enter\": false, \"keys\": \"ctrl+s\", \"direction\": \"down\", \"amount\": 5}}\n"
                    "Set done=true (and omit action) only when the goal is visibly complete."
                )
                try:
                    plan = extract_json(self._ask_vision(prompt, img))
                except Exception as exc:
                    result["errors"].append(f"Vision model error: {exc}")
                    result["status"] = "error"
                    break
                action = plan.get("action") if plan else None
                if isinstance(action, dict) and str(action.get("type", "")).strip().lower() == "done":
                    plan["done"], action = True, None
                if self.emergency_stop:
                    result["status"] = "stopped"
                    break
                if not plan or not (_truthy(plan.get("done")) or (isinstance(action, dict) and action)):
                    result["errors"].append(f"Step {step}: the model's reply wasn't a valid JSON action.")
                    bad_replies += 1
                    if bad_replies >= 2:
                        result["status"] = "error"
                        break
                    continue
                bad_replies = 0          # the limit is for consecutive unusable replies
                reason = str(plan.get("reason", ""))
                if _truthy(plan.get("done")):
                    check = self._goal_check(goal, reason)
                    if check is None or check >= 0.5:
                        result["status"] = "completed"
                        result["summary"] = reason
                        break
                    history.append(f"model said done but verification disagreed ({reason[:60]})")
                    continue
                # a "wait" legitimately leaves the screen unchanged, so it must not count as stuck
                previous_shot = None if str(action.get("type", "")).strip().lower() == "wait" else shot
                ok, msg = self.execute_action(action, (w, h))
                history.append(f"{action.get('type')} {action.get('target', '')}: {msg}")
                result["actions_taken"].append({"step": step, "action": action, "success": ok, "message": msg})
                self._log({"action": action.get("type"), "target": action.get("target"), "ok": ok, "goal": goal})
                result["steps_completed"] = step
                if not ok:
                    result["errors"].append(f"Step {step}: {msg}")
                    if msg in ("declined by user", "stopped") or msg.startswith("fail-safe"):
                        result["status"] = "stopped"
                        break
                if not self._sleep(Config.AUTOMATION_ACTION_DELAY):
                    result["status"] = "stopped"
                    break
            if result["status"] == "running":
                result["status"] = "stopped" if self.emergency_stop else "incomplete"
        except Exception as exc:     # screenshot / image errors must not escape with is_running stuck
            log.exception("Screen automation failed")
            result["status"] = "error"
            result["errors"].append(f"Automation error: {exc}")
        finally:
            self.is_running, self.current_task = False, None
        return result

    @staticmethod
    def format_result(result: Dict[str, Any]) -> str:
        status = result.get("status")
        head = {"completed": "Done", "cancelled": "Cancelled", "stopped": "Stopped",
                "stuck": "I got stuck", "error": "Automation failed",
                "incomplete": "I ran out of steps"}.get(status, status)
        lines = [f"{head}: {result.get('goal')}", f"Actions taken: {len(result.get('actions_taken', []))}"]
        if result.get("summary"):
            lines.append(result["summary"])
        for err in result.get("errors", [])[:3]:
            lines.append(f"• {err}")
        return "\n".join(lines)

    # ── Status ───────────────────────────────────────────────────────────────

    def stop_automation(self):
        """Safe to call from any thread (GUI, hotkey listener). The running loop sees the
        flag at its next check and clears ``is_running`` itself when it has really stopped —
        clearing it here let a second task start (and reset the stop flag) while the first
        was still driving the mouse."""
        self.emergency_stop = True

    def get_status(self) -> Dict[str, Any]:
        return {"is_running": self.is_running, "current_task": self.current_task,
                "emergency_stop": self.emergency_stop, "history_count": len(self.automation_history)}

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.automation_history[-limit:]

    def clear_history(self):
        self.automation_history.clear()

    def cleanup(self):
        self.stop_automation()


def process_automation_command(command: str, jarvis_instance=None) -> str:
    """Text front-end used by JARVIS for screen commands."""
    automation = getattr(jarvis_instance, "screen_automation", None) or ScreenAutomationSkill(jarvis_instance)
    text = (command or "").strip()
    low = text.lower()
    if re.search(r"\bstop automation\b|\babort\b", low):
        automation.stop_automation()
        return "Automation stopped."
    if "automation status" in low:
        st = automation.get_status()
        return f"Running: {st['is_running']}. Task: {st['current_task'] or 'none'}."
    if "automation history" in low:
        hist = automation.get_history(8)
        return "No automation history." if not hist else "\n".join(
            f"{h['time']} {h.get('action')} {h.get('target') or ''}" for h in hist)
    m = re.match(r"^(?:please\s+)?(double[- ]?click|right[- ]?click|click|tap|press on)\s+(?:on\s+)?(?:the\s+)?(.+)$", low)
    if m and not re.search(r"\b(then|and then)\b", low):
        kind = m.group(1).replace("-", "").replace(" ", "")
        res = automation.find_and_click_element(m.group(2).strip(), button="right" if kind == "rightclick" else "left",
                                                double=kind == "doubleclick")
        return res["message"]
    if re.search(r"screen ?shot|capture (?:the |my )?screen", low) and not re.search(
            r"\b(describe|analy[sz]e|tell me|what)\b", low):
        try:
            return f"Screenshot saved to {automation.take_screenshot()}"
        except Exception as exc:
            return f"Screenshot failed: {exc}"
    if re.search(r"what(?:'s|s| is) on (?:my |the )?screen|describe|analy[sz]e|look at (?:my |the )?screen|"
                 r"read (?:my |the )?screen|tell me what you see", low):
        question = re.sub(r"^(?:take a screenshot and\s+)?", "", text, flags=re.I)
        return automation.describe_screen(question)
    goal = re.sub(r"^(?:please\s+)?(?:automate|ai help with|do this on screen:?)\s*", "", text, flags=re.I)
    if not goal:
        return "Tell me what to do on screen, e.g. 'automate open Notepad and type hello'."
    return ScreenAutomationSkill.format_result(automation.automate_task(goal))
