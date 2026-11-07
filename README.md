# JARVIS — desktop AI assistant for Windows

JARVIS chats, controls your PC, and handles multi-step jobs. You can type or talk to it. Think of it as a HeyClicky-style companion for Windows: a small buddy sits next to your cursor. Hold a hotkey and ask about whatever is on screen, and it answers out loud and points at the right button.

- **Buddy mode (cursor companion).** Hold **Ctrl + Alt** anywhere, speak, and let go. Ask "where's the export button?" or "how do I change my wallpaper?" and the buddy next to your cursor draws arrows and rings on the exact controls, numbered in order, and says what to do. It never clicks for you. Say a command ("open settings and turn on dark mode") and it does it. The screen is captured only while you use the hotkey, and the overlay is hidden from screenshots.
- **Local decision model.** Every request is routed by [Laya](https://huggingface.co/convaiinnovations/laya), an open (Apache-2.0) typed decision model. It runs on your own machine in tens of milliseconds, with no cloud call. If Laya isn't installed yet, deterministic rules route instead.
- **Any language model.** Chat uses Gemini (free key), OpenRouter (free models available) or local Ollama models. All three can use JARVIS's tools (open apps, files, volume, screen, reminders…) through one shared tool registry. If a model fails, JARVIS switches to another one automatically.
- **Real Windows control.** It can open and close apps and websites, play YouTube videos, control media and volume, lock, sleep, restart or shut down, manage windows, open Settings pages, set brightness, and use the clipboard.
- **Screen vision.** It can describe the screen, click elements by description, and run multi-step UI automation. It uses DPI-correct coordinates and has an emergency stop.
- **Live voice, acts while you speak.** Click 🎤 and speak naturally. An offline streaming recogniser (Vosk, Indian-English model) hears each command as you say it, and JARVIS starts it straight away. "…and simultaneously…" runs commands in parallel lanes, and "…after which…" / "then" keeps them in order. Spoken replies use a neural voice (edge-tts), with the offline Windows voice as a fallback.
- **Memory and reminders.** JARVIS remembers facts about you, and you can view or edit them. Alarms and reminders persist across restarts.
- **Safe by default.** Shutdown, restart, deleting files, closing apps and risky clicks always ask first. There is no shell-command tool.

## How it looks

JARVIS is a **tray app**. After installing, it waits next to the clock and gives you four surfaces:

| Surface | How you reach it | What it's for |
|---|---|---|
| **Cursor buddy** | Hold **Ctrl + Alt** anywhere | Talk: it points at things on screen or does what you say |
| **Command bar** | **Ctrl + Shift + Space** anywhere, or click the tray icon | Type a request; replies appear as cards underneath |
| **Dashboard** | Double-click the tray icon, or ⤢ in the command bar | Chat history, automation queue, system page, memory, settings |
| **Tray menu** | Right-click the tray icon | Buddy / live voice / start with Windows switches, settings, quit |

Everything shares one **HUD design**: near-black glass, cyan light and an animated arc-reactor orb that shows what JARVIS is doing. It is green while listening, blue while thinking, amber while carrying out steps, and pulses while speaking. The orb, the status pill, the Activity timeline (each step, its lane and duration), the command bar and the tray icon all change together.

A welcome setup runs on the first start: pick Gemini, OpenRouter or local Ollama, choose hotkeys, and turn start with Windows on or off.

## Install

**The installer (recommended).** Double-click `build_installer.bat` once to make `dist\JARVIS-Setup-3.1.0.exe`, then run that. It installs per user with no admin prompt, adds Start-menu entries (plus an optional desktop icon and start with Windows), and includes an uninstaller. If the project is on GitHub, copy `installer/windows-installer.yml` to `.github/workflows/` and GitHub will build the installer on Windows for every push. Download it from the run's *Artifacts*.

**From source:**

```powershell
cd D:\jarvis\jarvis
py -3 -m venv .venv
.venv\Scripts\activate
python setup.py            # installs requirements, creates %APPDATA%\Jarvis\.env
python app.py              # the tray app   (python main_gui.py: just the window; python jarvis.py: terminal)
```

Add a Gemini key (free at aistudio.google.com/apikey) or an OpenRouter key in the welcome setup or in **Settings**. You can also install [Ollama](https://ollama.com) and JARVIS will use local models offline.

The first start downloads the Laya weights once (about 0.8 GB, into the Hugging Face cache). Until they are ready, the header shows **● Rules**; afterwards it shows **● Laya**. If you'd rather not download them, choose *Settings → Decisions → Rules only*, or install with `python setup.py --no-laya`.

Check your machine at any time with `python doctor.py`. Add `--laya` to test the decision model, `--get-voice-model` to download the live-voice speech model (~1 GB, otherwise it downloads on the first 🎤 click), or `--live` to ping each AI provider.

## Examples

| You say | JARVIS does |
|---|---|
| `open chrome, go to youtube and play michael jackson, then set volume to 30` | 3 ordered steps, the video plays in Chrome |
| `open chrome and go to youtube and play rick roll and move to the next video simultaneously open the alarm set the alarm for 10 am after which open settings and change the screen resolution to 720p` | Two lanes run at once: (1) Chrome → YouTube → play → Next once it's playing; (2) Clock → 10 am alarm → Settings → 1280×720, which reverts in 15 s unless you say **keep resolution** |
| `lock my pc` · `show desktop` · `open bluetooth settings` | Native Windows actions |
| `restart the computer` | Asks first, then restarts in 30 s (`cancel shutdown` stops it) |
| `remind me to stretch in 20 minutes` · `set an alarm for 7 am` | Persistent reminder or alarm |
| `create file notes/todo.txt with content buy milk` | File in Documents\notes |
| `what's on my screen` · `click the Save button` | Screen vision |
| `automate open notepad and type hello` | Vision-driven mouse and keyboard (Ctrl+Alt+Esc stops it) |
| `remember that I'm vegetarian` · `what do you know about me` | Editable memory |
| `list models` · `switch model gemini-flash` · `benchmark models` · `decision status` | Model management |

Say **help** for the full list.

## Layout

| Path | What it is |
|---|---|
| `app.py` | **The tray app** (what `JARVIS.exe` runs): single instance, first-run setup, tray, command bar, dashboard |
| `ui/theme.py`, `ui/widgets.py` | The HUD design system: palette, fonts, drawn icon set, the `ArcOrb`, toggle switches, bracketed panels, status pill |
| `ui/chat_view.py`, `ui/activity.py`, `ui/dash_widgets.py` | The dashboard's Markdown chat, greeting screen, Activity timeline, and system gauges |
| `ui/shell.py`, `ui/tray.py`, `ui/command_bar.py`, `ui/onboarding.py` | Tray wiring, tray icon and single-instance handling, the floating command bar, the welcome wizard, and the shared look and icons |
| `main_gui.py` | The dashboard window: chat, automation queue, system page, embedded browser. It owns JARVIS, the command worker, voice and the buddy |
| `core/autostart.py`, `core/hotkeys.py` | Start with Windows (HKCU Run) and the global command-bar hotkey |
| `build/build_installer.py`, `build/jarvis.spec`, `installer/jarvis.iss` | Icon → PyInstaller one-folder app → self-test → Inno Setup installer |
| `jarvis.py` | The assistant core: routing (planner first, then decision, handler and LLM), confirmation queue, CLI/voice loops |
| `handlers/` | One module per domain (apps, media, control, schedule, files, screen, memory, info, chat). Each one both **handles its intents** and **registers its LLM tools**, so every capability is defined once. |
| `core/executor.py` | `ExecutionSession`: parallel lanes of ordered steps, stop-on-failure per lane, shared input lock |
| `core/buddy.py`, `ui/buddy_overlay.py` | Buddy mode: push-to-talk hotkey, recording and offline transcription, screen guidance (one vision call gives the answer and the points), and the click-through cursor overlay |
| `core/streaming.py` | Live voice: Vosk streaming recogniser, clause tracker, act-while-speaking session |
| `core/decision.py` | Laya decision engine and rule fallback |
| `core/brain.py` | Gemini / OpenRouter / Ollama chat, tool-calling loop, failover, vision, benchmarks |
| `core/tools.py` | The single tool registry exposed to language models |
| `core/config.py` | Settings (per-user `.env`) and data folders |
| `core/memory.py`, `core/voice.py`, `core/ollama_manager.py`, `core/logging_setup.py` | Memory, speech, local AI, logging |
| `skills/` | App control, Windows control, files, scheduler, screen automation, web, weather, system info … |
| `ui/settings.py` | Settings dialog |
| `tests/` | Offline unit tests: `python -m unittest discover -s tests` |
| `doctor.py` | Live environment check |
| `build/`, `installer/`, `build_installer.bat` | Packaging (see *Install*) |

Settings, memory, chat history, schedules, logs and screenshots all live in `%APPDATA%\Jarvis`, never in the program folder. See **SETUP_GUIDE.md** for installation details and **USERGUIDE.md** for everyday use.
