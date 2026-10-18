"""What the viewport colours entries by: their categories, and the places with problems."""

from __future__ import annotations

from dataclasses import dataclass, field

from .assembly import AssembledVehicle
from .assembly.links import link_target
from .checks import duplicate_key
from .lua import truthy

CATEGORY_KEYS = {"BREAK_GROUP": "breakGroup", "DEFORM_GROUP": "deformGroup", "GROUP": "group"}


def category(entry, by: str) -> str | None:
    """The name an entry is coloured by: its part, or the first name of a key such as breakGroup or group."""
    if by == "PART":
        return entry.part or None
    value = entry.props.get(CATEGORY_KEYS.get(by, by))
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str) and v), None)
    return value if isinstance(value, str) and value else None


@dataclass
class Problems:
    beams: set[int] = field(default_factory=set)
    """Indices in the vehicle's beams of beams that repeat another one, and of the ones they repeat."""
    faces: list[tuple[str, ...]] = field(default_factory=list)
    """Nodes of triangles and quads that use a node twice or have no area."""
    nodes: set[str] = field(default_factory=set)
    """Nodes of beams, faces, hydros and rails whose other nodes do not exist."""

    def __bool__(self) -> bool:
        return bool(self.beams or self.faces or self.nodes)


def find_problems(vehicle: AssembledVehicle) -> Problems:
    found = Problems()
    first: dict[tuple, int] = {}
    for index, beam in enumerate(vehicle.beams):
        key = duplicate_key(beam)
        if key is None:
            continue
        if key in first:
            found.beams.update((first[key], index))
        else:
            first[key] = index
    known = vehicle.nodes.keys() | vehicle.external_nodes.keys()
    for face in (*vehicle.triangles, *vehicle.quads):
        if len(set(face.ids)) < len(face.ids) or (known >= set(face.ids) and _flat(vehicle, face.ids)):
            found.faces.append(face.ids)
    rows = [((entry.id1, entry.id2) if hasattr(entry, "id1") else entry.ids, entry.props)
            for entry in (*vehicle.beams, *vehicle.triangles, *vehicle.quads, *vehicle.extras)]
    rows += [(tuple(str(v) for k, v in row.items() if link_target(k) == "nodes" and isinstance(v, str)), row)
             for _section, row in vehicle.dropped]
    for ids, props in rows:
        if truthy(props.get("optional")):
            continue
        present = [i for i in ids if i in known]
        if len(present) < len(ids):
            found.nodes.update(present)
    return found


def _flat(vehicle: AssembledVehicle, ids: tuple[str, ...]) -> bool:
    nodes = [(vehicle.nodes.get(i) or vehicle.external_nodes[i]).pos for i in ids]
    a, b, c = nodes[0], nodes[1], nodes[2]
    area = _cross_length(a, b, c)
    if len(nodes) == 4:
        area += _cross_length(a, c, nodes[3])
    longest = max(sum((p - q) ** 2 for p, q in zip(x, y)) for x in nodes for y in nodes)
    return area <= 1e-6 * longest


def _cross_length(a, b, c) -> float:
    u = [q - p for p, q in zip(a, b)]
    v = [q - p for p, q in zip(a, c)]
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return sum(x * x for x in cross) ** 0.5
