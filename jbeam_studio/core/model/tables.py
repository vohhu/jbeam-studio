from __future__ import annotations

import json
import math
import re

from ..diagnostics import CHECKS, TABLE, DiagnosticList
from ..lua import deep_copy, is_dict
from ..sjson import JDict
from .modifiers import DEFAULT_RESETS, is_default

SPECIAL_VALUES = {"FLT_MAX": math.inf, "MINUS_FLT_MAX": -math.inf}
IGNORED_SECTIONS = frozenset({"maxIDs", "options"})
PREPROCESSED_SECTIONS = frozenset({"slots", "slots2"})
_SECTION_NAME = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\Z")


class TableEntry(JDict):
    """A processed table row; `columns` is the header the game used to read its cells."""

    __slots__ = ("columns",)

    def __init__(self, data=(), src=None, columns=()):
        super().__init__(data, src)
        self.columns = tuple(columns)


def replace_special_values(value):
    if isinstance(value, dict):
        for key in list(value):
            value[key] = replace_special_values(value[key])
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = replace_special_values(item)
        return value
    if isinstance(value, str):
        return SPECIAL_VALUES.get(value, value)
    return value


def process_table(rows, input_options, diags: DiagnosticList, section: str = "") -> dict | None:
    """Turns a JBeam table into entries the way the game's table schema does.

    The first row is the header. Dictionary rows set options for all following rows, a dictionary in the cell
    after the last header column sets options for its own row. Entries are keyed by their `id` (kept as `name`)
    or by the row counter, which also counts option rows. Returns None when the header is invalid.
    """
    where = getattr(rows, "src", None)
    header = rows[0] if rows else None
    if not isinstance(header, list) or is_dict(header):
        diags.at(getattr(header, "src", None) or where, "error", TABLE,
                 f'section "{section}": the first row must be the table header, a list of column names')
        return None
    options = replace_special_values(deep_copy(input_options)) if input_options else JDict()
    entries: dict = {}
    inherited = _Inheritance(section)
    for counter, row in enumerate(rows[1:], start=1):
        _process_row(row, counter, header, options, entries, diags, section, where, inherited)
    inherited.report(diags)
    return entries


class _Inheritance:
    """Modifiers that one part leaves set and the rows of later parts get, for the keys worth resetting."""

    def __init__(self, section: str):
        self.section = section
        self.keys = DEFAULT_RESETS.get(section, {})
        self.setters: dict[str, tuple] = {}
        self.found: dict[str, dict] = {}

    def modifier(self, row: dict, options: dict) -> None:
        part = row.get("partOrigin", options.get("partOrigin"))
        for key in row:
            if key in self.keys:
                self.setters[key] = (part, getattr(row, "src", None))

    def data_row(self, entry: dict, own: set) -> None:
        part = entry.get("partOrigin")
        for key, (setter, src) in self.setters.items():
            value = entry.get(key)
            if (setter is None or setter == part or key in own or key not in entry
                    or is_default(key, value, self.keys[key])):
                continue
            leak = self.found.setdefault(setter, {"keys": {}, "parts": [], "src": src})
            leak["keys"].setdefault(key, value)
            if part not in leak["parts"]:
                leak["parts"].append(part)

    def report(self, diags: DiagnosticList) -> None:
        for setter, leak in self.found.items():
            values = ", ".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in leak["keys"].items())
            parts = ", ".join(f'"{p}"' for p in leak["parts"][:3]) + (" \u2026" if len(leak["parts"]) > 3 else "")
            diags.at(leak["src"], "warning", CHECKS,
                     f'part "{setter}" leaves {values} set at the end of "{self.section}", and rows of {parts} get it; '
                     f"Add Resets sets it back", fix=("add_resets", setter))


def _process_row(row, counter, header, options, entries, diags, section, where, inherited=None):
    row_where = getattr(row, "src", None) or where
    if not isinstance(row, (dict, list)):
        diags.at(row_where, "warning", TABLE, f'section "{section}": invalid table row {row!r}, skipped')
        return
    if is_dict(row):
        if isinstance(row, dict):
            if "include" in row:
                diags.at(row_where, "warning", TABLE,
                         f'section "{section}": CSV "include" rows are not supported, the included rows are missing')
                row = JDict({k: v for k, v in row.items() if k != "include"}, src=row.src)
            if inherited is not None:
                inherited.modifier(row, options)
            options.update(replace_special_values(deep_copy(row)))
        return
    header_size = len(header)
    if len(row) > header_size + 1:
        diags.at(row_where, "warning", TABLE,
                 f'section "{section}": row has {len(row)} cells, the header allows {header_size} plus one options '
                 f'cell; skipped')
        return
    entry = TableEntry(deep_copy(options), src=getattr(row, "src", None), columns=header)
    cells = list(row)
    own = set(header)
    if len(cells) == header_size + 1 and is_dict(cells[header_size]):
        if isinstance(cells[header_size], dict):
            entry.update(replace_special_values(deep_copy(cells[header_size])))
            own.update(cells[header_size])
        cells = cells[:header_size]
    variables = entry.get("variables")
    if entry.get("disable") is True or (isinstance(variables, dict) and variables.get("disable") is True):
        return
    for index, value in enumerate(cells):
        if value is None:
            break
        if index >= header_size:
            diags.at(row_where, "warning", TABLE,
                     f'section "{section}": no header column for cell {index + 1}, the cell is ignored')
            continue
        column = header[index]
        if not isinstance(column, (str, int, float)):
            diags.at(row_where, "error", TABLE, f'section "{section}": invalid header column {column!r}')
            continue
        entry[column] = replace_special_values(deep_copy(value))
    if inherited is not None:
        inherited.data_row(entry, own)
    if "id" in entry:
        key = entry.pop("id")
        entry["name"] = key
    else:
        key = counter
    try:
        duplicate = key in entries
    except TypeError:
        diags.at(row_where, "error", TABLE, f'section "{section}": invalid id {key!r}')
        return
    if duplicate:
        earlier = entries[key].get("partOrigin")
        if earlier == entry.get("partOrigin"):
            diags.at(row_where, "warning", TABLE,
                     f'section "{section}": duplicate id "{key}", this row replaces the earlier one')
        else:
            diags.at(row_where, "info", TABLE,
                     f'section "{section}": part "{entry.get("partOrigin")}" redefines "{key}" from part "{earlier}"')
    entries[key] = entry


def process_vehicle_tables(vehicle: dict, diags: DiagnosticList) -> None:
    """Moves top-level values into `options` and converts every list section into entries, like the game."""
    options = vehicle.get("options")
    if not isinstance(options, dict):
        options = JDict()
    for key in list(vehicle):
        if not isinstance(vehicle[key], (dict, list)):
            options[key] = vehicle.pop(key)
    vehicle["options"] = options
    for key in list(vehicle):
        section = vehicle[key]
        if not isinstance(key, str) or not _SECTION_NAME.match(key):
            diags.at(getattr(section, "src", None), "error", TABLE, f'invalid section name "{key}"')
            continue
        if key in IGNORED_SECTIONS or key in PREPROCESSED_SECTIONS or not isinstance(section, list) or not section:
            continue
        entries = process_table(section, options, diags, key)
        vehicle[key] = entries if entries is not None else {}
