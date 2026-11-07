"""Files and folders (deterministic syntax; free-form requests go to the model's file tools)."""
import re

from core.tools import params
from handlers.base import Handler

_DELETE = re.compile(r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?file\s+(.+?)[.!?]*$", re.I)


class FilesHandler(Handler):
    intents = {"FILE"}

    def handle(self, text, intent):
        fs = getattr(self.app, "file_skill", None)
        if fs is None:
            return None
        # A plan step or live-voice clause reaches here without jarvis._route's delete check:
        # deleting must still wait for an explicit yes.
        m = _DELETE.match(text.strip())
        if m and hasattr(self.app, "_ask_to_confirm"):
            target = m.group(1).strip().strip('"\'')
            return self.app._ask_to_confirm(f"Delete the file '{target}'?", lambda: fs.delete_file(target),
                                            "delete_file")
        return fs.handle_file_command(text)

    def register_tools(self, t):
        fs = self.app.file_skill
        t.add("list_files", "List files in a folder (default: current folder; 'desktop', 'downloads' work).",
              lambda path="": fs.list_files(path or None), params(path=("string", "Folder path")))
        t.add("read_file", "Read a text file.", fs.read_file, params(["path"], path=("string", "File path")))
        t.add("create_file", "Create a text file (asks before overwriting).",
              lambda path, content="": fs.create_file(path, content),
              params(["path"], path=("string", "File path, e.g. 'notes/todo.txt' or 'desktop/list.txt'"),
                     content=("string", "Text to write")))
        t.add("rename_file", "Rename a file.", fs.rename_file,
              params(["old_name", "new_name"], old_name=("string", "Existing file"), new_name=("string", "New name")))
        t.add("delete_file", "Delete a file (to the Recycle Bin when possible).", fs.delete_file,
              params(["path"], path=("string", "File path")), confirm=True, confirm_text="Delete the file '{path}'?")
        t.add("create_archive", "Zip one or more files/folders into a single .zip.",
              lambda sources, archive_name: fs.create_archive(
                  [s.strip() for s in sources.split(",")] if isinstance(sources, str) else sources, archive_name),
              params(["sources", "archive_name"],
                    sources=("string", "File/folder path, or several separated by commas"),
                    archive_name=("string", "Name for the new .zip, e.g. 'backup'")))
        t.add("extract_archive", "Extract a .zip file into a folder.", fs.extract_archive,
              params(["archive_name"], archive_name=("string", "The .zip file to extract"),
                    destination=("string", "Optional destination folder")))
        t.add("search_file_contents", "Search for text inside files under a folder (recursive).",
              lambda query, folder="", extensions="": fs.search_file_contents(
                  query, folder or None, [e.strip() for e in extensions.split(",")] if extensions else None),
              params(["query"], query=("string", "Text to search for"),
                    folder=("string", "Folder to search (default: current folder)"),
                    extensions=("string", "Optional comma-separated extensions, e.g. 'txt,md'")))
        t.add("find_duplicate_files", "Find files with identical content under a folder.",
              lambda folder="": fs.find_duplicate_files(folder or None),
              params(folder=("string", "Folder to scan (default: current folder)")))
        t.add("disk_usage_by_folder", "Show what's using space under a folder, largest first.",
              lambda folder="": fs.disk_usage_by_folder(folder or None),
              params(folder=("string", "Folder to check (default: current folder)")))
