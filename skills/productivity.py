"""Productivity extras: clipboard history, screen/image OCR, and direct PDF/Word
text extraction — reading a document's text without opening the app that made it.

Clipboard history runs a lightweight background thread that polls the clipboard
(win32clipboard) roughly once a second and keeps the last N unique, non-empty text
entries in memory only; nothing is written to disk, and it's gone when JARVIS exits.
Restoring a past entry is just a copy, not a destructive action, so none of the
clipboard-history reads/restores are confirm-gated — only clearing history is,
since that's a (trivial, in-memory-only) data loss.
"""
from __future__ import annotations

import os
import threading
from collections import deque
from typing import Deque, Optional

from core import clipboard
from core.logging_setup import get_logger

log = get_logger("jarvis.productivity")

_POLL_SECONDS = 1.0
_MAX_HISTORY = 50


class ClipboardHistory:
    """Background poller that remembers recent clipboard text (in memory only)."""

    def __init__(self, poll_seconds: float = _POLL_SECONDS, max_history: int = _MAX_HISTORY):
        self._poll_seconds = poll_seconds
        self._history: Deque[str] = deque(maxlen=max_history)
        self._lock = threading.Lock()
        self._last_seen: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="clipboard-history", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def _read_clipboard() -> Optional[str]:
        try:
            import win32clipboard
        except Exception:
            return None
        try:
            with clipboard.LOCK:
                clipboard.open_clipboard(win32clipboard, attempts=3)
                try:
                    if clipboard.is_excluded_from_history(win32clipboard):
                        return None     # a password manager asked not to be recorded
                    if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                        return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
                    return None
                finally:
                    win32clipboard.CloseClipboard()
        except Exception:
            return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            text = self._read_clipboard()
            if text and text != self._last_seen:
                self._last_seen = text
                with self._lock:
                    if not self._history or self._history[0] != text:
                        self._history.appendleft(text)
            self._stop.wait(self._poll_seconds)

    def list_history(self, limit: int = 20) -> str:
        with self._lock:
            items = list(self._history)[:max(1, min(50, int(limit)))]
        if not items:
            return "Clipboard history is empty."
        lines = []
        for i, text in enumerate(items):
            snippet = text.replace("\n", " ").replace("\r", "")
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            lines.append(f"{i}: {snippet}")
        return "\n".join(lines)

    def get_entry(self, index: int) -> Optional[str]:
        with self._lock:
            items = list(self._history)
        if 0 <= index < len(items):
            return items[index]
        return None

    def clear(self) -> str:
        with self._lock:
            self._history.clear()
        self._last_seen = None
        return "Cleared clipboard history."


class ProductivitySkill:
    """Clipboard history, OCR, and direct document (PDF/Word) text extraction."""

    def __init__(self, app=None):
        self.app = app
        self.clipboard_history = ClipboardHistory()
        self.clipboard_history.start()

    # ── clipboard history ────────────────────────────────────────────────────

    def list_clipboard_history(self, limit: int = 20) -> str:
        return self.clipboard_history.list_history(limit)

    def copy_from_history(self, index) -> str:
        try:
            index = int(index)
        except (TypeError, ValueError):
            return "Give me a clipboard history index — see 'clipboard history' for the list."
        text = self.clipboard_history.get_entry(index)
        if text is None:
            return f"No clipboard history entry at index {index}."
        try:
            import win32clipboard
        except Exception:
            return "Clipboard access isn't available on this platform."
        try:
            with clipboard.LOCK:
                clipboard.open_clipboard(win32clipboard)
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
                finally:
                    win32clipboard.CloseClipboard()
        except Exception as exc:
            return f"Couldn't copy that to the clipboard: {exc}"
        return "Copied to the clipboard."

    def clear_clipboard_history(self) -> str:
        return self.clipboard_history.clear()

    # ── OCR ───────────────────────────────────────────────────────────────────

    def ocr_image(self, path: str, lang: str = "") -> str:
        if not path or not os.path.isfile(path):
            return f"Can't find the image '{path}'."
        try:
            import asyncio
            import winsdk.windows.globalization as globalization_ns
            import winsdk.windows.graphics.imaging as imaging_ns
            import winsdk.windows.media.ocr as ocr_ns
            import winsdk.windows.storage as storage_ns
        except Exception:
            return "OCR needs the optional 'winsdk' package. Install it with: pip install winsdk"

        async def run():
            file = await storage_ns.StorageFile.get_file_from_path_async(path)
            stream = await file.open_async(storage_ns.FileAccessMode.READ)
            decoder = await imaging_ns.BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            if lang:
                engine = ocr_ns.OcrEngine.try_create_from_language(globalization_ns.Language(lang))
            else:
                engine = ocr_ns.OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                return None
            result = await engine.recognize_async(bitmap)
            return result.text

        try:
            text = asyncio.run(run())
        except Exception as exc:
            return f"Couldn't read text from the image: {exc}"
        if text is None:
            return "No OCR engine is available for that language on this PC."
        return text.strip() or "No text found in the image."

    def screen_text(self, region=None) -> str:
        screen = getattr(self.app, "screen_automation", None) if self.app else None
        if screen is None:
            return "Screen capture isn't available."
        try:
            path = screen.take_screenshot(region)
        except Exception as exc:
            return f"Couldn't capture the screen: {exc}"
        return self.ocr_image(path)

    # ── documents ─────────────────────────────────────────────────────────────

    def read_pdf_text(self, path: str, max_pages: int = 20) -> str:
        if not path or not os.path.isfile(path):
            return f"Can't find the file '{path}'."
        try:
            from pypdf import PdfReader
        except Exception:
            return "Reading PDFs needs the optional 'pypdf' package. Install it with: pip install pypdf"
        try:
            reader = PdfReader(path)
        except Exception as exc:
            return f"Couldn't open '{path}': {exc}"
        pages = reader.pages[:max(1, min(200, int(max_pages)))]
        text = "\n".join((p.extract_text() or "") for p in pages).strip()
        return text or "No extractable text found in that PDF (it may be scanned images)."

    def read_docx_text(self, path: str) -> str:
        if not path or not os.path.isfile(path):
            return f"Can't find the file '{path}'."
        try:
            import docx
        except Exception:
            return ("Reading Word documents needs the optional 'python-docx' package. "
                    "Install it with: pip install python-docx")
        try:
            document = docx.Document(path)
        except Exception as exc:
            return f"Couldn't open '{path}': {exc}"
        text = "\n".join(p.text for p in document.paragraphs).strip()
        return text or "No text found in that document."
