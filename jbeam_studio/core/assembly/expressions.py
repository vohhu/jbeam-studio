"""Evaluator for JBeam `$=` expressions.

The game evaluates them as Lua expressions in a sandbox. This module implements the subset of Lua expression
syntax and the sandbox functions that vehicle files use, with Lua value semantics.
"""

from __future__ import annotations

import functools
import math
import random
import re
from typing import Callable, Mapping

from ..lua import is_number, tostring, truthy


class ExpressionError(Exception):
    pass


_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<var>\$[A-Za-z0-9_]+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\.\.\.|\.\.|==|~=|<=|>=|[-+*/%^\#<>(){}\[\],.:;])
""", re.VERBOSE | re.DOTALL)
_ASSIGNMENT = re.compile(r"[^<>~=]=[^=]")
_DECIMAL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_HEX = re.compile(r"[+-]?0[xX][0-9a-fA-F]+")
_CONSTANTS = {"true": True, "false": False, "nil": None}
_KEYWORD_OPS = {"and", "or", "not"}
_BINARY = {
    "or": (1, 1), "and": (2, 2),
    "<": (3, 3), ">": (3, 3), "<=": (3, 3), ">=": (3, 3), "~=": (3, 3), "==": (3, 3),
    "..": (5, 4), "+": (6, 6), "-": (6, 6), "*": (7, 7), "/": (7, 7), "%": (7, 7), "^": (10, 9),
}
_UNARY_PRIORITY = 8
_STRING_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "\\": "\\", "'": "'", '"': '"', "\n": "\n",
}


def _unescape(body: str) -> str:
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt.isdigit():
                digits = re.match(r"\d{1,3}", body[i + 1:]).group()
                out.append(chr(int(digits)))
                i += 1 + len(digits)
                continue
            out.append(_STRING_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _tokenize(text: str) -> list[tuple[str, object]]:
    tokens: list[tuple[str, object]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None:
            raise ExpressionError(f"unexpected character {text[pos]!r}")
        pos = match.end()
        kind, value = match.lastgroup, match.group()
        if kind == "ws":
            continue
        if kind == "num":
            if value[:2].lower() == "0x":
                tokens.append(("const", int(value, 16)))
            elif "." in value or "e" in value or "E" in value:
                tokens.append(("const", float(value)))
            else:
                tokens.append(("const", int(value)))
        elif kind == "str":
            tokens.append(("const", _unescape(value[1:-1])))
        elif kind == "name" and value in _CONSTANTS:
            tokens.append(("const", _CONSTANTS[value]))
        elif kind == "name" and value in _KEYWORD_OPS:
            tokens.append(("op", value))
        else:
            tokens.append((kind, value))
    tokens.append(("eof", None))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def take(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def is_op(self, *values) -> bool:
        kind, value = self.peek()
        return kind == "op" and value in values

    def expect(self, value: str) -> None:
        kind, found = self.take()
        if kind != "op" or found != value:
            raise ExpressionError(f"expected {value!r}, found {found!r}")

    def expression(self, limit: int = 0):
        if self.is_op("not", "-", "#"):
            _, op = self.take()
            node = ("unary", op, self.expression(_UNARY_PRIORITY))
        else:
            node = self.simple()
        while True:
            kind, op = self.peek()
            if kind != "op" or op not in _BINARY or _BINARY[op][0] <= limit:
                return node
            self.take()
            node = ("binary", op, node, self.expression(_BINARY[op][1]))

    def simple(self):
        kind, value = self.peek()
        if kind == "const":
            self.take()
            return ("const", value)
        if kind == "op" and value == "{":
            raise ExpressionError("table constructors are not supported")
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == "var":
            node = ("var", value)
        elif kind == "name":
            node = ("name", value)
        elif kind == "op" and value == "(":
            node = self.expression()
            self.expect(")")
        else:
            raise ExpressionError(f"unexpected {value!r}" if value is not None else "unexpected end of expression")
        while True:
            if self.is_op("."):
                self.take()
                kind, name = self.take()
                if kind != "name":
                    raise ExpressionError("a field name must follow '.'")
                node = ("index", node, ("const", name))
            elif self.is_op("["):
                self.take()
                key = self.expression()
                self.expect("]")
                node = ("index", node, key)
            elif self.is_op("("):
                self.take()
                args = []
                if not self.is_op(")"):
                    args.append(self.expression())
                    while self.is_op(","):
                        self.take()
                        args.append(self.expression())
                self.expect(")")
                node = ("call", node, args)
            elif self.is_op(":"):
                raise ExpressionError("method calls are not supported")
            else:
                return node


@functools.lru_cache(maxsize=16384)
def _compile(body: str):
    parser = _Parser(_tokenize(body))
    tree = parser.expression()
    kind, value = parser.peek()
    if kind != "eof":
        raise ExpressionError(f"unexpected {value!r}")
    return tree


def _type_name(value) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "boolean"
    if is_number(value):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (dict, list)):
        return "table"
    if callable(value):
        return "function"
    return type(value).__name__


def _to_number(value):
    if is_number(value):
        return value
    if isinstance(value, str):
        text = value.strip()
        if _HEX.fullmatch(text):
            return int(text, 16)
        if _DECIMAL.fullmatch(text):
            return float(text) if any(c in text for c in ".eE") else int(text)
    return None


def _operand(value):
    number = _to_number(value)
    if number is None:
        raise ExpressionError(f"attempt to perform arithmetic on a {_type_name(value)} value")
    return number


def _lua_equal(a, b) -> bool:
    if is_number(a) and is_number(b):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return a is b
    return type(a) is type(b) and a == b


def _divide(x, y):
    if y == 0:
        if x == 0 or x != x:
            return math.nan
        return math.copysign(math.inf, x) * math.copysign(1.0, y)
    return x / y


def _modulo(x, y):
    if y == 0:
        return math.nan
    return x - math.floor(x / y) * y


def _power(x, y):
    try:
        return math.pow(x, y)
    except ValueError:
        return math.nan
    except OverflowError:
        return math.inf


def _binary(op: str, a, b):
    if op == "==":
        return _lua_equal(a, b)
    if op == "~=":
        return not _lua_equal(a, b)
    if op in ("<", "<=", ">", ">="):
        if not ((is_number(a) and is_number(b)) or (isinstance(a, str) and isinstance(b, str))):
            raise ExpressionError(f"attempt to compare {_type_name(a)} with {_type_name(b)}")
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        return a >= b
    if op == "..":
        for value in (a, b):
            if not (isinstance(value, str) or is_number(value)):
                raise ExpressionError(f"attempt to concatenate a {_type_name(value)} value")
        return (a if isinstance(a, str) else tostring(a)) + (b if isinstance(b, str) else tostring(b))
    x, y = _operand(a), _operand(b)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if op == "/":
        return _divide(x, y)
    if op == "%":
        return _modulo(x, y)
    return _power(x, y)


def _unary(op: str, value):
    if op == "not":
        return not truthy(value)
    if op == "-":
        return -_operand(value)
    if isinstance(value, (str, list)):
        return len(value)
    if isinstance(value, dict):
        return 0
    raise ExpressionError(f"attempt to get length of a {_type_name(value)} value")


def _index(obj, key):
    if isinstance(obj, dict):
        try:
            return obj.get(key)
        except TypeError:
            return None
    if isinstance(obj, list):
        if is_number(key) and float(key).is_integer() and 1 <= key <= len(obj):
            return obj[int(key) - 1]
        return None
    raise ExpressionError(f"attempt to index a {_type_name(obj)} value")


class Evaluator:
    """Evaluates `$=` expressions; `random()` draws from `rng` so results are reproducible."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random(0)
        self.variables: Mapping[str, object] = {}
        self.globals = self._globals()

    def evaluate(self, expression: str, variables: Mapping[str, object]):
        if not isinstance(expression, str) or not expression.startswith("$="):
            raise ExpressionError("expressions start with '$='")
        body = expression[2:]
        if _ASSIGNMENT.search(body):
            raise ExpressionError("assignments are not supported inside expressions")
        tree = _compile(body)
        previous = self.variables
        self.variables = variables
        try:
            return self._eval(tree)
        except (TypeError, ValueError, OverflowError, ZeroDivisionError, RecursionError) as error:
            raise ExpressionError(str(error)) from error
        finally:
            self.variables = previous

    def evaluate_safe(self, expression: str, variables: Mapping[str, object], on_error: Callable[[str], None]):
        try:
            return self.evaluate(expression, variables)
        except ExpressionError as error:
            on_error(f'cannot evaluate "{expression}": {error}')
            return None

    def lookup(self, name: str):
        value = self.variables.get(name)
        if isinstance(value, dict):
            return value.get("val")
        return value

    def _eval(self, node):
        kind = node[0]
        if kind == "const":
            return node[1]
        if kind == "var":
            return self.lookup(node[1])
        if kind == "name":
            name = node[1]
            if name in self.globals:
                return self.globals[name]
            return self.lookup("$" + name[4:])
        if kind == "index":
            return _index(self._eval(node[1]), self._eval(node[2]))
        if kind == "call":
            function = self._eval(node[1])
            if not callable(function):
                raise ExpressionError(f"attempt to call a {_type_name(function)} value")
            return function(*[self._eval(arg) for arg in node[2]])
        if kind == "unary":
            return _unary(node[1], self._eval(node[2]))
        op = node[1]
        left = self._eval(node[2])
        if op == "and":
            return self._eval(node[3]) if truthy(left) else left
        if op == "or":
            return left if truthy(left) else self._eval(node[3])
        return _binary(op, left, self._eval(node[3]))

    def _globals(self) -> dict:
        rng = self.rng

        def number(value, function: str):
            result = _to_number(value)
            if result is None:
                raise ExpressionError(f"bad argument to '{function}' (number expected, got {_type_name(value)})")
            return result

        def unary(name, function):
            def call(x=None, *_):
                try:
                    return function(number(x, name))
                except ValueError:
                    return math.nan
                except OverflowError:
                    return math.inf
            return call

        def lua_log(x=None, base=None):
            x = number(x, "log")
            try:
                return math.log(x) if base is None else math.log(x, number(base, "log"))
            except ValueError:
                return -math.inf if x == 0 else math.nan

        def lua_random(m=None, n=None):
            if m is None:
                return rng.random()
            if n is None:
                return rng.randint(1, int(number(m, "random")))
            return rng.randint(int(number(m, "random")), int(number(n, "random")))

        def lua_randomseed(seed=None):
            rng.seed(seed)

        def lua_min(*args):
            if not args:
                raise ExpressionError("bad argument to 'min' (number expected, got no value)")
            return min(number(a, "min") for a in args)

        def lua_max(*args):
            if not args:
                raise ExpressionError("bad argument to 'max' (number expected, got no value)")
            return max(number(a, "max") for a in args)

        def lua_fmod(a=None, b=None):
            b = number(b, "fmod")
            return math.fmod(number(a, "fmod"), b) if b != 0 else math.nan

        def lua_modf(x=None):
            return float(math.modf(number(x, "modf"))[1])

        def lua_atan(y=None, x=None):
            return math.atan(number(y, "atan")) if x is None else math.atan2(number(y, "atan"), number(x, "atan"))

        def lua_pow(x=None, y=None):
            return _power(number(x, "pow"), number(y, "pow"))

        def lua_case(selector=None, *args):
            if isinstance(selector, bool):
                index = 1 if selector else 2
            elif is_number(selector):
                index = math.floor(selector)
            else:
                index = 0
            value = args[index - 1] if 1 <= index <= len(args) else None
            if truthy(value):
                return value
            return args[-1] if args else None

        def lua_round(a=None):
            return math.floor(number(a, "round") + 0.5)

        def lua_square(a=None):
            a = number(a, "square")
            return a * a

        def lua_clamp(x=None, low=None, high=None):
            return min(max(number(x, "clamp"), number(low, "clamp")), number(high, "clamp"))

        def lua_smoothstep(x=None):
            x = min(max(number(x, "smoothstep"), 0), 1)
            return x * x * (3 - 2 * x)

        def lua_smootherstep(x=None):
            x = number(x, "smootherstep")
            return min(max(x * x * x * (x * (x * 6 - 15) + 10), 0), 1)

        def lua_smoothmin(a=None, b=None, k=None):
            a, b = number(a, "smoothmin"), number(b, "smoothmin")
            k = 0.1 if k is None else number(k, "smoothmin")
            h = max(min(0.5 + (b - a) / k, 1), 0)
            return h * a + (1 - h) * (b - h * k * 0.5)

        def lua_sign(x=None):
            x = number(x, "sign")
            return 1 if x > 0 else -1 if x < 0 else 0

        def vec3(x=0, y=0, z=0):
            return {"x": x, "y": y, "z": z}

        def quat(x=0, y=0, z=0, w=1):
            return {"x": x, "y": y, "z": z, "w": w}

        def concat(table=None, separator="", *_):
            if not isinstance(table, list):
                raise ExpressionError("bad argument to 'concat' (table expected)")
            return separator.join(v if isinstance(v, str) else tostring(v) for v in table)

        def include(*_):
            raise ExpressionError("include() of external CSV or XLSX files is not supported")

        def var_(name=None):
            return "$" if name is None else self.lookup("$" + tostring(name))

        def var(name=None):
            return "$" + ("" if name is None else tostring(name))

        def lua_print(value=None, label=None):
            return value

        functions = {
            "abs": unary("abs", abs), "ceil": unary("ceil", math.ceil), "floor": unary("floor", math.floor),
            "sqrt": unary("sqrt", math.sqrt), "sin": unary("sin", math.sin), "cos": unary("cos", math.cos),
            "tan": unary("tan", math.tan), "asin": unary("asin", math.asin), "acos": unary("acos", math.acos),
            "exp": unary("exp", math.exp), "log10": unary("log10", math.log10), "deg": unary("deg", math.degrees),
            "rad": unary("rad", math.radians), "sinh": unary("sinh", math.sinh), "cosh": unary("cosh", math.cosh),
            "tanh": unary("tanh", math.tanh), "atan": lua_atan, "atan2": lua_atan, "log": lua_log, "pow": lua_pow,
            "min": lua_min, "max": lua_max, "fmod": lua_fmod, "modf": lua_modf,
            "random": lua_random, "randomseed": lua_randomseed, "pi": math.pi, "huge": math.inf,
            "round": lua_round, "square": lua_square, "clamp": lua_clamp, "smoothstep": lua_smoothstep,
            "smootherstep": lua_smootherstep, "smoothmin": lua_smoothmin, "sign": lua_sign, "case": lua_case,
            "vec3": vec3, "quat": quat, "concat": concat, "include": include, "var_": var_, "var": var,
            "print": lua_print,
        }
        return functions


def evaluate(expression: str, variables: Mapping[str, object], rng: random.Random | None = None):
    return Evaluator(rng).evaluate(expression, variables)
