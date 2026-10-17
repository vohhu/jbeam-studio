from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from enum import Enum

from ..diagnostics import DiagnosticList


class Kind(Enum):
    OBJECT = "object"
    ARRAY = "array"
    STRING = "string"
    NUMBER = "number"
    BOOL = "bool"
    NULL = "null"


@dataclass(eq=False, slots=True)
class Member:
    key: str
    key_start: int
    key_end: int
    value: Node


@dataclass(eq=False, slots=True)
class Node:
    """A value in the source text; `start` and `end` are offsets into `Document.text`."""

    kind: Kind
    start: int
    end: int
    value: object = None
    items: list[Node] = field(default_factory=list)
    members: list[Member] = field(default_factory=list)
    braced: bool = True


@dataclass(eq=False)
class Document:
    path: str
    text: str
    root: Node | None = None
    diagnostics: DiagnosticList = field(default_factory=DiagnosticList)

    def __post_init__(self) -> None:
        self._line_starts = [0] + [m.end() for m in re.finditer("\n", self.text)]

    def line_col(self, offset: int) -> tuple[int, int]:
        """1-based line and column of a text offset."""
        line = bisect.bisect_right(self._line_starts, offset) - 1
        return line + 1, offset - self._line_starts[line] + 1

    def serialize(self) -> str:
        return self.text
