"""Local file search: index folders of text/PDF/docx files, then search their
content by keyword. Indexing/searching only reads files and writes JARVIS's
own index, so none of it is confirm-gated."""
import re

from core.tools import params
from handlers.base import Handler

_ADD_FOLDER = re.compile(r"^(?:please\s+)?index\s+(?:the\s+)?folder\s+(.+?)[.!?]*$", re.I)
_REMOVE_FOLDER = re.compile(r"^(?:please\s+)?(?:remove|unindex)\s+(?:the\s+)?folder\s+(.+?)\s+from\s+"
                            r"(?:the\s+)?index[.!?]*$", re.I)
_CLEAR_INDEX = re.compile(r"^(?:please\s+)?clear\s+(?:the\s+|my\s+)?file\s+index\b", re.I)
_INDEX_STATUS = re.compile(r"\bfile\s+index\s+status\b|\bhow\s+many\s+files\s+are\s+indexed\b", re.I)
_SEARCH_FILES = re.compile(r"^(?:please\s+)?search\s+(?:my\s+|indexed\s+)?files\s+for\s+(.+?)[.!?]*$", re.I)
_FIND_FILE = re.compile(r"^(?:please\s+)?find\s+(?:the\s+)?(?:file|document)\s+(?:about|where|that)\s+"
                        r"(.+?)[.!?]*$", re.I)


class FileIndexHandler(Handler):
    intents = {"FILEINDEX"}

    def handle(self, text, intent):
        app = self.app
        fi = getattr(app, "file_index", None)
        if fi is None:
            return "The file index isn't available."
        low = text.strip()

        m = _ADD_FOLDER.match(low)
        if m:
            return fi.add_folder(m.group(1).strip())
        m = _REMOVE_FOLDER.match(low)
        if m:
            return fi.remove_folder(m.group(1).strip())
        if _CLEAR_INDEX.search(low):
            return fi.clear_index()
        if _INDEX_STATUS.search(low):
            return fi.index_status()
        m = _SEARCH_FILES.match(low)
        if m:
            return fi.search(m.group(1).strip())
        m = _FIND_FILE.match(low)
        if m:
            return fi.search(m.group(1).strip())
        return None

    def register_tools(self, t):
        fi = getattr(self.app, "file_index", None)
        if fi is None:
            return
        t.add("index_folder", "Index a folder's text/PDF/docx files for local keyword search.", fi.add_folder,
              params(["folder"], folder=("string", "Folder path to index"),
                    extensions=("array", "File extensions to include (optional, e.g. ['.txt', '.pdf'])")))
        t.add("remove_indexed_folder", "Remove a folder's files from the file index.", fi.remove_folder,
              params(["folder"], folder=("string", "Folder path to remove")))
        t.add("clear_file_index", "Clear the entire file index.", fi.clear_index)
        t.add("file_index_status", "Show how many files/words are in the file index.", fi.index_status)
        t.add("search_indexed_files", "Search indexed files by keyword; returns ranked matches with snippets.",
              fi.search, params(["query"], query=("string", "Search terms"),
                               limit=("integer", "Max results (optional, default 10)")))
