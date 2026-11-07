# JARVIS user guide

## Starting

- **Installed:** Start menu → **JARVIS**. It lives in the system tray (the cyan ring next to the clock). Launching it again while it's running just opens the command bar.
  - **Ctrl + Shift + Space** anywhere opens the **command bar**. Type, press Enter, and replies appear under it. ↑ recalls earlier requests, Esc hides the bar, and ⤢ opens the dashboard.
  - **Hold Ctrl + Alt** anywhere to talk to the **cursor buddy** (see *Buddy mode*).
  - **Click** the tray icon for the command bar, **double-click** it for the dashboard, and **right-click** it for switches (buddy, live voice, start with Windows), Settings and Quit.
  - Closing the dashboard keeps JARVIS running in the tray. Use *Quit JARVIS* in the tray menu to exit.
  - Reminders and alarms appear as Windows notifications while the dashboard is closed.
- **From source:** `python app.py` (the tray app, same as installed) or `start_jarvis_gui.bat`. `python main_gui.py` opens just the dashboard window.
- **Terminal:** `python jarvis.py` (text), `python jarvis.py voice` (wake word), or `python jarvis.py "what time is it"` (one command).

## The dashboard

- **The orb** in the header, and the large one on the empty chat screen, shows JARVIS's state: cyan standing by, green listening, blue thinking, amber working through steps, and a pulsing wave while speaking. The status pill next to it spells the state out.
- **Chat** renders Markdown: lists, bold text, links, and code blocks with a copy button. Hover over a reply to copy it. If you scroll up while JARVIS is talking, a **↓ Latest** button takes you back down.
- **Activity** (the list icon, top right) is a live timeline. Every step JARVIS runs appears there, typed, spoken or queued, with lane badges (L1/L2) for things running at the same time, how long each step took, and why it failed if it did.
- **System** shows live CPU, memory, disk and battery gauges. **Automate** holds the screen tools and the task queue. **Memory** lets you search and delete what JARVIS remembers.
- **Settings** is organised into sections: AI Models, Decisions, Voice, Buddy & Hotkeys, Safety, Location and About. Use the search box (Ctrl+F) to find any setting. *Save changes* lights up only when something has changed, and changed rows are marked.

## How JARVIS decides what to do

1. Laya, the local decision model, reads your message and picks a skill: apps, media, files, reminders, screen, system, search, chat… It also flags multi-step and destructive requests. This takes milliseconds and nothing leaves your PC.
2. If you asked for several things, JARVIS runs them as ordered steps: "open Chrome, go to YouTube and play jazz, then set volume to 30". If you open a browser first, later website steps use that browser.
3. The chosen skill answers directly. If it can't, the language model takes over, and it can still act through JARVIS's tools.
4. Anything destructive asks first: shutdown, restart, sign out, sleep, deleting files, closing apps, emptying the Recycle Bin, and risky clicks. Reply **yes** or **no**, in text or by voice.

The header shows **● Laya** (green) when the decision model is loaded and **● Rules** otherwise. `decision status` shows the details.

## Things to try

**Apps and web**

- `open spotify`, `close chrome`, `list apps adobe`
- `go to github.com`, `play lo-fi beats`, `open youtube and play interstellar soundtrack`

**Media and volume**

- `pause`, `next track`, `previous song`, `what's playing` (needs `winsdk`)
- `volume 35`, `turn it down`, `mute`, `unmute`

**PC control**

- `lock my pc`, `show desktop`, `minimize chrome`, `switch to notepad`, `list windows`, `close all windows`
- `open bluetooth settings`, `wifi settings`, `brightness 60`
- `restart the computer`, `shut down`, `sleep`, `cancel shutdown`

**Files** (default folder: Documents)

- `create file notes/todo.txt with content buy milk`, `make a new file called ideas.txt on my desktop`
- `read file todo`, `rename todo.txt to groceries`, `copy report.txt to backups/`, `delete file old.txt`
- `open downloads folder`, `list files in desktop`, `file info report.txt`

**Time, alarms and reminders** (these survive restarts)

- `what time is it`, `what's the date`
- `set an alarm for 6:45 am`, `alarm in 20 minutes`
- `remind me to call mom in 30 minutes`, `remind me at 5 pm to stretch`, `set a timer for 10 minutes`
- `every day at 8 am weather`, `list reminders`, `cancel reminder`

**Information**

- `weather in Pune`, `will it rain tomorrow`
- `search for the latest Python release`, `news headlines`, `wikipedia alan turing`
- `cpu usage`, `memory usage`, `battery`, `disk space`, `system health`, `network info`
- `what's 18% of 2450`, `square root of 729`

**Screen**

- `take a screenshot`, `what's on my screen`, `click the Save button`, `double click the recycle bin`
- `type hello from JARVIS` (any language), `press ctrl+s`
- `automate open notepad and write a haiku`. The vision model drives the mouse and keyboard. Stop it with **Ctrl+Alt+Esc** or by moving the mouse into a screen corner.

**Memory**

- `remember that I'm allergic to peanuts`, `my name is Raghav`, `I live in Chennai`
- `what do you know about me`, `forget peanuts`, `forget everything`
- Or use **🧠 Memory** in the sidebar to view, add and remove facts.

**Models**

- `list models`, `switch model gemini-flash`, `benchmark models`, `refresh models`, `clear history`

## The Automation page

- **Screen vision:** take a screenshot, describe the screen, or click something by description.
- **Multi-step task:** *Plan Steps* shows how JARVIS will split and route the task without running it. *Add to Queue* runs it.
- **Task queue:** a real queue. **Pause** lets the current task finish and holds the rest, **Resume** continues, **Clear** empties it, and **Stop Current** stops a running plan or automation. Chat messages always go ahead of queued tasks.

## Buddy mode (cursor companion)

Buddy mode is on by default. A small cyan dot follows your cursor.

- **Hold Ctrl + Alt** (you can change the hotkey in Settings → Voice), ask your question, and let go. The dot pulses while it listens and spins while it thinks. The answer appears in a bubble next to the cursor and is spoken aloud.
- **Questions about the screen** ("where is…", "how do I…", "show me…", "what is this…", "which button…", "I can't find…") get **pointing**. Arrows fly from the buddy to each control, ring it, and number the steps in order. The buddy doesn't click anything. You stay in control.
- **Commands** ("open Spotify", "turn the volume down and pause the music") are carried out, just like typing them.
- Typing a "where is…" question in the chat uses the pointer too.
- **Privacy:** the screen is captured only when you ask, and the overlay itself never appears in screenshots or screen shares (Windows 10 version 2004 or later).
- Screen questions need a vision-capable model. Gemini's free key works, as does a local `ollama pull qwen2.5vl:3b`.
- The **Buddy** button in the chat header turns it off or on.

## Voice

- **Voice On** (chat header) speaks replies. Long answers are summarised aloud, and the full text stays on screen.
- **🎤** starts **live voice**. JARVIS listens continuously and acts on each command as soon as you finish saying it, without waiting for you to finish the whole sentence. You'll hear a short beep each time it starts something. When you stop talking it says a one-line summary. The first click downloads the speech model (Indian English, about 1 GB, one time only). Until the model is ready, JARVIS uses classic voice chat.
  - **Connectors:** "and", "then", "after which" and "after that" run commands in order. "simultaneously", "meanwhile", "at the same time" and "while" start a **parallel lane**. For example, "open chrome and play rick roll on youtube **simultaneously** set an alarm for 10 am **after which** change the resolution to 720p" runs the YouTube steps and the alarm-then-resolution steps side by side.
  - **"next video"** waits until the video is actually playing (via the Windows media session when `winsdk` is installed, otherwise a few seconds) before pressing Next.
  - **Screen resolution** changes revert automatically after 15 s unless you say **"keep resolution"**. That way you're never stuck on a mode your screen can't show. It resets on reboot.
  - **Alarms:** the Windows Clock app can't take alarms from other programs, so "open the alarm" opens Clock, and "set the alarm for 10 am" sets a JARVIS alarm (it survives restarts).
  - Questions and chat ("what's the weather like…", "tell me a joke") wait until you've stopped talking. Actions run immediately. Risky actions (shutdown, closing apps) still ask, and you can answer "yes" or "no" out loud.
  - Settings → Voice: turn live voice off, choose **Act on commands: at each short pause** if it's too eager, or pick a smaller speech model.
- Confirmations can be answered by voice.
- In the terminal, `python jarvis.py voice` waits for the wake word (default "jarvis", matched as a whole word). Set a Vosk model in Settings → Voice to detect it offline.

## Troubleshooting

- **"No AI model is configured"** — add a key in Settings or install Ollama. Everything except open-ended chat still works.
- **An answer says a model failed** — JARVIS already tried a fallback model. Check the key and connection, or pick another model.
- **Laya stuck on "loading"** — the first download is about 0.8 GB. Check `%APPDATA%\Jarvis\logs\jarvis.log`. Choose *Rules only* in Settings to skip it.
- **An app won't open** — try its exact Start-menu name, or `list apps <part of name>`.
- **Logs:** `%APPDATA%\Jarvis\logs\jarvis.log` (File → Open Data Folder).
- **Health check:** `python doctor.py`.
- **Live voice falls back to classic voice** — check `python doctor.py` for "live voice". Run `pip install vosk`, then `python doctor.py --get-voice-model`.
- **Live voice acts on a half-heard word** — switch Settings → Voice → *Act on commands* to *At each short pause*.
