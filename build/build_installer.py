#!/usr/bin/env python3
"""Build JARVIS-Setup.exe:  icon → PyInstaller (dist/JARVIS/) → self-test → Inno Setup installer.

    python build/build_installer.py            # the full thing (Windows)
    python build/build_installer.py --no-installer   # just dist/JARVIS/JARVIS.exe (portable folder)

Needs Windows, Python 3.10+ with requirements.txt installed. PyInstaller is
installed automatically; Inno Setup 6 too (via winget) when it's missing.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "_pyibuild"
SPEC = ROOT / "build" / "jarvis.spec"
ISS = ROOT / "installer" / "jarvis.iss"
HF_CACHE = ROOT / "_hf_cache"           # pre-downloaded Laya weights; bundled by jarvis.spec if present
ISCC_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
]


def app_version() -> str:
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    m = re.search(r'setApplicationVersion\("([\d.]+)"\)', text)
    version = m.group(1) if m else "3.1"
    return version if version.count(".") >= 2 else version + ".0"


def step(msg: str):
    print(f"\n== {msg}", flush=True)


def run(cmd, **kw):
    print("   $ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        step("Installing PyInstaller")
        run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.10"])


def make_icon():
    step("Drawing the icon")
    run([sys.executable, str(ROOT / "build" / "make_icon.py")])


def warm_up_laya():
    """Best-effort: download Laya's model now, into _hf_cache/, so jarvis.spec
    can bundle it and the packaged app has offline decision-making from its
    first run. Skipped (with a warning, not a failure) if laya isn't
    installed or the download can't complete — the app still works either
    way, it just downloads the model on first use instead, same as a
    from-source install."""
    step("Warming up Laya's model cache (downloads ~0.8 GB once)")
    env = dict(os.environ, HF_HOME=str(HF_CACHE))
    HF_CACHE.mkdir(parents=True, exist_ok=True)
    code = (
        "import laya\n"
        "from core.config import Config\n"
        "subfolder = 'multilingual' if Config.LAYA_MODEL == 'multilingual' else None\n"
        "agent = laya.load(Config.LAYA_REPO, subfolder=subfolder)\n"
        "agent.predict('hello', {'w': {'type': 'noul', 'instructions': 'Is this a greeting?'}})\n"
        "print('Laya model cached.')\n"
    )
    try:
        run([sys.executable, "-c", code], cwd=ROOT, env=env, timeout=1800)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"   couldn't warm up Laya ({exc}) — the packaged app will download it on first run instead "
              f"(pip install -r requirements.txt first if laya isn't installed).")


def pyinstaller():
    step("Packaging with PyInstaller (a few minutes)")
    for path in (DIST / "JARVIS", WORK):
        shutil.rmtree(path, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean",
         f"--distpath={DIST}", f"--workpath={WORK}"], cwd=ROOT)
    exe = DIST / "JARVIS" / ("JARVIS.exe" if os.name == "nt" else "JARVIS")
    if not exe.exists():
        raise SystemExit(f"PyInstaller finished but {exe} is missing.")
    return exe


def selftest(exe: Path):
    step("Self-test of the packaged app")
    log = Path(tempfile.gettempdir()) / "jarvis_selftest.log"
    env = dict(os.environ, JARVIS_SELFTEST_LOG=str(log), QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", ""))
    result = subprocess.run([str(exe), "--selftest"], env=env, timeout=180)
    report = log.read_text(encoding="utf-8") if log.exists() else "(no log)"
    print("   " + report.strip().replace("\n", "\n   "))
    if result.returncode != 0:
        raise SystemExit("The packaged app failed its self-test; see above.")


def find_iscc():
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return Path(found)
    for path in ISCC_CANDIDATES:
        if path.exists():
            return path
    return None


def ensure_inno():
    iscc = find_iscc()
    if iscc or os.name != "nt":
        return iscc
    step("Installing Inno Setup 6 (winget)")
    try:
        run(["winget", "install", "--id", "JRSoftware.InnoSetup", "-e", "--silent",
             "--accept-package-agreements", "--accept-source-agreements"])
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"   couldn't install it automatically ({exc}).")
    return find_iscc()


def installer(version: str):
    iscc = ensure_inno()
    if iscc is None:
        print("\nInno Setup 6 isn't installed, so no installer was made. Get it from "
              "https://jrsoftware.org/isdl.php and run this again. The portable app is in dist\\JARVIS.")
        return None
    step("Building the installer with Inno Setup")
    run([str(iscc), f"/DAppVersion={version}", str(ISS)], cwd=ROOT / "installer")
    out = DIST / f"JARVIS-Setup-{version}.exe"
    if not out.exists():
        raise SystemExit(f"Inno Setup finished but {out} is missing.")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-installer", action="store_true", help="stop after the portable dist\\JARVIS folder")
    parser.add_argument("--skip-selftest", action="store_true")
    parser.add_argument("--skip-laya-warmup", action="store_true",
                        help="don't pre-download Laya's model; the packaged app still bundles the laya/torch "
                             "packages and downloads the model on first run instead")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("Note: PyInstaller builds for the OS it runs on — run this on Windows to get JARVIS.exe.")
    version = app_version()
    print(f"JARVIS {version} — building from {ROOT}")
    ensure_pyinstaller()
    make_icon()
    if os.getenv("JARVIS_BUNDLE_LAYA", "1") == "1" and not args.skip_laya_warmup:
        warm_up_laya()
    exe = pyinstaller()
    if not args.skip_selftest:
        selftest(exe)
    if args.no_installer:
        print(f"\nDone: {exe}")
        return 0
    setup = installer(version)
    if setup:
        size = setup.stat().st_size / 1e6
        print(f"\nDone: {setup}  ({size:.0f} MB)\nDouble-click it to install JARVIS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
