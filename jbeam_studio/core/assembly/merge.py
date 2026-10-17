from __future__ import annotations

from ..diagnostics import TABLE, DiagnosticList
from ..lua import deep_copy, is_number
from ..sjson import JDict

_NOT_MERGED = frozenset({"slots", "slots2", "information"})
_KEPT_SCALARS = frozenset({"slotType", "partName"})


def _slot_options_rows(slot_options: JDict, part_name, part_path: str) -> tuple[JDict, JDict]:
    options = deep_copy(slot_options)
    options["partOrigin"] = part_name
    options["partPath"] = part_path
    reset = JDict({key: "" for key in options}, src=options.src)
    return options, reset


def unify(target: JDict, source: JDict, slot_options: JDict, part_path: str, diags: DiagnosticList) -> None:
    """Merges a child part into its parent like the game: list sections get the child's rows appended under the
    parent's header, wrapped in option rows that carry the slot options and the part origin."""
    for key, section in list(source.items()):
        if key in _NOT_MERGED:
            continue
        if key not in target:
            target[key] = section
            if isinstance(section, list) and section:
                options, reset = _slot_options_rows(slot_options, source.get("partName"), part_path)
                section.insert(1, options)
                section.append(reset)
            continue
        existing = target[key]
        if isinstance(existing, (dict, list)) and isinstance(section, (dict, list)):
            if isinstance(section, list):
                if not section:
                    continue
                if not isinstance(existing, list):
                    diags.at(section.src, "warning", TABLE,
                             f'section "{key}" is a list here but an object in the parent part; not merged')
                    continue
                options, reset = _slot_options_rows(slot_options, source.get("partName"), part_path)
                existing.append(options)
                existing.extend(section[1:])
                existing.append(reset)
                continue
            if not isinstance(existing, dict):
                if existing:
                    diags.at(section.src, "warning", TABLE,
                             f'section "{key}" is an object here but a list in the parent part; not merged')
                    continue
                existing = target[key] = JDict(src=getattr(existing, "src", None))
            _merge_dict(existing, section)
        elif key not in _KEPT_SCALARS:
            target[key] = section


def _merge_dict(existing: dict, section: dict) -> None:
    for key, value in section.items():
        if is_number(value) and isinstance(key, str) and key.startswith("$"):
            actual = key[2:]
            current = existing.get(actual)
            modifier = existing.get(key)
            if is_number(modifier):
                current, actual = modifier, key
            if is_number(current):
                op = key[1:2]
                if op == "+":
                    existing[actual] = current + value
                elif op == "*":
                    existing[actual] = current * value
                elif op == "<":
                    existing[actual] = min(current, value)
                elif op == ">":
                    existing[actual] = max(current, value)
                else:
                    existing[key] = value
            else:
                existing[key] = value
        else:
            existing[key] = value


def merge_named_sections(vehicle: dict, target: str, source: str, diags: DiagnosticList) -> None:
    """Moves the entries of a numbered section such as `rails2` into its base section."""
    entries = vehicle.setdefault(target, {})
    moved = vehicle.pop(source, None)
    if not isinstance(moved, dict) or not isinstance(entries, dict):
        return
    for key, value in moved.items():
        if key in entries:
            diags.at(getattr(value, "src", None), "warning", TABLE,
                     f'"{key}" from section "{source}" replaces the entry in "{target}"')
        if isinstance(value, dict):
            value["originSection"] = source
        entries[key] = value
