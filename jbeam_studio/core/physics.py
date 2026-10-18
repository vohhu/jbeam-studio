"""Physical values of an assembled vehicle the way the game reads them: defaults of options, mass, centre of mass."""

from __future__ import annotations

import math
from typing import Iterable

from .assembly import AssembledVehicle, NodeEntry
from .lua import is_number

DEFAULTS = {"beamSpring": 4300000, "beamDeform": 220000, "beamDamp": 580, "beamStrength": math.inf, "nodeWeight": 25}
"""Values the game gives keys of the vehicle's options that no part sets (lua/common/jbeam/loader.lua)."""


def option(vehicle: AssembledVehicle, key: str):
    """A key of the vehicle's options, or the game's default for it."""
    options = vehicle.data.get("options")
    value = options.get(key) if isinstance(options, dict) else None
    return value if is_number(value) else DEFAULTS.get(key)


def value_of(vehicle: AssembledVehicle, props: dict, key: str) -> float | None:
    """A number of a node or beam as the game uses it: its own, else the vehicle's option for keys that have one."""
    value = props.get(key)
    if is_number(value):
        return float(value)
    fallback = option(vehicle, key)
    return float(fallback) if is_number(fallback) else None


def mass(vehicle: AssembledVehicle, nodes: Iterable[NodeEntry]) -> tuple[float, tuple[float, float, float] | None]:
    """The total nodeWeight of nodes, in kg, and their centre of mass; wheels the game adds are not counted."""
    total, moment = 0.0, [0.0, 0.0, 0.0]
    for node in nodes:
        weight = value_of(vehicle, node.props, "nodeWeight") or 0.0
        total += weight
        for axis in range(3):
            moment[axis] += weight * node.pos[axis]
    return total, (tuple(m / total for m in moment) if total else None)
