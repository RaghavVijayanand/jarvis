import os
import hashlib
import re
import threading
import time
import shutil
from pathlib import Path
from datetime import datetime

class FileManagerSkill:
    def __init__(self):
        # Default to the user's Documents folder, falling back to the user's
        # home directory (frozen EXEs are often installed to non-writable
        # locations, so the app folder is a poor default — see audit UC 7.1).
        self.current_directory = str(self._default_documents_folder())
        self._pending_overwrite = None
        self._write_lock = threading.RLock()

    @staticmethod
    def _default_documents_folder() -> Path:
        home = Path.home()
        documents = home / "Documents"
        try:
            documents.mkdir(parents=True, exist_ok=True)
            return documents
        except Exception:
            return home

    
    def route_command(self, command):
        """Deterministic file syntax; None means the request belongs elsewhere."""
        text = command.strip()
        answer = text.casefold().rstrip('.!?')
        with self._write_lock:
            pending = self._pending_overwrite
            if pending and answer in {'no', 'cancel', 'cancel overwrite'}:
                self._pending_overwrite = None
                return 'Overwrite cancelled. The file was not changed.'
            if answer in {'yes', 'confirm', 'overwrite'} or answer.startswith('overwrite '):
                if not pending:
                    return 'There is no pending file overwrite to confirm.' if answer.startswith('overwrite') else None
                if answer.startswith('overwrite ') and answer[10:].strip(' "\'') != pending['path'].name.casefold():
                    return 'That filename does not match the pending overwrite. Say yes or cancel.'
                self._pending_overwrite = None
                if time.monotonic() - pending['created'] > 120:
                    return 'Overwrite confirmation expired. Please repeat the create-file request.'
                try:
                    path = pending['path']
                    if path.is_symlink() or not path.is_file() or self._fingerprint(path) != pending['fingerprint']:
                        return 'The file changed since the request. Nothing was overwritten; please repeat the request.'
                    return self._write_file(path, pending['content'], overwrite=True)
                except OSError as error:
                    return f'Unable to confirm overwrite: {error}'
            # An unrelated turn invalidates a pending confirmation, preventing a
            # later conversational 'yes' from approving a stale operation.
            self._pending_overwrite = None
        match = re.fullmatch(r'(?:please\s+)?create\s+file\s+(?!(?:called|named)\s)(.+?)(?:\s+with\s+content\s+([\s\S]*))?', text, re.IGNORECASE)
        if match:
            name, content = match.group(1), match.group(2) or ''
            where = re.fullmatch(r"(.+?)\s+(?:on|in)\s+(?:my\s+|the\s+)?(desktop|documents|downloads)(?:\s+folder)?",
                                 name, re.IGNORECASE)
            if where:
                return self.create_file_at_location(where.group(1), content, where.group(2))
            return self.create_file(name, content)
        if answer in {'list files', 'show files', 'list my files'}:
            return self.list_files()
        m = re.fullmatch(r"(?:please\s+)?(?:create|make)\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?file\s+(?:called|named)\s+"
                         r"(.+?)(?:\s+(?:on|in)\s+(?:my\s+|the\s+)?(desktop|documents|downloads)(?:\s+folder)?)?"
                         r"(?:\s+(?:with(?:\s+(?:the\s+)?(?:content|contents|text))?|containing|saying|that\s+says)"
                         r"\s*:?\s+([\s\S]*))?", text, re.IGNORECASE)
        if m:
            return self.create_file_at_location(m.group(1), m.group(3) or '', m.group(2) or '')
        m = re.fullmatch(r"(?:please\s+)?rename\s+(?:the\s+)?(file\s+)?(.+?)\s+(?:to|as)\s+(.+)", text, re.IGNORECASE)
        # "rename this playlist to chill" is not a file operation: without the word
        # "file", the source must look like a file name or a path.
        if m and (m.group(1) or re.search(r"\.\w{1,5}\b|[/\\]", m.group(2))):
            m = (m.group(2), m.group(3))
        else:
            m = None
        if m:
            return self.rename_file(m[0], m[1])
        m = re.fullmatch(r"(?:please\s+)?(copy|move)\s+(?:the\s+)?(?:file\s+)?(.+?)\s+to\s+(.+)", text, re.IGNORECASE)
        if m and re.search(r"\.\w{1,5}\b|/|\\\\", m.group(2)):
            return (self.copy_file if m.group(1).lower() == 'copy' else self.move_file)(m.group(2), m.group(3))
        m = re.fullmatch(r"(?:please\s+)?open\s+(?:the\s+|my\s+)?(?:file\s+|folder\s+)?(.+?\.(?:txt|md|pdf|docx?|xlsx?|pptx?|csv|json|py|js|html?|png|jpe?g|gif|mp3|mp4|log|zip|ini|xml)|.+?\s+folder)", text, re.IGNORECASE)
        if m:
            target = re.sub(r"\s+folder$", "", m.group(1), flags=re.IGNORECASE)
            return self.open_path(target)
        m = re.fullmatch(r"(?:please\s+)?open\s+(?:the\s+|my\s+)(.+?)\s+(spreadsheet|document|doc|presentation|slides|deck|pdf)",
                         text, re.IGNORECASE)
        if m:
            found = self._find_by_description(m.group(1), m.group(2).lower())
            if found is not None:
                return self.open_path(str(found))
        m = re.fullmatch(r"(?:please\s+)?(?:list|show)\s+(?:the\s+|my\s+)?(?:files|contents)\s+(?:in|of|on)\s+(?:my\s+|the\s+)?(.+)", text, re.IGNORECASE)
        if m:
            return self.list_files(re.sub(r"\s+folder$", "", m.group(1), flags=re.IGNORECASE))
        if answer in {'where am i', 'current folder', 'current directory', 'pwd'}:
            return self.get_current_directory()
        # 'delete file' is deliberately absent: deletes always go through JARVIS's yes/no
        # confirmation (jarvis._route / handlers.files), never straight from here.
        for verb, method in (('read file', self.read_file),
                             ('create folder', self.create_folder), ('change directory', self.change_directory),
                             ('file info', self.get_file_info), ('show file', self.read_file),
                             ('open file', self.open_path), ('open folder', self.open_path)):
            if text.casefold().startswith(verb + ' '):
                return method(text[len(verb):].strip())
        return None

    def handle_file_command(self, command: str) -> str:
        response = self.route_command(command)
        if response is not None:
            return response
        return None

    @staticmethod
    def _fingerprint(path):
        return hashlib.sha256(path.read_bytes()).digest()

    def _write_file(self, filepath, content, overwrite=False):
        """Keep content and resolved target together throughout confirmation."""
        with self._write_lock:
            filepath = filepath.absolute()
            if filepath.is_symlink():
                return 'Refusing to overwrite a symbolic link.'
            if filepath.exists() and not overwrite:
                self._pending_overwrite = dict(path=filepath, content=content,
                                              fingerprint=self._fingerprint(filepath), created=time.monotonic())
                return f"File '{filepath.name}' already exists at {filepath.parent}. Reply yes to overwrite, or cancel."
            text = content if content else f"# {filepath.name}\n\nCreated by JARVIS on {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            # Exclusive creation prevents an unseen file from being truncated.
            with filepath.open('w' if overwrite else 'x', encoding='utf-8') as stream:
                stream.write(text)
            self._pending_overwrite = None
            return f"File '{filepath.name}' created successfully at {filepath}\nContent: {len(text)} characters written"
    
    def file_exists(self, filename: str) -> bool:
        """Check whether a file exists in the current directory.
        Accepts names with or without extension and cleans invalid characters.
        Returns True if found, otherwise False.
        """
        try:
            if not filename:
                return False
            name = self._clean_filename(filename)
            # Try exact
            path = Path(self.current_directory) / name
            if path.exists() and path.is_file():
                return True
            # Try with .txt fallback when no extension was provided originally
            if not Path(name).suffix:
                path_txt = Path(self.current_directory) / f"{name}.txt"
                if path_txt.exists() and path_txt.is_file():
                    return True
            return False
        except Exception:
            return False
        
    def create_file(self, filename, content="", overwrite=False):
        """Create a new file with optional content.

        Returns a confirmation prompt for existing files; route_command handles
        the user's next yes/cancel turn without losing the requested content.
        """
        try:
            filepath = self._resolve(filename)
            if not self._has_extension(filepath.name):
                filepath = filepath.with_name(filepath.name + ".txt")
            self._check_writable(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            return self._write_file(filepath, content, overwrite)
            
        except Exception as e:
            return f"Error creating file: {e}"
    
    def create_file_at_location(self, filename, content="", location="", overwrite=False):
        """Create a file at a specific location"""
        try:
            # Clean the filename
            filename = self._clean_filename(filename)
            if not filename:
                raise ValueError("No file name given.")

            # Add .txt extension if no extension provided
            if not self._has_extension(filename):
                filename += ".txt"
            
            # Determine target directory
            loc = (location or "").strip().lower()
            folder = next((f for f in self._KNOWN_FOLDERS if f in loc), None)
            if folder:
                target_dir = Path.home() / folder.title()
            elif location and (os.path.isabs(os.path.expanduser(location))):
                target_dir = Path(os.path.expanduser(location))
            else:
                target_dir = Path(self.current_directory)
            self._check_writable(target_dir / filename)
            
            # Ensure target directory exists
            target_dir.mkdir(parents=True, exist_ok=True)
            
            filepath = target_dir / filename
            
            return self._write_file(filepath, content, overwrite)
            
        except Exception as e:
            return f"Error creating file: {e}"
    
    def read_file(self, filename):
        """Read contents of a file"""
        try:
            filepath = self._find_existing(filename)
            if filepath is None or not filepath.is_file():
                return f"File '{filename}' not found in {self.current_directory}"
            # Only the head of a large file is read; decode it with the BOM's
            # encoding, else UTF-8, else the Windows ANSI code page.
            limit = 64 * 1024
            with open(filepath, 'rb') as f:
                raw = f.read(limit + 1)
            truncated = len(raw) > limit
            raw = raw[:limit]
            content = self._decode_text(raw, truncated)
            if content is None:
                return f"'{filepath.name}' looks like a binary file; I can only read text files."
            if len(content) > 2000 or truncated:
                content = content[:2000] + "\n… (truncated)"

            return f"Contents of '{filepath.name}':\n\n{content}"
            
        except Exception as e:
            return f"Error reading file: {e}"
    
    def delete_file(self, filename):
        """Delete a file"""
        try:
            filepath = self._find_existing(filename)
            if filepath is None:
                return f"File '{filename}' not found"
            if filepath.is_dir():
                return f"'{filepath.name}' is a folder; I only delete individual files."
            self._check_writable(filepath)
            try:
                from send2trash import send2trash
            except ImportError:
                if os.name == "nt":
                    # Never fall back to a permanent delete on the real platform.
                    return (f"I can't move '{filepath.name}' to the Recycle Bin (send2trash is not "
                            "installed), so I left it in place.")
                filepath.unlink()
                return f"File '{filepath.name}' deleted successfully"
            send2trash(str(filepath))
            return f"File '{filepath.name}' deleted (moved to the Recycle Bin)"
            
        except Exception as e:
            return f"Error deleting file: {e}"
    
    def list_files(self, directory=None):
        """List files in current or specified directory"""
        try:
            if directory:
                target_dir = self._resolve(directory)
            else:
                target_dir = Path(self.current_directory)
            
            if not target_dir.exists() or not target_dir.is_dir():
                return f"Directory '{target_dir}' does not exist"
            
            files = []
            folders = []
            
            for item in target_dir.iterdir():
                try:
                    is_file = item.is_file()
                    size = item.stat().st_size if is_file else 0
                except OSError:
                    continue  # unreadable entry (permissions, broken link)
                if is_file:
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024*1024:
                        size_str = f"{size/1024:.1f} KB"
                    else:
                        size_str = f"{size/(1024*1024):.1f} MB"
                    
                    files.append(f"📄 {item.name} ({size_str})")
                elif item.is_dir():
                    folders.append(f"📁 {item.name}/")
            
            result = f"Contents of {target_dir}:\n\n"
            
            if folders:
                result += "Folders:\n"
                for folder in sorted(folders)[:10]:  # Limit to 10 items
                    result += f"  {folder}\n"
                if len(folders) > 10:
                    result += f"  ... and {len(folders) - 10} more folders\n"
                result += "\n"
            
            if files:
                result += "Files:\n"
                for file in sorted(files)[:10]:  # Limit to 10 items
                    result += f"  {file}\n"
                if len(files) > 10:
                    result += f"  ... and {len(files) - 10} more files\n"
            
            if not files and not folders:
                result += "Directory is empty"
            
            return result
            
        except Exception as e:
            return f"Error listing files: {e}"
    
    def create_folder(self, foldername):
        """Create a new folder"""
        try:
            folderpath = self._resolve(foldername)
            self._check_writable(folderpath)
            
            if folderpath.exists():
                return f"Folder '{foldername}' already exists"
            
            folderpath.mkdir(parents=True)
            return f"Folder '{foldername}' created successfully"
            
        except Exception as e:
            return f"Error creating folder: {e}"
    
    def copy_file(self, source, destination):
        """Copy a file"""
        try:
            source_path = self._find_existing(source)
            if source_path is None:
                return f"Source file '{source}' not found"
            dest_path = self._destination(source_path, destination)
            if dest_path.exists():
                return f"'{dest_path.name}' already exists; not overwriting."
            self._check_writable(dest_path)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)
            return f"File copied from '{source}' to '{destination}'"
            
        except Exception as e:
            return f"Error copying file: {e}"
    
    def rename_file(self, old_name, new_name):
        """Rename a file"""
        try:
            old_path = self._find_existing(old_name)
            if old_path is None:
                return f"File '{old_name}' not found"
            new_name = self._clean_filename(new_name)
            if not new_name:
                return "Please give the new name."
            if "/" not in new_name and not self._has_extension(new_name) and old_path.suffix:
                new_name += old_path.suffix
            new_path = old_path.parent / new_name
            self._check_writable(old_path)
            self._check_writable(new_path)

            # A case-only rename ("a.txt" -> "A.txt") on a case-insensitive
            # filesystem is not a collision with itself.
            same = os.path.normcase(str(new_path.absolute())) == os.path.normcase(str(old_path.absolute()))
            if new_path.exists() and not same:
                return f"File '{new_name}' already exists"
            
            old_path.rename(new_path)
            return f"File renamed from '{old_name}' to '{new_name}'"
            
        except Exception as e:
            return f"Error renaming file: {e}"
    
    def get_file_info(self, filename):
        """Get information about a file"""
        try:
            filepath = self._find_existing(filename)
            if filepath is None:
                return f"File '{filename}' not found"
            stat = filepath.stat()
            size = stat.st_size
            
            if size < 1024:
                size_str = f"{size} bytes"
            elif size < 1024*1024:
                size_str = f"{size/1024:.1f} KB"
            else:
                size_str = f"{size/(1024*1024):.1f} MB"
            
            created = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
            modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            return f"File information for '{filepath.name}':\nSize: {size_str}\nCreated: {created}\nModified: {modified}\nPath: {filepath}"
            
        except Exception as e:
            return f"Error getting file info: {e}"
    
    def change_directory(self, directory):
        """Change current working directory"""
        try:
            if str(directory).strip().strip('"\'').lower() in ("..", "up", "parent", "parent folder"):
                new_dir = Path(self.current_directory).resolve().parent
            else:
                new_dir = self._resolve(directory).resolve()
            
            if not new_dir.exists():
                return f"Directory '{directory}' does not exist"
            
            if not new_dir.is_dir():
                return f"'{directory}' is not a directory"
            
            self.current_directory = str(new_dir)
            # Note: intentionally does NOT call os.chdir(); changing the
            # process-wide CWD broke relative paths elsewhere (audit UC 7.4).
            
            return f"Changed directory to {self.current_directory}"
            
        except Exception as e:
            return f"Error changing directory: {e}"
    
    def get_current_directory(self):
        """Get current working directory"""
        return f"Current directory: {self.current_directory}"
    
    _KNOWN_FOLDERS = ("desktop", "documents", "downloads", "pictures", "music", "videos")
    _PROTECTED = ("windows", "program files", "program files (x86)", "programdata",
                  "$recycle.bin", "system volume information", "recovery", "boot")
    # Device names Windows reserves in every folder, with or without an extension.
    _RESERVED = frozenset({"con", "prn", "aux", "nul", "conin$", "conout$"}
                          | {f"{p}{n}" for p in ("com", "lpt") for n in "123456789¹²³"})
    _KIND_EXTENSIONS = {
        "spreadsheet": (".xlsx", ".xlsm", ".xls", ".csv", ".ods"),
        "document": (".docx", ".doc", ".odt", ".rtf", ".pdf", ".txt", ".md"),
        "doc": (".docx", ".doc", ".odt", ".rtf", ".pdf", ".txt", ".md"),
        "presentation": (".pptx", ".ppt", ".odp"),
        "slides": (".pptx", ".ppt", ".odp"),
        "deck": (".pptx", ".ppt", ".odp"),
        "pdf": (".pdf",),
    }

    @staticmethod
    def _has_extension(name) -> bool:
        """'notes.txt' has one; 'Mr. Smith notes' and 'notes' do not."""
        return re.search(r"\.[A-Za-z0-9]{1,10}$", str(name)) is not None

    @staticmethod
    def _decode_text(raw: bytes, truncated: bool = False):
        """Decode a text file's head; None for binary content."""
        for bom, encoding in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe\x00\x00", "utf-32"),
                              (b"\x00\x00\xfe\xff", "utf-32"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
            if raw.startswith(bom):
                if truncated:
                    unit = 4 if encoding == "utf-32" else 2
                    raw = raw[:len(raw) - (len(raw) - len(bom)) % unit]
                return raw.decode(encoding, errors="replace")
        if b"\x00" in raw:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            # A multi-byte character cut by the read limit is not an encoding error.
            if truncated and error.start >= len(raw) - 3:
                try:
                    return raw[:error.start].decode("utf-8")
                except UnicodeDecodeError:
                    pass
        return raw.decode("cp1252", errors="replace")

    def _protected_roots(self):
        """Locations whose modification is a persistence/credential risk."""
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        roots = [Path(appdata) / "Microsoft" / "Windows" / "Start Menu",  # Startup programs
                 Path(appdata) / "Jarvis"]                                 # JARVIS settings / API keys
        return [os.path.normcase(os.path.realpath(r)) for r in roots if os.path.isabs(r)]

    def _destination(self, source: Path, destination) -> Path:
        """Target for copy/move: a folder (existing, known or 'name/') receives the source's name."""
        raw = str(destination).strip().strip('"\'')
        dest = self._resolve(destination)
        known = {Path.home() / f.title() for f in self._KNOWN_FOLDERS}
        if dest.is_dir() or raw.endswith(("/", "\\")) or dest in known:
            dest = dest / source.name
        return dest

    def _find_by_description(self, words, kind):
        """'the budget spreadsheet' -> the newest spreadsheet whose name contains 'budget'."""
        extensions = self._KIND_EXTENSIONS.get(kind, ())
        terms = [w for w in re.split(r"\W+", words.casefold()) if w and w not in ("the", "my", "a")]
        if not terms:
            return None
        folders, seen, hits = [Path(self.current_directory)] + [Path.home() / f for f in
                                                              ("Documents", "Desktop", "Downloads")], set(), []
        for folder in folders:
            key = os.path.normcase(str(folder))
            if key in seen or not folder.is_dir():
                continue
            seen.add(key)
            try:
                for item in folder.iterdir():
                    stem = item.stem.casefold()
                    if item.suffix.lower() in extensions and all(t in stem for t in terms) and item.is_file():
                        hits.append(item)
            except OSError:
                continue
        if not hits:
            return None
        return max(hits, key=lambda p: p.stat().st_mtime)

    def _clean_filename(self, filename):
        """Remove characters Windows forbids, per path component.

        Spaces and sub-folders are kept ("notes/2024 plan.txt" stays a path,
        audit UC 7.2); only <>:"|?* and control characters are replaced.
        """
        filename = str(filename).strip().strip('"\'')
        parts = re.split(r"[\\/]+", filename)
        cleaned = []
        for part in parts:
            part = re.sub(r'[<>:"|?*\x00-\x1f]', "_", part).strip().rstrip(".")
            if part and part not in (".", ".."):
                cleaned.append(part)
        return "/".join(cleaned)

    def _resolve(self, name):
        """Resolve a user path: absolute, ~, 'desktop/…' style known folders, or relative."""
        raw = str(name).strip().strip('"\'')
        if not raw:
            raise ValueError("No file name given.")
        expanded = os.path.expandvars(os.path.expanduser(raw))
        path = Path(expanded)
        if not path.is_absolute():
            first, _, rest = raw.replace("\\", "/").partition("/")
            key = re.sub(r"\s+folder$", "", re.sub(r"^(?:my|the)\s+", "", first.lower().strip()))
            if key in self._KNOWN_FOLDERS:
                path = Path.home() / key.title() / self._clean_filename(rest) if rest else Path.home() / key.title()
            else:
                cleaned = self._clean_filename(raw)
                if not cleaned:
                    # '..' or '.' alone would otherwise name the current folder itself.
                    raise ValueError(f"'{raw}' is not a valid file name.")
                path = Path(self.current_directory) / cleaned
        return path

    def _check_writable(self, path: Path) -> None:
        # Check the literal path and its real target: '..' segments, symlinks
        # and junctions must not reach a system folder.
        absolute = path.absolute()
        real = Path(os.path.realpath(absolute))
        for candidate in (absolute, real):
            parts = [p.lower() for p in candidate.parts[1:3]]
            if parts and parts[0] in self._PROTECTED:
                raise PermissionError(f"JARVIS won't modify system folders ({path.parent}).")
        real_key = os.path.normcase(str(real))
        for root in self._protected_roots():
            if real_key == root or real_key.startswith(root.rstrip(os.sep) + os.sep):
                raise PermissionError(f"JARVIS won't modify protected folders ({path.parent}).")
        stem = path.name.split(".")[0].strip().lower()
        if stem in self._RESERVED:
            raise ValueError(f"'{path.name}' is a reserved Windows device name.")

    def _find_existing(self, name):
        path = self._resolve(name)
        if path.exists():
            return path
        if not self._has_extension(path.name):
            candidate = path.with_name(path.name + ".txt")
            if candidate.exists():
                return candidate
        return None

    def open_path(self, name):
        """Open a file or folder with its default app (Explorer for folders)."""
        try:
            path = self._find_existing(name)
            if path is None:
                return f"'{name}' not found in {self.current_directory}."
            os.startfile(str(path)) if os.name == "nt" else None  # type: ignore[attr-defined]
            return f"Opened {path}."
        except Exception as e:
            return f"Couldn't open '{name}': {e}"

    def move_file(self, source, destination):
        try:
            src = self._find_existing(source)
            if src is None:
                return f"'{source}' not found."
            dest = self._destination(src, destination)
            if dest.exists():
                return f"'{dest}' already exists; not moving."
            self._check_writable(src)
            self._check_writable(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            return f"Moved '{src.name}' to {dest.parent}."
        except Exception as e:
            return f"Error moving file: {e}"

    # ── Archives ─────────────────────────────────────────────────────────────

    def create_archive(self, sources, archive_name):
        """Zip one or more files/folders into a single .zip."""
        try:
            import zipfile
            names = [sources] if isinstance(sources, str) else list(sources)
            if not names:
                return "Tell me what to zip."
            paths = []
            for name in names:
                p = self._find_existing(name) or self._resolve(name)
                if not p.exists():
                    return f"'{name}' not found."
                paths.append(p)
            archive = self._resolve(archive_name)
            if not archive.suffix:
                archive = archive.with_suffix(".zip")
            self._check_writable(archive)
            if archive.exists():
                return f"'{archive.name}' already exists; choose a different name."
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive_key = os.path.normcase(str(archive.absolute()))   # never zip the zip into itself
            file_count = 0
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in paths:
                    if p.is_dir():
                        for f in p.rglob("*"):
                            if f.is_file() and os.path.normcase(str(f.absolute())) != archive_key:
                                zf.write(f, arcname=str(Path(p.name) / f.relative_to(p)))
                                file_count += 1
                    else:
                        zf.write(p, arcname=p.name)
                        file_count += 1
            return f"Created {archive.name} ({archive.stat().st_size:,} bytes, {file_count} file(s))."
        except Exception as e:
            return f"Error creating archive: {e}"

    def extract_archive(self, archive_name, destination=None):
        """Extract a .zip into a folder (default: a same-named folder next to it)."""
        try:
            import zipfile
            archive = self._find_existing(archive_name)
            if archive is None:
                return f"'{archive_name}' not found."
            if archive.suffix.lower() != ".zip":
                return f"I can only extract .zip archives right now (not '{archive.suffix or archive.name}')."
            if not zipfile.is_zipfile(archive):
                return f"'{archive.name}' doesn't look like a valid zip file."
            dest = self._resolve(destination) if destination else archive.with_suffix("")
            self._check_writable(dest)
            dest_real = str(Path(os.path.realpath(dest)))
            with zipfile.ZipFile(archive) as zf:
                clashes = []
                for member in zf.namelist():
                    target = os.path.realpath(os.path.join(dest_real, member))
                    if not (target == dest_real or target.startswith(dest_real + os.sep)):
                        return f"Refusing to extract '{member}' — it would land outside the destination folder."
                    if not member.endswith("/") and os.path.exists(target):
                        clashes.append(member)
                if clashes:
                    return (f"Extracting would overwrite {len(clashes)} existing file(s) in {dest} (e.g. "
                            f"'{clashes[0]}'). Pick an empty destination folder.")
                needed = sum(info.file_size for info in zf.infolist())
                probe = Path(dest_real)
                while not probe.exists() and probe.parent != probe:
                    probe = probe.parent
                free = shutil.disk_usage(probe).free
                if needed > free:
                    return (f"{archive.name} unpacks to {self._human_size(needed)}, more than the "
                            f"{self._human_size(free)} free there.")
                dest.mkdir(parents=True, exist_ok=True)
                zf.extractall(dest)
                member_count = len(zf.namelist())
            return f"Extracted {archive.name} ({member_count} item(s)) to {dest}."
        except Exception as e:
            return f"Error extracting archive: {e}"

    # ── Search & analysis ────────────────────────────────────────────────────

    def search_file_contents(self, query, folder=None, extensions=None, max_results=30):
        """Search for text inside files under a folder (recursive); skips binaries and
        anything too large to be worth grepping."""
        try:
            query = str(query or "").strip()
            if not query:
                return "Tell me what text to search for."
            base = self._resolve(folder) if folder else Path(self.current_directory)
            if not base.is_dir():
                return f"'{folder or base}' is not a folder."
            exts = tuple((e if e.startswith(".") else f".{e}").lower() for e in extensions) if extensions else None
            needle = query.casefold()
            hits = []
            for path in base.rglob("*"):
                if len(hits) >= max_results:
                    break
                try:
                    if not path.is_file() or path.stat().st_size > 5_000_000:
                        continue
                except OSError:
                    continue
                if exts and path.suffix.lower() not in exts:
                    continue
                try:
                    raw = path.read_bytes()[:200_000]
                except OSError:
                    continue
                text = self._decode_text(raw, truncated=len(raw) == 200_000)
                if text is None:
                    continue                       # binary file
                for i, line in enumerate(text.splitlines(), 1):
                    if needle in line.casefold():
                        try:
                            rel = path.relative_to(base)
                        except ValueError:
                            rel = path
                        hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                        break                       # one hit per file keeps the list scannable
            if not hits:
                return f"No files under {base} mention '{query}'."
            more = " (showing the first matches)" if len(hits) >= max_results else ""
            return f"{len(hits)} file(s) match '{query}'{more}:\n" + "\n".join(hits)
        except Exception as e:
            return f"Error searching files: {e}"

    @staticmethod
    def _file_hash(path, chunk_size=1 << 20):
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def find_duplicate_files(self, folder=None, max_groups=15):
        """Group files under a folder by content hash — only exact duplicates count."""
        try:
            base = self._resolve(folder) if folder else Path(self.current_directory)
            if not base.is_dir():
                return f"'{folder or base}' is not a folder."
            by_size = {}
            for path in base.rglob("*"):
                try:
                    if path.is_file():
                        by_size.setdefault(path.stat().st_size, []).append(path)
                except OSError:
                    continue
            groups = []
            for size, paths in by_size.items():
                if size == 0 or len(paths) < 2:
                    continue
                by_hash = {}
                for p in paths:
                    try:
                        by_hash.setdefault(self._file_hash(p), []).append(p)
                    except OSError:
                        continue
                groups.extend(g for g in by_hash.values() if len(g) > 1)
            if not groups:
                return f"No duplicate files found under {base}."
            groups.sort(key=lambda g: -(g[0].stat().st_size * len(g)))
            lines = []
            for g in groups[:max_groups]:
                size = g[0].stat().st_size
                names = ", ".join(str(p.relative_to(base)) for p in g)
                lines.append(f"{len(g)}× {self._human_size(size)} each: {names}")
            wasted = sum(p.stat().st_size for g in groups for p in g[1:])
            header = f"{len(groups)} duplicate group(s), ~{self._human_size(wasted)} could be freed:"
            if len(groups) > max_groups:
                header += f" (showing the {max_groups} largest)"
            return header + "\n" + "\n".join(lines)
        except Exception as e:
            return f"Error finding duplicates: {e}"

    @staticmethod
    def _human_size(n):
        size = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"

    def disk_usage_by_folder(self, folder=None, top=15):
        """Immediate children of ``folder``, sorted by total size — a quick 'what's using my space'."""
        try:
            base = self._resolve(folder) if folder else Path(self.current_directory)
            if not base.is_dir():
                return f"'{folder or base}' is not a folder."
            sizes = []
            for entry in base.iterdir():
                try:
                    if entry.is_dir() and not entry.is_symlink():
                        total = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                    elif entry.is_file():
                        total = entry.stat().st_size
                    else:
                        continue
                except OSError:
                    continue
                sizes.append((entry.name, total))
            if not sizes:
                return f"{base} is empty."
            sizes.sort(key=lambda t: -t[1])
            lines = [f"{self._human_size(size):>8}  {name}" for name, size in sizes[:top]]
            total = sum(s for _, s in sizes)
            return f"{self._human_size(total)} total under {base}:\n" + "\n".join(lines)
        except Exception as e:
            return f"Error reading disk usage: {e}"
