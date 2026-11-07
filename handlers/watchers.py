"""Watch-and-react automation. Starting, listing, stopping and clearing watchers
all run immediately — they only touch JARVIS's own in-memory watch list, the same
risk class as canceling a reminder."""
import re

from core.tools import params
from handlers.base import Handler

_WATCH_FILE = re.compile(r"^(?:please\s+)?(?:watch for|tell me when)\s+(?:the\s+)?(?:file\s+)?"
                         r"(.+?)(?:\s+to)?\s+(?:appears?|is created|exists)[.!?]*$", re.I)
_WATCH_DOWNLOAD = re.compile(r"^(?:please\s+)?(?:tell me|notify me)\s+when\s+(?:the\s+)?download(?:ing)?\s+"
                             r"(?:of\s+)?(.+?)\s+(?:finishes|completes|is done)[.!?]*$", re.I)
_WATCH_PROCESS = re.compile(r"^(?:please\s+)?(?:tell me|notify me)\s+when\s+(.+?)\s+"
                            r"(?:closes|exits|ends|finishes)[.!?]*$", re.I)
_WATCH_CPU = re.compile(r"^(?:please\s+)?(?:notify|tell) me\s+if\s+cpu\s+(?:is\s+|stays\s+)?(?:above|over)\s+"
                        r"(\d+(?:\.\d+)?)%?(?:\s+for\s+(\d+(?:\.\d+)?)\s*min(?:ute)?s?)?[.!?]*$", re.I)
_WATCH_MEM = re.compile(r"^(?:please\s+)?(?:notify|tell) me\s+if\s+(?:memory|ram)\s+(?:is\s+|stays\s+)?"
                        r"(?:above|over)\s+(\d+(?:\.\d+)?)%?(?:\s+for\s+(\d+(?:\.\d+)?)\s*min(?:ute)?s?)?"
                        r"[.!?]*$", re.I)
_LIST_WATCHERS = re.compile(r"\blist\s+watchers\b|\bwhat\s+(?:are\s+)?(?:you\s+)?watching\b", re.I)
_STOP_WATCHER = re.compile(r"^(?:please\s+)?stop\s+watch(?:er|ing)\s+(\S+)[.!?]*$", re.I)
_CLEAR_WATCHERS = re.compile(r"^(?:please\s+)?clear\s+(?:all\s+)?watchers[.!?]*$", re.I)


class WatcherHandler(Handler):
    intents = {"WATCH"}

    def handle(self, text, intent):
        app = self.app
        wm = getattr(app, "watchers", None)
        if wm is None:
            return "Watchers aren't available."
        low = text.strip()

        m = _WATCH_DOWNLOAD.match(low)
        if m:
            return wm.watch_download_finished(m.group(1).strip())
        m = _WATCH_PROCESS.match(low)
        if m:
            return wm.watch_process_ends(m.group(1).strip())
        m = _WATCH_FILE.match(low)
        if m:
            return wm.watch_file_created(m.group(1).strip())
        m = _WATCH_CPU.match(low)
        if m:
            threshold = float(m.group(1))
            minutes = float(m.group(2)) if m.group(2) else 1.0
            return wm.watch_cpu_above(threshold, minutes)
        m = _WATCH_MEM.match(low)
        if m:
            threshold = float(m.group(1))
            minutes = float(m.group(2)) if m.group(2) else 1.0
            return wm.watch_memory_above(threshold, minutes)
        if _LIST_WATCHERS.search(low):
            return wm.list_watchers()
        m = _STOP_WATCHER.match(low)
        if m:
            return wm.stop_watcher(m.group(1).strip())
        if _CLEAR_WATCHERS.match(low):
            return wm.clear_watchers()
        return None

    def register_tools(self, t):
        wm = getattr(self.app, "watchers", None)
        if wm is None:
            return
        t.add("watch_file_created", "Watch for a file to be created/appear, and notify when it does.",
              wm.watch_file_created, params(["path"], path=("string", "Full path to watch for")))
        t.add("watch_download_finished", "Watch for a download to finish and notify when it does.",
              wm.watch_download_finished,
              params(["filename_contains"], filename_contains=("string", "Text the downloaded filename contains"),
                    folder=("string", "Folder to watch (default: the user's Downloads folder)")))
        t.add("watch_process_ends", "Watch for a running process to close and notify when it does.",
              wm.watch_process_ends, params(["process_name"], process_name=("string", "Process name to watch")))
        t.add("watch_cpu_above", "Notify if CPU usage stays above a threshold for a sustained period.",
              wm.watch_cpu_above, params(["threshold"], threshold=("number", "CPU percent threshold"),
                                        minutes=("number", "How many minutes it must stay above")))
        t.add("watch_memory_above", "Notify if memory usage stays above a threshold for a sustained period.",
              wm.watch_memory_above, params(["threshold"], threshold=("number", "Memory percent threshold"),
                                           minutes=("number", "How many minutes it must stay above")))
        t.add("list_watchers", "List active watchers.", wm.list_watchers)
        t.add("stop_watcher", "Stop a specific watcher by id.", wm.stop_watcher,
              params(["watcher_id"], watcher_id=("string", "Watcher id from 'list_watchers'")))
        t.add("clear_watchers", "Stop all active watchers.", wm.clear_watchers)
