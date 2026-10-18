from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..sjson import Document, parse, to_python


@dataclass(eq=False)
class SourceFile:
    path: Path
    doc: Document
    data: object
    mtime_ns: int
    size: int
    cache: dict = field(default_factory=dict)


_files: dict[Path, SourceFile] = {}
_edited: dict[Path, SourceFile] = {}
_absolute: dict = {}
"""Paths found to be absolute already, which `Path.absolute` is slow to tell."""


def absolute(path) -> Path:
    found = _absolute.get(path)
    if found is None:
        found = Path(path).absolute()
        if found == Path(path):
            _absolute[path] = found
    return found


def read_text(path: Path) -> str:
    return Path(path).read_bytes().decode("utf-8", errors="surrogateescape")


def encode_text(text: str) -> bytes:
    return text.encode("utf-8", errors="surrogateescape")


def load_source_file(path: Path, text: str | None = None) -> SourceFile:
    """Parses a JBeam or part config file; unchanged files come from the cache.

    `text` replaces the file's content on disk, for files edited in memory.
    """
    path = absolute(path)
    if text is not None:
        on_disk = _files.get(path)
        if on_disk is not None and (on_disk.doc.text is text or on_disk.doc.text == text):
            return on_disk
        cached = _edited.get(path)
        if cached is None or cached.doc.text != text:
            doc = parse(text, str(path))
            cached = SourceFile(path, doc, to_python(doc), -1, len(text))
            _edited[path] = cached
        return cached
    stat = path.stat()
    cached = _files.get(path)
    if cached is not None and cached.mtime_ns == stat.st_mtime_ns and cached.size == stat.st_size:
        return cached
    doc = parse(read_text(path), str(path))
    source = SourceFile(path, doc, to_python(doc), stat.st_mtime_ns, stat.st_size)
    _files[path] = source
    return source


def clear_file_cache() -> None:
    _files.clear()
    _edited.clear()
