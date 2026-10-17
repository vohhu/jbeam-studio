"""Lua value and table semantics that the game relies on while it assembles JBeam."""

from __future__ import annotations

import math

from .sjson.values import JDict, JList


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_table(value) -> bool:
    return isinstance(value, (dict, list))


def is_dict(value) -> bool:
    """Lua `tableIsDict`: objects and the empty table count as dictionaries."""
    return isinstance(value, dict) or (isinstance(value, list) and not value)


def is_list(value) -> bool:
    return isinstance(value, list) and len(value) > 0


def truthy(value) -> bool:
    return value is not None and value is not False


def ipairs(values):
    """List values up to the first nil, like Lua `ipairs`."""
    for value in values:
        if value is None:
            return
        yield value


def ipairs_keyed(entries: dict):
    """Values stored under 1, 2, 3... up to the first missing key, like Lua `ipairs` on a sparse table."""
    key = 1
    while key in entries:
        yield entries[key]
        key += 1


def length(entries: dict) -> int:
    return sum(1 for _ in ipairs_keyed(entries))


def sign(x) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def tostring(value) -> str:
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return "%.14g" % value
    return str(value)


def deep_copy(value):
    if isinstance(value, dict):
        return JDict({k: deep_copy(v) for k, v in value.items()}, src=getattr(value, "src", None))
    if isinstance(value, list):
        return JList([deep_copy(v) for v in value], src=getattr(value, "src", None))
    return value
