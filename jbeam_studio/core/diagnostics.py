from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

PARSE = "parse"
TABLE = "table"
SLOTS = "slots"
VARIABLES = "variables"
REFERENCES = "references"
CHECKS = "checks"
GAME_DIFF = "game-diff"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Located(Protocol):
    @property
    def file(self) -> str: ...

    @property
    def line(self) -> int: ...

    @property
    def column(self) -> int: ...


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Severity
    category: str
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    fix: tuple = ()
    """How the problem can be fixed, for a fix button: a kind and its arguments, such as ("add_resets", part)."""

    def __str__(self) -> str:
        location = ""
        if self.file:
            location = self.file
            if self.line is not None:
                location += f":{self.line}:{self.column or 1}"
            location += ": "
        return f"{location}{self.severity.value} [{self.category}] {self.message}"


class DiagnosticList(list):
    def add(self, severity, category: str, message: str, file: str | None = None,
            line: int | None = None, column: int | None = None, fix: tuple = ()) -> Diagnostic:
        diagnostic = Diagnostic(Severity(severity), category, message, file, line, column, fix)
        self.append(diagnostic)
        return diagnostic

    def at(self, where: Located | None, severity, category: str, message: str, fix: tuple = ()) -> Diagnostic:
        if where is None:
            return self.add(severity, category, message, fix=fix)
        return self.add(severity, category, message, where.file, where.line, where.column, fix)

    def errors(self) -> list[Diagnostic]:
        return [d for d in self if d.severity is Severity.ERROR]

    def warnings(self) -> list[Diagnostic]:
        return [d for d in self if d.severity is Severity.WARNING]

    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self)
