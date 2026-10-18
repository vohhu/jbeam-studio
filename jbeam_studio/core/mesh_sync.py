"""An edit session shown as a mesh, and edits of that mesh turned into session operations.

Nodes become vertices, beams edges, triangles and quads faces. Each of them gets a uid that stays the same while
the session's history moves back and forth, so a mesh restored by an undo in the 3D editor can be matched with
the session state it was built from. Beams between the same two nodes share one edge, and faces on the same
nodes share one face, because a mesh cannot hold duplicates.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Mapping

from .edit import EditError, EditSession
from .edit.session import Change, NewBlock

PLACE_END = "end"
PLACE_SOURCE = "source"
PLACE_GROUP = "group"

MOVE_EPSILON = 5e-5
"""Smallest change of a vertex position taken as a move; meshes keep coordinates as 32-bit floats."""
FACE_EDGE = -2
"""Edge uid of an edge that only borders triangles or quads: it is not a beam."""


def uid_check(uid: int) -> int:
    """The value stored next to each node uid.

    Tools that blend vertex data, such as subdividing an edge, give a new vertex the average of its neighbours'
    uids, which may be the uid of some other node; its check value then does not match.
    """
    return (uid * 2654435761 + 97) % 2147483629 + 1


@dataclass
class Group:
    uid: int
    nodes: tuple[int, ...]
    """Node uids in the order of the first entry."""
    indices: list[int] = field(default_factory=list)
    """Indices into the vehicle's beams, or into its triangles followed by its quads."""


@dataclass
class UidMap:
    nodes: dict[str, int]
    beams: dict[int, Group]
    faces: dict[int, Group]
    _ids: dict[int, str] | None = None

    @property
    def ids(self) -> dict[int, str]:
        """Node ids by uid."""
        if self._ids is None:
            self._ids = {uid: node_id for node_id, uid in self.nodes.items()}
        return self._ids


@dataclass
class MeshData:
    """Plain mesh data, as written to or read from the 3D editor."""

    positions: list[tuple[float, float, float]] = field(default_factory=list)
    node_uids: list[int] = field(default_factory=list)
    node_checks: list[int] = field(default_factory=list)
    edges: list[tuple[int, int]] = field(default_factory=list)
    edge_uids: list[int] = field(default_factory=list)
    faces: list[tuple[int, ...]] = field(default_factory=list)
    face_uids: list[int] = field(default_factory=list)
    ghosts: list[bool] = field(default_factory=list)
    """Nodes of other parts, shown but not edited."""
    parts: list[int] = field(default_factory=list)
    """Index of each vertex's part in `MeshLink.part_names`, -1 for nodes of other parts."""


@dataclass
class SyncPlan:
    """Operations that bring the session to the state of a mesh."""

    moves: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    deleted_nodes: list[str] = field(default_factory=list)
    new_nodes: dict[int, tuple[float, float, float]] = field(default_factory=dict)
    """Positions of new nodes by vertex index."""
    deleted_beams: list[int] = field(default_factory=list)
    deleted_faces: list[int] = field(default_factory=list)
    flipped_faces: list[int] = field(default_factory=list)
    new_beams: list[tuple[str | int, str | int]] = field(default_factory=list)
    """Node ids of existing nodes, vertex indices of new ones."""
    new_faces: list[tuple[str | int, ...]] = field(default_factory=list)
    vertex_nodes: dict[int, str] = field(default_factory=dict)
    """Existing node of each vertex that has one."""
    new_sources: dict[int, str | int] = field(default_factory=dict)
    """What each new node came from, for naming it: the node it was duplicated or extruded from, or a node it is
    joined to by an edge; a vertex index when that is a new node too."""
    new_beam_sources: dict[int, tuple[str, ...]] = field(default_factory=dict)
    """Node ids of the beam each new beam was copied from (Shift+D, extruding an edge), by index in `new_beams`."""
    new_face_sources: dict[int, tuple[str, ...]] = field(default_factory=dict)
    ghosts_moved: int = 0
    ghosts_deleted: int = 0
    ngons: int = 0
    """New faces with more than four corners, which JBeam has no section for."""
    scope: str | None = None
    """The part the mesh shows, whose rows alone the plan changes; None for the whole vehicle."""

    @property
    def empty(self) -> bool:
        return not (self.moves or self.deleted_nodes or self.new_nodes or self.deleted_beams or self.deleted_faces
                    or self.flipped_faces or self.new_beams or self.new_faces)

    @property
    def needs_rebuild(self) -> bool:
        """The mesh differs from the session in a way the plan does not change, so it should be built again."""
        return bool(self.ghosts_moved or self.ghosts_deleted or self.ngons)


_NAME = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)(?P<suffix>[A-Za-z]*)$")
_SIDES = {"l": ("l", "r"), "r": ("l", "r"), "ll": ("ll", "rr"), "rr": ("ll", "rr")}
CENTER = 0.005
"""Nodes closer than this to X = 0 are centre nodes and get no side letter."""


def name_like(source: str, position, taken: set[str]) -> str:
    """A new node id in the naming scheme of `source`: its prefix, the next number of that prefix, and its side
    letter (`l` for +X, `r` for -X, none at the centre) when the source has one, as in `e3l` -> `e5r`."""
    match = _NAME.match(source)
    prefix, suffix = (match["prefix"], match["suffix"]) if match else (source, "")
    if suffix in _SIDES:
        left, right = _SIDES[suffix]
        suffix = left if position[0] > CENTER else right if position[0] < -CENTER else ""
    used = [int(m["number"]) for m in map(_NAME.match, taken) if m and m["prefix"] == prefix]
    number = max(used, default=0) + 1
    while f"{prefix}{number}{suffix}" in taken:
        number += 1
    return f"{prefix}{number}{suffix}"


def _digest(text: str) -> bytes:
    return hashlib.sha1(text.encode("utf-8")).digest()


def _moved(position, target) -> bool:
    return any(abs(float(a) - b) > MOVE_EPSILON for a, b in zip(position, target))


def _reversed(face: tuple[int, ...], reference: tuple[int, ...]) -> bool:
    if reference[0] not in face:
        return False
    start = face.index(reference[0])
    rotated = face[start:] + face[:start]
    return rotated != reference and (rotated[0], *reversed(rotated[1:])) == reference


MAPS_KEPT = 128
VEHICLES_KEPT = 4


class MeshLink:
    """Uids of one session's nodes, beams and faces for every state its history can reach.

    A state is numbered by the content of the files, so reaching the same texts again, as when an undo in the
    3D editor is followed by a redo that applies the same mesh edits, gives the same number and the same uids.
    """

    def __init__(self, session: EditSession):
        self.session = session
        self._next_uid = 1
        self._generation = random.randrange(1, 1 << 30)
        """Part of every state number, so a mesh saved by an earlier Blender session never matches a state."""
        self._original: dict = {}
        """Digest and text of each edited file as it was before its first change."""
        self._snapshots: OrderedDict[int, dict] = OrderedDict()
        """Texts of the edited files in recent states, to return to states the history no longer reaches."""
        self._rev_cache: tuple | None = None
        self._positions: dict[int, tuple[Change, int]] = {}
        self._base_rev = 0
        self._maps: OrderedDict[int, UidMap] = OrderedDict()
        self._vehicles: OrderedDict[int, object] = OrderedDict()
        self._parts_cache: tuple | None = None
        self._current = self.rev
        self._maps[self._current] = self._derive(None, {})
        self._remember()

    def _new_uid(self) -> int:
        self._next_uid += 1
        return self._next_uid - 1

    # states

    @property
    def rev(self) -> int:
        """Number of the session's current state, from the content of the files."""
        session = self.session
        if self._rev_cache is not None and self._rev_cache[0] is session.vehicle:
            return self._rev_cache[1]
        for change in session.history:
            for path, text in change.before.items():
                if path not in self._original:
                    self._original[path] = (_digest(text), text)
        digest = hashlib.sha1(str(self._generation).encode())
        texts = {}
        for path in sorted(self._original, key=str):
            text = session.text_of(path)
            texts[path] = text
            current = _digest(text)
            if current != self._original[path][0]:
                digest.update(str(path).encode("utf-8"))
                digest.update(current)
        rev = int.from_bytes(digest.digest()[:4], "big") & 0x7FFFFFFF or 1
        self._rev_cache = (session.vehicle, rev)
        self._snapshots[rev] = texts
        self._snapshots.move_to_end(rev)
        while len(self._snapshots) > MAPS_KEPT:
            self._snapshots.popitem(last=False)
        if session.position == 0:
            self._base_rev = rev
        else:
            change = session.history[session.position - 1]
            self._positions[id(change)] = (change, rev)
        return rev

    def position_of(self, rev: int) -> int | None:
        """History position of a state, or None if the history no longer reaches it."""
        if rev == self._base_rev:
            return 0
        for position, change in enumerate(self.session.history, 1):
            stored = self._positions.get(id(change))
            if stored is not None and stored[0] is change and stored[1] == rev:
                return position
        return None

    def goto(self, rev: int) -> bool:
        """Brings the session to a state: through the history, or from the texts kept of a state it no longer has."""
        position = self.position_of(rev)
        if position is not None:
            if position != self.session.position:
                self.session.goto(position, self._vehicles.get(rev))
        elif rev in self._snapshots:
            target = {path: text for path, (_, text) in self._original.items()}
            target.update(self._snapshots[rev])
            self.session.restore(target, self._vehicles.get(rev))
            if self.rev != rev:
                return False
        else:
            return False
        self._current = self.rev
        if self._current not in self._maps:
            self.changed()
        self._remember()
        return True

    @property
    def map(self) -> UidMap:
        if self.rev not in self._maps:
            self.changed()
        return self._maps[self.rev]

    def changed(self, renames: Mapping[str, str] | None = None) -> None:
        """Takes in the state the session reached with an operation; `renames` maps new node ids to old ones."""
        rev = self.rev
        if rev not in self._maps:
            self._maps[rev] = self._derive(self._maps.get(self._current), renames or {})
        self._maps.move_to_end(rev)
        while len(self._maps) > MAPS_KEPT:
            self._maps.popitem(last=False)
        self._current = rev
        live = {id(change) for change in self.session.history}
        self._positions = {key: value for key, value in self._positions.items() if key in live}
        self._remember()

    def _remember(self) -> None:
        """Keeps the assembled vehicle of the current state, so going back to it needs no assembly."""
        self._vehicles[self._current] = self.session.vehicle
        self._vehicles.move_to_end(self._current)
        while len(self._vehicles) > VEHICLES_KEPT:
            self._vehicles.popitem(last=False)

    def reset(self) -> None:
        """Takes in a session whose history was cleared, as by reloading a file; uids are kept where possible."""
        previous = self._maps.get(self._current)
        self._generation = random.randrange(1, 1 << 30)
        self._original.clear()
        self._snapshots.clear()
        self._positions.clear()
        self._rev_cache = None
        self._vehicles.clear()
        self._maps = OrderedDict()
        self._current = self.rev
        self._maps[self._current] = self._derive(previous, {})
        self._remember()

    def _derive(self, previous: UidMap | None, renames: Mapping[str, str]) -> UidMap:
        vehicle = self.session.vehicle
        old = previous.nodes if previous is not None else {}
        nodes: dict[str, int] = {}
        used: set[int] = set()
        for node_id in [*vehicle.nodes, *vehicle.external_nodes]:
            if node_id in nodes:
                continue
            uid = old.get(renames.get(node_id, node_id))
            if uid is None or uid in used:
                uid = self._new_uid()
            nodes[node_id] = uid
            used.add(uid)
        beams = self._groups([(b.id1, b.id2) for b in vehicle.beams], nodes,
                             previous.beams if previous is not None else {})
        faces = self._groups([f.ids for f in vehicle.triangles + vehicle.quads], nodes,
                             previous.faces if previous is not None else {})
        return UidMap(nodes, beams, faces)

    def _groups(self, links: list[tuple[str, ...]], nodes: dict[str, int], previous: dict[int, Group]) -> dict[int, Group]:
        old = {frozenset(g.nodes): g.uid for g in previous.values()}
        by_key: dict[frozenset, Group] = {}
        for index, ids in enumerate(links):
            uids = tuple(nodes.get(node_id) for node_id in ids)
            if None in uids or len(set(uids)) != len(uids):
                continue
            key = frozenset(uids)
            group = by_key.get(key)
            if group is None:
                group = by_key[key] = Group(old.get(key) or self._new_uid(), uids)
            group.indices.append(index)
        return {g.uid: g for g in by_key.values()}

    # mesh

    @property
    def part_names(self) -> list[str]:
        return list(self.session.vehicle.parts)

    def node_of(self, uid: int, check: int) -> str | None:
        """The node a vertex stands for, judged by its uid and check value."""
        if uid <= 0 or check != uid_check(uid):
            return None
        return self.map.ids.get(uid)

    def _partition(self) -> tuple[dict, dict, dict]:
        """The nodes, beam groups and face groups of each part, worked out once for each state."""
        vehicle, uid_map = self.session.vehicle, self.map
        cached = self._parts_cache
        if cached is not None and cached[0] is vehicle and cached[1] is uid_map:
            return cached[2]
        nodes: dict[str, set[str]] = defaultdict(set)
        beams: dict[str, list[Group]] = defaultdict(list)
        faces: dict[str, list[Group]] = defaultdict(list)
        for node_id, node in vehicle.nodes.items():
            nodes[node.part].add(node_id)
        for group in uid_map.beams.values():
            for part in dict.fromkeys(vehicle.beams[i].part for i in group.indices):
                beams[part].append(group)
        all_faces = vehicle.triangles + vehicle.quads
        for group in uid_map.faces.values():
            for part in dict.fromkeys(all_faces[i].part for i in group.indices):
                faces[part].append(group)
        self._parts_cache = (vehicle, uid_map, (nodes, beams, faces))
        return nodes, beams, faces

    def own_nodes(self, scope: str | None) -> set[str]:
        """Nodes a mesh of part `scope` edits: the nodes of that part, or of the whole vehicle for None."""
        if scope is None:
            return set(self.session.vehicle.nodes)
        return self._partition()[0].get(scope, set())

    def scoped(self, scope: str | None) -> tuple[list[Group], list[Group]]:
        """The beam and face groups a mesh of part `scope` shows: those with a row in that part."""
        if scope is None:
            uid_map = self.map
            return list(uid_map.beams.values()), list(uid_map.faces.values())
        _, beams, faces = self._partition()
        return beams.get(scope, []), faces.get(scope, [])

    def ghost_nodes(self, scope: str | None) -> set[str]:
        """Nodes of other parts that the beams and faces of part `scope` use."""
        if scope is None:
            return set(self.session.vehicle.external_nodes)
        ids, own = self.map.ids, self.own_nodes(scope)
        beams, faces = self.scoped(scope)
        return {ids[uid] for group in beams + faces for uid in group.nodes} - own

    def build(self, scope: str | None = None, all_nodes: bool = False) -> MeshData:
        """The mesh of the whole vehicle, or of part `scope`: its nodes, beams and faces, with the nodes of other
        parts they use as ghosts, or with every other node of the vehicle as a ghost if `all_nodes` is set."""
        vehicle, uid_map = self.session.vehicle, self.map
        part_index = {name: i for i, name in enumerate(self.part_names)}
        own = self.own_nodes(scope)
        ghosts = self.ghost_nodes(scope)
        beams, faces = self.scoped(scope)
        data = MeshData()
        vertex: dict[int, int] = {}
        for nodes in (vehicle.nodes, vehicle.external_nodes):
            for node_id, node in nodes.items():
                ghost = node_id not in own
                if ghost and not (all_nodes or node_id in ghosts):
                    continue
                uid = uid_map.nodes[node_id]
                if uid in vertex:
                    continue
                vertex[uid] = len(data.positions)
                data.positions.append(tuple(node.pos))
                data.node_uids.append(uid)
                data.node_checks.append(uid_check(uid))
                data.ghosts.append(ghost)
                data.parts.append(-1 if ghost else part_index.get(node.part, -1))
        for group in beams:
            data.edges.append((vertex[group.nodes[0]], vertex[group.nodes[1]]))
            data.edge_uids.append(group.uid)
        for group in faces:
            data.faces.append(tuple(vertex[uid] for uid in group.nodes))
            data.face_uids.append(group.uid)
        return data

    def plan(self, mesh: MeshData, scope: str | None = None) -> SyncPlan:
        """Operations that make the session match `mesh`, a mesh built from the current state and then edited.

        Every vertex, edge and face that does not stand for an existing entry is new: a node, a beam, and a
        triangle or quad. Edges marked `FACE_EDGE` are never beams. For a mesh of part `scope`, nodes of other
        parts are ghosts, and only the nodes, beams and faces of that part can be deleted; a ghost vertex whose
        node no longer exists is left out.
        """
        vehicle, uid_map = self.session.vehicle, self.map
        plan = SyncPlan(scope=scope)
        own = self.own_nodes(scope)
        refs: list[str | int | None] = []
        seen: set[int] = set()
        flags = mesh.ghosts if len(mesh.ghosts) == len(mesh.positions) else [False] * len(mesh.positions)
        for index, (position, uid, check) in enumerate(zip(mesh.positions, mesh.node_uids, mesh.node_checks)):
            node_id = self.node_of(uid, check) if uid not in seen else None
            if node_id is None:
                copied = self.node_of(uid, check)
                if copied is None and flags[index]:
                    refs.append(None)
                    plan.ghosts_deleted += 1
                    continue
                refs.append(index)
                plan.new_nodes[index] = tuple(float(c) for c in position)
                if copied is not None:
                    plan.new_sources[index] = copied
                continue
            seen.add(uid)
            refs.append(node_id)
            plan.vertex_nodes[index] = node_id
            if node_id not in own:
                node = vehicle.nodes.get(node_id) or vehicle.external_nodes[node_id]
                if _moved(position, node.pos):
                    plan.ghosts_moved += 1
                continue
            node = vehicle.nodes[node_id]
            if _moved(position, node.pos):
                plan.moves[node_id] = tuple(float(p) if abs(float(p) - c) > MOVE_EPSILON else c
                                            for p, c in zip(position, node.pos))
        missing_ghosts = {uid_map.nodes[i] for i in self.ghost_nodes(scope)} - seen
        plan.ghosts_deleted += len(missing_ghosts)
        plan.deleted_nodes = [node_id for node_id in vehicle.nodes
                              if node_id in own and uid_map.nodes[node_id] not in seen]
        keys = [uid_map.nodes[ref] if isinstance(ref, str) else -(ref + 1) if ref is not None else None
                for ref in refs]
        for want_existing in (True, False):
            for a, b in mesh.edges:
                for vertex, other in ((a, b), (b, a)):
                    if (vertex in plan.new_nodes and vertex not in plan.new_sources and vertex != other
                            and refs[other] is not None and isinstance(refs[other], str) == want_existing):
                        plan.new_sources[vertex] = refs[other]

        scoped_beams, scoped_faces = self.scoped(scope)
        beam_keys = {frozenset(g.nodes): g.uid for g in uid_map.beams.values()}
        kept: set[int] = set()
        unmatched = []
        for (a, b), uid in zip(mesh.edges, mesh.edge_uids):
            if uid == FACE_EDGE or a == b or keys[a] is None or keys[b] is None:
                continue
            key = frozenset((keys[a], keys[b]))
            group = uid_map.beams.get(uid) if uid > 0 else None
            if group is not None and uid not in kept and frozenset(group.nodes) == key:
                kept.add(uid)
            else:
                unmatched.append((a, b, key, group))
        ids = uid_map.ids
        for a, b, key, copied in unmatched:
            existing = beam_keys.get(key)
            if existing is not None:
                kept.add(existing)
            else:
                if copied is not None:
                    plan.new_beam_sources[len(plan.new_beams)] = tuple(ids[u] for u in copied.nodes)
                plan.new_beams.append((refs[a], refs[b]))
        plan.deleted_beams = [g.uid for g in scoped_beams if g.uid not in kept and not missing_ghosts & set(g.nodes)]

        face_keys = {frozenset(g.nodes): g.uid for g in uid_map.faces.values()}
        kept = set()
        unmatched = []
        for verts, uid in zip(mesh.faces, mesh.face_uids):
            ordered = tuple(keys[v] for v in verts)
            if None in ordered:
                continue
            group = uid_map.faces.get(uid) if uid > 0 else None
            if (group is not None and uid not in kept and len(group.nodes) == len(ordered)
                    and frozenset(group.nodes) == frozenset(ordered)):
                kept.add(uid)
                if _reversed(ordered, group.nodes):
                    plan.flipped_faces.append(uid)
            else:
                unmatched.append((verts, uid, ordered))
        for verts, uid, ordered in unmatched:
            existing = face_keys.get(frozenset(ordered))
            if existing is not None and len(uid_map.faces[existing].nodes) == len(ordered):
                if existing not in kept:
                    kept.add(existing)
                    if _reversed(ordered, uid_map.faces[existing].nodes):
                        plan.flipped_faces.append(existing)
            elif len(verts) in (3, 4) and len(set(ordered)) == len(ordered):
                copied = uid_map.faces.get(uid) if uid > 0 else None
                if copied is not None:
                    plan.new_face_sources[len(plan.new_faces)] = tuple(ids[u] for u in copied.nodes)
                plan.new_faces.append(tuple(refs[v] for v in verts))
            else:
                plan.ngons += 1
        plan.deleted_faces = [g.uid for g in scoped_faces if g.uid not in kept and not missing_ghosts & set(g.nodes)]
        return plan

    def new_names(self, plan: SyncPlan, vertices: list[int], prefix: str = "n") -> list[str]:
        """Ids for new nodes in the naming scheme of the nodes they came from (see `name_like`); nodes that came
        from nothing get the prefix and a number."""
        vehicle = self.session.vehicle
        taken = set(vehicle.nodes) | set(vehicle.external_nodes)
        names: dict[int, str] = {}
        pending = list(vertices)
        while pending:
            ready = [v for v in pending if not isinstance(plan.new_sources.get(v), int)
                     or plan.new_sources[v] in names or plan.new_sources[v] not in plan.new_nodes]
            for vertex in ready or pending[:1]:
                source = plan.new_sources.get(vertex)
                if isinstance(source, int):
                    source = names.get(source)
                if source:
                    name = name_like(source, plan.new_nodes[vertex], taken)
                else:
                    number = 1
                    while f"{prefix}{number}" in taken:
                        number += 1
                    name = f"{prefix}{number}"
                names[vertex] = name
                taken.add(name)
                pending.remove(vertex)
        return [names[v] for v in vertices]

    def apply(self, plan: SyncPlan, part_name: str | None, prefix: str = "n", allow_shared: bool = False,
              auto_names: bool = False, placement: str = PLACE_END, group: str | None = None,
              prefer: int | None = None) -> dict[int, str]:
        """Runs a plan as one change and returns the ids given to new nodes, by vertex index.

        With `auto_names` new nodes are named after the nodes they came from, otherwise with the prefix.
        `placement` says where new rows go in their tables: at the end (`PLACE_END`), next to the row they come
        from (`PLACE_SOURCE`), or into node group `group` (`PLACE_GROUP`). `prefer` is the vertex whose rows
        are looked at first, such as the active vertex when two nodes are joined.
        """
        if plan.empty:
            return {}
        session, uid_map = self.session, self.map
        node_parts, link_part = self._parts_of_new(plan, part_name)
        beam_parts = [link_part(beam) for beam in plan.new_beams]
        face_parts = [link_part(face) for face in plan.new_faces]
        if None in [*node_parts.values(), *beam_parts, *face_parts]:
            raise EditError("choose the part that new nodes, beams and faces are added to")
        new_ids: dict[int, str] = {}

        def resolve(ref: str | int) -> str:
            return new_ids[ref] if isinstance(ref, int) else ref

        def by_part(items, parts):
            grouped: dict[str, list] = {}
            for item, part in zip(items, parts):
                grouped.setdefault(part, []).append(item)
            return grouped.items()

        def own(entries):
            return [e for e in entries if plan.scope is None or e.part == plan.scope]

        with session.transaction("Edit the mesh"):
            vehicle = session.vehicle
            faces = vehicle.triangles + vehicle.quads
            if plan.flipped_faces:
                session.flip_faces(own([faces[i] for uid in plan.flipped_faces for i in uid_map.faces[uid].indices]),
                                   allow_shared)
                count = len(faces)
                vehicle = session.vehicle
                faces = vehicle.triangles + vehicle.quads
                if len(faces) != count:
                    raise EditError("the faces changed while flipping them")
            entries = own([vehicle.beams[i] for uid in plan.deleted_beams for i in uid_map.beams[uid].indices])
            entries += own([faces[i] for uid in plan.deleted_faces for i in uid_map.faces[uid].indices])
            if entries:
                session.delete_entries(entries, allow_shared)
            if plan.deleted_nodes:
                session.delete_nodes(plan.deleted_nodes, cascade=True, allow_shared=allow_shared)
            if plan.moves:
                session.move_nodes(plan.moves, allow_shared)
            if plan.new_nodes:
                vertices = list(plan.new_nodes)
                names = dict(zip(vertices, self.new_names(plan, vertices, prefix))) if auto_names else None
                for part, chunk in by_part(vertices, [node_parts[v] for v in vertices]):
                    ids = session.add_nodes(part, [plan.new_nodes[v] for v in chunk],
                                            node_ids=[names[v] for v in chunk] if names else None,
                                            prefix=prefix, allow_shared=allow_shared,
                                            anchors=self._node_anchors(plan, chunk, part, placement, group))
                    new_ids.update(zip(chunk, ids))
            origins = {new_ids[v]: self._root(plan, v) for v in new_ids}
            preferred = plan.vertex_nodes.get(prefer) or new_ids.get(prefer)
            for section, links, sources, parts in (("beams", plan.new_beams, plan.new_beam_sources, beam_parts),
                                                   ("faces", plan.new_faces, plan.new_face_sources, face_parts)):
                for part, chunk in by_part(list(enumerate(links)), parts):
                    resolved = [tuple(map(resolve, link)) for _, link in chunk]
                    anchors = self._link_anchors(section, part, resolved, [sources.get(i) for i, _ in chunk],
                                                 placement, group, preferred, origins)
                    if section == "beams":
                        session.add_beams(part, resolved, allow_shared, anchors)
                    else:
                        session.add_faces(part, resolved, allow_shared, anchors)
        self.changed()
        return new_ids

    @staticmethod
    def _root(plan: SyncPlan, vertex: int) -> str | None:
        """The existing node a new node came from, through chains of new nodes."""
        ref: str | int | None = vertex
        seen: set[int] = set()
        while isinstance(ref, int) and ref not in seen:
            seen.add(ref)
            ref = plan.new_sources.get(ref)
        return ref if isinstance(ref, str) else None

    @staticmethod
    def _in_group(node, group: str) -> bool:
        value = node.props.get("group")
        return value == group or (isinstance(value, list) and group in value)

    def _rows_of(self, part: str, section: str) -> list:
        vehicle = self.session.vehicle
        items = (vehicle.nodes.values() if section == "nodes" else vehicle.beams if section == "beams"
                 else vehicle.triangles + vehicle.quads)
        return [entry for entry in items if entry.part == part and entry.src is not None]

    def _node_anchors(self, plan: SyncPlan, vertices: list[int], part: str, placement: str, group: str | None):
        nodes = self.session.vehicle.nodes
        if placement == PLACE_GROUP and group:
            members = [n for n in self._rows_of(part, "nodes") if self._in_group(n, group)]
            return [members[-1].src.node if members else NewBlock("group", group)] * len(vertices)
        if placement == PLACE_SOURCE:
            anchors = []
            for vertex in vertices:
                node = nodes.get(self._root(plan, vertex) or "")
                anchors.append(node.src.node if node is not None and node.part == part and node.src is not None
                               else None)
            return anchors
        return None

    def _link_anchors(self, section: str, part: str, links: list[tuple[str, ...]], sources: list, placement: str,
                      group: str | None, preferred: str | None, origins: dict[str, str | None]):
        if placement not in (PLACE_SOURCE, PLACE_GROUP) or (placement == PLACE_GROUP and not group):
            return None
        nodes = self.session.vehicle.nodes
        rows = self._rows_of(part, section)

        def ids_of(entry) -> tuple:
            return (entry.id1, entry.id2) if section == "beams" else entry.ids

        def in_group(node_id: str) -> bool:
            node = nodes.get(node_id)
            return node is not None and self._in_group(node, group)

        anchors = []
        for link, source in zip(links, sources):
            candidates = [r for r in rows if section == "beams" or len(r.ids) == len(link)]
            found = []
            if placement == PLACE_GROUP:
                found = ([r for r in candidates if all(in_group(i) for i in ids_of(r))]
                         or [r for r in candidates if any(in_group(i) for i in ids_of(r))])
            else:
                if source is not None:
                    found = [r for r in candidates if frozenset(ids_of(r)) == frozenset(source)]
                order = sorted(link, key=lambda node_id: node_id != preferred)
                for node_id in [n for i in order for n in (i, origins.get(i)) if n]:
                    if found:
                        break
                    found = [r for r in candidates if node_id in ids_of(r)]
            anchors.append(found[-1].src.node if found else None)
        return anchors

    def _parts_of_new(self, plan: SyncPlan, active: str | None):
        """The part each new node goes to, and a function giving the part of a new beam or face.

        A new node goes to the part of the node it came from; a beam or face goes to the part of its first new
        node, or to the part all its nodes share. Everything else goes to the active part.
        """
        vehicle = self.session.vehicle
        if plan.scope is not None:
            scope = plan.scope if plan.scope in vehicle.parts else None
            return {vertex: scope for vertex in plan.new_nodes}, lambda refs: scope
        if active not in vehicle.parts:
            active = None

        def own_part(node_id: str) -> str | None:
            node = vehicle.nodes.get(node_id)
            return node.part if node is not None and node.part in vehicle.parts else None

        node_parts: dict[int, str | None] = {}
        pending = list(plan.new_nodes)
        while pending:
            ready = [v for v in pending if not isinstance(plan.new_sources.get(v), int)
                     or plan.new_sources[v] in node_parts]
            for vertex in ready or pending[:1]:
                source = plan.new_sources.get(vertex)
                part = node_parts.get(source) if isinstance(source, int) else own_part(source) if source else None
                node_parts[vertex] = part or active
                pending.remove(vertex)

        def link_part(refs) -> str | None:
            for ref in refs:
                if isinstance(ref, int):
                    return node_parts[ref]
            owners = {own_part(ref) for ref in refs}
            return owners.pop() if len(owners) == 1 and None not in owners else active

        return node_parts, link_part

    # session operations that clear the history

    def reload_file(self, path) -> None:
        self.session.reload_file(path)
        self.reset()

    def rescan(self) -> None:
        self.session.rescan()
        self.reset()
