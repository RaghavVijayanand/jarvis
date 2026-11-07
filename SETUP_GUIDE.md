# JARVIS setup guide

## Requirements

- Windows 10 or 11. Most features also run on macOS/Linux, but PC control, volume, windows and app discovery are Windows-only.
- Python **3.10 or newer**. 3.11–3.14 are tested.
- About 3 GB of free disk space if you use Laya (for PyTorch and the model weights).
- Optional: a microphone, [Ollama](https://ollama.com) for offline chat, and a Gemini or OpenRouter API key.

## Install

```powershell
cd D:\jarvis\jarvis
py -3 -m venv .venv
.venv\Scripts\activate
python setup.py
```

`setup.py` installs `requirements.txt` and creates `%APPDATA%\Jarvis\.env`. It has two options:

- `python setup.py --laya` also downloads and tests the Laya decision model right away.
- `python setup.py --no-laya` skips PyTorch/Laya. JARVIS then routes with rules, which works well for common phrasing.

Verify with:

```powershell
python doctor.py          # packages, keys, Ollama, microphones
python doctor.py --laya   # loads Laya and shows how it routes sample requests
python -m unittest discover -s tests   # offline unit tests
```

### Common install problems

| Problem | Fix |
|---|---|
| `PyAudio` fails to build | Installed as its own step (not part of `requirements.txt`) precisely so this doesn't block everything else — you'll see a warning, not a failed setup. To actually fix it: install PortAudio's dev headers with [vcpkg](https://github.com/microsoft/vcpkg) (`vcpkg install portaudio:x64-windows`, then set `VCPKG_PATH` to your vcpkg root) and retry `pip install PyAudio`, or use a Python version with a prebuilt wheel (3.10-3.12 usually have one; very new Python releases often don't yet). Voice input is optional either way — everything else works without it. |
| PyTorch wheel not found | Use 64-bit Python. You can also install it first with `pip install torch --index-url https://download.pytorch.org/whl/cpu`. |
| `speech_recognition` errors on Python 3.13+ | `pip install standard-aifc audioop-lts` (already listed in requirements). |
| Laya download blocked (proxy/firewall) | Set `HF_ENDPOINT` or download `convaiinnovations/laya` elsewhere and copy it into the Hugging Face cache, or use *Rules only*. |
| Volume control errors | `pip install --upgrade pycaw comtypes` |

## Configure

Everything is in **⚙ Settings**, which writes `%APPDATA%\Jarvis\.env`:

- **AI Models.** A Gemini key, an OpenRouter key, the default model and the request timeout. The model lists refresh automatically. OpenRouter free models and Gemini's `-latest` aliases are discovered live.
- **Decisions.** Laya or rules, the English or multilingual checkpoint, and the confidence threshold.
- **Voice.** Neural or offline voice, the voice name, the wake word, and an optional Vosk model folder for an offline wake word. Download a small English model from alphacephei.com/vosk/models and install `pip install vosk`.
- **Safety.** Whether to confirm before automation takes over the mouse and keyboard, safe mode for risky clicks, the vision provider/model, and whether to start Ollama with JARVIS.
- **Location.** Used for weather. Leave it empty to auto-detect.

`.env.example` lists every key if you prefer to edit the file by hand.

## Local AI with Ollama (no keys)

1. Install Ollama from ollama.com.
2. Pull a chat model that supports tools, e.g. `ollama pull qwen2.5:7b` or `ollama pull llama3.2`.
3. For screen vision, also pull `ollama pull qwen2.5vl:3b`. If you have no models at all, JARVIS pulls this one on the first start.

JARVIS starts Ollama automatically. Local models show up in the model list as `ollama:<name>`; the tags show whether each one supports tools and vision.

## Build the installer

Double-click **`build_installer.bat`**, or run:

```powershell
pip install -r requirements_exe.txt
python build\build_installer.py          # → dist\JARVIS-Setup-3.1.0.exe
python build\build_installer.py --no-installer   # just the portable dist\JARVIS\ folder
$env:JARVIS_BUNDLE_LAYA=0; python build\build_installer.py   # smaller, rules-only build (skip Laya/torch)
python build\build_installer.py --skip-laya-warmup   # bundle Laya/torch but don't pre-download the model
```

Laya (the local decision model — PyTorch + transformers, +~1 GB) is bundled by default, so a fresh install never needs a separate `pip install laya`.

It runs these steps:

1. Draws the icon (`assets\jarvis.ico`).
2. Pre-downloads Laya's model weights (~0.8 GB, once) into `_hf_cache\`, so the packaged app has Laya ready offline from its first run — skipped with a warning (not a failure) if there's no internet or `laya` isn't installed locally; the app then just downloads the model on first use instead, same as a from-source install.
3. Packages the app with PyInstaller. This is a one-folder build, so it starts in a second or two.
4. Runs the packaged `JARVIS.exe --selftest`, which loads every module and fails the build if anything is missing.
5. Builds the installer with Inno Setup 6. If Inno Setup isn't installed, the script installs it with winget; you can also get it from jrsoftware.org.

The installer:

- Installs per user by default, with no admin prompt.
- Adds Start-menu shortcuts for **JARVIS** and **JARVIS dashboard**.
- Offers a desktop icon and *start with Windows*.
- Closes a running JARVIS before updating.
- On uninstall, asks whether to keep your settings and memory.

**Automatic builds:** copy `installer/windows-installer.yml` to `.github/workflows/` in your GitHub repo, and it runs the tests and builds the installer on Windows. Download `JARVIS-Setup` from the run's *Artifacts*. A tag such as `v3.1.0` also attaches it to a release.

`JARVIS.exe` options: `--tray` (start hidden, used at sign-in), `--dashboard`, `--setup` (show the welcome again), `--selftest`.

## Where things are stored

`%APPDATA%\Jarvis\` holds:

- `.env` — settings
- `memory\memory.json` — what JARVIS remembers
- `logs\jarvis.log`, `logs\conversation_history.json`
- `scheduled_tasks.json` — alarms, reminders, schedules
- `cache\screenshots\`, `backups\`

Older versions kept memory and history inside the program folder. They are copied here automatically on the first start.
