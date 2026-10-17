from __future__ import annotations

import math
import re

from ..diagnostics import PARSE
from .cst import Document, Kind, Member, Node

_SPACE = re.compile(r"[\x00-\x20,\ufeff]+")
_STRING_STOP = re.compile(r'["\\]')
_NUMBER = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")
_INFINITY = re.compile(r"-?(?:Infinity|1#INF00)")
_BARE_KEY = re.compile(r"[A-Za-z0-9_$.+\-]+")
_WORD_CHAR = re.compile(r"[A-Za-z0-9_]")
_HEX4 = re.compile(r"[0-9a-fA-F]{4}")
_WORDS = (("true", Kind.BOOL, True), ("false", Kind.BOOL, False), ("null", Kind.NULL, None))
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class _ParseError(Exception):
    def __init__(self, message: str, offset: int):
        super().__init__(message)
        self.offset = offset


class _Parser:
    def __init__(self, doc: Document):
        self.doc = doc
        self.s = doc.text
        self.n = len(doc.text)
        self.i = 0

    def warn(self, message: str, offset: int) -> None:
        line, column = self.doc.line_col(offset)
        self.doc.diagnostics.add("warning", PARSE, message, self.doc.path, line, column)

    def skip(self) -> None:
        s, n = self.s, self.n
        while self.i < n:
            space = _SPACE.match(s, self.i)
            if space:
                self.i = space.end()
                continue
            if s[self.i] != "/":
                return
            nxt = s[self.i + 1] if self.i + 1 < n else ""
            if nxt == "/":
                end = s.find("\n", self.i)
                self.i = n if end < 0 else end
            elif nxt == "*":
                end = s.find("*/", self.i + 2)
                if end < 0:
                    raise _ParseError("unterminated block comment", self.i)
                self.i = end + 2
            else:
                raise _ParseError("invalid comment, expected // or /*", self.i)

    def value(self) -> Node:
        self.skip()
        if self.i >= self.n:
            raise _ParseError("unexpected end of file, a value is missing", self.i)
        s, start = self.s, self.i
        ch = s[start]
        if ch == "{":
            return self.object(braced=True)
        if ch == "[":
            return self.array()
        if ch == '"':
            text = self.string()
            return Node(Kind.STRING, start, self.i, text)
        match = _INFINITY.match(s, start) or _NUMBER.match(s, start)
        if match:
            self.i = match.end()
            token = match.group()
            if "I" in token:
                number = -math.inf if token.startswith("-") else math.inf
            elif "." in token or "e" in token or "E" in token:
                number = float(token)
            else:
                number = int(token)
            return Node(Kind.NUMBER, start, self.i, number)
        for word, kind, value in _WORDS:
            end = start + len(word)
            if s.startswith(word, start) and not (end < self.n and _WORD_CHAR.match(s, end)):
                self.i = end
                return Node(kind, start, end, value)
        raise _ParseError(f"unexpected character {ch!r}", start)

    def string(self) -> str:
        s, n = self.s, self.n
        start = self.i
        i = start + 1
        parts = []
        while True:
            stop = _STRING_STOP.search(s, i)
            if stop is None:
                raise _ParseError("unterminated string", start)
            j = stop.start()
            parts.append(s[i:j])
            if s[j] == '"':
                self.i = j + 1
                return "".join(parts)
            escape = s[j + 1] if j + 1 < n else ""
            if escape in _ESCAPES:
                parts.append(_ESCAPES[escape])
                i = j + 2
            elif escape == "u" and _HEX4.fullmatch(s, j + 2, j + 6):
                parts.append(chr(int(s[j + 2:j + 6], 16)))
                i = j + 6
            elif escape == "":
                raise _ParseError("unterminated string", start)
            else:
                self.warn(f"unknown escape sequence \\{escape}", j)
                parts.append("\\" + escape)
                i = j + 2

    def key(self) -> str:
        if self.s[self.i] == '"':
            return self.string()
        match = _BARE_KEY.match(self.s, self.i)
        if match is None:
            raise _ParseError(f"expected a key, found {self.s[self.i]!r}", self.i)
        self.i = match.end()
        return match.group()

    def object(self, braced: bool) -> Node:
        s = self.s
        start = self.i
        if braced:
            self.i += 1
        node = Node(Kind.OBJECT, start, start, braced=braced)
        seen: set[str] = set()
        while True:
            self.skip()
            if self.i >= self.n:
                if braced:
                    raise _ParseError("missing '}' for this object", start)
                break
            if s[self.i] == "}":
                if braced:
                    self.i += 1
                else:
                    self.warn("unmatched '}', the rest of the file is ignored", self.i)
                    self.i = self.n
                break
            key_start = self.i
            key = self.key()
            key_end = self.i
            self.skip()
            if self.i >= self.n or s[self.i] not in ":=":
                raise _ParseError(f'expected ":" or "=" after key "{key}"', key_start)
            self.i += 1
            value = self.value()
            if key in seen:
                self.warn(f'duplicate key "{key}", the later value is used', key_start)
            seen.add(key)
            node.members.append(Member(key, key_start, key_end, value))
        node.end = self.i
        return node

    def array(self) -> Node:
        start = self.i
        self.i += 1
        node = Node(Kind.ARRAY, start, start)
        while True:
            self.skip()
            if self.i >= self.n:
                raise _ParseError("missing ']' for this list", start)
            if self.s[self.i] == "]":
                self.i += 1
                break
            node.items.append(self.value())
        node.end = self.i
        return node


def parse(text: str, path: str = "<memory>") -> Document:
    doc = Document(path, text)
    parser = _Parser(doc)
    try:
        parser.skip()
        if parser.i < parser.n and text[parser.i] in "{[":
            root = parser.value()
            parser.skip()
            if parser.i < parser.n:
                parser.warn("content after the end of the document is ignored", parser.i)
        else:
            root = parser.object(braced=False)
        doc.root = root
    except _ParseError as error:
        line, column = doc.line_col(error.offset)
        doc.diagnostics.add("error", PARSE, str(error), path, line, column)
    except RecursionError:
        doc.diagnostics.add("error", PARSE, "the document is nested too deeply", path, 1, 1)
    return doc
