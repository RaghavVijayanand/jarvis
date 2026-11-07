"""One process-wide gate for the Win32 clipboard.

``OpenClipboard(None)`` ties the clipboard to the calling *task*, not the
thread, so two JARVIS threads can both "open" it at once. When one of them
closes it while the other is still copying a handle out with
``GetClipboardData``, the heap is corrupted and the whole process dies
(0xC0000374). Every clipboard read/write in JARVIS goes through this lock.
"""
from __future__ import annotations

import threading
import time

LOCK = threading.RLock()

# Password managers (KeePass, 1Password, Bitwarden...) put this format on the
# clipboard to ask history/monitoring tools not to record the copy.
_EXCLUDE_FORMAT_NAME = "ExcludeClipboardContentFromMonitorProcessing"


def open_clipboard(win32clipboard, attempts: int = 10) -> None:
    """Another app may hold the clipboard for a moment; retry briefly. Caller holds LOCK."""
    for i in range(attempts):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(0.05)


def is_excluded_from_history(win32clipboard) -> bool:
    """True when the current contents ask not to be monitored. Clipboard must be open."""
    try:
        fmt = win32clipboard.RegisterClipboardFormat(_EXCLUDE_FORMAT_NAME)
        return bool(fmt) and bool(win32clipboard.IsClipboardFormatAvailable(fmt))
    except Exception:
        return False


def mark_private(win32clipboard) -> None:
    """Flag the contents just set as not-for-history. Clipboard must be open."""
    try:
        fmt = win32clipboard.RegisterClipboardFormat(_EXCLUDE_FORMAT_NAME)
        if fmt:
            win32clipboard.SetClipboardData(fmt, b"0")
    except Exception:
        pass
