"""Text edits on JBeam documents that touch only the edited values, rows and sections."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..sjson import Document, Kind, Member, Node

DEFAULT_DECIMALS = 3
_EDITOR_SHIFT = re.compile(r"^\$=(\$[A-Za-z0-9_]+|\(.*\)) ([+-]) (\d+(?:\.\d+)?)$", re.S)
_VARIABLE = re.compile(r"^\$[A-Za-z0-9_]+$")
_TRIVIA = re.compile(r"(?:\s|,|//[^\n]*|/\*.*?\*/)*", re.S)


class TextEditError(Exception):
    pass


@dataclass(frozen=True)
class TextEdit:
    """A replacement of `text[start:end]`; `target` is the span of the syntax node the edit is meant to change."""

    start: int
    end: int
    text: str
    target: tuple[int, int] | None = None


def apply_edits(text: str, edits: list[TextEdit]) -> str:
    """Applies non-overlapping edits; identical duplicates are applied once."""
    unique = sorted({e for e in edits if e.text or e.start != e.end}, key=lambda e: (e.start, e.end), reverse=True)
    previous_start = len(text) + 1
    for edit in unique:
        if edit.end > previous_start or (edit.end == previous_start and edit.start == edit.end == previous_start):
            raise TextEditError(f"overlapping edits at offset {edit.start}")
        text = text[:edit.start] + edit.text + text[edit.end:]
        previous_start = edit.start
    return text


def outside_target(text: str, edit: TextEdit) -> str | None:
    """Why an edit reaches beyond its target node, if it does.

    An edit may replace text inside its target, insert inside it, or remove its target together with the
    spaces, commas and comments around it, but nothing else.
    """
    if edit.target is None:
        return "the edit has no target"
    start, end = edit.target
    if edit.start == edit.end:
        return None if start <= edit.start <= end else "the insertion is outside its target"
    if start <= edit.start and edit.end <= end:
        return None
    if not (edit.start <= start and end <= edit.end):
        return "the edit overlaps its target only partly"
    removed = text[edit.start:start] + text[end:edit.end]
    if _TRIVIA.fullmatch(removed):
        return None
    return f"the edit would also remove {removed.strip()[:60]!r}"


def literal_decimals(text: str) -> int:
    mantissa = re.split(r"[eE]", text, maxsplit=1)[0]
    return len(mantissa.split(".", 1)[1]) if "." in mantissa else 0


def format_number(value: float, decimals: int = DEFAULT_DECIMALS) -> str:
    text = f"{value:.{decimals}f}"
    if float(text) == 0:
        text = f"{0:.{decimals}f}"
    return text


def json_literal(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, float):
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return repr(value)
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def modifier_text(values: dict) -> str:
    """A modifier row in the compact style of the game's files: {"beamPrecompression":1, "beamType":"|NORMAL"}."""
    return "{" + ", ".join(f"{json.dumps(k, ensure_ascii=False)}:{json_literal(v)}" for k, v in values.items()) + "}"


def shift_expression(expression: str, delta: float, decimals: int = DEFAULT_DECIMALS) -> str:
    """Adds `delta` to an expression or variable, reusing the offset term a previous shift added."""
    match = _EDITOR_SHIFT.match(expression)
    if match:
        inner, op, number = match.groups()
        offset = (float(number) if op == "+" else -float(number)) + delta
    elif expression.startswith("$="):
        inner, offset = f"({expression[2:].strip()})", delta
    elif _VARIABLE.match(expression):
        inner, offset = expression, delta
    else:
        raise TextEditError(f'"{expression}" is neither a number, a variable nor an expression')
    if float(format_number(abs(offset), decimals)) == 0:
        return inner if inner.startswith("$") else "$=" + inner[1:-1]
    return f"$={inner} {'+' if offset >= 0 else '-'} {format_number(abs(offset), decimals)}"


def newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def line_start(text: str, offset: int) -> int:
    return text.rfind("\n", 0, offset) + 1


def line_end(text: str, offset: int) -> int:
    end = text.find("\n", offset)
    if end < 0:
        return len(text)
    return end - 1 if end > 0 and text[end - 1] == "\r" else end


def indent_at(text: str, offset: int) -> str:
    start = line_start(text, offset)
    return re.match(r"[ \t]*", text[start:]).group()


def _indent_unit(outer: str, inner: str) -> str:
    if inner.startswith(outer) and len(inner) > len(outer):
        return inner[len(outer):]
    return "\t" if "\t" in inner else "    "


def format_row(cells: list[str], template: Node | None, text: str) -> str:
    """A table row whose cells line up with the columns of `template`, a neighbouring row."""
    if template is None or template.kind is not Kind.ARRAY or not template.items:
        return "[" + ", ".join(cells) + "]"
    starts = [item.start - template.start for item in template.items]
    spaced = any(text[a.end:b.start].strip(", ") == "" and " " in text[a.end:b.start]
                 for a, b in zip(template.items, template.items[1:]))
    out = "["
    for index, cell in enumerate(cells):
        if index > 0:
            out += ","
            gap = starts[index] - len(out) if index < len(starts) else 0
            out += " " * (gap if gap > 0 else (1 if spaced else 0))
        out += cell
    return out + "]"


def replace_value(node: Node, text: str) -> TextEdit:
    return TextEdit(node.start, node.end, text, (node.start, node.end))


def insert_into(node: Node, position: int, text: str) -> TextEdit:
    return TextEdit(position, position, text, (node.start, node.end))


def insert_row(doc: Document, table: Node, cells: list[str]) -> TextEdit:
    """Appends a row to the end of a table, on its own line with the indentation of the rows above."""
    return insert_rows(doc, table, [cells])


def insert_rows(doc: Document, table: Node, rows: list[list[str]], after: Node | None = None) -> TextEdit:
    """Adds rows after the row `after`, or at the end of the table, lined up with the rows around them."""
    text = doc.text
    template = after if after is not None and after.kind is Kind.ARRAY else next(
        (item for item in reversed(table.items[1:]) if item.kind is Kind.ARRAY), table.items[0])
    return insert_values(doc, table, [format_row(cells, template, text) for cells in rows], after)


def insert_values(doc: Document, table: Node, formatted: list[str], after: Node | None = None) -> TextEdit:
    """Adds value texts, such as rows or modifier rows, after the item `after` or at the end of a table.

    After an item that shares its line with the next item the values go on that line too, as in tables
    written with several rows per line; otherwise each value gets its own line.
    """
    text = doc.text
    if after is not None and after is not table.items[-1]:
        following = table.items[table.items.index(after) + 1]
        if line_start(text, following.start) == line_start(text, after.start):
            return insert_into(table, after.end, "".join(", " + value for value in formatted))
        comma = "," if text[after.end:following.start].lstrip(" \t").startswith(",") else ""
        newline, indent = newline_of(text), indent_at(text, after.start)
        return insert_into(table, line_end(text, after.end), "".join(newline + indent + v + comma for v in formatted))
    last = table.items[-1]
    closing = table.end - 1
    if line_start(text, last.start) <= table.start:
        indent = indent_at(text, table.start) + _indent_unit("", indent_at(text, table.start) or "    ")
    else:
        indent = indent_at(text, last.start)
    after_last = text[last.end:closing]
    comma = "," if after_last.lstrip(" \t").startswith(",") else ""
    end_of_line = line_end(text, last.end)
    if end_of_line < closing:
        newline = newline_of(text)
        return insert_into(table, end_of_line, "".join(newline + indent + row + comma for row in formatted))
    return insert_into(table, closing, ("" if after_last.rstrip().endswith(",") else ", ") + ", ".join(formatted))


def delete_value(doc: Document, node: Node) -> TextEdit:
    """Removes a row or value; a row alone on its line goes with its line and a trailing comment."""
    return _delete_span(doc, node.start, node.end)


def delete_member(doc: Document, member: Member) -> TextEdit:
    """Removes a key and its value from an object, the same way `delete_value` removes a row."""
    return _delete_span(doc, member.key_start, member.value.end)


def _delete_span(doc: Document, start: int, stop: int) -> TextEdit:
    text = doc.text
    end = stop
    probe = end
    while probe < len(text) and text[probe] in " \t":
        probe += 1
    if probe < len(text) and text[probe] == ",":
        end = probe + 1
    start_of_line, end_of_line = line_start(text, start), line_end(text, end)
    before, after = text[start_of_line:start], text[end:end_of_line].strip()
    trailing_comment = after.startswith("//") or (after.startswith("/*") and after.find("*/") == len(after) - 2)
    target = (start, stop)
    if before.strip() == "" and (after == "" or trailing_comment):
        next_line = end_of_line
        if text.startswith("\r\n", next_line):
            next_line += 2
        elif text.startswith("\n", next_line):
            next_line += 1
        return TextEdit(start_of_line, next_line, "", target)
    while end < len(text) and text[end] in " \t":
        end += 1
    return TextEdit(start, end, "", target)


def insert_member(doc: Document, obj: Node, key: str, value: str) -> list[TextEdit]:
    """Adds `"key": value` as the last member of an object, on its own line like the members above."""
    text = doc.text
    newline = newline_of(text)
    member = f"{json_literal(key)}: {value}"
    if not obj.members:
        indent = indent_at(text, obj.start)
        return [insert_into(obj, obj.start + 1,
                            newline + indent + _indent_unit(indent, indent) + member + "," + newline + indent)]
    last = obj.members[-1]
    closing = obj.end - 1
    probe = last.value.end
    while probe < closing and text[probe] in " \t":
        probe += 1
    has_comma = text[probe] == ","
    if line_start(text, last.key_start) <= obj.start:
        return [insert_into(obj, closing, ("" if text[last.value.end:closing].rstrip().endswith(",") else ", ")
                            + member)]
    line = newline + indent_at(text, last.key_start) + member
    end_of_line = line_end(text, last.value.end)
    if end_of_line >= closing:
        return [insert_into(obj, probe + 1 if has_comma else last.value.end, ("" if has_comma else ",") + line)]
    if not has_comma and end_of_line == last.value.end:
        return [insert_into(obj, end_of_line, "," + line)]
    edits = [insert_into(obj, end_of_line, line + ("," if has_comma else ""))]
    if not has_comma:
        edits.append(insert_into(obj, last.value.end, ","))
    return edits


def insert_section(doc: Document, part: Node, name: str, header: list[str], rows: list[list[str]]) -> list[TextEdit]:
    """Adds a `"name": [header, rows...]` table as the last member of a part."""
    text = doc.text
    part_indent = indent_at(text, part.start)
    member_indent = indent_at(text, part.members[-1].key_start) if part.members else part_indent + "    "
    unit = _indent_unit(part_indent, member_indent)
    lines = [f'{member_indent}"{name}": [', f"{member_indent}{unit}{format_row(header, None, text)},"]
    lines += [f"{member_indent}{unit}{format_row(row, None, text)}," for row in rows]
    lines.append(f"{member_indent}],")
    return _append_lines(doc, part, lines)


def insert_object_section(doc: Document, part: Node, name: str, members: list[tuple[str, str]]) -> list[TextEdit]:
    """Adds a `"name": {"key": value, ...}` section, such as rails, as the last member of a part."""
    text = doc.text
    part_indent = indent_at(text, part.start)
    member_indent = indent_at(text, part.members[-1].key_start) if part.members else part_indent + "    "
    unit = _indent_unit(part_indent, member_indent)
    lines = [f"{member_indent}{json_literal(name)}: {{"]
    lines += [f"{member_indent}{unit}{json_literal(key)}: {value}," for key, value in members]
    lines.append(f"{member_indent}}},")
    return _append_lines(doc, part, lines)


def _append_lines(doc: Document, part: Node, lines: list[str]) -> list[TextEdit]:
    text = doc.text
    newline = newline_of(text)
    part_indent = indent_at(text, part.start)
    block = newline + newline.join(lines)
    if not part.members:
        return [insert_into(part, part.start + 1, block)]
    value_end = part.members[-1].value.end
    probe = value_end
    while probe < len(text) and text[probe] in " \t":
        probe += 1
    comma = "" if probe < len(text) and text[probe] == "," else ","
    closing = part.end - 1
    end_of_line = line_end(text, value_end)
    if end_of_line >= closing:
        return [insert_into(part, value_end, comma), insert_into(part, closing, block + newline + part_indent)]
    if comma and end_of_line == value_end:
        return [insert_into(part, value_end, comma + block)]
    edits = [insert_into(part, end_of_line, block)]
    if comma:
        edits.append(insert_into(part, value_end, comma))
    return edits


def merge_texts(base: str, ours: str, theirs: str) -> str | None:
    """Joins two edits of one text, line by line: the lines either side changed, kept or not, go into the result.
    None when both change or insert at the same lines in different ways."""
    if ours == base or ours == theirs:
        return theirs
    if theirs == base:
        return ours
    lines = base.splitlines(keepends=True)

    def changes(text: str):
        new = text.splitlines(keepends=True)
        matcher = SequenceMatcher(None, lines, new, autojunk=False)
        return [(i1, i2, "".join(new[j1:j2])) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]

    merged: list[str] = []
    at = 0
    last = None
    for change in sorted(set(changes(ours)) | set(changes(theirs))):
        start, end, text = change
        if start < at or (last is not None and start == last[0] == last[1] == end):
            return None
        merged += lines[at:start]
        merged.append(text)
        at, last = end, change
    merged += lines[at:]
    return "".join(merged)
