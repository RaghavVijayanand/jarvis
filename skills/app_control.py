"""Open and close applications and websites on Windows.

Launching goes through the Windows shell (``os.startfile`` / ShellExecute),
which resolves registered "App Paths" (chrome.exe, winword.exe …), protocol
URIs (ms-settings:, spotify:) and Start-menu shortcuts without ever passing
user text to a command interpreter.
"""
import json
import os
import re
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

try:
    import winreg
except ImportError:  # non-Windows
    winreg = None

from core.logging_setup import get_logger

log = get_logger("jarvis.apps")

# Common site keywords → canonical URLs
_SITE_MAP = {
    "youtube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google translate": "https://translate.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "reddit": "https://www.reddit.com",
    "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com",
    "amazon": "https://www.amazon.com",
    "flipkart": "https://www.flipkart.com",
    "github": "https://github.com",
    "stack overflow": "https://stackoverflow.com",
    "stackoverflow": "https://stackoverflow.com",
    "linkedin": "https://www.linkedin.com",
    "wikipedia": "https://www.wikipedia.org",
    "whatsapp web": "https://web.whatsapp.com",
    "spotify web": "https://open.spotify.com",
    "twitch": "https://www.twitch.tv",
    "discord web": "https://discord.com/app",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "outlook web": "https://outlook.live.com",
}

# Friendly name → shell target (exe name resolved via App Paths, or a URI).
_APP_ALIASES = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe",
    "paint": "mspaint.exe", "wordpad": "write.exe", "snipping tool": "snippingtool.exe",
    "cmd": "cmd.exe", "command prompt": "cmd.exe", "terminal": "wt.exe", "windows terminal": "wt.exe",
    "powershell": "powershell.exe", "explorer": "explorer.exe", "file explorer": "explorer.exe",
    "files": "explorer.exe", "task manager": "taskmgr.exe", "control panel": "control.exe",
    "registry editor": "regedit.exe", "device manager": "devmgmt.msc", "disk management": "diskmgmt.msc",
    "services": "services.msc", "event viewer": "eventvwr.msc",
    "settings": "ms-settings:", "windows settings": "ms-settings:", "microsoft store": "ms-windows-store:",
    "store": "ms-windows-store:", "camera": "microsoft.windows.camera:", "clock": "ms-clock:",
    "alarms": "ms-clock:", "alarm": "ms-clock:", "photos": "ms-photos:", "mail": "outlookmail:",
    "calendar": "outlookcal:", "maps app": "bingmaps:", "xbox": "xbox:",
    "chrome": "chrome.exe", "google chrome": "chrome.exe", "firefox": "firefox.exe",
    "edge": "msedge.exe", "microsoft edge": "msedge.exe", "brave": "brave.exe", "opera": "opera.exe",
    "vs code": "code", "vscode": "code", "visual studio code": "code",
    "word": "winword.exe", "microsoft word": "winword.exe", "excel": "excel.exe",
    "microsoft excel": "excel.exe", "powerpoint": "powerpnt.exe", "outlook": "outlook.exe",
    "onenote": "onenote.exe", "teams": "ms-teams:", "zoom": "zoommtg:", "spotify": "spotify:",
    "whatsapp": "whatsapp:", "telegram": "tg:", "discord": "discord:", "steam": "steam:",
    "vlc": "vlc.exe",
}

# Friendly name → process image names (for closing apps).
_PROCESS_NAMES = {
    "chrome": ["chrome.exe"], "google chrome": ["chrome.exe"], "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"], "firefox": ["firefox.exe"], "brave": ["brave.exe"],
    "opera": ["opera.exe"], "notepad": ["notepad.exe"], "calculator": ["calculatorapp.exe", "calc.exe"],
    "calc": ["calculatorapp.exe", "calc.exe"], "paint": ["mspaint.exe"], "word": ["winword.exe"],
    "excel": ["excel.exe"], "powerpoint": ["powerpnt.exe"], "outlook": ["outlook.exe", "olk.exe"],
    "teams": ["ms-teams.exe", "teams.exe"], "spotify": ["spotify.exe"], "discord": ["discord.exe"],
    "vs code": ["code.exe"], "vscode": ["code.exe"], "visual studio code": ["code.exe"],
    "steam": ["steam.exe"], "zoom": ["zoom.exe"], "vlc": ["vlc.exe"], "whatsapp": ["whatsapp.exe"],
    "telegram": ["telegram.exe"], "task manager": ["taskmgr.exe"], "file explorer": [],
    "terminal": ["windowsterminal.exe"], "windows terminal": ["windowsterminal.exe"],
}
BROWSERS = {"chrome": "chrome.exe", "google chrome": "chrome.exe", "edge": "msedge.exe",
            "microsoft edge": "msedge.exe", "firefox": "firefox.exe", "brave": "brave.exe",
            "opera": "opera.exe"}

_NAV_PREFIX = re.compile(r"^(?:please\s+)?(?:can you\s+)?(?:go to|navigate to|visit|open website|open the website|"
                         r"browse to|take me to|open|launch|start|run)\s+", re.I)
_ACTION = re.compile(r"\b(?:and|then|to)\s+(play|search(?: for)?|find|watch|look up|listen to|stream|show me)\s+(.+)$", re.I)
_FILLER = re.compile(r"\b(?:the|my|app|application|program|browser|please|for me|now|up)\b", re.I)
_SAFE_NAME = re.compile(r"[^\w .+&'-]")
# Extensions that make "name.ext" a file/program rather than a web domain.
_FILE_EXTS = {"exe", "msc", "lnk", "bat", "cmd", "ps1", "txt", "pdf", "doc", "docx", "xls", "xlsx",
              "ppt", "pptx", "png", "jpg", "jpeg", "gif", "mp3", "mp4", "mkv", "zip", "py", "csv", "json"}


def _word_re(name: str) -> str:
    """Whole-word pattern that also works for names ending in symbols ('notepad++')."""
    return rf"(?<!\w){re.escape(name)}(?!\w)"


def _icon_path(icon: str) -> str:
    """'"C:\\a,b\\app.exe",0' → 'C:\\a,b\\app.exe' (drop quotes and the icon index only)."""
    icon = (icon or "").strip()
    m = re.match(r'^"([^"]*)"', icon)
    if m:
        return m.group(1)
    return re.sub(r",\s*-?\d+$", "", icon).strip('"')


def youtube_first_video(query: str, timeout: float = 6.0):
    """Return the watch URL of the first YouTube search result, or None."""
    try:
        import requests
        resp = requests.get("https://www.youtube.com/results", params={"search_query": query},
                            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.8"},
                            timeout=timeout)
        if resp.status_code != 200:
            return None
        match = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', resp.text) or \
            re.search(r'/watch\?v=([\w-]{11})', resp.text)
        return f"https://www.youtube.com/watch?v={match.group(1)}" if match else None
    except Exception as exc:
        log.info("YouTube lookup failed: %s", exc)
        return None


class ApplicationControl:
    def __init__(self, scan: bool = True):
        self.installed_apps = {}
        self._browser_callback = None  # set by the GUI to use the embedded browser
        self._start_apps = None        # cached Get-StartApps list
        self._scan_lock = threading.Lock()
        if scan:
            threading.Thread(target=self.refresh_app_list, name="AppScan", daemon=True).start()

    def set_browser_callback(self, fn):
        """Register a callback(url, then_js) that opens URLs in the embedded browser."""
        self._browser_callback = fn

    # ── Discovery ────────────────────────────────────────────────────────────

    def refresh_app_list(self):
        with self._scan_lock:
            try:
                self.installed_apps = self._get_installed_applications()
            except Exception as exc:
                log.warning("Error refreshing app list: %s", exc)
        return len(self.installed_apps)

    def _get_installed_applications(self):
        apps = {}
        if winreg is None:
            return apps
        roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
        for hive, path in roots:
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                continue
            try:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    except OSError:
                        continue
                    try:
                        name = winreg.QueryValueEx(sub, "DisplayName")[0]
                    except OSError:
                        winreg.CloseKey(sub)
                        continue
                    location = executable = None
                    try:
                        location = winreg.QueryValueEx(sub, "InstallLocation")[0] or None
                    except OSError:
                        pass
                    try:
                        icon = _icon_path(str(winreg.QueryValueEx(sub, "DisplayIcon")[0]))
                        if icon.lower().endswith(".exe") and "unins" not in icon.lower():
                            executable = icon
                    except OSError:
                        pass
                    apps[name.lower()] = {"name": name, "location": location, "executable": executable}
                    winreg.CloseKey(sub)
            finally:
                winreg.CloseKey(key)
        return apps

    def discover_applications(self) -> str:
        count = self.refresh_app_list()
        start = self._get_start_apps(refresh=True)
        return (f"Found {count} installed programs and {len(start)} Start-menu apps. "
                f"Say 'open <name>' to launch one, or 'list apps <filter>' to search.")

    def list_installed_apps(self, filter_text=""):
        names = {v["name"] for v in self.installed_apps.values()}
        names |= {a["Name"] for a in self._get_start_apps() if a.get("Name")}
        if filter_text:
            names = {n for n in names if filter_text.lower() in n.lower()}
        if not names:
            return "No applications found matching the filter."
        ordered = sorted(names, key=str.lower)
        more = f"\n… and {len(ordered) - 50} more" if len(ordered) > 50 else ""
        return "Installed applications:\n" + "\n".join(ordered[:50]) + more

    def _get_start_apps(self, refresh: bool = False):
        """Start-menu apps (incl. Store apps) via PowerShell Get-StartApps, cached."""
        if self._start_apps is not None and not refresh:
            return self._start_apps
        if os.name != "nt":
            self._start_apps = []
            return self._start_apps
        apps = []
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                 "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads((out.stdout or "").strip() or "[]")
            data = data if isinstance(data, list) else [data]
            apps = [a for a in data if isinstance(a, dict) and a.get("Name") and a.get("AppID")]
        except Exception as exc:
            log.info("Get-StartApps unavailable: %s", exc)
        self._start_apps = apps   # publish the finished list (other threads never see a half-filled one)
        return self._start_apps

    # ── URLs ─────────────────────────────────────────────────────────────────

    def open_url(self, url: str, then_js: str = None, browser: str = None) -> str:
        """Open a URL in a named browser, the embedded JARVIS browser, or the default browser."""
        if not str(url or "").lower().startswith(("http://", "https://")):
            # The URL becomes a browser command-line argument: '--gpu-launcher=…' would run a program.
            return f"I only open web addresses (http/https), not '{url}'."
        try:
            exe = BROWSERS.get((browser or "").strip().lower())
            if exe is None and (browser or "").strip().lower() in BROWSERS.values():
                exe = browser.strip().lower()
            if exe and os.name == "nt":
                # Only known browser executables — never an arbitrary program named by user/LLM text.
                os.startfile(exe, arguments=url)  # type: ignore[attr-defined]
                return f"Opened {url} in {browser.strip().title()}."
            if self._browser_callback:
                self._browser_callback(url, then_js)
                return f"Opened {url} in JARVIS browser."
            webbrowser.open(url)
            return f"Opened {url} in your browser."
        except Exception as e:
            return f"Failed to open URL: {e}"

    @staticmethod
    def _site_url(text: str):
        raw = text.strip().rstrip(".!?")
        text = raw.lower()
        if text.startswith(("http://", "https://")):
            return raw.split()[0]          # keep the path's case (YouTube IDs); never pass trailing words
        m = re.fullmatch(r"[\w-]+(?:\.[\w-]+)*\.([a-z]{2,24})(/\S*)?", text)
        if text.startswith("www.") or (m and m.group(1) not in _FILE_EXTS):
            return "https://" + raw.split()[0]
        if text in _SITE_MAP:
            return _SITE_MAP[text]
        for key in sorted(_SITE_MAP, key=len, reverse=True):
            if re.search(rf"\b{re.escape(key)}\b", text) and len(key) > 1:
                return _SITE_MAP[key]
        return None

    @staticmethod
    def clean_query(query: str) -> str:
        """'a video called rick roll' → 'rick roll'; 'some songs by arijit' → 'songs by arijit'."""
        q = (query or "").strip().rstrip(".!?")
        q = re.sub(r"^(?:me\s+)?(?:a|an|the|some)\s+", "", q, flags=re.I)
        q = re.sub(r"^(?:video|song|track|music video|clip|movie|film)s?\s+(?:(?:called|named|titled|of|about)\s+)?(?!by\b)", "", q,
                   flags=re.I)
        q = re.sub(r"\s+(?:on|in)\s+(?:youtube|spotify)$", "", q, flags=re.I)
        return q.strip() or query

    def _site_action_url(self, url: str, query: str):
        """Refine a site URL with a search/play query. Returns (url, then_js)."""
        query = self.clean_query(query)
        encoded = quote_plus(query)
        if "youtube.com" in url:
            direct = youtube_first_video(query)
            if direct:
                return direct, None
            js = ("setTimeout(function(){var v=document.querySelector('ytd-video-renderer a#thumbnail, "
                  "a#video-title');if(v){v.click();}},2500);")
            return f"https://www.youtube.com/results?search_query={encoded}", js
        if "spotify" in url:
            return f"https://open.spotify.com/search/{quote_plus(query)}", None
        if "reddit.com" in url:
            return f"https://www.reddit.com/search/?q={encoded}", None
        if "amazon." in url:
            return f"https://www.amazon.com/s?k={encoded}", None
        if "wikipedia" in url:
            return f"https://en.wikipedia.org/w/index.php?search={encoded}", None
        if "github.com" in url:
            return f"https://github.com/search?q={encoded}", None
        if "maps.google" in url:
            return f"https://www.google.com/maps/search/{encoded}", None
        return f"https://www.google.com/search?q={encoded}", None

    # ── Launching ────────────────────────────────────────────────────────────

    def launch_app_by_name(self, app_name, browser: str = None):
        """Open an app, website or folder described in natural language."""
        try:
            text = (app_name or "").strip()
            if not text:
                return "Please tell me what to open."
            from skills.command_processor import normalize_site_names
            text = normalize_site_names(text)          # "go to yputube" → "go to youtube"
            direct = _NAV_PREFIX.sub("", text.rstrip(".!?")).strip()
            if re.fullmatch(r"https?://\S+|[\w-]+(?:\.[\w-]+)+(?:/\S*)?", direct, re.I) and self._site_url(direct):
                return self.open_url(self._site_url(direct), None, browser)   # URL case preserved
            low = text.lower().rstrip(".!?")
            low = _NAV_PREFIX.sub("", low).strip()
            query = None
            m = _ACTION.search(low)
            verb = None
            if m:
                verb, query = m.group(1).lower(), m.group(2).strip()
                low = low[:m.start()].strip()
            # "play despacito" with no site → YouTube.
            if not low and verb:
                low = "youtube"
            if re.match(r"^play\s+", text, re.I) and not m:
                query = re.sub(r"^play\s+", "", text, flags=re.I)
                query = re.sub(r"\s+on\s+(youtube|spotify)$", "", query, flags=re.I)
                low = "spotify web" if re.search(r"on spotify$", text, re.I) else "youtube"
            site = re.sub(r"\s+(?:website|site|web ?page)$", "", low)
            url = self._site_url(site)
            if url and (site not in _APP_ALIASES or site in ("youtube", "google")):
                then_js = None
                if query:
                    url, then_js = self._site_action_url(url, query)
                result = self.open_url(url, then_js, browser)
                query = self.clean_query(query) if query else query
                return result + (f" Playing: {query}." if query and verb in (None, "play", "watch", "listen to", "stream") and "watch?v=" in url else "")
            name = _FILLER.sub(" ", site)
            name = re.sub(r"\s+", " ", name).strip()
            if not name:
                return "Please tell me which app to open."
            return self._launch_named_app(name)
        except Exception as e:
            log.exception("launch failed")
            return f"Error launching application: {e}"

    def open_app(self, app_name: str) -> str:
        return self.launch_app_by_name(app_name)

    def _launch_named_app(self, name: str) -> str:
        safe = _SAFE_NAME.sub("", name).strip()
        if not safe:
            return "That doesn't look like an application name."
        # Known folders
        folders = {"desktop": Path.home() / "Desktop", "downloads": Path.home() / "Downloads",
                   "documents": Path.home() / "Documents", "pictures": Path.home() / "Pictures",
                   "music": Path.home() / "Music", "videos": Path.home() / "Videos"}
        if safe in folders or safe.rstrip("s") + "s" in folders:
            folder = folders.get(safe) or folders[safe.rstrip("s") + "s"]
            return self._shell_open(str(folder), safe.title() + " folder")
        if safe in _APP_ALIASES:
            return self._shell_open(_APP_ALIASES[safe], safe.title(), expect=_PROCESS_NAMES.get(safe))
        shortcut = self._find_start_menu_shortcut(safe)
        if shortcut:
            return self._shell_open(shortcut, Path(shortcut).stem)
        app = self._match_start_app(safe)
        if app:
            return self._shell_open(f"shell:AppsFolder\\{app['AppID']}", app["Name"], via_explorer=True)
        info = self._match_installed(safe)
        if info:
            exe = info.get("executable")
            if exe and os.path.exists(exe):
                return self._shell_open(exe, info["name"], expect=[os.path.basename(exe).lower()])
            loc = info.get("location")
            if loc and os.path.isdir(loc):
                exes = [p for p in Path(loc).glob("*.exe") if "unins" not in p.name.lower()]
                if exes:
                    return self._shell_open(str(exes[0]), info["name"], expect=[exes[0].name.lower()])
            return f"{info['name']} is installed, but I couldn't find its program file."
        # Let ShellExecute try App Paths for "<name>.exe" (e.g. 'spotify' → spotify.exe).
        if re.fullmatch(r"[\w.-]+", safe):
            result = self._shell_open(safe if safe.endswith(".exe") else safe + ".exe", safe.title(),
                                      quiet_fail=True)
            if result:
                return result
        return (f"I couldn't find an app called '{name}'. Try 'list apps {name.split()[0]}' "
                f"to see what's installed.")

    def _match_start_app(self, name: str):
        apps = self._get_start_apps()
        lname = name.lower()
        exact = [a for a in apps if a.get("Name", "").lower() == lname]
        if exact:
            return exact[0]
        starts = [a for a in apps if a.get("Name", "").lower().startswith(lname)]
        if starts:
            return min(starts, key=lambda a: len(a["Name"]))
        words = [a for a in apps if re.search(_word_re(lname), a.get("Name", "").lower())]
        return min(words, key=lambda a: len(a["Name"])) if words else None

    def _match_installed(self, name: str):
        if name in self.installed_apps:
            return self.installed_apps[name]
        hits = [k for k in self.installed_apps if re.search(_word_re(name), k)]
        return self.installed_apps[min(hits, key=len)] if hits else None

    def _find_start_menu_shortcut(self, name: str):
        if os.name != "nt":
            return None
        bases = [Path(root) / "Microsoft/Windows/Start Menu/Programs"
                 for root in (os.getenv("APPDATA"), os.getenv("PROGRAMDATA") or r"C:\ProgramData") if root]
        best = None
        for base in bases:
            if not base.is_dir():
                continue
            for path in base.rglob("*.lnk"):
                stem = path.stem.lower()
                if "uninstall" in stem:
                    continue
                if stem == name:
                    return str(path)
                if re.search(_word_re(name), stem) and (best is None or len(stem) < len(Path(best).stem)):
                    best = str(path)
        return best

    def _shell_open(self, target: str, display: str, expect=None, via_explorer: bool = False,
                    quiet_fail: bool = False):
        before = self._process_names() if expect else set()
        try:
            if via_explorer:
                subprocess.Popen(["explorer.exe", target])
            elif os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", target])
        except OSError as exc:
            if quiet_fail:
                return None
            return f"Windows couldn't open {display}: {exc.strerror or exc}"
        if expect:
            deadline = time.time() + 4
            wanted = {e.lower() for e in expect}
            while time.time() < deadline:
                running = self._process_names()
                if wanted & running:
                    return f"Opened {display}."
                time.sleep(0.4)
            if wanted & before:
                return f"{display} is already running — brought it up."
            return f"Asked Windows to open {display}; it hasn't appeared yet."
        return f"Opened {display}."

    @staticmethod
    def _process_names():
        if psutil is None:
            return set()
        names = set()
        for proc in psutil.process_iter(["name"]):
            try:
                names.add((proc.info.get("name") or "").lower())
            except Exception:
                continue
        return names

    # ── Closing / info ───────────────────────────────────────────────────────

    def resolve_process_names(self, app_name: str):
        name = _FILLER.sub(" ", (app_name or "").lower())
        name = re.sub(r"\s+", " ", name).strip()
        if name in _PROCESS_NAMES:
            return _PROCESS_NAMES[name]
        alias = _APP_ALIASES.get(name, "")
        if alias.endswith(".exe"):          # "microsoft word" → winword.exe
            return [alias]
        name = name.removesuffix(".exe")
        return [name + ".exe"] if re.fullmatch(r"[\w.-]+", name) else []

    def close_app_by_name(self, app_name):
        """Gracefully close every process of an app (exact image-name match)."""
        if psutil is None:
            return "Process control unavailable."
        targets = {t.lower() for t in self.resolve_process_names(app_name)}
        if not targets:
            return f"I don't know which program '{app_name}' is."
        procs = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if (proc.info.get("name") or "").lower() in targets and proc.info["pid"] not in (0, 4, os.getpid()):
                    proc.terminate()
                    procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not procs:
            return f"{app_name} doesn't seem to be running."
        gone, alive = psutil.wait_procs(procs, timeout=5)
        msg = f"Closed {app_name} ({len(gone)} process{'es' if len(gone) != 1 else ''})."
        if alive:
            msg += f" {len(alive)} process(es) did not exit yet."
        return msg

    def get_app_info(self, app_name):
        info = self._match_installed((app_name or "").lower())
        if not info:
            return f"Application '{app_name}' not found."
        running = False
        if info.get("executable") and psutil:
            exe = os.path.basename(info["executable"]).lower()
            running = exe in self._process_names()
        return (f"Name: {info['name']}\nInstall location: {info.get('location') or 'Unknown'}\n"
                f"Executable: {info.get('executable') or 'Unknown'}\n"
                f"Status: {'Running' if running else 'Not running'}")

    def uninstall_app(self, app_name):
        """Open Windows' own uninstall page; JARVIS never runs uninstallers silently."""
        try:
            os.startfile("ms-settings:appsfeatures")  # type: ignore[attr-defined]
            return f"Opened Installed apps in Settings — search for {app_name} there to uninstall it."
        except Exception as e:
            return f"Could not open Settings: {e}"

    def create_desktop_shortcut(self, app_name):
        info = self._match_installed((app_name or "").lower())
        if not info or not info.get("executable"):
            return f"No executable found for '{app_name}'."
        try:
            import win32com.client
            shortcut_path = Path.home() / "Desktop" / f"{info['name']}.lnk"
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(str(shortcut_path))
            shortcut.TargetPath = info["executable"]
            shortcut.WorkingDirectory = str(Path(info["executable"]).parent)
            shortcut.save()
            return f"Created desktop shortcut for {info['name']}."
        except Exception as e:
            return f"Error creating shortcut: {e}"
