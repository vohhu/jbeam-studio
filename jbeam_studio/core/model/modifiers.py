"""Modifier rows of JBeam tables and the values they leave set for the parts after them.

The game appends the rows of every part to one table per section before it reads the modifier rows, so a
modifier such as {"group":"rotor"} at the end of one part's nodes also applies to the nodes of the parts read
after it, unless the part resets it.
"""

from __future__ import annotations

from ..sjson import Kind, Node

DEFAULT_RESETS: dict[str, dict[str, object]] = {
    "nodes": {
        "group": "", "collision": True, "selfCollision": False, "frictionCoef": 1, "fixed": False,
        "nodeMaterial": "|NM_METAL",
    },
    "beams": {
        "beamType": "|NORMAL", "beamPrecompression": 1, "beamLongBound": 1, "beamShortBound": 1,
        "breakGroup": "", "deformGroup": "", "deformLimitExpansion": "", "optional": False, "breakGroupType": 0,
        "disableTriangleBreaking": False, "disableMeshBreaking": False,
    },
    "triangles": {
        "group": "", "breakGroup": "", "dragCoef": 100, "liftCoef": 100, "stallAngle": 0.58, "pressureGroup": "",
        "triangleType": "NORMALTYPE", "externalCollisionBias": "",
    },
}
"""The values the game uses when a key is not set (from its vehicle loader), for the keys that are worth
resetting at the end of a table. Spring, damping and weight values are left out: parts set their own."""
DEFAULT_RESETS["quads"] = dict(DEFAULT_RESETS["triangles"])


def plain(node: Node):
    """The value of a syntax node as plain Python data."""
    if node.kind is Kind.ARRAY:
        return [plain(item) for item in node.items]
    if node.kind is Kind.OBJECT:
        return {member.key: plain(member.value) for member in node.members}
    return node.value


def is_default(key: str, value, default) -> bool:
    if key == "group" and value in ([], None):
        return True
    return value == default and type(value) is not bool or value is default


def modifier_state(table: Node) -> dict[str, tuple[object, Node]]:
    """The value each modifier key has after the last row of a table, with the modifier row that set it."""
    state: dict[str, tuple[object, Node]] = {}
    for item in table.items[1:]:
        if item.kind is Kind.OBJECT:
            for member in item.members:
                state[member.key] = (plain(member.value), item)
    return state


def leaks(table: Node, section: str, defaults: dict[str, dict[str, object]] | None = None) -> dict[str, tuple]:
    """Keys a table leaves set to something other than their default, with their value and modifier row."""
    known = (defaults or DEFAULT_RESETS).get(section, {})
    return {key: found for key, found in modifier_state(table).items()
            if key in known and not is_default(key, found[0], known[key])}
