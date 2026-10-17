"""Finding parts, tables and node references in the source text of JBeam files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..assembly.links import link_target
from ..model.syntax import header_of, part_object, section_node
from ..sjson import Document, Kind, Node

__all__ = ["Location", "header_of", "link_values", "link_variables", "location", "node_references", "part_object",
           "section_node", "string_values"]


@dataclass(frozen=True)
class Location:
    path: Path
    start: int
    end: int
    line: int
    column: int
    part: str
    kind: str
    """"link" for a reference in a column or key ending with ":", "text" for any other equal string."""


def link_values(part: Node) -> list[Node]:
    """String values in node link positions: cells of link columns (`id1:`) and values of link keys (`links:`)."""
    found: list[Node] = []

    def collect(value: Node) -> None:
        if value.kind is Kind.STRING:
            found.append(value)
        elif value.kind is Kind.ARRAY:
            found.extend(item for item in value.items if item.kind is Kind.STRING)

    def walk(node: Node) -> None:
        if node.kind is Kind.OBJECT:
            for member in node.members:
                if link_target(member.key) == "nodes":
                    collect(member.value)
                walk(member.value)
        elif node.kind is Kind.ARRAY:
            header = header_of(node)
            if header is not None:
                columns = [i for i, name in enumerate(header) if link_target(name) == "nodes"]
                for row in node.items[1:]:
                    if row.kind is Kind.ARRAY:
                        for index in columns:
                            if index < len(row.items):
                                collect(row.items[index])
            for item in node.items:
                walk(item)

    walk(part)
    return found


def link_variables(parts) -> set[str]:
    """Variables such as `$nodeRef` that some part puts into a node link position."""
    return {value.value for part in parts for value in link_values(part)
            if value.value.startswith("$") and not value.value.startswith("$=")}


def node_references(part: Node, node_id: str, variables: set[str] | frozenset = frozenset()) -> list[Node]:
    """Values that reference `node_id`: in link positions, and as values of `variables` objects for the given
    variables, through which slots hand node ids to the link positions of their parts."""
    found = [value for value in link_values(part) if value.value == node_id]
    if variables:
        stack = [part]
        while stack:
            node = stack.pop()
            stack.extend(node.items)
            for member in node.members:
                if member.key == "variables" and member.value.kind is Kind.OBJECT:
                    found.extend(v.value for v in member.value.members
                                 if v.key in variables and v.value.kind is Kind.STRING and v.value.value == node_id)
                stack.append(member.value)
    return found


def string_values(node: Node, value: str) -> list[Node]:
    if node.kind is Kind.STRING:
        return [node] if node.value == value else []
    found: list[Node] = []
    for child in node.items:
        found.extend(string_values(child, value))
    for member in node.members:
        found.extend(string_values(member.value, value))
    return found


def location(doc: Document, node: Node, part: str, kind: str) -> Location:
    line, column = doc.line_col(node.start)
    return Location(Path(doc.path), node.start, node.end, line, column, part, kind)
