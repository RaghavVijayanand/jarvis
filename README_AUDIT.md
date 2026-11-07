# JARVIS — Use-Case Audit: Bugs & Improvements

## Overhaul status (2026-09-22) — supersedes the checklists below

Every item in this audit has been addressed in code. "Verified" means covered by the offline suite
(`python -m unittest discover -s tests`) or the offscreen GUI smoke run. "Needs live check"
means the code path depends on real Windows hardware or services that can't run in CI; use
`python doctor.py` and the checklist at the end.

| Area | UC | What changed | Status |
|---|---|---|---|
| Routing | 0.2, 2.1, 2.2, 2.5 | The ~900-line dead block is gone and `jarvis.py` was rewritten. Laya (local decision model, `core/decision.py`) with a rule fallback replaces the LLM classifier, so routing costs zero LLM calls. Categories and handlers match 1:1 (14 intents + EXIT). | Verified |
| Routing | 2.3, 2.4, 2.6, 2.7 | Weather gets the full query. Every handler returns a string, or `None` to hand off to the LLM. Lifecycle words must match exactly. Sleep replies with a hint. | Verified |
| Compound commands | 0.2, 13.1 | `CommandProcessor` is now a real step planner and executor, with per-step routing, waits, stop-on-failure, and "open Chrome … go to YouTube" using that browser. YouTube "play X" resolves the first video URL directly. | Verified (split/route); needs live check (playback) |
| Tools | 0.3, 3.3, 11.1, 11.2 | The LangChain agent was removed. One `ToolRegistry` (`core/tools.py`) serves OpenRouter, Gemini and Ollama function calling. Duplicate brain-level tools are gone (skills only). There is no shell tool, and confirmation-gated tools can't run without a yes. | Verified |
| Providers | 1.2, 1.3, 3.1, 3.2, 3.5, 3.6, 3.7, 3.8 | No demo model and no keyless defaults. Model catalogs are fetched live (OpenRouter free models, Gemini `-latest` aliases). Gemini uses its OpenAI-compatible endpoint. Errors come back as `Reply(is_error=True)`, are never stored, and trigger automatic failover. All calls have timeouts. The benchmark is real. | Verified |
| Voice | 4.1, 4.2, 4.3, 4.4 | Full-length playback (MCI, then playsound, then a duration-aware PowerShell fallback). Whole-word wake word with optional offline Vosk. The wake-word listener opens the mic lazily (it used to crash with `None`). The broken "sir → Sir." substitutions are gone. Speech is summarised. | Verified (logic); needs live check (audio) |
| GUI | 1.1, 1.5, 5.1–5.7 | The window paints first, then JARVIS initialises. One persistent `CommandWorker` has chat priority and a pausable, clearable task queue, with no `terminate()`. Automation buttons call skills directly. Plan Steps shows the real plan. Settings cover every option. Skill tests run real probes. There is a Memory dialog. Signal handlers are installed in the CLI only. | Verified (offscreen smoke) |
| Automation | 6.1–6.5 | `screen_automation.py` was rewritten. It uses one shared instance and a single Ctrl+Alt+Esc hotkey (the old Ctrl+Shift+Esc clashed with Task Manager). Confirmation goes through the GUI dialog. Unicode is pasted. Structured done-checks are cross-checked by Laya and screen-change detection. Coordinates are mapped from the downscaled model image to real screen pixels, and Gemini `box_2d` is supported. | Verified (helpers); needs live check |
| Files | 7.1–7.5 | Subfolders and spaces are kept, `..` is stripped, and system folders are refused. Natural phrasing works: rename, copy, move, open, list. Deletes need a yes and go to the Recycle Bin (send2trash). Backups copy JARVIS's own user data. | Verified |
| Scheduling | 8.1–8.6 | Alarms are persistent one-shot tasks (`once <iso>`). Missed tasks are reported on start. Natural reminder phrasing works. Reminders reach the GUI transcript and are spoken only when voice is on. | Verified |
| Search | 9.1–9.3 | Resilient search (kept). LLM summaries fall back to raw results when the model errors. Voice reads a summary. | Verified |
| Memory | 10.1–10.4 | Name capture is case-sensitive with a stop-list (no more "Going Home"). Laya flags other personal facts. There is a list/forget/forget-all API, chat commands and a GUI dialog. A corrupt file is quarantined, not silently wiped. | Verified |
| System | 11.3, 13.4, 14 | New `skills/windows_control.py`: lock, sleep, restart/shutdown (confirmed, cancellable), sign out, media keys, volume get/set/step/mute (with a fixed pycaw API call), brightness, windows focus/min/max/close/close-all, show desktop, Settings pages, clipboard, Unicode typing, now-playing via SMTC (optional `winsdk`). App launch/close was rewritten around ShellExecute with no user text passed to a shell, and it closes by exact process name. | Needs live check |
| Packaging | 1.4, 1.6, 12.1–12.6 | One dependency list with platform markers. `setup.py` and `doctor.py`. The spec can optionally bundle Laya. User data moved to `%APPDATA%\Jarvis` with migration. Central rotating log file. `config_user.py`/`config_template.py` were retired (settings live in `.env`). Docs were rewritten. | Verified |

### Architecture restructure and live voice (2026-09-23)

| Change | Why it's better |
|---|---|
| **`handlers/` package.** One class per domain (`apps`, `media`, `control`, `schedule`, `files`, `screen`, `memory`, `info`, `chat`), each with `intents`, `handle()` and `register_tools()`, dispatched by `HandlerRegistry`. | Before, every capability lived twice: once as an intent handler in `jarvis.py` and once as an LLM tool in `_register_tools`. Now a capability is written once and the two can't drift. `jarvis.py` shrank to routing and lifecycle. Adding a skill means adding one file. |
| **Planner-first routing.** `CommandProcessor.plan()` runs before classification, and anything with more than one step goes to the executor. | Compound sentences no longer depend on the classifier's `multi` flag, so a typed or spoken multi-command sentence always runs every step. |
| **`core/executor.py` `ExecutionSession`.** Ordered lanes that can run in parallel. A failure skips only the rest of its own lane. An input lock serialises key-sending steps, each lane has its own browser context, and a settle hook runs after each step. | One engine now serves typed plans, streaming voice, and the Automation queue, and "simultaneously" means real concurrency. |
| **`core/streaming.py` live voice.** A Vosk streaming recogniser feeds a `ClauseTracker` (it releases a clause once it has been stable for 2 updates and a connector follows). Actions are dispatched immediately and chat is deferred to the end of the utterance. The mic is muted while speaking, there is a beep per action, a spoken summary at the end, and yes/no confirmations by voice. | JARVIS acts while you're still talking, fully offline. The Indian-English large model is the default. |
| Pending confirmations are a **queue**, not a single slot. | Two risky steps in one sentence each get their own yes/no. |
| New Windows capability: **screen resolution** (`parse_resolution`, `set_resolution` dynamic mode with a 15 s auto-revert, and "keep resolution"). Media playback detection before **next video**. Clock app opening. | Covers the requested example sentence end to end. |

Offline suite: **740 tests**, stable across repeated back-to-back runs (including `test_streaming.py`, `test_buddy.py`, the per-module `test_cov_*.py` suites and a real-HTTP `test_end_to_end.py`).

### Buddy mode (2026-09-23): HeyClicky-style companion for Windows
`core/buddy.py` and `ui/buddy_overlay.py` provide:
- **Push to talk:** hold a global hotkey (Ctrl + Alt by default; AltGr typing is ignored) to record. The recording is transcribed offline with Vosk when the model is present, otherwise with Google.
- **Routing:** screen questions go to a single vision call that returns the answer plus points to highlight. Anything else goes to the normal command path.
- **Overlay:** a click-through, always-on-top window following the cursor. It shows listening, thinking and speaking states, draws animated numbered arrows and rings, and is excluded from screen capture via `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`.
- **Chat:** typed "where is…" questions in chat use the same pointer.
- **Tests:** `tests/test_buddy.py` (23 tests) covers this, including offscreen painting.

### Tray app and installer (2026-09-23)
- **App shell:** `app.py`, the tray app (single instance via a local socket, the installer's mutex, first-run wizard). `ui/shell.py` wires the tray, command bar, buddy and dashboard together. The dashboard (`MainWindow`) still owns JARVIS and the single command worker, so every surface shares one queue, history and set of confirmations.
- **New surfaces:** `ui/command_bar.py` (the floating bar, global hotkey `core/hotkeys.py`), `ui/tray.py` (menu, toasts, busy icon), `ui/onboarding.py` (welcome wizard), `ui/theme.py` (one palette and code-drawn icons), and `core/autostart.py` (HKCU Run).
- **Packaging:** `build/jarvis.spec` builds a one-folder, windowed app from `app.py`, including the vosk DLLs and pynput's Windows backends. `build/build_installer.py` runs icon → PyInstaller → `--selftest` of the frozen exe → Inno Setup (`installer/jarvis.iss`). `build_installer.bat` does all of it in one step, and a GitHub Actions workflow (`installer/windows-installer.yml`, copy it into `.github/workflows/`) builds the installer on `windows-latest`.
- **Verified here:** the spec was built with PyInstaller on Linux, where the frozen app passed `--selftest` and started in tray mode without errors. `tests/test_tray_app.py` (32 tests) and offscreen screenshots of every surface. The Windows `.exe` and installer themselves have to be built on Windows (PyInstaller doesn't cross-compile).

### Live acceptance checklist (run on the Windows machine)
- [ ] `build_installer.bat` produces `dist\JARVIS-Setup-3.1.0.exe`. Installing it shows the welcome wizard, JARVIS appears in the tray, **Ctrl+Shift+Space** opens the command bar from any app, closing the dashboard keeps it in the tray, running the Start-menu shortcut again opens the bar instead of a second copy, and uninstalling offers to keep your data.
- [ ] Buddy: hold Ctrl+Alt, ask "where is the start button", release → an arrow and ring land on it and the answer is spoken; a screenshot taken now doesn't show the buddy.
- [ ] `python doctor.py --get-voice-model`, then click 🎤 and say the full example: "open chrome and go to youtube and play a video called rick roll and move to the next video simultaneously open the alarm set the alarm for 10 am after which open settings and change the screen resolution to 720p". Chrome should start before you finish the sentence, and the resolution should revert after 15 s unless you say "keep resolution".
- [ ] `python doctor.py --laya` — Laya loads and routes the sample phrases sensibly.
- [ ] Fresh settings, no keys: the chat banner explains the options; "open notepad", "volume 30" and "set an alarm in 2 minutes" work.
- [ ] Add a Gemini key: "hi" answers, and "put some jazz on YouTube" makes the model call `open_app_or_website`.
- [ ] "Open Chrome, go to YouTube and play Michael Jackson, then set volume to 30" runs the steps in order and the video plays in Chrome.
- [ ] "restart the computer" → "no" does nothing; "yes" schedules a restart; "cancel shutdown" aborts it.
- [ ] "set an alarm for <2 minutes from now>", restart JARVIS, and the alarm still rings.
- [ ] "what's on my screen" works with a vision model. "automate open notepad and type hello" asks first, and Ctrl+Alt+Esc stops it.
- [ ] A long spoken answer plays to the end.

---

## Historical record (2026-09-17 verification pass)


### Implementation status (2026-09-17, historical)

The findings below are a historical baseline, not a claim that fixes are complete.
Original line references will drift as code changes. This checklist tracks remediation:

- [x] P0: UC 11.1 / section 0.3 — unrestricted shell tool removed; skill refuses all inputs. Offline refusal and registry checks pass. Other action tools still need a permission review.
- [x] P0: UC 1.2–1.3 — no unconfigured or simulated default model (offline provider-discovery test; onboarding wizard remains open).
- [x] P0: UC 3.1 / part of 2.1 — current message sent once; context-free requests do not write history or memory. Classifier cost/routing remains open.
- [x] P0: UC 2.3 — weather receives the original query. Disk-usage, search, and FILE handlers now return result text; UC 2.4 remains open for SCREEN_AUTOMATION boolean returns.
- [x] P0: UC 2.6–2.7 — lifecycle words now match whole commands only ("How do I quit smoking?" is safe); sleeping returns an explicit wake-up hint. Voice-mode wake-word substring matching (UC 4.2) remains open.
- [x] P0: UC 3.6 (provider half) — OpenRouter initial and tool follow-up calls, Gemini, and Ollama all send timeouts; UC 5.2 (GUI `.terminate()`) remains open.
- [x] P0: UC 8.2 — alarm rollover uses `timedelta(days=1)`; month-end and leap-year cases tested offline.
- [x] Additional end-to-end check — real `run_text_mode` loop driven with a canned brain; no subprocess/pyautogui calls; cp1252 console crash fixed (`sys.stdout/stderr.reconfigure(errors="replace")`).
- [ ] P1: section 0.2 / UC 2.2 — remove dead code and align supported routing.
- [ ] P1: UC 1.1 / 1.5 / 5.1–5.4 — background initialization, task queue, worker lifecycle.
- [ ] P1: UC 6.1–6.5 — shared automation, confirmation, Unicode, verified outcomes and coordinates.
- [x] P1: UC 3.4 (persistence half) — `clear_history` persists the clear; reload-safe (offline test).
- [ ] P1: UC 10.1 / 10.3 — regex-only extraction and memory not user-visible/editable. (UC 10.2 token budgeting is fixed; see below.)
- [x] P1: UC 10.4 — Settings and chat-stated locations share the persisted preference used by AI memory and weather. Clearing it cannot restore a legacy memory location; failed detection no longer invents Chennai. Save/reload/clear/failure paths tested offline; live Settings dialog not exercised.
- [x] P1 (scoped): UC 7.1 / 7.4 — file operations default to `~/Documents` (home fallback); skill directory change no longer mutates process CWD.
- [x] P1: UC 7.3 — conversational overwrite confirmation implemented: retain target/content, route yes/cancel before classification, expire stale requests, reject changed files and mismatched filenames. Nine focused offline tests pass, including the real JARVIS command-router method. Backups (UC 7.5) and arbitrary path support (UC 7.2) remain separate open items; scoped agent-tool argument adapters are covered below.
- [x] Additional scheduler cancellation fix — pending timers cancelled, callback guard, CLI/GUI cleanup; seven offline tests.
- [x] Additional scheduler persistence — restores the task counter from saved IDs, retains absolute deadlines, persists running/completed state, and uses an instance-owned scheduler. Atomic saves propagate errors; completed/interrupted work is not automatically replayed. Verified by persistence and real-thread tests. See scheduler limitations below.
- [x] Shared browser control (part of tool fixes) — the agent now receives JARVIS's `ApplicationControl`, so GUI-registered embedded-browser callbacks apply to agent-driven navigation too; standalone construction still works with the system-browser fallback. Three wiring tests pass.
- [x] Additional tool argument adapters (scoped) — `rename_file` and `create_file` accept validated single-string JSON objects; `flip_coin` ignores its input and calls the zero-argument skill. Six offline tests cover argument routing, defaults, Unicode/whitespace preservation, invalid input rejection, temporary-file create/rename, and preservation of existing files pending overwrite confirmation. The parser does not expose the overwrite bypass. Real LangChain execution with a scripted brain also passes for these three tools; live provider behavior remains unverified.
- [x] P2: UC 6.6 — hardcoded Gemini key replaced with `os.getenv('GEMINI_API_KEY', '')`; literal also redacted from this document. External rotation still required by the key owner.
- [ ] P2: UC 3.2–3.3 / 3.5 / 3.8 — model catalog, tool architecture, errors, benchmarks.
- [x] P2 (scoped): UC 3.7 — Ollama `num_ctx` now matches the advertised context window (offline test). Token budgeting for long histories (UC 10.2) is also fixed; see the scoped UC 10.2 entry below.
- [x] P2 (scoped): UC 4.3 — phrase limit raised to 15 s on both listeners; CLI/GUI three-second overrides removed. Real microphone behavior unverified.
- [x] P2 (scoped): UC 4.4 — microphone construction and calibration are deferred until listening or explicit device setup. Both listeners initialize lazily, failed initialization is retryable, and failed device replacement preserves the previous device/index. Nine hardware-free regression tests cover these paths. TTS still initializes at startup; live audio and concurrent device-switch/listen behavior remain unverified.
- [ ] P2: UC 4.1–4.2 — playback completion and offline voice/wake word remain open.
- [x] P2: UC 8.3 — compound durations sum full tokens (e.g. 1 hour 30 minutes = 90 minutes); malformed input rejected.
- [x] P2: UC 8.4 — saved/displayed recurring deadlines match the instance-owned library job and are updated together after execution.
- [x] P2: UC 8.5 — task storage defaults to `%APPDATA%\Jarvis\scheduled_tasks.json` (home fallback), independent of CWD.
- [ ] P2: UC 8.1 / 8.6 — the separate JARVIS alarm threads still need persistence; GUI reminder delivery/voice-toggle integration remains open.
- [x] P2 (scoped): UC 9.1 — search resilience: Google 200-response CAPTCHA/block pages (429/503, `/sorry/`, captcha, "unusual traffic") are detected and trigger the DuckDuckGo fallback; DDG results unwrap `uddg=` redirect links to real URLs (protocol-relative `//` handled); a DDG block or non-200 returns honest manual-search links; network failure reports no results. Five offline tests with canned HTML; live engine behavior unverified. Voice summaries (UC 9.3) remain open.
- [x] P2 (scoped): UC 11.3 — `kill_process` matches exact case-insensitive executable names (optional `.exe`), rejects blanks/paths/wildcards, skips self and PIDs 0/4, reports access-denied. Graceful terminate()/confirmation and UC 11.2 tool consolidation remain open.
- [ ] P2: UC 12.1–12.6 / 1.4 / 1.6 — dependencies, launch/build/config docs, offline tests, logging. (Partial: `launcher.bat` points at the real `dist\JARVIS.exe`, `_pyibuild/` gitignored, offline test suite grown; README/SETUP_GUIDE drift, Python-version docs, and logging remain.)
- [ ] P2: UC 13–14 — deterministic workflows and native Windows integrations; require live acceptance tests.


### Follow-up reliability batch

- [x] UC 7.1 / 7.4 (scoped): file skill defaults to `~/Documents` with a home fallback; changing the skill directory no longer changes process CWD. Windows redirected Known Folders are not yet resolved.
- [x] UC 7.3: both creation methods retain pending target/content; yes/cancel confirmation now runs before AI classification. Tests cover cancellation, expiry, external content changes, unrelated turns, wrong filenames, directory changes, and Unicode content. This is not an OS-level atomic compare-and-write guarantee against concurrent external writers.
- [x] UC 10.4: one persisted preference feeds Settings, chat-stated location, AI memory, and weather. Legacy memory locations are ignored; clear/reload cannot resurrect them. Failed saves retain the previous runtime preference; failed auto-detection asks for a city instead of inventing one.
- [x] UC 4.3: command listeners allow 15-second phrases by default; CLI and GUI no longer override this with three seconds. Actual microphone behavior is unverified.
- [x] UC 11.3 (selection only): process termination uses exact case-insensitive executable names (optional `.exe`), rejects blanks/paths/wildcards, and skips self/system PIDs 0 and 4. Permission/confirmation design remains open; this is not comprehensive critical-process protection.
- [x] UC 10.2 (scoped): request history is bounded by the model's context window before sending. `MultiModelBrain._history_budget` reserves headroom from the advertised context window and `_history_window` packs the newest prior turns under that character budget; the raw `[-8:]` slice is applied in the window itself. Wired into all three history-sending call sites (OpenRouter, Gemini, Ollama; the demo provider sends no history). Invalid or missing context windows fall back to a 8192-token default, with a floor to keep at least one small turn eligible. Four tests: budget computation with defaults/fallbacks, newest-first packing within budget, oversized-turn drop with order preserved, and an end-to-end OpenRouter request asserting oversized turns are excluded and the budget holds. This is a character-budget approximation (≈4 chars/token), not exact tokenization; the system prompt is sent outside the budget and untested providers beyond these three would not be covered.
- [x] Latest validation: `python -B -m unittest discover -s tests` passed **91 tests**; `git diff --check` passed. The production-import smoke test runs the real LangChain executor with a scripted brain and real FileManagerSkill/UtilitySkill instances, verifying the create-file → rename-file → flip-coin intermediate tool sequence, actual temporary-file contents, successful tool observations, and their inclusion in the next model prompt. History-budget tests cover helper math, packing order, oversized-turn drops, and the real OpenRouter request path. Search-resilience tests use canned Google-CAPTCHA and DuckDuckGo HTML; no live engine, provider, microphone, or GUI was exercised. Unused desktop dependencies are mocked. Python 3.14/Pydantic compatibility and deprecation warnings remain.
- [x] Agent dependency compatibility (scoped): imports now use `langchain_classic.agents` and `langchain_core.tools`; requirements declare langchain-classic>=1.0.8,<2 and compatible major-version bounds for LangChain/core. Installed langchain-classic 1.0.8 and langchain-text-splitters 1.1.2; production import and real-executor smoke test pass with LangChain 1.4.0, core 1.6.3, and Pydantic 2.12.5. Escaped JSON examples prevent prompt-template missing-input errors. This does not validate every tool, live model behavior, or the complete dependency set on a clean installation.
- Scheduler limitations: overdue tasks (including recurring tasks) load as `missed`; interrupted tasks load as `interrupted`. Neither auto-executes: explicitly create a new schedule. JARVIS must remain running for delivery. Old project-local `scheduled_tasks.json` is not automatically migrated; recreate schedules or explicitly supply a reviewed legacy file via the constructor. Use one application instance per storage file: cross-process locking is not implemented. Corrupt storage raises an error rather than silently replacing user data. Local naive datetimes are retained; timezone/DST transitions are not validated. Cancellation cannot interrupt an already executing action.
- Test-isolation caveat: an earlier location test wrote `Bristol` to production `memory/memory.json`. Tests now use a fresh temporary memory directory each time; the final full suite left production memory byte-for-byte unchanged. The pre-test location is unknown, so the existing value was not deleted or replaced.


Only checked items are complete for the stated scope. Offline tests do not establish
live provider, microphone, GUI, or operating-system integration correctness.


This is a line-by-line re-verification of the previous audit against the actual code in `D:\jarvis\jarvis` today. Every UC below was re-checked; line numbers are current. Tags:

- **[CONFIRMED]** — read the exact code, bug is real as described.
- **[CONFIRMED+]** — real, and worse/broader than originally described (details below).
- **[CORRECTED]** — the original claim was wrong or stale; current code does something different (in some cases, better).
- **[RISK]** — plausible failure mode inferred from the code path, not exercised at runtime.
- **[NEW]** — not in the original audit; found during this verification pass.

---

## 0. Corrections to the previous audit (read this first)

These change the overall picture and are easy to miss if you only skim the UC list below.

### 0.1 — YouTube/browser deep-linking already exists (previous UC 13.1/13.2 were stale)
The old audit said there was "no deep-link composition" for things like *"go to YouTube and play a video from Michael Jackson"* and that the embedded browser's JS bridge was "unused in automation flows." **That's no longer true.** `skills/app_control.py:140-350` (`launch_app_by_name`) already:
- Maps common sites (`_SITE_MAP`, lines 11-30) including YouTube, Google, Reddit, Spotify, etc.
- Strips navigation prefixes ("go to", "navigate to", …) at lines 155-159.
- Extracts an action clause ("... and play X" / "... then search Y") via regex at lines 161-166 and 187-196.
- For YouTube specifically, builds a search URL and injects JS to auto-click the first video result after load (lines 199-206):
  ```python
  found_url = f"https://www.youtube.com/results?search_query={encoded}"
  then_js = "setTimeout(function(){ var v=document.querySelector('ytd-thumbnail a, a#video-title'); if(v){v.click();} }, 2500);"
  ```
- `open_url(url, then_js)` (lines 129-138) routes through `ApplicationControl._browser_callback` if one is registered, else falls back to the system default browser.
- `main_gui.py:544-716` has a fully working `BrowserWindow` (QWebEngineView-based) with `navigate`, `navigate_then_js`, and `run_js`.
- `main_gui.py:752-753` wires it up: `self.jarvis.app_control.set_browser_callback(self._on_browser_open)`, and `_on_browser_open`/`navigate_browser_with_js` (lines 1223-1257) marshal the call onto the Qt main thread via signals (`_browser_open_js`, lines 722-723) — this is done correctly (thread-safe), not naively.

So "open chrome, go to YouTube and play a video by Michael Jackson" — the *"go to YouTube and play X"* portion is now handled close to the spec the old audit proposed. What's still genuinely missing: verifying playback actually started (no SMTC / media-session check — see §14.1), and the "open chrome" prefix is a separate app-launch that doesn't compose with the browser navigation (see UC 13.1 below, revised).

### 0.2 — ~900 lines of jarvis.py are unreachable dead code, and it's worse than "some legacy handlers"
The old UC 2.5 said `_get_ai_response` (jarvis.py) returns before ~250 lines of legacy handling. Re-reading the whole file: **the dead block is actually jarvis.py:1231-2129 (≈900 lines, ~37% of the file's line count)**, all sitting inside `_get_ai_response(self, prompt)` after its `try/except` already returns unconditionally in every branch (line 1230 is the last reachable statement). Concretely:

```python
def _get_ai_response(self, prompt):          # jarvis.py:1218 — only parameter is `prompt`
    try:
        ...
        return ...
    except Exception as e:
        console.print(...)
        return "I'm sorry, I couldn't process that request."   # line 1230 — always returns here on error
        examples = """..."""                                    # line 1231 — dead, and also references
        if use_voice:                                            # `command` / `use_voice`, which are NOT
            ...                                                  # parameters of this method — a NameError
    # ... (unreachable) file creation, rename, alarms, compound-command
    # processing, model management, greetings, math fallback, "clear history" —
    # all the way to line 2129, then `_fallback_brain` / `run_text_mode` / `main()` resume
```
Even if a future refactor made this block reachable, it would immediately crash with `NameError: name 'command' is not defined` (and `use_voice`), because those names belong to `process_command`, not `_get_ai_response`. This isn't just legacy cruft — it's proof this whole tail of the file has not executed, at all, since whatever refactor split these methods apart.

**Direct consequence — [NEW]: `CommandProcessor` (skills/command_processor.py) is completely orphaned.** Its only call site anywhere in the codebase is inside this dead block:
```
jarvis.py:2073   steps = self.command_processor.parse_complex_command(command)
jarvis.py:2083   results = self.command_processor.execute_parsed_commands(steps, use_voice)
```
`self.command_processor` is constructed in `__init__` (jarvis.py:112) and put in `self.skills['command_processor']` (jarvis.py:184), so it shows up as "Active" in the GUI's Skills tab — but it is never invoked by anything reachable. "Then/and then" compound commands are **not** actually decomposed by this processor; they either get misrouted by the classifier (UC 2.1/2.2) or fall through to the LangChain agent (§0.3).

Even if `CommandProcessor` were rewired to a reachable call site, it has its own latent bug: `_execute_complex_task` (skills/command_processor.py:492) does `from skills.visual_task_orchestrator import process_visual_task` — that module was deleted in the prior refactor (see project memory) — so this branch always raises `ImportError`, silently caught by its own `except Exception` (line 506) and turned into a generic failure string. Dead code calling a module that no longer exists.

Also dead as a result: the AI model management commands ("list models", "switch model X", "benchmark models", "model stats", "smart model"), the simple-greeting/math/"clear history" text fallbacks, "system report", the two hardcoded "screenshot → calculator → type 2+2" demo sequences, and most of the `launch `/`open `/`close app`/file-management/task-scheduling handling that the old audit quoted as UC 7–9 fallbacks. None of that code runs. (Equivalent functionality for *some* of these — file creation, app launch, weather — is still reachable via the classified-intent path in `_handle_classified_command`, or via the LangChain agent's tools; see the per-UC notes below for which is which.)

### 0.3 — The real "whole-laptop" fallback path is a LangChain ReAct agent, and it changes the risk picture for UC 11.1
When a command doesn't match the classifier's short list or an explicit prefix, `process_command` (jarvis.py:396-398) does:
```python
if self.agent_available and hasattr(self, 'agent'):
    response = self.agent.run(original_command)
```
`self.agent` is `AgentOrchestrator` (agents/orchestrator.py), a LangChain `ZERO_SHOT_REACT_DESCRIPTION` agent wired to ~30 `Tool`s, **including**:
```python
Tool(name="run_command", func=self.system_control.run_command,
     description="Run a system command and return output. Use carefully.")
```
`SystemControl.run_command` (skills/system_control.py:503-516) is `subprocess.run(command, shell=True, ...)` with **no allowlist, no confirmation, no logging**. `Config.SECURITY["restricted_paths"]` (core/config.py:189) is defined but — confirmed by grep — **referenced nowhere else in the entire codebase**. So this isn't a hypothetical risk gated behind enabling tool-calling in the brain (UC 3.3); if `agents/orchestrator.py` imports successfully (i.e., `langchain` is installed — `AGENT_AVAILABLE`, jarvis.py:29-37), **arbitrary shell execution is already one LLM decision away from any natural-language prompt today.** A prompt-injected web page (via `web_search`/`search_web`, also a tool) or a jailbreak in chat is a viable path to this.

If `langchain` is *not* installed, `AGENT_AVAILABLE=False` and everything silently downgrades to `_fallback_brain` → `brain.process_command(command, skills=self.skills)` — a plain chat completion with `skills` passed in but never used (no model has `supports_tools: True`, see UC 3.3), so the assistant will *describe* doing things without doing them, with no error surfaced to the user either way. This single import success/failure silently flips the app between "can execute arbitrary shell commands from chat" and "can't actually do anything, just talks." `requirements.txt` pins `langchain>=0.0.444`; `requirements_exe.txt` doesn't include `langchain` in its core list at all (only under "Optional"), so the EXE build likely ships in the *second* mode without anyone deciding that on purpose.

---

## 1. Startup & Initialization

### UC 1.1 — Launch GUI (`main_gui.py`) [CONFIRMED, lines updated]
`MainWindow.__init__` (main_gui.py:725) constructs `JARVIS()` at line 734 — *before* `setup_ui()` (747), `setup_menus()` (748), `refresh_models()` (749), and the Ollama-manager kickoff (762) all run. Every skill's `__init__` (registry scan for `_get_installed_applications`, mic calibration in `VoiceEngine`, `TaskScheduler`'s background thread) executes synchronously on the GUI thread with zero splash/progress UI. The window object doesn't even exist yet at this point (it's created via `super().__init__()` at line 726, but nothing is shown until `main()` calls `win.show()` — main_gui.py:1822).
**Fix unchanged:** move `JARVIS()` construction to a `QThread`/`QTimer.singleShot`, show the window first with a "Starting…" state.

### UC 1.2 — No API keys configured [CONFIRMED, exact lines match]
`MultiModelBrain._initialize_providers` (core/brain.py:320-352): when `OPENROUTER_API_KEY` is unset, it still populates `available_models` with both OpenRouter configs, just appending `" (requires API key)"` to the description (lines 329-334). `_set_default_model` (386-406) will happily select one of these as `current_model` if nothing else qualifies.

### UC 1.3 — Demo model as false fallback [CONFIRMED, exact lines match]
core/brain.py:345-352 — if `available_models` is empty after providers init, a `"demo-model"` entry is injected so `current_model` is never `None`. `_process_demo` (brain.py:650-659) returns canned strings like *"This is a demo model. Add API keys in Settings for real AI models."* — this is what a fresh user's first message gets routed to.

### UC 1.4 — Python version compatibility [CONFIRMED, exact line]
`core/config.py:35`: `def save_api_keys(openrouter_key: str | None, gemini_key: str | None):` — PEP 604 syntax, requires Python ≥3.10. README/SETUP_GUIDE still advertise 3.8 support (unverified in this pass, but the syntax fact is confirmed).

### UC 1.5 — Signal handlers in a GUI app [CONFIRMED]
`JARVIS.__init__` (jarvis.py:190-191) calls `signal.signal(SIGINT, ...)` / `signal.signal(SIGTERM, ...)` unconditionally, including when constructed from `main_gui.MainWindow.__init__` (main_gui.py:734). No effect in a windowed/noconsole EXE except polluting the main thread's signal table.

### UC 1.6 — [NEW] `config_user.py` doesn't exist; only `config_template.py` ships
`core/config.py:6-11` does `from config_user import *` at import time, wrapped in `try/except ImportError` (so it's non-fatal), but the repo only ships `config_template.py` at the root — there is no `config_user.py`, and nothing in the app creates one automatically. A user following naive instructions ("edit config_user.py") will silently get no effect from the import (ImportError swallowed), and never learn their edits aren't being read unless they know to copy `config_template.py → config_user.py` first. This is the same class of drift as UC 12.2/12.4 below, just one file over.

---

## 2. Command Routing (the core loop)

### UC 2.1 — Every message costs two LLM calls minimum [CONFIRMED, exact lines]
`process_command` (jarvis.py:339) calls `_classify_command_intent` (235) before any handler. The classification prompt goes through `self.multi_brain.process_command(classification_prompt, use_context=False)` (jarvis.py:260) → `MultiModelBrain.process_command` (brain.py:499-532) which **always** appends both the prompt and the reply to `self.conversation_history` (brain.py:510-512, 528-530) and persists it (`_save_history`, line 531) regardless of `use_context`. Every classification round-trip is written into `logs/conversation_history.json` and later replayed as real conversation turns (brain.py:557: `for msg in self.conversation_history[-8:]`).

### UC 2.2 — The prompt says 10 categories, handlers support 12 [CONFIRMED, exact lines]
Classifier prompt (jarvis.py:239-256) offers `AUTOMATION/APP/WEATHER/SEARCH/MATH/TIME/SYSTEM/FILE/UTILITY/GENERAL` — no `EXIT`, no `SCREEN_AUTOMATION`. `_handle_classified_command` (jarvis.py:287-337) has live branches for both `EXIT` (290) and `SCREEN_AUTOMATION` (334-335) that the classifier can never produce, since `valid_categories` (line 270) doesn't include them either.

### UC 2.3 — Weather ignores the requested city [CONFIRMED, exact lines match the old audit]
`_handle_classified_command` WEATHER branch (jarvis.py:311-317):
```python
elif intent == 'WEATHER':
    result = self.weather_skill.get_weather()
```
No argument passed. `WeatherSkill.get_weather(self, query="")` (skills/weather.py:11-25) calls `_extract_city_from_query("")` → empty → falls to `_get_auto_location()` (line 40), which checks `JARVIS_LOCATION` env var first (line 45, correctly wired to the Settings dialog — see §0's location note below), then IP geolocation, then defaults to `"Chennai"` (line 94). **"What's the weather in London?" always returns the configured default location, never London**, because the city was already parsed by the classifier and then thrown away.

### UC 2.4 — Handlers return inconsistent types [CONFIRMED, lines updated]
- `_handle_system_commands` (jarvis.py:614-734): every branch calls `return response`/`return result` with a string **except** the disk-usage branch (726-732), which does `console.print(Panel(...))` then `return True` (line 732) — the GUI's `JarvisWorker` will emit `True` (a bool) as the chat response, which `append_text` will stringify as the literal text "True".
- `_handle_file_commands` (jarvis.py:912-915) is a one-line stub: `return False` — always. So the classifier's `FILE` category is decorative; every file-intent command falls through to the agent orchestrator (§0.3) regardless of what the AI classified it as.
- `_handle_search_commands` (jarvis.py:736-766) always `return True` (line 766), same "True" leaks to chat.
- `_handle_screen_automation_commands` (jarvis.py:1075-1137) returns `True` in all three exit paths (1124, 1130, 1137).
**Fix unchanged:** standardize on "return the response string, or `None`/falsy if unhandled."

### UC 2.5 — see §0.2 above (massively expanded from the original)

### UC 2.6 — Sleeping swallows commands silently [CONFIRMED, exact lines]
jarvis.py:361-368 sets `is_sleeping=True` and jarvis.py:381-382 `return`s `None` with no reply while sleeping. Also: "sleep"/"standby"/"go to sleep" (line 361) and "quit"/"exit"/"goodbye"/"shutdown jarvis" (line 351) are checked with `any(word in command ...)` **before** intent classification — plain substring containment, so "don't go to sleep yet" and "how do I quit smoking" both fire.

### UC 2.7 — Exit keywords fire on substrings [CONFIRMED, exact line]
jarvis.py:351: `if any(word in command for word in ["goodbye", "exit", "quit", "shutdown jarvis"])`. This check happens at the very top of `process_command`, before classification, before the sleep check. Any message containing "quit" or "exit" anywhere in the string calls `self.shutdown()` (jarvis.py:357) → `sys.exit(0)` (jarvis.py:2414) in CLI mode. In the GUI it runs inside `JarvisWorker` (a `QThread`), so `sys.exit()` there raises `SystemExit` inside the worker thread rather than killing the whole app — worth independently verifying which behavior you actually see, but either way the intent-classification safety net is bypassed entirely.

---

## 3. AI Providers (core/brain.py)

### UC 3.1 — Duplicate user message in context [CONFIRMED, exact lines]
`process_command` appends the user command to `conversation_history` at brain.py:510-512, then `_process_openrouter` builds `messages = [system] + history[-8:] + [{"role":"user","content":command}]` (brain.py:554-560) — since `command` is already the tail of `history` (appended two lines above at the call site), it appears **twice** in the last two positions of every OpenRouter/Ollama request. Same shape in `_process_gemini` (634-642: history includes the just-appended user turn, then `chat.send_message(command)` sends it again) and `_process_ollama` (671-683).

### UC 3.2 — Model list contains non-existent models [RISK, exact lines]
brain.py:298-313 hardcodes `"nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"` and `"google/gemma-4-31b-it:free"` as the only two OpenRouter entries. These IDs are not verified against OpenRouter's catalog in code; a bad ID surfaces as a raw `"OpenRouter error 404: ..."` string shown as the chat reply (see UC 3.5).

### UC 3.3 — Tool calling effectively disabled [CONFIRMED, exact lines — see also §0.3 for why this matters less than it looks]
`supports_tools = config.get("supports_tools", False) and bool(skills)` (brain.py:545). Both OpenRouter model configs explicitly set `"supports_tools": False` (brain.py:303, 311); Gemini/Ollama/demo configs don't set the key at all (defaults to `False`). So `JARVIS_TOOLS`/`_execute_tool` (brain.py:101-260, 426-473) is dead weight for every text-chat and voice-chat path today — `VoiceChatWorker._process_command_with_skills` (main_gui.py:380-385) *does* pass `skills=self.skills` into `brain.process_command`, but the gate still kills it before any tool schema reaches the API. The equivalent capability (open apps, get weather, take screenshots, etc. from natural language) is instead provided by the **separate** LangChain agent (§0.3) — so "fixing" this gate would introduce a second, parallel tool-execution path rather than turning on the only one.

### UC 3.4 — `clear_history` doesn't clear persisted history [CONFIRMED, exact lines]
`MultiModelBrain.clear_history` (brain.py:716-718) does `self.conversation_history.clear()` and returns a string — never touches `self._history_file` (`logs/conversation_history.json`). `MainWindow.on_clear` (main_gui.py:1486-1489) calls `self.brain.clear_history()` then `self.transcript.clear()` — the on-screen chat empties, but `_load_history` (brain.py:408-414) will restore the "cleared" conversation from disk on the next launch, and worse, **the very next message** re-appends onto the still-populated (in different object, but same file) history the next time `_save_history` runs after `_load_history` was called freshly — this is cosmetic only within the current process.

### UC 3.5 — Error text spoken aloud / treated as answers [CONFIRMED]
Every provider method (`_process_openrouter`, `_process_gemini`, `_process_ollama`) returns raw error strings on failure (e.g. brain.py:574, 578, 580, 612, 617, 648, 697, 699) which flow straight back through `process_command`'s `reply` variable, get appended to `conversation_history` as an `"assistant"` turn (brain.py:528-530), and are spoken via TTS by whichever caller invoked it with `use_voice=True`.

### UC 3.6 — No timeout on OpenRouter/Gemini calls [CONFIRMED, exact line]
`_req.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body)` (brain.py:572) — no `timeout=`. The follow-up tool-call request (brain.py:602-606) also has no timeout. `_process_gemini`'s `chat.send_message` (brain.py:642) has no timeout either. Only `_process_ollama` sets one (`timeout=120`, brain.py:693). A hung OpenRouter/Gemini call freezes the `JarvisWorker` QThread indefinitely; `on_send` (main_gui.py:1407-1409) will call `.terminate()` on it if the user sends another message (see UC 5.2).

### UC 3.7 — Ollama num_ctx mismatch [CONFIRMED, exact lines]
brain.py:379 advertises `"context_window": 8192` for discovered Ollama models; `_process_ollama` sends `"options": {"num_ctx": 4096}` (brain.py:691). Long conversations silently truncate at half the advertised window.

### UC 3.8 — `benchmark_models` is a stub [CONFIRMED, exact lines]
brain.py:725-728 — literal placeholder string. Also unreachable from the GUI/CLI text flow per §0.2 (the only caller was in the dead block, jarvis.py~1326-1341); still callable directly as `self.brain.benchmark_models(...)` if something else called it, but nothing currently does.

---

## 4. Voice (core/voice.py)

### UC 4.1 — TTS plays only ~5 seconds of long replies [CONFIRMED, exact lines]
`_speak_edge_tts` (voice.py:113-151): when `playsound` isn't available, falls back to a PowerShell one-liner (voice.py:132-140) that does `$p.Play(); Start-Sleep -s 5` — a hardcoded 5-second sleep regardless of clip length, then the temp `.mp3` is deleted (voice.py:142-143) potentially while still playing. Note: `playsound==1.2.2` **is** pinned in requirements.txt, so on a machine with that dependency actually installed, this fallback path isn't hit — but if `playsound` fails to import for any reason (it's a notoriously fragile package on Windows), every long reply gets cut at 5s.

### UC 4.2 — Wake word requires Google connectivity per ~1s poll [CONFIRMED, exact lines]
`listen_for_wake_word` (voice.py:285-309): `self.recognizer.listen(source, timeout=1, phrase_time_limit=3)` (line 294) then `recognize_google` (line 297) — a network round trip roughly every second while idle in voice mode. `wake_word in command` (line 298) is plain substring containment against `Config.WAKE_WORD = "jarvis"` (config.py:114).

### UC 4.3 — `phrase_time_limit=1` in `listen_for_command` [CONFIRMED, exact line]
voice.py:205: `def listen_for_command(self, timeout=5, phrase_timeout=1):` — default 1-second phrase limit, called with these defaults from `MicrophoneSettingsDialog.test_microphone` (main_gui.py:516: `self.voice_engine.listen_for_command(timeout=5)`, using the 1s phrase default) and from `run_voice_mode` with an explicit override (`timeout=10, phrase_timeout=3`, jarvis.py:2372) — so the *voice-mode* path already overrides this to something more usable; it's the microphone-test dialog and any other unqualified caller that gets cut off at 1s.

### UC 4.4 — Calibration at import time on machines without mics [CORRECTED — softer than originally stated]
`VoiceEngine.__init__` (voice.py:29-48) does construct `sr.Microphone()` and call `self.calibrate_microphone()` unconditionally when a mic is present (lines 35-40). However, both the microphone construction (35-44) and `calibrate_microphone` itself (voice.py:192-203) are wrapped in `try/except Exception`, so on a genuinely mic-less machine this degrades to `self.sr_available = False` with a printed warning (line 43) rather than crashing. On a machine *with* a mic device present but no working audio backend (common on RDP), `sr.Microphone()` may succeed but block or throw during the actual `adjust_for_ambient_noise` call inside `calibrate_microphone` (voice.py:198-201) with no timeout — this can still add real startup latency even though it won't hard-crash.

---

## 5. GUI (main_gui.py) — line numbers below all reconfirmed against the current 1827-line file

### UC 5.1 — Pause/Resume task queue do nothing [CONFIRMED, exact lines]
`pause_task_queue` (main_gui.py:1783-1785) and `resume_task_queue` (1787-1789) each only append one line to `task_execution_log`. There is no queue object anywhere in the class. `execute_complex_task` (1753-1766) calls `self.jarvis.process_command(task)` **directly on the GUI thread** (line 1762) — not via `self.worker` — so it blocks the whole window for the task's duration; `task_queue_list.addItem(...)` (1761) is just a static log entry, never dequeued.

### UC 5.2 — `worker.terminate()` misuse [CONFIRMED, exact lines]
`on_send` (main_gui.py:1407-1409):
```python
if self.worker.isRunning():
    self.worker.terminate()
    self.worker.wait(1000)
```
Same pattern in `closeEvent` (1802-1804). `QThread.terminate()` can kill mid-syscall (e.g. mid-`requests.post`), leaking sockets/locks with no cleanup.

### UC 5.3 — Automation tab buttons route through full NLU [CONFIRMED, exact lines]
`take_screenshot_and_analyze` (1696-1706), `analyze_current_screen` (1708-1717), `execute_visual_task` (1719-1730), `discover_applications` (1732-1741), and `launch_application_dialog` (1743-1751) all call `self.jarvis.process_command("<english sentence>")` instead of invoking `self.jarvis.screen_automation`/`self.jarvis.app_control` methods directly. `discover_applications`'s prompt — *"discover available applications"* — matches no classifier category and no explicit prefix, so (per §0.2/§0.3) it lands on the LangChain agent, which has no `discover_applications`-shaped tool; closest is `list_installed_apps`, so results depend entirely on the agent's ReAct reasoning picking the right tool from a natural-language button click.

### UC 5.4 — Plan/pause buttons fabricate results [CONFIRMED, exact lines]
`plan_task_steps` (main_gui.py:1768-1781) sends `f"Plan the steps needed to complete this task without executing them: {task}"` through `self.jarvis.process_command(...)` and prints whatever comes back as "Plan:". No planner/orchestrator structure exists — it's one LLM guess, unlabeled as such in the log except for the surrounding UI chrome.

### UC 5.5 — Settings only cover 2 providers + location [CONFIRMED, exact — full file reviewed]
`ui/settings.py` is 76 lines total: `SettingsDialog` has exactly three fields — OpenRouter key, Gemini key, location (lines 12-25) — and that's the entire dialog. No Ollama toggle, no wake-word field, no voice rate/volume, no safe-mode/automation-confirmation toggle, despite all of `AUTOMATION_SAFE_MODE`, `AUTOMATION_CONFIRMATION_REQUIRED`, `VOICE_RATE`, `WAKE_WORD` existing as `Config` attributes (core/config.py:114, 120-121, 127).

### UC 5.6 — Skills tree test doesn't test automation skills [CONFIRMED, exact lines]
`test_selected_skill` (main_gui.py:1525-1543): real calls only for `weather` (1534), `utility` (1536), `system_monitor` (1538); every other entry — `file_manager`, `automation`, `app_control`, `command_processor`, `task_scheduler`, `screen_automation` — hits the `else` branch (1539-1540): `result = f"{name} skill is available"`. `test_all_skills` (1545-1549) loops this over every skill, so "Test All" always reports full green regardless of whether e.g. `screen_automation`'s vision API key is even configured.

### UC 5.7 — [NEW] `on_send`'s worker replacement leaks the old worker's signal connections
`on_send` (main_gui.py:1411-1416) creates a brand-new `JarvisWorker` and reconnects `response_ready`/`error_occurred`/`status_update` every single call, but never disconnects the previous worker's signals before it's terminated/discarded. In practice `.terminate()`+`.wait(1000)` (1408-1409) usually reaps it fast enough that this doesn't visibly double-fire, but it's relying on timing, not an explicit disconnect — a slow terminate (e.g. mid network call, see UC 3.6) can leave a stale worker object referencing an old `self.jarvis`/`self.skills` snapshot alive briefly alongside the new one.

---

## 6. Automation & Screen Control (skills/screen_automation.py, skills/app_control.py)

### UC 6.1 — New skill instances bypass shared state [CONFIRMED, exact lines]
`_handle_automation_commands` (jarvis.py:936-937: `automation = ScreenAutomationSkill()`) and `_handle_screenshot_command`/`_handle_click_command` (jarvis.py:1143, 1171) construct **fresh** `ScreenAutomationSkill()` instances instead of `self.screen_automation`. Each fresh instance re-runs `setup_emergency_stop()` (screen_automation.py:86-99), registering a new global `pynput.keyboard.GlobalHotKeys` listener for Ctrl+Shift+Esc every time — old listeners are never `.stop()`'d (no reference kept), so repeated automation commands leak hotkey listener threads. Also, `automation_history` (per-instance list) fragments across instances, so `get_history()`/`clear_history()` calls made against `self.screen_automation` never see what the ad-hoc instances did.

### UC 6.2 — `_confirm_action` checks a nonexistent attribute [CONFIRMED, exact lines]
`_confirm_action` (screen_automation.py:714-738): `if self.jarvis and hasattr(self.jarvis, 'gui')`. Verified against `jarvis.py`'s `JARVIS.__init__` (lines 59-193) — there is no `self.gui` attribute anywhere on the class; `MainWindow` (main_gui.py) holds `self.jarvis = JARVIS()` (the reference goes the *other* direction — GUI → JARVIS, never JARVIS → GUI). So `hasattr(self.jarvis, 'gui')` is always `False`, and every confirmation falls to `input(...)` (screen_automation.py:733) — a blocking console read that, when this runs inside a GUI worker thread, blocks that thread invisibly (no dialog appears, no error — the app just looks frozen on that step).

### UC 6.3 — `typewrite` vs Unicode [CONFIRMED, exact line]
`_execute_type` (screen_automation.py:660-670): `pyautogui.typewrite(text, interval=interval)` (line 666) — will raise/skip characters outside the ASCII keyboard-mappable set. Note `core/brain.py`'s separate `_tool_type_text` (brain.py:77-95) already does the correct thing (clipboard + Ctrl+V) but that's a different, currently-unreachable code path (UC 3.3) — the fix already exists in the codebase, just not wired to `screen_automation.py`.

### UC 6.4 — Goal-achieved detection is keyword folklore [CONFIRMED, exact lines]
`_check_goal_achieved` (screen_automation.py:831-852): matches `success_keywords = ['completed', 'finished', 'done', 'success', 'opened', 'loaded']` against the vision model's own description text (line 848), intersected with words from the goal string (line 840). This is the vision model grading its own homework via keyword overlap, not a state check.

### UC 6.5 — Screenshot coordinate scaling [CONFIRMED, exact lines]
`_adjust_coordinates_for_accuracy` (screen_automation.py:854-896) hardcodes a menu-word list (`['file', 'edit', 'view', 'help', 'terminal', 'run']`, line 867) and nudges X by `max(5, text_length)` pixels (line 886) — a heuristic guess, not DPI/scale-aware. `_validate_coordinates` (898-914) only clamps to screen bounds, doesn't correct for a screenshot taken at a different logical/physical pixel ratio than what the vision model assumes.

### UC 6.6 — [NEW] Hardcoded Gemini API key in source
`screen_automation.py:330`: `gemini_key = 'AIzaSy…[REDACTED — see remediation status at top]…'` — a live-looking Google API key was hardcoded directly in the source file (`_query_gemini_vision`), not read from `Config`/env. If a key like this is real and the file is ever pushed to a public repo, it should be treated as compromised and rotated immediately. Even if it's a dead/quota-zero placeholder, hardcoding secrets in source is the wrong pattern regardless — it should read `os.getenv("GEMINI_API_KEY")` like every other provider call in the codebase does. *(Remediated: source now reads the env var; the literal was also removed from this document. If this key was ever real, rotate it in Google AI Studio regardless of this cleanup, since it existed in file history.)*

---

## 7. Files (skills/file_manager.py)

### UC 7.1 — Files are created in the app directory [CONFIRMED, exact lines]
`FileManagerSkill.__init__` (file_manager.py:6-10): `script_dir = Path(__file__).parent.parent.absolute(); self.current_directory = str(script_dir)` — resolves to `D:\jarvis\jarvis` (the app's own root, parent of `skills/`). `create_file("notes")` → `D:\jarvis\jarvis\notes.txt`. In a frozen/installed EXE, this directory is typically not user-writable.

### UC 7.2 — Filename cleaning destroys intent [CONFIRMED, exact lines]
`_clean_filename` (file_manager.py:348-361) replaces `<>:"/\\|?*` and spaces with `_` (lines 354-359) — "notes/2024.txt" → "notes_2024.txt"; no subfolder creation is possible through a path-shaped filename.

### UC 7.3 — "Overwrite?" prompt is never answered [CONFIRMED, exact lines]
`create_file` (file_manager.py:72-101) returns `f"File '{filename}' already exists. Would you like me to overwrite it?"` at line 86 (and `create_file_at_location`, line 130, has the identical pattern) — grepped the codebase for any handling of a "yes"/"overwrite" follow-up referencing this: none exists.

### UC 7.4 — `change_directory` mutates process CWD [CONFIRMED, exact lines]
`change_directory` (file_manager.py:325-342): `self.current_directory = str(new_dir); os.chdir(self.current_directory)` (line 337) — global process CWD change, affecting `TaskScheduler`'s relative `scheduled_tasks.json` path (UC 8.5) and `_perform_backup`'s relative `Path("backups")` (task_scheduler.py:266) in the same process.

### UC 7.5 — [NEW] `_perform_backup` silently skips the files it claims to back up
`TaskScheduler._perform_backup` (task_scheduler.py:259-288) backs up `important_files = ["config.py", "jarvis.py", "*.txt"]` (line 270). `config.py` doesn't exist at the repo root — it's `core/config.py` — so `Path("config.py").exists()` (line 281) is always `False` and that "important file" is silently never backed up. `jarvis.py` does exist at root and would be backed up correctly, assuming CWD hasn't been moved by UC 7.4.

---

## 8. Scheduling & Alarms (jarvis.py `_set_alarm`, skills/task_scheduler.py)

### UC 8.1 — Alarms lost on restart; sleeping thread per alarm [CONFIRMED, exact lines]
`_set_alarm` (jarvis.py:846-910): spawns `threading.Thread(target=_ring, daemon=True)` (line 902) that does `time.sleep(seconds_until)` (line 894) inside `_ring`. Nothing is persisted — closing the app loses the alarm; each alarm is a parked thread for its full duration.

### UC 8.2 — Date rollover crash [CONFIRMED, exact line]
jarvis.py:877: `alarm_time = alarm_time.replace(day=now.day + 1)` — raises `ValueError: day is out of range for month` whenever `now.day` is the last day of the month (28/29/30/31 depending on month) and the requested alarm time has already passed today.

### UC 8.3 — `_parse_schedule_time` digit-scraping [CONFIRMED, exact lines]
task_scheduler.py:131 (`minutes = int(''.join(filter(str.isdigit, when)))`), 134, 137 — all three branches (minute/hour/day) do this. `"in 1 hour 30 minutes"` contains "hour" first in the `if/elif` chain (line 129-138 checks "minute" before "hour" — actually re-checking: line 130 checks `"minute" in when` first, and "in 1 hour 30 minutes" does contain "minute", so it takes the *minutes* branch and digit-scrapes `"130"` → schedules for 130 minutes from now, not 90). Either way, compound durations collapse into one wrong number.

### UC 8.4 — Recurring tasks: `next_run` field is disconnected from the `schedule` library's actual trigger [CONFIRMED, refined]
`_parse_schedule_time` for `"daily"` returns `now + timedelta(days=1)` (task_scheduler.py:154), stored as `task['next_run']` and shown verbatim by `list_scheduled_tasks` (line 94). Separately, `_add_to_scheduler` (174-192) registers the *actual* trigger with the `schedule` library via `schedule.every().day.do(...)` (line 180) with no `.at()` time — the `schedule` library computes its own real next-run time internally (typically ~24h from registration, not from whatever `next_run` says). **The UI-facing "Next run" timestamp and the library's real internal timer are two unrelated values that can drift apart**, so "list scheduled tasks" can show a next-run time that has nothing to do with when the task will actually fire. (The original audit's phrasing — "fires today" — overstates the specific failure mode; the confirmed, verifiable bug is the display/reality disconnect, not a guaranteed same-day fire.)

### UC 8.5 — `scheduled_tasks.json` relative path [CONFIRMED, exact line]
task_scheduler.py:18: `self.tasks_file = "scheduled_tasks.json"` — resolves against process CWD, movable by UC 7.4, and differs between `python jarvis.py`, `python main_gui.py`, and the frozen EXE's working directory.

### UC 8.6 — Scheduler reminder voice speaks to nobody [CONFIRMED, exact lines]
`_execute_task` reminder branch (task_scheduler.py:228-231): `self.jarvis.voice_engine.speak(...)` unconditionally — doesn't check the GUI's `btn_voice` toggle state (that state lives only in `MainWindow`, main_gui.py:884-889, never consulted by `TaskScheduler`) and the result string is never pushed into the GUI transcript (no signal/callback back to `MainWindow.append_text`).

---

## 9. Search & Web (skills/web_scraper.py, skills/web_search.py)

### UC 9.1 — Search results scraped from Google HTML [CONFIRMED, exact lines]
`WebScraperSkill.search_google` (web_scraper.py:18-...) builds `https://www.google.com/search?q=...` (line 22) and parses the raw HTML response with BeautifulSoup using selector guesses (`div.g`, `div.tF2Cxc`, etc., lines 35-40) that Google changes without notice; there's a `time.sleep(random.uniform(1,3))` (line 25) to look less bot-like, but no CAPTCHA/block detection or fallback messaging. `Config.BRAVE_API_KEY` (core/config.py:208) is defined but grepped nowhere else in the codebase — confirmed unused.

### UC 9.2 — `_handle_search_commands` returns `True`, not the result [CONFIRMED — see UC 2.4]

### UC 9.3 — Voice reads raw scraped text [CONFIRMED, exact lines]
jarvis.py:756-763 (inside `_handle_search_commands`) takes `result.split('\n')[:5]` for voice output when the result exceeds 500 chars — first 5 lines of scraped markdown/nav text, not a summary.

---

## 10. Memory & Conversation (core/memory.py)

### UC 10.1 — Memory extraction is regex-based, not LLM-based [CORRECTED — more capable than "toy" implies, but confirmed still regex]
`MemoryManager.extract_from_message` (core/memory.py:61-92) actually has three regex categories, not "a handful of phrases": name (`my name is|call me|i am|i'm` + capitalized word, lines 66-72), explicit memory requests (`remember that|note that|keep in mind that|don't forget that`, lines 75-81), and location (`i live in|i'm in|i'm from|i am in|i am from`, lines 84-90). It's more deliberate than a toy, but still purely pattern-based — "I prefer email over calls" or any naturally-phrased fact outside these three templates is never captured, while `_get_system_prompt` (brain.py:475-482) injects `memory.get_context_string()` into every single request regardless.

### UC 10.2 — History grows unbounded in the request [CONFIRMED]
Only the last 8 messages are sent (brain.py:557, 636, 672) with no token budgeting — combined with UC 3.7 (Ollama's real 4096 `num_ctx` vs advertised 8192), long messages can still overflow smaller local models.

### UC 10.3 — Memory/context not user-visible or editable [CONFIRMED] — plus:

### UC 10.4 — [NEW] Settings-dialog location and MemoryManager's location preference are two disconnected stores
`ui/settings.py`'s location field writes to the `JARVIS_LOCATION` env var / `.env` file (lines 49-52). `WeatherSkill._get_auto_location` correctly reads that same env var (weather.py:45) — that path is wired correctly. **But** `MemoryManager.get_context_string` (core/memory.py:47-59), which is what actually gets injected into the LLM's system prompt (brain.py:476), reads `self.memory.get("preferences", {}).get("location")` (memory.py:51) — a completely separate value, stored in `memory/memory.json`, only ever set via the `set_preference("location", ...)` call inside `extract_from_message`'s "I live in X" regex (memory.py:89) or the `set_volume`-style `remember_fact` tool (which is unreachable per UC 3.3 anyway). **Setting your location in the Settings dialog has zero effect on what the AI believes your location is** unless you *also* type "I live in \<city\>" in chat at some point. Both paths independently hardcode `"Chennai, India"`/`"Chennai"` as their final fallback (config.py:28/33, memory.py:51, weather.py:94) — three separate hardcoded defaults for the same fact.

---

## 11. System Control (skills/system_control.py) — see also §0.3

### UC 11.1 — `run_command` is an arbitrary shell execution skill [CONFIRMED+ — already live, not just a future risk]
`SystemControl.run_command` (system_control.py:503-516): `subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)`. `Config.SECURITY["restricted_paths"]` (config.py:189) is confirmed dead (grepped, zero other references anywhere). As detailed in §0.3, this is directly exposed as a LangChain agent `Tool` (agents/orchestrator.py:138-142) with **no gate at all** — reachable today from any unclassified natural-language prompt, independent of whether brain.py's `supports_tools` flag (UC 3.3) is ever turned on.

### UC 11.2 — Volume/screenshot tools duplicated [CONFIRMED, exact lines]
`core/brain.py:13-95` defines module-level `_tool_set_volume`, `_tool_take_screenshot`, `_tool_get_clipboard`, `_tool_set_clipboard`, `_tool_type_text` — a second, independent implementation of functionality that also exists in `SystemControl`/`AutomationSkill`/`ScreenAutomationSkill`. Worth noting: `_tool_type_text` (brain.py:77-95, clipboard-paste based) is actually the *better* implementation relative to `ScreenAutomationSkill._execute_type`'s `pyautogui.typewrite` (UC 6.3) — but it's the one that's currently unreachable (UC 3.3).

### UC 11.3 — Process listing/kill string parsing [CONFIRMED+, exact lines]
`kill_process` (system_control.py:374-389): `if process_name.lower() in proc.info['name'].lower(): proc.kill()` (lines 379-381) — substring match against **every** running process, killing **all** matches (not just one), no confirmation, `proc.kill()` (SIGKILL-equivalent) rather than a graceful `terminate()`. "Kill chrome" will kill every process whose name contains "chrome" as a substring.

---

## 12. Packaging & Ops

### UC 12.1 — Two divergent dependency lists [CONFIRMED, contents re-read]
`requirements.txt` (39 packages, includes `langchain>=0.0.444`, `selenium`, `webdriver-manager`, `mcp`, `websockets`, `aiohttp` — several of which (selenium/webdriver-manager/mcp/websockets/aiohttp) don't appear to be imported by any file checked in this pass) vs `requirements_exe.txt` (lists `openai`, `anthropic`, `numpy` — none of which this codebase imports anywhere found — and puts `langchain` under an "Optional" section, meaning the packaged EXE may ship *without* the agent orchestrator at all; see §0.3 for what that silently does to behavior). `wmi`, `pywin32`, `pycaw` are Windows-only with no platform markers, despite `README.md:82` explicitly claiming "Windows/Mac/Linux compatible" — `pip install -r requirements.txt` will fail outright on macOS/Linux at the first Windows-only package.

### UC 12.2 — `launcher.bat` references files that don't exist [CONFIRMED+, more precise than the original]
`launcher.bat` checks for `JARVIS_AI_Assistant.exe` (line 11) and tells the user to "set up API keys in `config_user.py`" (its closing message) — but the actual build output in this repo is `dist\JARVIS.exe` (confirmed present on disk, different filename entirely), and as established in UC 1.6, the config file that's actually distributed is `config_template.py`, not `config_user.py`. Running `launcher.bat` as shipped will always print "Error: JARVIS_AI_Assistant.exe not found!" and exit.

### UC 12.3 — Empty test package [CONFIRMED, byte sizes verified] — but `test_jarvis.py` is more than the audit gives it credit for
`tests/test_fixes.py`, `test_keyword_free.py`, `test_natural_language.py` are confirmed **exactly 0 bytes** each (`wc -c`). However, `test_jarvis.py` at the repo root is **not** a trivial stub — it's a real 489-line hand-rolled regression suite covering config loading, the brain's model list, the Ollama `num_ctx` mismatch (UC 3.7), `app_control`'s `_SITE_MAP`/URL routing, the embedded `BrowserWindow`'s thread-safe signal wiring, alarm-time parsing, OpenRouter error-response guards, and `main_gui.py` signal wiring — constructing real objects including a live `QApplication` and `MultiModelBrain()`. It's still not pytest-based or CI-safe (it touches the Ollama HTTP endpoint and other live paths), but its existence and specific assertions are themselves evidence that **the YouTube/embedded-browser fix in §0.1 and the OpenRouter model-ID concern in UC 3.2 already had deliberate fix/test attempts made against them** after the original audit was written — worth knowing before assuming everything above is undiscovered.

### UC 12.4 — README drift [CONFIRMED, exact quotes]
`README.md` still describes an earlier architecture and a different (abandoned?) provider setup:
- Line 19: "Install Python 3.8 or higher" — contradicts UC 1.4 (`core/config.py:35` uses PEP 604 `str | None`, requires ≥3.10).
- Lines 24-27: tells the user to set `OPENAI_API_KEY` in `.env` — the codebase never reads that variable anywhere; the real keys are `OPENROUTER_API_KEY`/`GEMINI_API_KEY` (core/config.py), configured via the Settings dialog into `%APPDATA%\Jarvis\.env`, not a project-root `.env` the user hand-writes per this instruction.
- Line 35: "This repo includes a safe GUI app for multi-model chat (**no system-control actions**)" — false; `main_gui.py` has a full Automation tab (screenshot/click/discover-apps/plan-task buttons, §5) wired to `ScreenAutomationSkill`/`app_control`/the LangChain agent (§0.3), which per UC 11.1 can already run arbitrary shell commands.
- Line 45: "Responses are **stubbed** until you wire real provider calls" — false; `core/brain.py` has fully wired OpenRouter/Gemini/Ollama/demo providers.
- Line 49: documents building the EXE as `pyinstaller ... --name JarvisAI ... main_gui.py`, and line 52 says the installer output is `dist\JarvisAI-Installer.exe` — the actual shipped artifact is `dist\JARVIS.exe` (confirmed on disk) plus `install_jarvis.bat`, a different name in both cases, and `launcher.bat` (UC 12.2) expects a third name (`JARVIS_AI_Assistant.exe`) — three different expected executable names across `README.md`, `launcher.bat`, and what's actually in `dist/`.
- Line 66: "customizing JARVIS by modifying the configuration in `config.py`" — no such file exists at the repo root; it's `core/config.py`, plus the separate `config_user.py`-that-doesn't-exist issue (UC 1.6).
- Lines 70-75 ("Architecture"): lists `voice_engine.py`, `brain.py`, `config.py` at repo root — actual locations are `core/voice.py`, `core/brain.py`, `core/config.py`.

### UC 12.5 — Silent exception swallowing everywhere [CONFIRMED, with fresh examples from this pass]
Representative current instances, all newly re-confirmed: `ui/settings.py:74-75` (`except Exception: pass  # Ignore errors silently` around `.env` write); `core/config.py:65-67` (`.env` load fallback); `main_gui.py:1363-1364` (`except Exception: pass` swallowing errors while probing for new Ollama models in `_on_ollama_ready`); `main_gui.py:1806-1809` (`OllamaManager.get().stop()` wrapped in a bare `except Exception: pass` during `closeEvent`); `core/brain.py:413, 423-424` (`_load_history`/`_save_history` failures vanish — a corrupt or unwritable history file is never reported). Also found this pass: `jarvis.py:1489` and `jarvis.py:1579` (bare `except:` swallowing invalid "click at" coordinates and invalid volume values respectively — both inside the dead block from §0.2, so currently unreachable, but would resurface if that block is ever restored); `jarvis.py:2171` (bare `except: pass` around a math-eval fallback, also inside the dead block); `core/voice.py:87-88` (bare `except: pass` setting the TTS pitch property); `core/memory.py:17-18` (`except Exception: pass` — a corrupted `memory.json` silently resets to an empty memory with no warning that prior facts were lost); `core/ollama_manager.py:62-63` and `:89-90` (`except Exception: pass`). None of these log to `Config.LOGS_DIR` or surface anything to the user.

### UC 12.6 — No logging framework [CONFIRMED] — the codebase mixes `console.print` (rich), bare `print`, and silent `pass`. `Config.LOGS_DIR` exists (config.py:196) and is used only for `conversation_history.json`.

---

## 13. End-to-End "Whole Laptop" Use Cases

### UC 13.1 — "Open Chrome, go to YouTube and play a video from Michael Jackson" [CORRECTED — partially works now, see §0.1]
The "go to YouTube and play X" half is implemented (§0.1). What's still broken/untested:
1. **Composition with "open chrome" doesn't happen.** `_handle_app_commands`'s regex `r'\b(?:open|launch|start|run)\s+(\w+)'` (jarvis.py:776) still captures only the single word `"chrome"` and discards the rest — confirmed unchanged from the original audit. Whether the whole sentence gets classified as `APP` (→ opens real Chrome, drops the YouTube part) or `AUTOMATION` (→ hits `_handle_automation_commands`'s website-navigation branch, jarvis.py:997-1003, which calls `launch_app_by_name` on the **entire lowercased command string including "open chrome"**) depends entirely on the LLM classifier's mood; in the `AUTOMATION` case, `launch_app_by_name("open chrome, go to youtube and play a video from michael jackson")` — the nav-prefix stripper (app_control.py:155-159) only strips a *leading* prefix like "go to", and "open chrome, go to..." doesn't start with any of those prefixes, so the whole thing falls through to the free-text `_SITE_MAP` substring search (app_control.py:176-182), which *would* still find "youtube" inside the string via the keyword-containment loop — so this specific example may actually work today by accident, but it's fragile: it depends on "youtube" being a longer, higher-priority match than any other keyword-containment hit, and there's still no actual "open Chrome first, then also navigate" two-step composition; whichever single URL/app wins is the only thing that happens.
2. No playback verification — see §14.1 (SMTC) for the recommended fix; `_check_goal_achieved`-style keyword folklore (UC 6.4) is the only thing in the codebase resembling this, and it isn't wired to the browser path at all.

### UC 13.2 — "Go to YouTube" (no app mentioned) [CORRECTED]
This now works as intended more often than the old audit suggested: `_handle_automation_commands`'s website branch (jarvis.py:997-1003) calls `app_control.launch_app_by_name("go to youtube")`, which strips the "go to" prefix (app_control.py:157-159) → `"youtube"` → exact `_SITE_MAP` hit (line 176-177) → `open_url` (129-138) → routes through `_browser_callback` if `MainWindow` registered one (it does, main_gui.py:752-753) → opens the **embedded** `BrowserWindow`, not the system default browser. The one gap: this only works when the GUI is running and `app_control.set_browser_callback` had a chance to run; in CLI/text mode (`jarvis.py` run standalone, no `MainWindow`), the callback is never registered, so `open_url` correctly falls back to `webbrowser.open(url)` (app_control.py:135) — which is arguably the right behavior for CLI mode anyway, not a bug.

### UC 13.3 — "Set an alarm for 7 AM" [CONFIRMED unchanged — see UC 8.1/8.2]
Still an in-process sleeping thread with no `ms-clock:`/Task Scheduler integration. Recommendation unchanged from the original audit.

### UC 13.4 — General "control my laptop" expectations [spot-checked against current code]
| Prompt | Current behavior (re-verified) |
|---|---|
| "Turn down the volume" | Two independent implementations exist: `SystemControl` (not re-read line-by-line this pass) and `core/brain.py`'s `_tool_set_volume` (brain.py:13-31, pycaw-based) — the latter is unreachable (UC 3.3/UC 11.2). |
| "Lock my PC" | Not found in any skill grepped this pass. Still not implemented. |
| "What's on my screen?" | Vision path exists and supports Ollama (`_query_ollama_vision`, screen_automation.py:539-588) *and* OpenRouter/Gemini (256-346), selected by `Config.AUTOMATION_VISION_PROVIDER` (defaults to `"openrouter"`, config.py:122) — so a local/offline path exists and is wired, it's just not the default. |
| "Close all windows" | `AutomationSkill.close_window`/`minimize_window` (skills/automation.py:171, 199) each take a single `window_title` and act via one `win32gui.EnumWindows` callback — no "all windows" batch variant exists in this file or anywhere else grepped. Original audit's claim confirmed unchanged. |

---

## 14. Windows SDKs & Native APIs to Leverage

Unchanged from the original audit's recommendations (§14.1–14.6) — none of `winsdk`/`winrt`, `pywinauto`, `Windows.Media.Control` (SMTC), or `Windows.Media.Ocr` were found anywhere in the current codebase during this pass. The one addition worth flagging: since §0.1 established that YouTube search-and-autoplay *already* works via the embedded browser + JS injection, **SMTC (`Windows.Media.Control`) is now the single highest-leverage addition** — it would let `_check_goal_achieved`-style verification (UC 6.4) be replaced with a real "is something actually playing" check for exactly the flow that was just confirmed to partially work, closing the loop the original audit asked for in UC 13.1.

---

## Priority Roadmap (revised)

### P0 — Safety and "feels broken"
1. **UC 11.1 / §0.3 — `run_command` is a live, ungated RCE surface via the LangChain agent today**, not a future risk. This is more urgent than the original roadmap ranked it.
2. UC 1.2/1.3 — don't select models without keys; kill demo-model default.
3. UC 3.1 — duplicate message bug (affects every reply quality, every provider).
4. UC 2.3 — weather city ignored (single-line fix: pass the classifier's extracted city, or just call `get_weather(command)` directly).
5. UC 2.4/9.2 — `True`/bool leaking into chat as text.
6. UC 2.7 — "quit"/"exit" substring shutdown bypasses everything.
7. UC 3.6 — network timeouts; GUI hang + unsafe `.terminate()` (UC 5.2).
8. UC 8.2 — month-end alarm crash.

### P1 — Structural, not just cosmetic
9. **§0.2 — the ~900-line dead block in jarvis.py.** Either delete it or actually re-wire `CommandProcessor` to it — right now compound "then/and" commands and the model-management voice commands are pure decoration.
10. UC 2.1/2.2 — cheap intent routing; align classifier categories with dispatcher; stop polluting history with classification prompts.
11. UC 5.1/5.2 — real task queue, no thread `.terminate()`.
12. UC 6.1/6.2 — shared automation instance; a confirmation path that can actually reach the GUI (there is no `JARVIS.gui` attribute to hook into — this needs a callback passed at construction time, not a `hasattr` check).
13. UC 3.4 — persisted clear-history.
14. UC 7.1/7.3 — sane file defaults; resolve the overwrite dead-end.
15. UC 10.4 — unify the three hardcoded-Chennai location fallbacks into one source of truth that the Settings dialog actually feeds.

### P2 — Trust, safety, maintainability
16. UC 6.6 — rotate/remove the hardcoded Gemini key in `screen_automation.py:330`.
17. UC 3.3 — either wire `supports_tools` for real, or delete the entire unreachable `JARVIS_TOOLS` machinery in `brain.py` (keeping two competing tool-execution systems, one dead, is worse than picking one).
18. UC 12.1/12.2/12.3 — dependency list reconciliation (decide if `langchain` is required or optional — §0.3 shows this silently changes what the app can do); fix `launcher.bat`'s filenames; flesh out tests.
19. UC 12.5/12.6 — logging & error surfacing.
20. UC 13.1 — make "open chrome, go to youtube, play X" a real two-step plan instead of a lucky keyword match; add SMTC-based playback verification (§14).
21. UC 14 — WinRT/UIA/protocol handlers for the rest of the "whole laptop" surface (lock PC, Bluetooth/Wi-Fi, wallpaper, offline STT/TTS).

---

## Verification Checklist (updated)
- [ ] Fresh install, no keys: onboarding wizard appears; no demo model selected.
- [ ] "hi" replies in < 1s with exactly one LLM call (or zero).
- [ ] "Weather in London" returns London; "weather" returns configured/detected location.
- [ ] "How do I quit smoking?" does not exit the app.
- [ ] A prompt like "run a command to list files" (or any phrasing that routes to the LangChain agent) either refuses, asks for confirmation, or is scoped to a safe allowlist — **currently it will just run it.**
- [ ] Disconnect network mid-chat: GUI recovers with an error bubble within 60s, without needing `.terminate()`.
- [ ] "Set alarm for 11:59 pm" on the 31st works; restart preserves it.
- [ ] Long AI reply is spoken fully (not cut at 5s) even if `playsound` is missing.
- [ ] GUI "Pause task" actually pauses a running queue.
- [ ] "Create file notes" lands in Documents; overwrite flow completes.
- [ ] "Open Chrome, go to YouTube, play Michael Jackson" completes all three steps in a *deterministic* order (not an accidental keyword-match), with playback verified via SMTC.
- [ ] "Go to YouTube" (no app named) opens the embedded browser; "open Chrome" opens Chrome. **(Already passes in the GUI today per §0.1/UC 13.2 — verify it still passes after any classifier changes.)**
- [ ] "Set alarm for 7 AM" opens Windows Alarms (`ms-clock:`) or a persistent task that survives reboot.
- [ ] "Pause the music" works via SMTC regardless of which app is playing.
- [ ] Setting a location in the Settings dialog changes what the AI says your location is, without also having to say "I live in X" in chat.
- [ ] `pytest` runs green offline in CI without a microphone, without requiring `langchain` to be installed to exercise the fallback path.
