"""Drive Python-scriptable desktop apps from a natural-language description: the AI
brain writes the script in the app's own dialect, JARVIS saves it and launches the
app to run it. Blender (``bpy``) is the first one wired up; the pattern — a system
prompt teaching the app's scripting API, a generated script on disk, a launch line
that runs it — generalizes to any app with a similar "run this script" entry point.

This is a real code-execution path by design: the brain's output runs unreviewed.
The caller (handlers/appscript.py) always confirms before calling in here — never
skip that, whatever the caller thinks it knows about the request.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.appscript")

_BLENDER_SEARCH_DIRS = (r"C:\Program Files\Blender Foundation", r"C:\Program Files (x86)\Blender Foundation")

_BLENDER_SYSTEM_PROMPT = (
    "You write Python scripts for Blender's built-in `bpy` API. Output ONLY runnable Python code — "
    "no explanation, no markdown code fences. The script is run inside Blender via `--python`, so "
    "`bpy` is already importable at the top of the file.\n"
    "Unless asked to build on the existing scene, clear it first:\n"
    "  import bpy\n"
    "  bpy.ops.object.select_all(action='SELECT')\n"
    "  bpy.ops.object.delete()\n"
    "Prefer bpy.ops.mesh.primitive_*_add (cube, uv_sphere, cylinder, cone, plane, torus, etc.) for "
    "basic shapes, and bpy.ops.transform.translate/rotate/resize (or set obj.location/.rotation_euler/"
    ".scale directly) to position and size them. Give created objects sensible names via obj.name. "
    "Do not export or save the file unless the request explicitly asks for that."
)

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?|\n?```\s*$", re.M)


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap code in ```python fences despite being told not to."""
    return _FENCE.sub("", text or "").strip()


# What a modeling script legitimately needs. The user approved a *description*, not this code,
# so anything that reaches outside Blender (files, processes, network) stops for a human look.
_SAFE_MODULES = {"bpy", "bmesh", "mathutils", "math", "random", "colorsys", "itertools", "functools",
                 "collections", "time", "typing"}
_RISKY_CALLS = {"eval", "exec", "compile", "__import__", "open", "globals", "getattr", "setattr", "delattr"}


def script_problems(code: str) -> List[str]:
    """Why generated code shouldn't run unreviewed ([] = fine to run)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"it isn't valid Python (line {exc.lineno}: {exc.msg})"]
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        else:
            mods = []
        for mod in mods:
            if mod.split(".")[0] not in _SAFE_MODULES:
                problems.append(f"line {node.lineno} imports '{mod}'")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _RISKY_CALLS:
            problems.append(f"line {node.lineno} calls {node.func.id}()")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            problems.append(f"line {node.lineno} uses {node.attr}")
    return problems


def find_blender() -> Optional[str]:
    """Locate blender.exe: PATH first, then the usual Program Files install locations
    (newest version first, since Blender installs each major version side by side)."""
    found = shutil.which("blender") or shutil.which("blender.exe")
    if found:
        return found
    for base in _BLENDER_SEARCH_DIRS:
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for sub in sorted(base_path.glob("Blender *"), reverse=True):
            exe = sub / "blender.exe"
            if exe.is_file():
                return str(exe)
    return None


def blender_available() -> bool:
    return find_blender() is not None


class AppScripting:
    """Generates and runs small scripts inside Python-scriptable apps."""

    def __init__(self, jarvis_instance=None):
        self.jarvis = jarvis_instance
        self.scripts_dir = Path(Config.SCREENSHOTS_DIR).parent / "generated_scripts"
        try:
            self.scripts_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    @property
    def brain(self):
        return getattr(self.jarvis, "brain", None)

    def _generate_code(self, description: str, system_prompt: str, max_tokens: int = 1800) -> str:
        brain = self.brain
        if brain is None or not hasattr(brain, "ask_text"):
            raise RuntimeError("No AI brain available to write the script.")
        return _strip_code_fence(brain.ask_text(description, system_prompt=system_prompt,
                                                max_tokens=max_tokens, temperature=0.2))

    def _save_script(self, app: str, code: str) -> Path:
        path = self.scripts_dir / f"{app}_{int(time.time() * 1000)}.py"
        path.write_text(code, encoding="utf-8")
        return path

    # ── Blender ──────────────────────────────────────────────────────────────

    def blender_run(self, description: str, save_as: str = "", background: bool = False) -> str:
        """Ask the brain for a bpy script matching ``description`` and run it in Blender.

        ``save_as`` appends a save-file step (a real path, so ask before passing one from
        untrusted text). ``background=True`` runs headless and waits for the result — good
        for a pure export with nothing to look at; the default opens the normal Blender
        window and doesn't block JARVIS waiting for the user to close it.
        """
        exe = find_blender()
        if exe is None:
            return ("Blender isn't installed (or I couldn't find it). Install it from blender.org, "
                    "or make sure its folder is on PATH, then try again.")
        try:
            code = self._generate_code(description, _BLENDER_SYSTEM_PROMPT)
        except Exception as exc:
            return f"Couldn't generate the Blender script: {exc}"
        if not code:
            return "The AI didn't return any code — try rephrasing what you want modeled."
        problems = script_problems(code)
        if problems:
            script_path = self._save_script("blender_unreviewed", code)
            return ("I didn't run the generated Blender script because " + "; ".join(problems[:5]) +
                    f". It's saved at {script_path} if you want to review it and run it yourself.")
        if save_as:
            path = str(Path(save_as).expanduser())
            code += f"\n\nimport bpy\nbpy.ops.wm.save_as_mainfile(filepath={path!r})\n"
        script_path = self._save_script("blender", code)
        args = [exe, *(["--background"] if background else []), "--python", str(script_path)]
        try:
            if background:
                proc = subprocess.run(args, capture_output=True, text=True, timeout=180,
                                      encoding="utf-8", errors="replace", check=False)
                tail = "\n".join(l for l in proc.stdout.splitlines() if l.strip())[-500:]
                if proc.returncode != 0:
                    return f"Blender exited with an error (code {proc.returncode}).{(' ' + tail) if tail else ''}"
                return f"Done.{(' ' + tail) if tail else ''}"
            subprocess.Popen(args)      # a GUI run isn't waited on — Blender stays open for the user
            return f"Opened Blender and ran the script ({script_path.name})."
        except subprocess.TimeoutExpired:
            return "Blender is taking a while in the background — it may still be working."
        except Exception as exc:
            return f"Couldn't launch Blender: {exc}"
