"""Mirroring nodes, beams, triangles and quads across a plane, with the side letters of their names swapped."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..assembly import EXTRA_SECTIONS
from ..lua import truthy
from .session import EditError, EditSession
from .text import json_literal

CENTER = 0.005
"""Nodes closer than this to the mirror plane are on it: they are their own mirror."""
AXES = {"x": 0, "y": 1, "z": 2}
DEFAULT_PAIRS = {
    "x": (("l", "r"), ("ll", "rr")),
    "y": (("f", "b"), ("ff", "bb")),
    "z": (("t", "d"), ("tt", "dd")),
}
"""Side letters swapped by mirroring across each axis: left and right, front and back, top and down."""
_NAME = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)(?P<suffix>[A-Za-z]*)$")


def parse_pairs(text: str) -> tuple[tuple[str, str], ...]:
    """Pairs written as "l:r, ll:rr"."""
    pairs = []
    for item in text.split(","):
        if ":" in item:
            a, b = (s.strip() for s in item.split(":", 1))
            if a and b and a != b:
                pairs.append((a, b))
    return tuple(pairs)


def mirror_name(node_id: str, pairs: Sequence[tuple[str, str]] = DEFAULT_PAIRS["x"]) -> str | None:
    """The id of the node on the other side, `e3l` -> `e3r`; None when the id does not end with a number and a
    side letter of `pairs`."""
    swap = {a: b for a, b in pairs} | {b: a for a, b in pairs}
    for side in sorted(swap, key=len, reverse=True):
        if node_id.endswith(side) and node_id[:-len(side)][-1:].isdigit():
            return node_id[:-len(side)] + swap[side]
    return None


def mirror_label(name: str, pairs: Sequence[tuple[str, str]], taken: set[str]) -> str:
    """The name of the mirror of a rail, `boxside_R` -> `boxside_L`, `leaf_RL` -> `leaf_RR`: its last side letter
    swapped, a lower-case one only after a digit or a sign. Without a side letter, or when that name is taken, a
    name of its own."""
    swap = {a: b for a, b in pairs} | {b: a for a, b in pairs}
    for side in sorted(swap, key=len, reverse=True):
        for here, there in ((side, swap[side]), (side.upper(), swap[side].upper())):
            if len(name) > len(here) and name.endswith(here) and (here.isupper() or not name[-len(here) - 1].isalpha()):
                candidate = name[:-len(here)] + there
                if candidate not in taken:
                    return candidate
    candidate, number = f"{name}_mirrored", 2
    while candidate in taken:
        candidate, number = f"{name}_mirrored{number}", number + 1
    return candidate


def _free_name(source: str, taken: set[str]) -> str:
    match = _NAME.match(source)
    prefix, suffix = (match["prefix"], match["suffix"]) if match else (source, "")
    used = [int(m["number"]) for m in map(_NAME.match, taken) if m and m["prefix"] == prefix]
    number = max(used, default=0) + 1
    while f"{prefix}{number}{suffix}" in taken:
        number += 1
    return f"{prefix}{number}{suffix}"


@dataclass
class MirrorResult:
    mirrors: dict[str, str] = field(default_factory=dict)
    """The mirror of each mirrored node (nodes on the plane are their own mirror)."""
    added: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    """Existing counterparts moved to the mirrored place."""
    beams: int = 0
    faces: int = 0
    extras: int = 0
    """Hydros, torsion bars, slide nodes and rails added."""


def mirror(session: EditSession, node_ids: Iterable[str], allow_shared: bool = False, axis: str = "x",
           center: float = 0.0, pairs: Sequence[tuple[str, str]] | None = None) -> MirrorResult:
    """Copies nodes to the other side of the plane `axis` = `center`, or moves their existing counterparts there,
    and mirrors the beams, triangles and quads that use them, as one change.

    A node's counterpart is the node with the mirrored name (`e3l` and `e3r` across X, `e3f` and `e3b` across Y).
    When a node and its counterpart are both given, both stay where they are. New nodes take the mirrored name,
    or the next free number when that is taken, and go to the part of their original; mirrored faces get the
    opposite winding so they face outwards.
    """
    if axis not in AXES:
        raise EditError(f'unknown mirror axis "{axis}"')
    index = AXES[axis]
    pairs = DEFAULT_PAIRS[axis] if pairs is None else pairs
    vehicle = session.vehicle
    nodes = vehicle.nodes
    selected = [n for n in dict.fromkeys(node_ids) if n in nodes]
    if not selected:
        raise EditError("select nodes of this vehicle to mirror")
    chosen = set(selected)
    taken = set(nodes) | set(vehicle.external_nodes)
    result = MirrorResult()
    additions: dict[str, list[tuple[str, tuple]]] = defaultdict(list)
    moves: dict[str, tuple] = {}

    def on_plane(position) -> bool:
        return abs(position[index] - center) <= CENTER

    for node_id in selected:
        position = nodes[node_id].pos
        if on_plane(position):
            result.mirrors[node_id] = node_id
            continue
        target = tuple(2 * center - c if i == index else c for i, c in enumerate(position))
        other = mirror_name(node_id, pairs)
        if other is not None and (other in nodes or other in vehicle.external_nodes):
            result.mirrors[node_id] = other
            if other in nodes and other not in chosen:
                moves[other] = target
            continue
        name = other if other is not None and other not in taken else _free_name(other or node_id, taken)
        taken.add(name)
        additions[nodes[node_id].part].append((name, target))
        result.mirrors[node_id] = name

    def mirrored(node_id: str) -> str | None:
        if node_id in result.mirrors:
            return result.mirrors[node_id]
        node = nodes.get(node_id) or vehicle.external_nodes.get(node_id)
        if node is not None and on_plane(node.pos):
            return node_id
        other = mirror_name(node_id, pairs)
        return other if other is not None and (other in nodes or other in vehicle.external_nodes) else None

    beams: dict[str, list[tuple[str, str]]] = defaultdict(list)
    existing = {frozenset((b.id1, b.id2)) for b in vehicle.beams}
    for beam in vehicle.beams:
        if not {beam.id1, beam.id2} & chosen:
            continue
        ends = (mirrored(beam.id1), mirrored(beam.id2))
        key = frozenset(ends)
        if None in ends or ends[0] == ends[1] or key == frozenset((beam.id1, beam.id2)) or key in existing:
            continue
        existing.add(key)
        beams[beam.part].append(ends)
    faces: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    existing = {frozenset(f.ids) for f in vehicle.triangles + vehicle.quads}
    for face in vehicle.triangles + vehicle.quads:
        if not set(face.ids) & chosen:
            continue
        ids = tuple(mirrored(i) for i in face.ids)
        key = frozenset(ids)
        if None in ids or len(key) != len(ids) or key == frozenset(face.ids) or key in existing:
            continue
        existing.add(key)
        faces[face.part].append((ids[0], *reversed(ids[1:])))
    rails, copies = _mirror_extras(session, chosen, mirrored, pairs)
    if not (moves or additions or beams or faces or rails or copies):
        return result
    with session.transaction(f"Mirror {len(selected)} node(s) across {axis.upper()}"):
        if moves:
            session.move_nodes(moves, allow_shared)
            result.moved = list(moves)
        for part, rows in additions.items():
            result.added += session.add_nodes(part, [p for _, p in rows], node_ids=[n for n, _ in rows],
                                              allow_shared=allow_shared)
        for part, rows in beams.items():
            session.add_beams(part, rows, allow_shared)
            result.beams += len(rows)
        for part, rows in faces.items():
            session.add_faces(part, rows, allow_shared)
            result.faces += len(rows)
        for part, name, links, rail in rails:
            session.add_rail(part, name, links, truthy(rail.props.get("looped")), rail.props.get("capped", True)
                             not in (False, 0), allow_shared,
                             broken=[mirrored(i) or i for i in rail.props.get("broken:") or []])
            result.extras += 1
        current = {(e.section, e.ids, e.name): e for e in session.vehicle.extras}
        found = [(current[key], cells) for key, cells in copies if key in current]
        if found:
            result.extras += session.copy_extras(found, allow_shared)
    return result


def _mirror_extras(session: EditSession, chosen: set[str], mirrored, pairs):
    """The rails to add, as (part, name, links, original), and the rows of hydros, torsion bars and slide nodes
    to copy, as (identity of the original, replaced cells), for mirroring the nodes `chosen`."""
    extras = session.vehicle.extras
    rails = {e.name: e for e in extras if e.section == "rails"}
    taken = set(rails)
    targets: dict[str, str | None] = {}
    added: list[tuple[str, str, list[str], object]] = []

    def target(rail, create: bool) -> str | None:
        if rail.name in targets:
            return targets[rail.name]
        links = tuple(mirrored(i) for i in rail.ids)
        if None in links:
            return None
        if set(links) == set(rail.ids):
            name = rail.name
        else:
            twin = next((r for r in rails.values() if r.ids in (links, links[::-1])), None)
            if twin is not None:
                name = twin.name
            elif create and session.extra_part(rail) is not None:
                name = mirror_label(rail.name, pairs, taken)
                taken.add(name)
                added.append((session.extra_part(rail), name, list(links), rail))
            else:
                return None
        targets[rail.name] = name
        return name

    for rail in rails.values():
        if set(rail.ids) & chosen:
            target(rail, create=True)
    existing = {_shape(e.section, e.ids, e.name) for e in extras}
    copies = []
    for extra in extras:
        if extra.section == "rails" or not set(extra.ids) & chosen:
            continue
        ids = tuple(mirrored(i) for i in extra.ids)
        if None in ids or len(set(ids)) != len(ids) or set(ids) == set(extra.ids):
            continue
        name = None
        if extra.section == "slidenodes":
            rail = rails.get(extra.name)
            name = target(rail, create=False) if rail is not None else None
            if name is None:
                continue
            cells = {"id:": json_literal(ids[0]), "railName": json_literal(name)}
        else:
            cells = dict(zip(EXTRA_SECTIONS[extra.section], map(json_literal, ids)))
        shape = _shape(extra.section, ids, name)
        if shape in existing:
            continue
        existing.add(shape)
        copies.append(((extra.section, extra.ids, extra.name), cells))
    return added, copies


def _shape(section: str, ids: tuple, name: str | None):
    """What makes two rows the same: a hydro joins two nodes in either order, and a torsion bar twists about its
    middle two nodes between its outer two, in any order of each pair."""
    if section == "hydros":
        return section, frozenset(ids), name
    if section in ("torsionbars", "torsionHydros") and len(ids) == 4:
        return section, frozenset(ids[1:3]), frozenset((ids[0], ids[3])), name
    return section, ids, name
