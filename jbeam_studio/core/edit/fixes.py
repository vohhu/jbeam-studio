"""Automatic fixes of the problems diagnostics report, for fix buttons."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..diagnostics import Diagnostic
from .session import EditError, EditSession

MARK_OPTIONAL = "mark_optional"
"""A row references a node or another entry that is missing; the argument is the offset where the row starts.
The row is kept and marked optional, since another part or mod may provide what it references."""
DELETE_DUPLICATE = "delete_duplicate"
"""A beam repeats an earlier one; the argument is the offset where its row starts."""
ADD_RESETS = "add_resets"
"""A part leaves modifiers set for the parts after it; the argument is the part."""

GROUPS = {MARK_OPTIONAL: "missing", DELETE_DUPLICATE: "duplicates", ADD_RESETS: "resets"}
"""Fixes that a "fix all" button applies together."""


@dataclass
class FixResult:
    optional: int = 0
    """Rows marked optional."""
    deleted: int = 0
    """Rows deleted."""
    resets: dict[str, dict] = field(default_factory=dict)
    """Keys reset by section, for each part that got resets."""


def group_of(diagnostic: Diagnostic) -> str | None:
    return GROUPS.get(diagnostic.fix[0]) if diagnostic.fix else None


def fix(session: EditSession, diagnostics: Iterable[Diagnostic], allow_shared: bool = False) -> FixResult:
    """Fixes the problems of the session's current vehicle as one change."""
    chosen = [d for d in diagnostics if group_of(d)]
    if not chosen:
        raise EditError("these problems have no automatic fix")
    result = FixResult()
    with session.transaction(f"Fix {len(chosen)} problem(s)"):
        missing = [(Path(d.file), d.fix[1]) for d in chosen if d.fix[0] == MARK_OPTIONAL and d.file]
        repeated = [(Path(d.file), d.fix[1]) for d in chosen if d.fix[0] == DELETE_DUPLICATE and d.file]
        if missing or repeated:
            result.optional, result.deleted = session.change_rows(missing, repeated, allow_shared)
        for part in dict.fromkeys(d.fix[1] for d in chosen if d.fix[0] == ADD_RESETS):
            done = session.add_resets(part)
            if done:
                result.resets[part] = done
    return result
