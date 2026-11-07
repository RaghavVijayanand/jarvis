#!/usr/bin/env python3
"""One-step setup for JARVIS.

    python setup.py            # install dependencies and create your settings file
    python setup.py --laya     # …and download the Laya decision model now (~0.8 GB)
    python setup.py --no-laya  # skip the Laya/PyTorch install (rule-based routing only)
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(args, what):
    print(f"→ {what}…")
    result = subprocess.run(args)
    if result.returncode != 0:
        print(f"✗ {what} failed (exit code {result.returncode}).")
        return False
    print(f"✓ {what}")
    return True


def main():
    if sys.version_info < (3, 10):
        print(f"Python 3.10 or newer is required (you have {sys.version.split()[0]}).")
        return 1
    print(f"Python {sys.version.split()[0]} OK")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], "Upgrading pip")
    req = ROOT / "requirements.txt"
    if "--no-laya" in sys.argv:
        lines = [l for l in req.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("laya")]
        req = ROOT / "requirements-nolaya.tmp.txt"
        req.write_text("\n".join(lines), encoding="utf-8")
    ok = run([sys.executable, "-m", "pip", "install", "-r", str(req)], "Installing dependencies")
    if req.name.endswith(".tmp.txt"):
        req.unlink()
    if not ok:
        print("Some packages failed to install — PyTorch (via laya) is the usual suspect on an unusual "
              "Python/OS combo. See SETUP_GUIDE.md.")

    # PyAudio (microphone input) is attempted on its own: it compiles against PortAudio and has no
    # prebuilt wheel on every Python version, so a failure here shouldn't block everything above.
    if not run([sys.executable, "-m", "pip", "install", "PyAudio>=0.2.14"], "Installing PyAudio (microphone input)"):
        print("PyAudio couldn't build — voice input will be unavailable, everything else still works. "
              "See SETUP_GUIDE.md for how to fix it (needs PortAudio dev headers).")

    sys.path.insert(0, str(ROOT))
    from core.config import ENV_PATH, APPDATA_DIR
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ENV_PATH.exists():
        shutil.copy(ROOT / ".env.example", ENV_PATH)
        print(f"✓ Created settings file {ENV_PATH}")
    else:
        print(f"✓ Settings file exists: {ENV_PATH}")

    if "--laya" in sys.argv:
        from core.decision import DecisionEngine
        engine = DecisionEngine(engine="laya")
        engine._load()
        print(("✓ " if engine.laya_ready else "✗ ") + engine.status)

    print("\nNext steps:\n  python main_gui.py        (desktop app)\n  python jarvis.py          (terminal)\n"
          "  python doctor.py          (check this machine)\nAdd a Gemini or OpenRouter key in Settings, or install "
          "Ollama for offline chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
