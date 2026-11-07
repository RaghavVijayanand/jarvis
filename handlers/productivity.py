"""Clipboard history, screen/image OCR, and PDF/Word text extraction. All reads
run immediately (including restoring a clipboard-history entry, which is just a
copy); only clearing clipboard history confirms first, since that's a data loss
even though it's trivial and in-memory only."""
import re

from core.tools import params
from handlers.base import Handler

_CLEAR_HISTORY = re.compile(r"^(?:please\s+)?clear\s+(?:the\s+)?clipboard\s+history[.!?]*$", re.I)
_LIST_HISTORY = re.compile(r"\bclipboard\s+history\b", re.I)
_COPY_FROM_HISTORY = re.compile(r"^(?:please\s+)?copy\s+(?:entry\s+)?(\d+)\s+from\s+(?:clipboard\s+)?history"
                                r"[.!?]*$", re.I)
_PASTE_HISTORY_ITEM = re.compile(r"^(?:please\s+)?paste\s+history\s+item\s+(\d+)[.!?]*$", re.I)
_SCREEN_TEXT = re.compile(r"\b(?:ocr|extract text from|get text from)\s+(?:my |the )?screen\b|"
                          r"\bwhat does (?:my |the )?screen say\b|"
                          r"\bread\s+(?:the\s+)?text\s+(?:in|from|on)\s+(?:this |the |my )?screen\b", re.I)
_IMAGE_TEXT = re.compile(r"^(?:please\s+)?(?:ocr|extract text from|get text from|read the text (?:in|from) )\s*"
                         r"(?:this |the )?(?:image|picture|photo)\s+(.+?)[.!?]*$", re.I)
_PDF_TEXT = re.compile(r"^(?:please\s+)?read\s+(?:the\s+text\s+(?:in|from)\s+)?(?:the\s+|this\s+)?pdf\s+(.+?)"
                       r"[.!?]*$", re.I)
_DOCX_TEXT = re.compile(r"^(?:please\s+)?read\s+(?:the\s+text\s+(?:in|from)\s+)?(?:the\s+|this\s+)?"
                        r"(?:docx?|word document)\s+(.+?)[.!?]*$", re.I)


class ProductivityHandler(Handler):
    intents = {"PRODUCTIVITY"}

    def handle(self, text, intent):
        app = self.app
        pr = getattr(app, "productivity", None)
        if pr is None:
            return "Productivity extras aren't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        if _CLEAR_HISTORY.match(low):
            return confirm("Clear clipboard history?", lambda: pr.clear_clipboard_history(), "clear_clipboard_history")
        m = _COPY_FROM_HISTORY.match(low) or _PASTE_HISTORY_ITEM.match(low)
        if m:
            return pr.copy_from_history(int(m.group(1)))
        if _LIST_HISTORY.search(low):
            return pr.list_clipboard_history()
        if _SCREEN_TEXT.search(low):
            return pr.screen_text()
        m = _IMAGE_TEXT.match(low)
        if m:
            return pr.ocr_image(m.group(1).strip())
        m = _PDF_TEXT.match(low)
        if m:
            return pr.read_pdf_text(m.group(1).strip())
        m = _DOCX_TEXT.match(low)
        if m:
            return pr.read_docx_text(m.group(1).strip())
        return None

    def register_tools(self, t):
        pr = getattr(self.app, "productivity", None)
        if pr is None:
            return
        t.add("list_clipboard_history", "List recent clipboard text entries (most recent first).",
              lambda limit=20: pr.list_clipboard_history(limit),
              params(limit=("integer", "How many entries to show")))
        t.add("copy_from_clipboard_history", "Restore a past clipboard-history entry to the clipboard.",
              pr.copy_from_history, params(["index"], index=("integer", "Index from 'list_clipboard_history'")))
        t.add("clear_clipboard_history", "Clear the in-memory clipboard history.", pr.clear_clipboard_history,
              confirm=True, confirm_text="Clear clipboard history?")
        t.add("ocr_image", "Read text out of an image file using OCR.", pr.ocr_image,
              params(["path"], path=("string", "Path to the image file"),
                    lang=("string", "BCP-47 language tag, e.g. 'en-US' (optional)")))
        t.add("screen_text", "Take a screenshot and read any text on it using OCR.",
              lambda: pr.screen_text())
        t.add("read_pdf_text", "Extract the text from a PDF file.", pr.read_pdf_text,
              params(["path"], path=("string", "Path to the PDF file"),
                    max_pages=("integer", "Maximum number of pages to read")))
        t.add("read_docx_text", "Extract the text from a Word (.docx) document.", pr.read_docx_text,
              params(["path"], path=("string", "Path to the .docx file")))
