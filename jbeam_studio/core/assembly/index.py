from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from ..diagnostics import PARSE, SLOTS, DiagnosticList
from ..lua import deep_copy, ipairs_keyed
from ..model.files import SourceFile, load_source_file
from ..model.tables import process_table
from ..sjson import JDict, JList

SLOTS_HEADER = ("type", "default", "description")
SLOTS2_HEADER = ("name", "allowTypes", "denyTypes", "default", "description")


@dataclass(eq=False)
class PartDef:
    name: str
    file: SourceFile
    slot_types: list[str]
    data: JDict


class PartIndex:
    """Parts of a vehicle folder and the common folder, searched in that order like the game does."""

    def __init__(self, directories: Sequence[Path], diags: DiagnosticList | None = None,
                 overrides: Mapping[Path, str] | None = None, commons: Sequence[Path] = (), closed: bool = False):
        """`overrides` replace file contents; with `closed` they are also the complete set of files, so the
        folders are not listed and files added or removed on disk are not seen."""
        self.directories = [Path(d).absolute() for d in directories]
        self.commons = [Path(c).absolute() for c in commons]
        self.diagnostics = diags if diags is not None else DiagnosticList()
        self.overrides = overrides or {}
        self.closed = closed
        self.files: dict[Path, SourceFile] = {}
        """Every file read, by path."""
        self._parts: list[dict[str, PartDef]] = [self._load_directory(d) for d in self.directories]

    def is_common(self, part: PartDef) -> bool:
        return any(part.file.path.is_relative_to(common) for common in self.commons)

    def directory_parts(self, directory: Path) -> dict[str, PartDef]:
        return self._parts[self.directories.index(Path(directory).absolute())]

    def get(self, name) -> PartDef | None:
        if not isinstance(name, str) or not name:
            return None
        for parts in self._parts:
            part = parts.get(name)
            if part is not None:
                return part
        return None

    def main_part_name(self) -> str | None:
        for parts in self._parts:
            mains = sorted(name for name, part in parts.items() if "main" in part.slot_types)
            if mains:
                if len(mains) > 1:
                    self.diagnostics.add("info", SLOTS, f'several main parts found ({", ".join(mains)}), using "{mains[0]}"')
                return mains[0]
        return None

    def __iter__(self) -> Iterator[PartDef]:
        for parts in self._parts:
            yield from parts.values()

    def jbeam_files(self, directory: Path) -> list[Path]:
        if self.closed:
            found = [p for p in self.overrides if p.suffix.lower() == ".jbeam" and p.is_relative_to(directory)]
        else:
            found = list(directory.rglob("*.jbeam")) if directory.is_dir() else []
        return sorted(found, key=lambda p: str(p).lower())

    def _load_directory(self, directory: Path) -> dict[str, PartDef]:
        parts: dict[str, PartDef] = {}
        if not self.closed and not directory.is_dir():
            self.diagnostics.add("warning", PARSE, f"folder not found: {directory}")
            return parts
        for path in self.jbeam_files(directory):
            source = load_source_file(path, self.overrides.get(path))
            self.files[source.path] = source
            file_parts, file_diags = parts_in_file(source)
            self.diagnostics.extend(file_diags)
            for name, part in file_parts.items():
                kept = parts.get(name)
                if kept is not None:
                    self.diagnostics.at(part.data.src, "warning", SLOTS,
                                        f'duplicate part "{name}", the one in {kept.file.path.name} is used')
                    continue
                parts[name] = part
        return parts


def parts_in_file(source: SourceFile) -> tuple[dict[str, PartDef], DiagnosticList]:
    """Prepared parts of a file and the problems found while preparing them; cached with the file."""
    cached = source.cache.get("parts")
    if cached is None:
        diags = DiagnosticList(source.doc.diagnostics)
        parts: dict[str, PartDef] = {}
        if isinstance(source.data, dict):
            for name, raw in source.data.items():
                part = prepare_part(name, raw, source, diags)
                if part is not None:
                    parts[name] = part
        elif source.doc.root is not None:
            diags.add("error", PARSE, "a JBeam file must be an object of parts", str(source.path), 1, 1)
        cached = (parts, diags)
        source.cache["parts"] = cached
    return cached


def prepare_part(name: str, raw, source: SourceFile, diags: DiagnosticList) -> PartDef | None:
    if not isinstance(raw, dict):
        diags.add("warning", PARSE, f'"{name}" is not a part object, ignored', str(source.path))
        return None
    data = deep_copy(raw)
    normalize_slots(data, name, diags)
    slot_type = data.get("slotType")
    if isinstance(slot_type, str):
        slot_types = [slot_type]
    elif isinstance(slot_type, list):
        slot_types = [t for t in slot_type if isinstance(t, str)]
    else:
        diags.at(data.src, "error", SLOTS, f'part "{name}" has no "slotType", ignored')
        return None
    data["partName"] = name
    return PartDef(name, source, slot_types, data)


def normalize_slots(part: JDict, name: str, diags: DiagnosticList) -> None:
    """Converts `slots` or `slots2` into a list of slot definitions in the `slots2` form, like the game's loader."""
    slots, slots2 = part.get("slots"), part.get("slots2")
    if not isinstance(slots, (dict, list)) and not isinstance(slots2, (dict, list)):
        return
    if isinstance(slots, (dict, list)):
        if isinstance(slots2, list) and slots2:
            diags.at(slots2.src, "warning", SLOTS,
                     f'part "{name}" has "slots" and "slots2"; the game uses "slots" and ignores "slots2"')
        definitions = _legacy_slots(slots, name, diags)
        for slot in definitions:
            slot_type = slot.pop("type", None)
            if slot.get("name") is None and slot_type is not None:
                slot["name"] = slot_type
            slot["allowTypes"] = JList([slot_type] if slot_type is not None else [])
            slot["denyTypes"] = JList()
        source = slots
        del part["slots"]
    else:
        definitions = _slots2(slots2, name, diags)
        source = slots2
    part["slots2"] = JList(definitions, src=getattr(source, "src", None))
    _check_slots(definitions, name, diags)


def _legacy_slots(slots, name: str, diags: DiagnosticList) -> list[JDict]:
    if not isinstance(slots, list) or not slots:
        if slots:
            diags.at(slots.src, "warning", SLOTS, f'"slots" of part "{name}" must be a table, ignored')
        return []
    rows = slots
    first = rows[0] if rows else None
    if isinstance(first, (dict, list)) and not (isinstance(first, list) and first and first[0] == "type"):
        diags.at(rows.src, "warning", SLOTS,
                 f'"slots" of part "{name}" has no table header; using ["type", "default", "description"]')
        rows = JList([JList(SLOTS_HEADER)] + list(rows), src=rows.src)
    entries = process_table(rows, None, diags, "slots")
    if entries is None:
        diags.at(rows.src, "warning", SLOTS, f'"slots" of part "{name}" is invalid, partly reconstructed')
        return _legacy_slots_fallback(rows)
    return list(ipairs_keyed(entries))


def _legacy_slots_fallback(rows) -> list[JDict]:
    definitions = []
    for row in rows:
        if not isinstance(row, list) or (row and row[0] == "type"):
            continue
        slot = JDict(src=getattr(row, "src", None))
        if len(row) > 0 and row[0] is not None:
            slot["type"] = row[0]
        if len(row) > 1 and row[1] is not None:
            slot["default"] = row[1]
        description = row[2] if len(row) > 2 and isinstance(row[2], str) else slot.get("type")
        if description is not None:
            slot["description"] = description
        if len(row) > 3 and isinstance(row[3], dict):
            slot.update(deep_copy(row[3]))
        definitions.append(slot)
    return definitions


def _slots2(slots2, name: str, diags: DiagnosticList) -> list[JDict]:
    if not isinstance(slots2, list) or not slots2:
        if isinstance(slots2, dict) and slots2:
            diags.at(slots2.src, "error", SLOTS, f'"slots2" of part "{name}" must be a table, ignored')
        return []
    header = slots2[0]
    if not (isinstance(header, list) and header and header[0] == "name"):
        header_text = "[" + ", ".join(f'"{column}"' for column in SLOTS2_HEADER) + "]"
        diags.at(getattr(header, "src", None) or slots2.src, "error", SLOTS,
                 f'"slots2" of part "{name}" has no table header, it must be {header_text}')
    entries = process_table(slots2, None, diags, "slots2")
    return list(ipairs_keyed(entries)) if entries is not None else []


def _check_slots(definitions: list[JDict], name: str, diags: DiagnosticList) -> None:
    seen: set[str] = set()
    for slot in definitions:
        slot_id = slot.get("name")
        if not isinstance(slot_id, str) or not slot_id:
            diags.at(slot.src, "error", SLOTS, f'a slot of part "{name}" has no name')
            continue
        if slot_id in seen:
            diags.at(slot.src, "warning", SLOTS,
                     f'slot "{slot_id}" is defined more than once in part "{name}"; '
                     f'a part config fills all of them with the same part')
        seen.add(slot_id)
        for key in ("allowTypes", "denyTypes"):
            if key in slot and not isinstance(slot[key], list):
                diags.at(slot.src, "error", SLOTS, f'slot "{slot_id}": "{key}" must be a list of slot types')
        allow = slot.get("allowTypes")
        if not any(isinstance(t, str) for t in (allow if isinstance(allow, list) else [])):
            diags.at(slot.src, "warning", SLOTS, f'slot "{slot_id}" has no "allowTypes", no part fits into it')
