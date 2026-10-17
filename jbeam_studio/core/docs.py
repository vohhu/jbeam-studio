"""Short descriptions of JBeam keys with links to the BeamNG documentation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA_FILE = Path(__file__).with_name("docs_data.json")


@dataclass(frozen=True)
class DocEntry:
    section: str
    key: str
    description: str
    type: str
    default: str
    url: str


@lru_cache(maxsize=1)
def _entries() -> dict[tuple[str, str], DocEntry]:
    data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return {(e["section"], e["key"].rstrip(":")): DocEntry(**e) for e in data["entries"]}


def lookup(section: str, key: str) -> DocEntry | None:
    """Documentation for a key of a section; link keys match with or without their trailing colon."""
    return _entries().get((section, key.rstrip(":")))


def all_entries() -> list[DocEntry]:
    return list(_entries().values())
