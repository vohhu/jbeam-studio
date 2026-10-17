"""Tokens of SJSON text for syntax colouring; tolerant of text that is being typed and does not parse yet."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

PART = "part"
"""Key that names a part: a top-level key of the file."""
SECTION = "section"
"""Key of a part's member, such as "nodes" or "information"."""
KEY = "key"
STRING = "string"
VARIABLE = "variable"
"""String that is a variable, such as "$ride_height"."""
EXPRESSION = "expression"
"""String that is an expression, such as "$=$x * 2"."""
NUMBER = "number"
LITERAL = "literal"
"""true, false and null."""
COMMENT = "comment"

_TOKEN = re.compile(r"""
    (?P<comment>//[^\n]*|/\*.*?(?:\*/|\Z))
  | (?P<string>"(?:[^"\\\n]|\\.)*(?:"|$))
  | (?P<number>-?(?:Infinity|1\#INF00)(?![A-Za-z0-9_])|[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<word>[A-Za-z_$][A-Za-z0-9_$.+\-]*)
  | (?P<open>[{\[])
  | (?P<close>[}\]])
  | (?P<colon>[:=])
""", re.S | re.M | re.X)
_LITERALS = {"true", "false", "null"}


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    start: int
    end: int


def tokenize(text: str) -> list[Token]:
    """Coloured tokens of `text`; punctuation and unknown characters are left out."""
    raw = [(m.lastgroup, m.start(), m.end()) for m in _TOKEN.finditer(text)]
    first = next((kind for kind, _, _ in raw if kind != "comment"), None)
    part_depth = 1 if first == "open" and text[next(s for k, s, _ in raw if k == "open")] == "{" else 0
    tokens: list[Token] = []
    stack: list[str] = []
    for index, (kind, start, end) in enumerate(raw):
        if kind == "open":
            stack.append(text[start])
            continue
        if kind == "close":
            if stack:
                stack.pop()
            continue
        if kind in ("colon",):
            continue
        if kind == "comment":
            tokens.append(Token(COMMENT, start, end))
            continue
        if kind == "number":
            tokens.append(Token(NUMBER, start, end))
            continue
        following = next((k for k, _, _ in raw[index + 1:index + 4] if k != "comment"), None)
        objects = stack.count("{")
        in_object = not stack or stack[-1] == "{"
        if following == "colon" and in_object:
            depth = objects if stack or part_depth == 0 else 0
            role = PART if depth == part_depth else SECTION if depth == part_depth + 1 else KEY
            tokens.append(Token(role, start, end))
        elif kind == "word":
            if text[start:end] in _LITERALS:
                tokens.append(Token(LITERAL, start, end))
        elif text.startswith('"$=', start):
            tokens.append(Token(EXPRESSION, start, end))
        elif text.startswith('"$', start):
            tokens.append(Token(VARIABLE, start, end))
        else:
            tokens.append(Token(STRING, start, end))
    return tokens


def tokens_by_line(text: str) -> list[list[tuple[int, int, str]]]:
    """Tokens of each line as (start column, end column, kind); tokens that span lines are split."""
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    lines: list[list[tuple[int, int, str]]] = [[] for _ in starts]
    for token in tokenize(text):
        line = bisect.bisect_right(starts, token.start) - 1
        position = token.start
        while position < token.end and line < len(starts):
            line_end = starts[line + 1] - 1 if line + 1 < len(starts) else len(text)
            end = min(token.end, line_end)
            if end > position:
                lines[line].append((position - starts[line], end - starts[line], token.kind))
            line += 1
            position = starts[line] if line < len(starts) else token.end
    return lines
