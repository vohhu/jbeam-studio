"""Finding parts and their sections in the syntax tree of a JBeam file."""

from __future__ import annotations

from ..sjson import Document, Kind, Node


def part_object(doc: Document, part_name: str) -> Node | None:
    if doc.root is None or doc.root.kind is not Kind.OBJECT:
        return None
    found = None
    for member in doc.root.members:
        if member.key == part_name and member.value.kind is Kind.OBJECT:
            found = member.value
    return found


def section_node(part: Node, section: str) -> Node | None:
    found = None
    for member in part.members:
        if member.key == section:
            found = member.value
    return found


def header_of(table: Node) -> list | None:
    if table.kind is not Kind.ARRAY or not table.items or table.items[0].kind is not Kind.ARRAY:
        return None
    return [cell.value for cell in table.items[0].items]
