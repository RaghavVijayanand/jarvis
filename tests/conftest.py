import ctypes
import os
import subprocess

import pytest

from core.config import Config


@pytest.fixture(autouse=True)
def _no_local_speech_models(monkeypatch):
    """Tests never load Whisper onto the GPU or speak through Kokoro: they keep the engines the
    voice tests were written against. test_local_speech / test_conversation use fakes for both."""
    monkeypatch.setattr(Config, "STT_ENGINE", "google")
    monkeypatch.setattr(Config, "TTS_ENGINE", "edge")
    monkeypatch.setattr(Config, "LOCAL_ONLY", False)       # the user's .env may switch it on


# ── Safety net: the suite must never touch the real PC ───────────────────────
# Most tests were written on Linux, where every Windows call is a harmless
# "only available on Windows". On a real Windows machine an unmocked path would
# lock the session, sign out, sleep, pop a UAC/password prompt, press keys or
# change the display. Those calls are replaced with recorders here; a test that
# mocks them itself (patch / patch.object) still layers on top as before.

_BLOCKED = []                       # (test id, what was attempted)
_POWER_EXES = {"shutdown", "shutdown.exe", "logoff", "logoff.exe", "rundll32", "rundll32.exe", "tsdiscon",
               "tsdiscon.exe"}


def _argv0(args):
    if isinstance(args, (list, tuple)) and args:
        first = str(args[0])
    else:
        first = str(args or "").strip().split(" ")[0]
    return os.path.basename(first.strip('"')).lower()


# JARVIS_STRICT_GUARD=1 (set in CI): a blocked call fails its test instead of only being
# listed at the end. Checked at teardown too, since app code often swallows exceptions.
_STRICT = os.environ.get("JARVIS_STRICT_GUARD", "").strip() == "1"


@pytest.fixture(autouse=True)
def _block_real_side_effects(monkeypatch, request):
    test_id = request.node.nodeid
    before = len(_BLOCKED)

    def blocker(what, result=0):
        def fake(*args, **kwargs):
            _BLOCKED.append((test_id, what))
            if _STRICT:
                raise AssertionError(f"test touched the real PC: {what}")
            return result
        return fake

    if os.name == "nt":
        user32, shell32, powrprof = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.powrprof
        for name in ("LockWorkStation", "ExitWindowsEx", "keybd_event", "SendInput", "mouse_event"):
            monkeypatch.setattr(user32, name, blocker(f"user32.{name}"), raising=False)
        monkeypatch.setattr(powrprof, "SetSuspendState", blocker("powrprof.SetSuspendState"), raising=False)
        monkeypatch.setattr(shell32, "ShellExecuteW", blocker("shell32.ShellExecuteW (UAC prompt)", 0),
                            raising=False)
        try:
            import win32api
            for name in ("ChangeDisplaySettings", "ChangeDisplaySettingsEx"):
                monkeypatch.setattr(win32api, name, blocker(f"win32api.{name}"), raising=False)
        except ImportError:
            pass
        monkeypatch.setattr(os, "startfile", blocker("os.startfile", None), raising=False)

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        real = getattr(subprocess, name)

        def guarded(*args, _real=real, _name=name, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            if _argv0(cmd) in _POWER_EXES:
                _BLOCKED.append((test_id, f"subprocess.{_name}({cmd!r})"))
                raise OSError(f"blocked in tests: {cmd!r}")
            return _real(*args, **kwargs)
        monkeypatch.setattr(subprocess, name, guarded)

    try:
        import pyautogui
        for name in ("press", "hotkey", "write", "typewrite", "keyDown", "keyUp", "click", "doubleClick",
                     "rightClick", "moveTo", "dragTo", "scroll"):
            monkeypatch.setattr(pyautogui, name, blocker(f"pyautogui.{name}", None), raising=False)
    except Exception:
        pass

    yield
    if _STRICT:
        touched = [what for tid, what in _BLOCKED[before:] if tid == test_id]
        if touched:
            pytest.fail("test touched the real PC (mock it): " + ", ".join(sorted(set(touched))), pytrace=False)


def pytest_terminal_summary(terminalreporter):
    if not _BLOCKED:
        return
    terminalreporter.section("real-PC side effects blocked (these tests need proper mocks)")
    for test_id, what in _BLOCKED:
        terminalreporter.write_line(f"{test_id}: {what}")
