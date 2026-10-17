from __future__ import annotations

import math

from ..lua import is_number, sign, truthy

_PREFIXES = (("nodeRotate", "rotate"), ("nodeOffset", "offset"), ("nodeMove", "move"))
Matrix = tuple[tuple[float, float, float, float], ...]
_IDENTITY: Matrix = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))


def _op_index(key: str, start: int) -> int:
    rest = key[start:start + 2]
    if not rest:
        return 0
    index = ord(rest[0]) - 48
    if len(rest) > 1:
        index = index * 10 + ord(rest[1]) - 48
    return index


def node_operations(node: dict) -> dict[int, dict[str, dict]]:
    """`nodeRotate`, `nodeOffset` and `nodeMove` modifiers of a node row, by their numeric suffix."""
    operations: dict[int, dict[str, dict]] = {}
    for key, data in node.items():
        if not isinstance(key, str) or not isinstance(data, dict) or not all(is_number(data.get(a)) for a in "xyz"):
            continue
        for prefix, kind in _PREFIXES:
            if key.startswith(prefix):
                if kind == "offset" and truthy(node.get("ignoreNodeOffset")):
                    break
                operations.setdefault(_op_index(key, len(prefix)), {})[kind] = data
                break
    return operations


def _mul(a: Matrix, b: Matrix) -> Matrix:
    return tuple(tuple(sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)) for r in range(4))


def _translation(x: float, y: float, z: float) -> Matrix:
    return ((1.0, 0.0, 0.0, x), (0.0, 1.0, 0.0, y), (0.0, 0.0, 1.0, z), (0.0, 0.0, 0.0, 1.0))


def _rotation(op: dict) -> Matrix:
    x, y, z = (math.radians(op[axis]) for axis in "xyz")
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rot_x = ((1.0, 0.0, 0.0, 0.0), (0.0, cx, -sx, 0.0), (0.0, sx, cx, 0.0), (0.0, 0.0, 0.0, 1.0))
    rot_y = ((cy, 0.0, sy, 0.0), (0.0, 1.0, 0.0, 0.0), (-sy, 0.0, cy, 0.0), (0.0, 0.0, 0.0, 1.0))
    rot_z = ((cz, -sz, 0.0, 0.0), (sz, cz, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    # The engine builds the matrix from Euler angles as Y * X * Z and the game passes negated angles,
    # which makes every factor a standard right-handed rotation.
    rotation = _mul(_mul(rot_y, rot_x), rot_z)
    pivot = [op.get(key) for key in ("px", "py", "pz")]
    if any(truthy(p) for p in pivot):
        px, py, pz = (p if is_number(p) else 0 for p in pivot)
        return _mul(_mul(_translation(px, py, pz), rotation), _translation(-px, -py, -pz))
    return rotation


def _forward(operations: dict[int, dict[str, dict]], x_sign: int) -> Matrix:
    matrix = _IDENTITY
    for index in sorted(operations):
        op = operations[index]
        if "rotate" in op:
            matrix = _mul(matrix, _rotation(op["rotate"]))
        if "offset" in op:
            offset = op["offset"]
            matrix = _mul(matrix, _translation(x_sign * offset["x"], offset["y"], offset["z"]))
        if "move" in op:
            move = op["move"]
            matrix = _mul(matrix, _translation(move["x"], move["y"], move["z"]))
    return matrix


def _inverse(matrix: Matrix) -> Matrix:
    rotation = [[matrix[c][r] for c in range(3)] for r in range(3)]
    translation = [-sum(rotation[r][k] * matrix[k][3] for k in range(3)) for r in range(3)]
    return tuple(tuple(rotation[r]) + (translation[r],) for r in range(3)) + ((0.0, 0.0, 0.0, 1.0),)


def _transform(matrix: Matrix, point) -> tuple[float, float, float]:
    x, y, z = point
    return tuple(matrix[r][0] * x + matrix[r][1] * y + matrix[r][2] * z + matrix[r][3] for r in range(3))


def raw_position_for(node: dict, target) -> tuple[float, float, float] | None:
    """posX/posY/posZ that put a node with this row's modifiers at `target`, or None if no position does.

    Offsets on X follow the sign of posX, so a node with a `nodeOffset` on X cannot get closer to the center
    than that offset; the sign is chosen to be consistent with the result.
    """
    operations = node_operations(node)
    if not operations:
        return tuple(target)
    for x_sign in dict.fromkeys((sign(node.get("posX", 0) or 0), sign(target[0]), 1, -1, 0)):
        raw = _transform(_inverse(_forward(operations, x_sign)), target)
        if sign(raw[0]) == x_sign:
            return raw
    return None


def node_position(node: dict) -> tuple[float, float, float]:
    """Final position of a node row: posX/posY/posZ with its rotate, offset and move modifiers applied."""
    x, y, z = node["posX"], node["posY"], node["posZ"]
    operations = node_operations(node)
    if not operations:
        return (x, y, z)
    x_sign = sign(x)
    if any("rotate" in op for op in operations.values()):
        return _transform(_forward(operations, x_sign), (x, y, z))
    dx = dy = dz = 0
    for index in sorted(operations):
        op = operations[index]
        if "offset" in op:
            offset = op["offset"]
            dx, dy, dz = dx + x_sign * offset["x"], dy + offset["y"], dz + offset["z"]
        if "move" in op:
            move = op["move"]
            dx, dy, dz = dx + move["x"], dy + move["y"], dz + move["z"]
    return (dx + x, dy + y, dz + z)
