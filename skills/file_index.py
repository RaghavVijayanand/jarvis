"""Local file search: a small, persistent keyword index over the text of files
under folders you've indexed — including PDFs and Word docs (via
skills/productivity.py's extractors), which the live grep in
skills/file_manager.py's ``search_file_contents`` can't read.

This is plain keyword/TF-IDF-style ranking, not embeddings — no model download,
works fully offline, and is good enough for "find the doc where I discussed the
Q3 budget" without needing exact filenames.

Indexing only reads files and writes JARVIS's own index file, so none of it is
confirm-gated — the same reasoning as clipboard history: rebuildable, no real
user data is ever changed or lost.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from core.config import Config
from core.logging_setup import get_logger

log = get_logger("jarvis.file_index")

_INDEX_FILE = Config.DATA_DIR / "file_index.json"
_DEFAULT_EXTENSIONS = (".txt", ".md", ".log", ".csv", ".json", ".py", ".js", ".html", ".pdf", ".docx")
_MAX_FILE_BYTES = 5_000_000
_MAX_FILES = 5000
_MAX_VISITED = 200_000        # entries walked (matching or not) per add_folder
_isjunction = getattr(os.path, "isjunction", lambda path: False)     # Python 3.12+
_WORD_RE = re.compile(r"[a-z0-9]+")

_PDF_FAILURE_PREFIXES = ("Can't find", "Couldn't open", "No extractable", "Reading PDFs needs")
_DOCX_FAILURE_PREFIXES = ("Can't find", "Couldn't open", "No text found", "Reading Word documents needs")


def _tokenize(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower())


class FileIndex:
    """A small, persistent keyword index over text/PDF/docx files."""

    def __init__(self, productivity=None, index_file=None):
        self.productivity = productivity
        self.index_file = Path(index_file) if index_file else _INDEX_FILE
        self._data = self._load()

    # ── building ─────────────────────────────────────────────────────────────

    def add_folder(self, folder: str, extensions: Optional[List[str]] = None) -> str:
        if not (folder or "").strip():
            return "Which folder should I index?"       # Path('') is '.', JARVIS's own working folder
        folder_path = Path(folder.strip()).expanduser()
        if not folder_path.is_dir():
            return f"'{folder}' is not a folder."
        exts = tuple((e if e.startswith(".") else f".{e}").lower() for e in extensions) if extensions \
            else _DEFAULT_EXTENSIONS
        indexed = skipped = seen = 0
        for path in self._walk(folder_path):
            if seen >= _MAX_FILES:
                break
            if path.suffix.lower() not in exts:
                continue
            seen += 1
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    skipped += 1
                    continue
            except OSError:
                skipped += 1
                continue
            text = self._extract_text(path)
            if text is None:
                skipped += 1
                continue
            self._index_file_entry(path, text)
            indexed += 1
        self._save()
        return f"Indexed {indexed} file(s) under '{folder}'" + (f" ({skipped} skipped)." if skipped else ".")

    @staticmethod
    def _walk(root: Path):
        """Files under ``root`` without following symlinks or junctions (which can loop back up
        the tree), and with a cap on entries visited, so 'index C:\\' can't run for hours."""
        visited = 0
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames
                           if not (os.path.islink(os.path.join(dirpath, d))
                                   or _isjunction(os.path.join(dirpath, d)))]
            for name in filenames:
                visited += 1
                if visited > _MAX_VISITED:
                    return
                yield Path(dirpath) / name

    @staticmethod
    def _under(path: str, folder: str) -> bool:
        path, folder = os.path.normcase(path), os.path.normcase(folder).rstrip("\\/")
        return path == folder or path.startswith(folder + os.sep)

    def _extract_text(self, path: Path) -> Optional[str]:
        suffix = path.suffix.lower()
        try:
            if suffix == ".pdf":
                if self.productivity is None:
                    return None
                text = self.productivity.read_pdf_text(str(path))
                return None if text.startswith(_PDF_FAILURE_PREFIXES) else text
            if suffix == ".docx":
                if self.productivity is None:
                    return None
                text = self.productivity.read_docx_text(str(path))
                return None if text.startswith(_DOCX_FAILURE_PREFIXES) else text
            raw = path.read_bytes()[:_MAX_FILE_BYTES]
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return None

    def _index_file_entry(self, path: Path, text: str) -> None:
        tokens = _tokenize(text)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        self._data["files"][str(path)] = {
            "terms": dict(Counter(tokens)), "length": len(tokens), "mtime": mtime,
            "snippet": text[:300].strip(),
        }

    def remove_folder(self, folder: str) -> str:
        if not (folder or "").strip():
            return "Which folder should I remove from the index?"     # '' would match every path
        folder_path = str(Path(folder.strip()).expanduser().absolute())
        before = len(self._data["files"])
        # A path-boundary match: removing 'C:\Docs' must leave 'C:\Docs2' alone.
        self._data["files"] = {p: v for p, v in self._data["files"].items() if not self._under(p, folder_path)}
        removed = before - len(self._data["files"])
        self._save()
        return f"Removed {removed} file(s) under '{folder}' from the index."

    def clear_index(self) -> str:
        count = len(self._data["files"])
        self._data = {"files": {}}
        self._save()
        return f"Cleared the file index ({count} file(s))."

    def index_status(self) -> str:
        files = self._data["files"]
        if not files:
            return "The file index is empty. Add a folder with 'index folder <path>'."
        total_terms = sum(v["length"] for v in files.values())
        return f"{len(files)} file(s) indexed, {total_terms} word(s) total."

    # ── searching ────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> str:
        query_terms = set(_tokenize(query))
        if not query_terms:
            return "Tell me what to search for."
        files = self._data["files"]
        if not files:
            return "The file index is empty. Add a folder with 'index folder <path>'."
        n_docs = len(files)
        dfs = {term: sum(1 for entry in files.values() if term in entry["terms"]) for term in query_terms}
        scores: Dict[str, float] = {}
        for path, entry in files.items():
            terms = entry["terms"]
            length = max(entry["length"], 1)
            score = 0.0
            for term in query_terms:
                tf = terms.get(term, 0)
                if tf == 0:
                    continue
                idf = math.log((n_docs + 1) / (dfs[term] + 1)) + 1
                score += (tf / length) * idf
            if score > 0:
                scores[path] = score
        if not scores:
            return f"No indexed files match '{query}'."
        limit = max(1, min(30, int(limit)))
        # Files deleted since indexing would otherwise keep showing up as results.
        ranked = [kv for kv in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
                  if os.path.exists(kv[0])][:limit]
        if not ranked:
            return f"No indexed files match '{query}' (the matching files have since been deleted)."
        lines = []
        for path, _score in ranked:
            snippet = files[path]["snippet"].replace("\n", " ").replace("\r", "")
            if len(snippet) > 140:
                snippet = snippet[:137] + "..."
            lines.append(f"• {path}\n    {snippet}")
        return "\n".join(lines)

    # ── storage ──────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self.index_file.exists():
            return {"files": {}}
        try:
            with self.index_file.open(encoding="utf-8-sig") as stream:
                data = json.load(stream)
            if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
                return {"files": {}}
            return data
        except (OSError, ValueError):
            return {"files": {}}

    def _save(self) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.index_file.parent,
                                            delete=False) as stream:
                temp = stream.name
                json.dump(self._data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.index_file)
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)
