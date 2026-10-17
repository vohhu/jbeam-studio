from __future__ import annotations

from dataclasses import dataclass

from .cst import Document, Kind, Node


@dataclass(frozen=True, slots=True, eq=False)
class SourceRef:
    doc: Document
    node: Node

    @property
    def file(self) -> str:
        return self.doc.path

    @property
    def line(self) -> int:
        return self.doc.line_col(self.node.start)[0]

    @property
    def column(self) -> int:
        return self.doc.line_col(self.node.start)[1]


class JDict(dict):
    """A JSON object that remembers where it came from."""

    __slots__ = ("src",)

    def __init__(self, data=(), src: SourceRef | None = None):
        super().__init__(data)
        self.src = src


class JList(list):
    """A JSON list that remembers where it came from."""

    __slots__ = ("src",)

    def __init__(self, data=(), src: SourceRef | None = None):
        super().__init__(data)
        self.src = src


def to_python(doc: Document):
    """Values of a document with Lua semantics: null object members are dropped, null list items stay None."""
    if doc.root is None:
        return None
    return _convert(doc, doc.root)


def _convert(doc: Document, node: Node):
    if node.kind is Kind.OBJECT:
        result = JDict(src=SourceRef(doc, node))
        for member in node.members:
            if member.value.kind is Kind.NULL:
                result.pop(member.key, None)
            else:
                result[member.key] = _convert(doc, member.value)
        return result
    if node.kind is Kind.ARRAY:
        return JList([_convert(doc, item) for item in node.items], src=SourceRef(doc, node))
    return node.value
