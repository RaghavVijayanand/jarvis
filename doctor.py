#!/usr/bin/env python3
"""JARVIS doctor — live checks of this machine's setup.

    python doctor.py           # quick checks (no downloads)
    python doctor.py --get-voice-model   # download the live-voice speech model now
    python doctor.py --laya    # also load Laya and route sample commands (downloads ~0.8 GB once)
    python doctor.py --live    # also send one short prompt to each configured AI provider

The offline unit tests live in tests/ (python -m unittest discover -s tests).
"""
import importlib
import os
import platform
import sys
import time

GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"
if os.name == "nt":
    os.system("")  # enable ANSI colours in Windows terminals

results = []


def report(name, ok, detail="", warn=False):
    mark = f"{GREEN}OK  {RESET}" if ok else (f"{YELLOW}WARN{RESET}" if warn else f"{RED}FAIL{RESET}")
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    results.append(ok or warn)


def check_python():
    ok = sys.version_info >= (3, 10)
    report("Python version", ok, platform.python_version() + ("" if ok else " (3.10+ required)"))


def check_packages():
    required = ["requests", "dotenv", "rich", "psutil", "schedule",
                "bs4", "PySide6", "pyautogui", "PIL"]
    optional = {"laya": "local decision model", "torch": "needed by Laya", "edge_tts": "neural voice",
                "pyttsx3": "offline voice", "speech_recognition": "voice input", "pyaudio": "microphone",
                "pycaw": "volume control", "win32gui": "window control (pywin32)", "wmi": "hardware info / brightness",
                "send2trash": "delete to Recycle Bin", "winsdk": "now-playing / media session",
                "vosk": "offline wake word", "pynput": "emergency-stop hotkey"}
    for name in required:
        try:
            importlib.import_module(name)
            report(f"package {name}", True)
        except Exception as exc:
            report(f"package {name}", False, f"pip install -r requirements.txt ({exc})")
    for name, why in optional.items():
        try:
            importlib.import_module(name)
            report(f"optional {name}", True, why)
        except Exception:
            report(f"optional {name}", False, f"not installed — {why}", warn=True)


def check_config():
    from core.config import Config, ENV_PATH
    report("settings file", True, str(ENV_PATH) + ("" if ENV_PATH.exists() else " (not created yet)"))
    report("Gemini key", bool(Config.GEMINI_API_KEY), "set" if Config.GEMINI_API_KEY else "not set", warn=True)
    report("OpenRouter key", bool(Config.OPENROUTER_API_KEY), "set" if Config.OPENROUTER_API_KEY else "not set",
           warn=True)
    report("decision engine", True, f"{Config.DECISION_ENGINE} ({Config.LAYA_MODEL}), threshold {Config.DECISION_THRESHOLD}")


def check_ollama():
    import requests
    from core.config import Config
    try:
        tags = requests.get(f"{Config.OLLAMA_URL}/api/tags", timeout=2).json().get("models", [])
        report("Ollama", True, f"{len(tags)} local model(s): " + ", ".join(m['name'] for m in tags[:5]))
    except Exception:
        report("Ollama", False, "not running (optional — install from ollama.com for offline chat)", warn=True)


def check_brain(live=False):
    from core.brain import MultiModelBrain
    brain = MultiModelBrain()
    print("   " + brain.refresh_catalog())
    report("AI models", bool(brain.available_models), f"{len(brain.available_models)} available, "
           f"active: {brain.current_model}", warn=not brain.available_models)
    if live and brain.available_models:
        print(brain.benchmark_models(limit=4))


def check_laya():
    from core.decision import DecisionEngine
    engine = DecisionEngine(engine="laya")
    print("   Loading Laya (first run downloads the model)…")
    engine._load()
    if not engine.laya_ready:
        report("Laya", False, engine.status)
        return
    report("Laya", True, engine.status)
    samples = ["what time is it", "could you turn it down a bit", "open spotify and play some jazz",
               "is it going to rain in pune tomorrow", "I need to call mom at 6", "shut the laptop down",
               "what's on my screen right now", "tell me about the roman empire"]
    for text in samples:
        start = time.perf_counter()
        d = engine.decide(text)
        print(f"   {text!r:45} → {d.intent:8} {d.confidence:.2f} ({d.source}) "
              f"multi={d.multi_step:.2f} {1000 * (time.perf_counter() - start):.0f} ms")


def check_voice():
    try:
        from core.voice import VoiceEngine
        voice = VoiceEngine()
        mics = voice.get_available_microphones()
        report("microphones", bool(mics), f"{len(mics)} found" if mics else "none found", warn=not mics)
        report("offline voice", voice.tts_engine is not None, "pyttsx3/SAPI", warn=voice.tts_engine is None)
    except Exception as exc:
        report("voice", False, str(exc), warn=True)
    try:
        from core import streaming
        from core.config import Config
        if not streaming.vosk_available():
            report("live voice", False, "pip install vosk (acts while you speak)", warn=True)
        elif streaming.model_ready():
            report("live voice", True, f"speech model ready: {streaming.model_dir()}")
        else:
            report("live voice", False, f"{Config.VOSK_MODEL_NAME} downloads on first mic click "
                                        f"(or run: python doctor.py --get-voice-model)", warn=True)
    except Exception as exc:
        report("live voice", False, str(exc), warn=True)


def get_voice_model():
    from core import streaming
    from core.config import Config

    def progress(message):
        print(f"   {message}", flush=True)
    try:
        print(f"Downloading {Config.VOSK_MODEL_NAME}…")
        path = streaming.ensure_model(Config.VOSK_MODEL_NAME, on_progress=progress)
        report("speech model", path is not None, str(path) if path else "download failed")
    except Exception as exc:
        report("speech model", False, str(exc))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    os.chdir(here)
    print("JARVIS doctor\n")
    check_python()
    check_packages()
    check_config()
    check_ollama()
    check_brain(live="--live" in sys.argv)
    check_voice()
    if "--get-voice-model" in sys.argv:
        get_voice_model()
    if "--laya" in sys.argv:
        check_laya()
    else:
        print("\n(Run 'python doctor.py --laya' to test the local decision model.)")
    failed = results.count(False)
    print(f"\n{len(results) - failed} checks passed, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
