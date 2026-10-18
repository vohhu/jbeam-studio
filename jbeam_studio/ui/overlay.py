"""Drawing in the 3D viewport: coloured beams and nodes, hydros and rails, nodes of other parts, problems, the
selection, node names, centres of mass and a legend. Faces hide what is behind them, except in X-ray, in wireframe
and with Through faces.

What is drawn over objects in Object Mode is worked out once and kept on the GPU, merged by colour, until the
objects, their sessions or the settings change, so moving the view only draws it again. Objects in Edit Mode are
read again for every redraw."""

from __future__ import annotations

import colorsys
import contextlib
import hashlib
import math
from dataclasses import dataclass, field

import blf
import bmesh
import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from ..blender import mesh_io, sessions
from ..core.display import CATEGORY_KEYS, category, find_problems
from ..core.lua import truthy
from ..core.physics import mass, value_of
from .view import BEAM_TYPES, EXTRA_SECTIONS, NODE_FLAGS, game, settings

BEAM_COLORS = {"|SUPPORT": game(223, 0, 223), "|BOUNDED": game(255, 255, 0), "|ANISOTROPIC": game(255, 135, 63),
               "|LBEAM": game(92, 92, 92), "|PRESSURED": game(0, 255, 255)}
"""Colours of the beam types in the game's debug view."""
UNKNOWN_BEAM_COLOR = game(255, 0, 0)
"""Beam types the game does not know, such as "| BOUNDED"."""
EXTRA_KIND = {"hydros": "hydros", "torsionbars": "torsionbars", "torsionHydros": "torsionbars",
              "rails": "rails", "slidenodes": "rails"}
"""Which switch of the Kinds setting each section follows."""
EXTRA_TITLES = {section: title for section, _, title in EXTRA_SECTIONS}
GRADIENT = ((0.15, 0.35, 1.0), (0.1, 0.8, 0.95), (0.3, 0.9, 0.3), (1.0, 0.85, 0.2), (1.0, 0.25, 0.2))
"""Colours of the rainbow gradient from low to high values."""
PALETTES = {
    "BEAMNG": ((1.0, 1.0, 1.0), (1.0, 0.0, 0.0)),
    "RAINBOW": GRADIENT,
    "COOLWARM": ((0.23, 0.3, 0.75), (0.55, 0.69, 0.99), (0.87, 0.87, 0.87), (0.96, 0.6, 0.48), (0.7, 0.02, 0.15)),
    "VIRIDIS": ((0.27, 0.0, 0.33), (0.23, 0.32, 0.55), (0.13, 0.57, 0.55), (0.37, 0.79, 0.38), (0.99, 0.91, 0.14)),
    "HEAT": ((0.3, 0.0, 0.0), (0.75, 0.1, 0.0), (1.0, 0.5, 0.0), (1.0, 0.85, 0.3), (1.0, 1.0, 0.9)),
}
GRADIENT_STEPS = 16
INFINITE_COLOR = game(255, 0, 255)
"""Values such as FLT_MAX, which do not fit a gradient."""
LEGEND_ROWS = 12
MAX_LABELS = 4000
LINE_LIFT = 0.002
"""How far what is drawn comes towards the viewer, as a part of its distance, so the faces it lies on do not hide
it."""
LABEL_LIFT = 0.015
LINE_LAYERS = ("beam", "hydros", "torsionbars", "torsion_axis", "rails", "problem", "selection")
POINT_LAYERS = ("node", "ghost", "slidenodes", "problem", "selection")
"""What is drawn, from bottom to top."""
_handles: list = []
_cache: dict = {}
_generation = 0
"""Counts the changes of the scene; what is kept for drawing is checked again when it changes."""
_object_changes: dict[str, int] = {}
"""Counts the changes of the geometry and the transform of each object."""


def beam_color(beam_type, colors=BEAM_COLORS, unknown=UNKNOWN_BEAM_COLOR) -> tuple | None:
    if beam_type in (None, "", "|NORMAL"):
        return None
    return colors.get(beam_type, unknown)


def group_color(name: str) -> tuple:
    """A colour of its own for each group name, the same in every session."""
    value = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:6], 16)
    return colorsys.hsv_to_rgb((value % 360) / 360.0, 0.65, 1.0)


def jet_color(x: float) -> tuple:
    """The game's jetColor: blue, cyan, green, yellow, red for x from 0 to 1."""
    return (min(1.0, max(0.0, 4 * x - 2)), min(1.0, max(0.0, 2 - abs(4 * x - 2))), min(1.0, max(0.0, 2 - 4 * x)))


def contrast_color(index: int) -> tuple:
    """The game's colour for the index-th break or deform group (getContrastColor)."""
    return jet_color((index % 17) / 16)


def gradient_color(t: float, stops=GRADIENT) -> tuple:
    """The colour at `t` between 0 (low) and 1 (high)."""
    t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    index = min(int(t), len(stops) - 2)
    a, b, f = stops[index], stops[index + 1], t - index
    return tuple(x + (y - x) * f for x, y in zip(a, b))


class Scale:
    """Where values lie between the 5th and the 95th percentile of the finite ones, so a few extreme values do not
    squeeze the rest into one colour; on a log scale of the positive values when they span a lot."""

    def __init__(self, values):
        finite = sorted(v for v in values if v is not None and math.isfinite(v))
        self.infinite = any(v is not None and not math.isfinite(v) for v in values)
        self.low, self.high = self._range(finite)
        positive = [v for v in finite if v > 0]
        low = self._range(positive)[0] if positive else 0.0
        self.log = low > 0 and self.high / low > 20
        if self.log:
            self.low = low

    @staticmethod
    def _range(values: list[float]) -> tuple[float, float]:
        if not values:
            return 0.0, 0.0
        low, high = values[round(0.05 * (len(values) - 1))], values[round(0.95 * (len(values) - 1))]
        return (low, high) if high > low else (values[0], values[-1])

    def at(self, value: float) -> float:
        if self.high <= self.low:
            return 0.5
        if self.log:
            if value <= 0:
                return 0.0
            t = (math.log(value) - math.log(self.low)) / (math.log(self.high) - math.log(self.low))
        else:
            t = (value - self.low) / (self.high - self.low)
        return min(max(t, 0.0), 1.0)

    def value(self, t: float) -> float:
        if self.log:
            return math.exp(math.log(self.low) + t * (math.log(self.high) - math.log(self.low)))
        return self.low + t * (self.high - self.low)

    def color(self, value: float | None, stops=GRADIENT, infinite=INFINITE_COLOR) -> tuple | None:
        if value is None:
            return None
        if not math.isfinite(value):
            return infinite
        step = round(self.at(value) * (GRADIENT_STEPS - 1))
        return gradient_color(step / (GRADIENT_STEPS - 1), stops)


def _kept(key, make):
    if key not in _cache:
        if len(_cache) > 8192:
            _cache.clear()
        _cache[key] = make()
    return _cache[key]


def _values(session, kind: str, key: str) -> tuple[dict, Scale]:
    """Values of a key for each beam uid or node id of the session's vehicle, and their scale."""
    def make():
        vehicle = session.edit.vehicle
        if kind == "beams":
            values = {uid: value_of(vehicle, vehicle.beams[g.indices[0]].props, key)
                      for uid, g in session.link.map.beams.items()}
        else:
            values = {node_id: value_of(vehicle, node.props, key)
                      for nodes in (vehicle.nodes, vehicle.external_nodes) for node_id, node in nodes.items()}
        return values, Scale(list(values.values()))
    return _kept((session.key, session.link.rev, kind, key), make)


def _color(value) -> tuple:
    return tuple(round(c, 4) for c in value)


class Style:
    """The display settings for one redraw, read once."""

    def __init__(self, display):
        self.scope, self.dim_others, self.dim = display.scope, display.dim_others, display.dim_opacity
        self.opacity, self.legend = display.line_opacity, display.legend
        self.beams, self.beam_by, self.normal = display.beam_colors, display.beam_color_by, display.normal_beams
        self.normal_color, self.unknown = _color(display.normal_color), _color(display.color_unknown)
        self.type_colors = {beam_type: _color(getattr(display, name)) for beam_type, name in BEAM_TYPES}
        self.width, self.extra_width = display.line_width, display.extra_width
        if display.palette == "CUSTOM":
            low, high = _color(display.gradient_low), _color(display.gradient_high)
            self.stops = (low, tuple((a + b) / 2 for a, b in zip(low, high)), high)
        else:
            self.stops = PALETTES[display.palette]
        self.infinite = _color(display.infinite_color)
        self.nodes, self.node_by, self.node_color = display.node_colors, display.node_color_by, _color(display.node_color)
        self.node_flags = tuple((flag, _color(getattr(display, name))) for flag, name in NODE_FLAGS)
        self.node_size = display.node_size
        self.ghosts, self.ghost_color, self.ghost_size = display.ghosts, _color(display.ghost_color), display.ghost_size
        self.extras, self.kinds = display.extras, frozenset(display.extra_kinds)
        self.extra_colors = {section: _color(getattr(display, name)) for section, name, _ in EXTRA_SECTIONS}
        self.torsion = tuple(_color(getattr(display, name)) for name in (
            "color_torsionbars", "color_torsionbars_second", "color_torsion_axis", "color_torsion_anisotropic",
            "color_torsion_anisotropic_second"))
        self.rail_mode, self.rail_color = display.rail_colors, _color(display.color_rails)
        self.selection, self.selection_color = display.selection, _color(display.selection_color)
        self.problems, self.problem_color = display.problems, _color(display.problem_color)
        self.labels, self.label_size = display.labels, display.label_size
        self.label_color, self.ghost_label_color = _color(display.label_color), _color(display.ghost_label_color)
        self.center, self.center_color = display.center_of_mass, _color(display.center_color)
        self.selection_center = display.selection_center
        self.selection_center_color = _color(display.selection_center_color)
        self.center_label, self.center_size = display.center_label, display.center_size
        self.content = (self.beams, self.beam_by, self.normal, self.normal_color, self.unknown,
                        tuple(self.type_colors.values()), self.stops, self.infinite, self.nodes, self.node_by,
                        self.node_color, self.node_flags, self.ghosts, self.ghost_color, self.extras, self.kinds,
                        tuple(self.extra_colors.values()), self.torsion, self.rail_mode, self.rail_color,
                        self.problems, self.problem_color)
        """What decides the colours of what is drawn, as opposed to how it is drawn."""

    def line_width(self, layer: str) -> float:
        if layer == "beam":
            return self.width
        if layer in ("problem", "selection"):
            return self.width + 2.0
        return self.extra_width * {"rails": 1.3, "torsion_axis": 2.0}.get(layer, 1.0)

    def point_size(self, layer: str) -> float:
        return {"node": self.node_size, "ghost": self.ghost_size, "slidenodes": self.node_size + 4,
                "problem": self.node_size + 5, "selection": self.node_size + 2}[layer]


def through(context) -> bool:
    """Whether faces let what is drawn show through: in X-ray, in wireframe, or with Through faces."""
    shading = getattr(context.space_data, "shading", None)
    if settings(context).through_faces or shading is None:
        return True
    return shading.type == "WIREFRAME" or (shading.type == "SOLID" and shading.show_xray)


@contextlib.contextmanager
def _faces_hide(context):
    hidden = not through(context)
    gpu.state.blend_set("ALPHA")
    if hidden:
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
    try:
        yield hidden
    finally:
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


@contextlib.contextmanager
def _lifted(context, amount: float):
    """Draws what is in world space moved towards the viewer by `amount` of its distance."""
    region_3d = context.region_data
    if not amount or region_3d is None:
        yield
        return
    if region_3d.is_perspective:
        lift = Matrix.Diagonal((1.0 - amount, 1.0 - amount, 1.0 - amount, 1.0))
    else:
        lift = Matrix.Translation((0.0, 0.0, region_3d.view_distance * amount))
    with gpu.matrix.push_pop():
        gpu.matrix.load_matrix(lift @ region_3d.view_matrix)
        yield


def _lift(context, points: np.ndarray, amount: float) -> np.ndarray:
    """Points moved towards the viewer by `amount` of their distance."""
    region_3d = context.region_data
    if region_3d is None or not len(points):
        return points
    view = np.array(region_3d.view_matrix.inverted(), dtype=np.float64)
    if region_3d.is_perspective:
        return (points + (view[:3, 3] - points) * amount).astype(np.float32)
    return (points + view[:3, 2] * (region_3d.view_distance * amount)).astype(np.float32)


# what objects show

@dataclass
class Geometry:
    positions: np.ndarray
    uids: np.ndarray
    checks: np.ndarray
    ghosts: np.ndarray
    edges: np.ndarray
    edge_uids: np.ndarray
    selected: np.ndarray | None = None
    edge_selected: np.ndarray | None = None


def _read(obj) -> Geometry | None:
    mesh = obj.data
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(mesh)
        layers = bm.verts.layers
        uid, check = layers.int.get(mesh_io.NODE_UID), layers.int.get(mesh_io.NODE_CHECK)
        if uid is None or check is None:
            return None
        ghost = layers.bool.get(mesh_io.GHOST) if hasattr(layers, "bool") else None
        beam = bm.edges.layers.int.get(mesh_io.BEAM_UID)
        verts = bm.verts
        verts.index_update()
        count = len(verts)
        return Geometry(
            np.array([v.co for v in verts], dtype=np.float32).reshape(-1, 3),
            np.fromiter((v[uid] for v in verts), dtype=np.int64, count=count),
            np.fromiter((v[check] for v in verts), dtype=np.int64, count=count),
            np.fromiter((bool(v[ghost]) for v in verts), dtype=bool, count=count) if ghost is not None
            else np.zeros(count, dtype=bool),
            np.array([(e.verts[0].index, e.verts[1].index) for e in bm.edges], dtype=np.int64).reshape(-1, 2),
            np.fromiter((e[beam] for e in bm.edges), dtype=np.int64, count=len(bm.edges)) if beam is not None
            else np.zeros(len(bm.edges), dtype=np.int64),
            np.fromiter((v.select for v in verts), dtype=bool, count=count),
            np.fromiter((e.select for e in bm.edges), dtype=bool, count=len(bm.edges)))
    count = len(mesh.vertices)
    positions = np.zeros(count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)
    ghosts = np.zeros(count, dtype=bool)
    attribute = mesh.attributes.get(mesh_io.GHOST)
    if attribute is not None and attribute.domain == "POINT" and count:
        attribute.data.foreach_get("value", ghosts)
    pairs = np.zeros(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", pairs)
    return Geometry(positions.reshape(-1, 3),
                    mesh_io._read(mesh, mesh_io.NODE_UID, "POINT", count).astype(np.int64),
                    mesh_io._read(mesh, mesh_io.NODE_CHECK, "POINT", count).astype(np.int64), ghosts,
                    pairs.reshape(-1, 2).astype(np.int64),
                    mesh_io._read(mesh, mesh_io.BEAM_UID, "EDGE", len(mesh.edges)).astype(np.int64))


def _world(obj, positions: np.ndarray) -> np.ndarray:
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    return (np.c_[positions.astype(np.float64), np.ones(len(positions))] @ matrix.T)[:, :3].astype(np.float32)


def _names(obj, session, geometry: Geometry) -> list:
    """The node of each vertex, or None."""
    node_of = session.link.node_of
    def make():
        return [node_of(u, c) for u, c in zip(geometry.uids.tolist(), geometry.checks.tolist())]
    if obj.mode != "EDIT":
        return make()
    key = ("names", obj.name, session.link.rev, hash(geometry.uids.tobytes()), hash(geometry.checks.tobytes()))
    return _kept(key, make)


def _beam_colors(session, style: Style) -> dict:
    """The colour of each beam uid of the session, by what the settings colour beams by."""
    def make():
        vehicle, beams = session.edit.vehicle, session.link.map.beams
        normal = style.normal_color if style.normal else None
        if style.beam_by == "TYPE":
            found = {}
            for uid, group in beams.items():
                beam_type = vehicle.beams[group.indices[0]].props.get("beamType")
                found[uid] = beam_color(beam_type, style.type_colors, style.unknown) or normal
            return found
        if style.beam_by in CATEGORY_KEYS or style.beam_by == "PART":
            colors = _category_colors(session, "beams", style.beam_by)
            found = {}
            for uid, group in beams.items():
                name = category(vehicle.beams[group.indices[0]], style.beam_by)
                found[uid] = colors[name] if name is not None else normal
            return found
        values, scale = _values(session, "beams", style.beam_by)
        return {uid: scale.color(value, style.stops, style.infinite) or normal for uid, value in values.items()}
    return _kept((session.key, session.link.rev, "beam colours", style.content), make)


def _node_colors(session, style: Style) -> dict:
    """The colour of each node of the session, by what the settings colour nodes by."""
    def make():
        vehicle = session.edit.vehicle
        nodes = {**vehicle.external_nodes, **vehicle.nodes}
        if style.node_by == "PLAIN":
            return dict.fromkeys(nodes, style.node_color)
        if style.node_by == "FLAGS":
            return {node_id: node_flag_color(node.props, style) for node_id, node in nodes.items()}
        if style.node_by in ("GROUP", "PART"):
            colors = _category_colors(session, "nodes", style.node_by)
            return {node_id: colors[name] if (name := category(node, style.node_by)) else style.node_color
                    for node_id, node in nodes.items()}
        values, scale = _values(session, "nodes", style.node_by)
        return {node_id: scale.color(values.get(node_id), style.stops, style.infinite) or style.node_color
                for node_id in nodes}
    return _kept((session.key, session.link.rev, "node colours", style.content), make)


def node_flag_color(props: dict, style: Style) -> tuple:
    """The colour the game gives a node: fixed, then selfCollision, then collision false, else the node colour."""
    for flag, color in style.node_flags:
        value = props.get(flag)
        if value is False if flag == "collision" else truthy(value):
            return color
    return style.node_color


def _category_colors(session, kind: str, by: str) -> dict[str, tuple]:
    """A colour for each break group, deform group, node group or part of the session's vehicle, in the order they
    first appear, as the game colours break and deform groups."""
    def make():
        vehicle = session.edit.vehicle
        entries = vehicle.beams if kind == "beams" else [*vehicle.nodes.values(), *vehicle.external_nodes.values()]
        order: dict[str, tuple] = {}
        for entry in entries:
            name = category(entry, by)
            if name is not None and name not in order:
                order[name] = contrast_color(len(order))
        return order
    return _kept((session.key, session.link.rev, "categories", kind, by), make)


def _rail_colors(session, style: Style) -> dict[str, tuple]:
    """The colour of each rail by name: one for each, as in the game, or the rail colour."""
    def make():
        rails = [e.name for e in session.edit.vehicle.extras if e.section == "rails"]
        if style.rail_mode == "ONE":
            return dict.fromkeys(rails, style.rail_color)
        return {name: jet_color(i / (len(rails) + 1)) for i, name in enumerate(rails)}
    return _kept((session.key, session.link.rev, "rails", style.rail_mode, style.rail_color), make)


_scene = [()]
"""The scene key of the current redraw."""


def _conflicts(session) -> frozenset:
    """Nodes of the session's part that other parts in the scene define too."""
    key = _scene[0]
    return _kept((session.key, session.link.rev, "conflicts", key),
                 lambda: frozenset(sessions.scene_conflicts(session, key)))


def _problems(session):
    """Problems of the session's vehicle, with the uids of the problem beams."""
    def make():
        problems = find_problems(session.edit.vehicle)
        uids = {uid for uid, group in session.link.map.beams.items() if problems.beams.intersection(group.indices)}
        return problems, uids
    return _kept((session.key, session.link.rev, "problems"), make)


@dataclass
class Content:
    """What is drawn over one object, in world space."""
    world: np.ndarray
    names: list
    ghosts: np.ndarray
    selected: np.ndarray | None
    lines: dict = field(default_factory=dict)
    points: dict = field(default_factory=dict)
    named: np.ndarray | None = None


def _content(obj, session, geometry: Geometry, style: Style) -> Content:
    world = _world(obj, geometry.positions)
    names = _names(obj, session, geometry)
    content = Content(world, names, geometry.ghosts, geometry.selected)
    lines: dict[tuple, list] = {}
    points: dict[tuple, list] = {}
    edges = geometry.edges
    if style.beams and len(edges):
        table = _beam_colors(session, style)
        _grouped(lines, "beam", [table.get(uid) for uid in geometry.edge_uids.tolist()], world[edges])
    own = ~geometry.ghosts
    if style.nodes and len(world):
        table = _node_colors(session, style)
        _grouped(points, "node", [table.get(n) if mine else None for n, mine in zip(names, own.tolist())], world)
    if style.ghosts and geometry.ghosts.any():
        _add(points, "ghost", style.ghost_color, world[geometry.ghosts])
    where = None
    if style.extras and style.kinds:
        extras = [e for e in session.edit.vehicle.extras if EXTRA_KIND[e.section] in style.kinds]
        if extras:
            where = _where(names, world)
            rails = _rail_colors(session, style)
            for extra in extras:
                chain = [where.get(node_id) for node_id in extra.ids]
                if None in chain:
                    continue
                color = style.extra_colors[extra.section]
                if extra.section == "slidenodes":
                    _add(points, "slidenodes", rails.get(extra.name, style.rail_color),
                         np.array(chain, dtype=np.float32))
                    continue
                if extra.section in ("torsionbars", "torsionHydros") and len(chain) == 4:
                    _torsion_bar(lines, extra, chain, style)
                    continue
                if extra.section == "rails":
                    color = rails.get(extra.name, style.rail_color)
                    if extra.props.get("looped") in (True, 1) and len(chain) > 2:
                        chain.append(chain[0])
                segments = [p for pair in zip(chain, chain[1:]) for p in pair]
                if segments:
                    _add(lines, extra.section, color, np.array(segments, dtype=np.float32))
    if style.problems:
        problems, uids = _problems(session)
        conflicts = _conflicts(session)
        if conflicts:
            where = where if where is not None else _where(names, world)
            spots = [where[i] for i in conflicts if i in where]
            if spots:
                _add(points, "problem", style.problem_color, np.array(spots, dtype=np.float32))
        if problems:
            if uids and len(edges):
                mask = np.fromiter((uid in uids for uid in geometry.edge_uids.tolist()), dtype=bool, count=len(edges))
                if mask.any():
                    _add(lines, "problem", style.problem_color, world[edges[mask]].reshape(-1, 3))
            where = where if where is not None else _where(names, world)
            outlines = []
            for ids in problems.faces:
                corners = [where.get(i) for i in ids]
                if None not in corners:
                    outlines += [p for pair in zip(corners, corners[1:] + corners[:1]) for p in pair]
            if outlines:
                _add(lines, "problem", style.problem_color, np.array(outlines, dtype=np.float32))
            spots = [where[i] for i in problems.nodes if i in where]
            if spots:
                _add(points, "problem", style.problem_color, np.array(spots, dtype=np.float32))
    if style.selection and geometry.selected is not None:
        chosen = geometry.edge_selected
        if chosen is not None and chosen.any():
            _add(lines, "selection", style.selection_color, world[edges[chosen]].reshape(-1, 3))
        if geometry.selected.any():
            _add(points, "selection", style.selection_color, world[geometry.selected])
    content.lines = {key: np.concatenate(parts).astype(np.float32) for key, parts in lines.items()}
    content.points = {key: np.concatenate(parts).astype(np.float32) for key, parts in points.items()}
    return content


def _torsion_bar(lines: dict, extra, chain: list, style: Style) -> None:
    """A torsion bar as the game draws it: from the first node to both axis nodes in one colour, from the last
    node to them in another, and the axis between the second and the third node."""
    first, axis_a, axis_b, last = chain
    anisotropic = extra.props.get("spring2") or extra.props.get("damp2")
    one, two = (style.torsion[3], style.torsion[4]) if anisotropic else (style.torsion[0], style.torsion[1])
    _add(lines, "torsionbars", one, np.array([first, axis_a, first, axis_b], dtype=np.float32))
    _add(lines, "torsionbars", two, np.array([last, axis_a, last, axis_b], dtype=np.float32))
    _add(lines, "torsion_axis", style.torsion[2], np.array([axis_a, axis_b], dtype=np.float32))


def _add(target: dict, layer: str, color: tuple, array: np.ndarray) -> None:
    if len(array):
        target.setdefault((layer, color), []).append(array.reshape(-1, 3))


def _grouped(target: dict, layer: str, colors: list, items: np.ndarray) -> None:
    by_color: dict[tuple, list[int]] = {}
    for index, color in enumerate(colors):
        if color is not None:
            by_color.setdefault(color, []).append(index)
    for color, indices in by_color.items():
        _add(target, layer, color, items[indices])


def _where(names: list, world: np.ndarray) -> dict:
    rows = world.tolist()
    return {name: rows[i] for i, name in enumerate(names) if name is not None}


# what is shown

@dataclass
class Shown:
    obj: object
    session: object
    dim: bool
    content: Content


@dataclass
class Frame:
    key: tuple = ()
    shown: list = field(default_factory=list)
    """Objects in Object Mode with what they show."""
    merged: tuple = ()
    draws: list = field(default_factory=list)
    """(kind, layer, colour, dimmed, batch) of the objects in Object Mode."""


_frame = Frame()
_contents: dict[str, tuple[tuple, Content]] = {}


def _shown_objects(context, style: Style, objects=None):
    """JBeam objects to draw over, of the visible ones or of `objects`, and whether they are drawn dimmed."""
    active = context.view_layer.objects.active
    for obj in context.visible_objects if objects is None else objects:
        if obj.type != "MESH":
            continue
        session = sessions.session_of(obj)
        if session is None:
            continue
        focus = (style.scope == "ALL" or obj == active
                 or (style.scope == "SELECTED" and obj.select_get()))
        if focus or style.dim_others:
            yield obj, session, not focus


def _object_key(obj, session, style: Style) -> tuple:
    mesh = obj.data
    return (session.key, session.part_name, session.link.rev, _object_changes.get(obj.name, 0),
            len(mesh.vertices), len(mesh.edges), tuple(obj.matrix_world.col[3]), tuple(obj.matrix_world.col[0]),
            obj.jbs.all_nodes, style.content, _conflicts(session) if style.problems else None)


def _static(context, style: Style) -> Frame:
    """The objects in Object Mode with what they show, and their batches; worked out again only when the scene,
    a session or the settings changed."""
    global _frame
    active = context.view_layer.objects.active
    scene = sessions.scene_key()
    key = (_generation, style.content, style.scope, style.dim_others, active.name if active else "", scene)
    if key == _frame.key:
        return _frame
    _scene[0] = scene
    frame = Frame(key)
    for obj, session, dim in _shown_objects(context, style):
        if obj.mode == "EDIT":
            continue
        object_key = _object_key(obj, session, style)
        kept = _contents.get(obj.name)
        if kept is None or kept[0] != object_key:
            geometry = _read(obj)
            if geometry is None:
                continue
            kept = _contents[obj.name] = (object_key, _content(obj, session, geometry, style))
        frame.shown.append(Shown(obj, session, dim, kept[1]))
    frame.merged = tuple((id(s.content), s.dim) for s in frame.shown)
    frame.draws = _frame.draws if frame.merged == _frame.merged else _batches(frame.shown)
    _frame = frame
    return frame


def _batches(shown: list[Shown]) -> list:
    merged: dict[tuple, list] = {}
    for item in shown:
        for kind, table in (("lines", item.content.lines), ("points", item.content.points)):
            for (layer, color), array in table.items():
                merged.setdefault((kind, layer, color, item.dim), []).append(array)
    draws = []
    for (kind, layer, color, dim), arrays in merged.items():
        shader = _shader(kind)
        array = np.ascontiguousarray(np.concatenate(arrays), dtype=np.float32)
        draws.append((kind, layer, color, dim, batch_for_shader(shader, "LINES" if kind == "lines" else "POINTS",
                                                                {"pos": array})))
    return draws


def _shader(kind: str):
    return gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR" if kind == "lines" else "POINT_UNIFORM_COLOR")


def _edited(context, style: Style) -> list[Shown]:
    found = []
    editing = [o for o in getattr(context, "objects_in_mode", None) or () if o.mode == "EDIT" and o.visible_get()]
    for obj, session, dim in _shown_objects(context, style, editing):
        if obj.mode == "EDIT":
            geometry = _read(obj)
            if geometry is not None:
                found.append(Shown(obj, session, dim, _content(obj, session, geometry, style)))
    return found


def _draw(context, style: Style, draws: list) -> None:
    """Draws (kind, layer, colour, dimmed, batch) in the order of the layers."""
    lines, points = _shader("lines"), _shader("points")
    scale = context.preferences.system.ui_scale
    lines.uniform_float("viewportSize", (context.region.width, context.region.height))
    order = {(kind, layer): i for i, (kind, layer) in enumerate(
        [("lines", layer) for layer in LINE_LAYERS] + [("points", layer) for layer in POINT_LAYERS])}
    for kind, layer, color, dim, batch in sorted(draws, key=lambda d: (order[d[0], d[1]], not d[3])):
        alpha = style.opacity * (style.dim if dim else 1.0)
        if kind == "lines":
            lines.uniform_float("lineWidth", style.line_width(layer) * scale)
            lines.uniform_float("color", (*color, alpha))
            batch.draw(lines)
        else:
            gpu.state.point_size_set(style.point_size(layer) * scale)
            points.uniform_float("color", (*color, alpha))
            batch.draw(points)
    gpu.state.point_size_set(1.0)


def _edit_draws(edited: list[Shown]) -> list:
    draws = []
    for item in edited:
        for kind, table in (("lines", item.content.lines), ("points", item.content.points)):
            for (layer, color), array in table.items():
                if item.dim and layer == "selection":
                    continue
                batch = batch_for_shader(_shader(kind), "LINES" if kind == "lines" else "POINTS", {"pos": array})
                draws.append((kind, layer, color, item.dim, batch))
    return draws


def draw_view() -> None:
    context = bpy.context
    if context.region is None or not sessions.SESSIONS:
        return
    style = Style(settings(context))
    frame = _static(context, style)
    edited = _edited(context, style)
    if frame.draws or edited:
        with _faces_hide(context) as hidden, _lifted(context, LINE_LIFT if hidden else 0.0):
            _draw(context, style, frame.draws + _edit_draws(edited))
    shown = frame.shown + edited
    _draw_centres(context, style, shown, edited)
    _draw_labels(context, style, shown)


# centres of mass

def _centres(context, style: Style, shown: list[Shown], edited: list[Shown]) -> list[tuple]:
    """(centre in world space, mass, colour) of the vehicle or part of the active object, and of the selected
    nodes in Edit Mode."""
    found = []
    active = context.view_layer.objects.active
    item = next((s for s in shown if s.obj == active), None)
    if style.center and item is not None:
        vehicle = item.session.edit.vehicle
        total, centre = _kept((item.session.key, item.session.link.rev, "centre"),
                              lambda: mass(vehicle, vehicle.nodes.values()))
        if centre is not None:
            found.append((item.obj.matrix_world @ Vector(centre), total, style.center_color))
    if style.selection_center and edited:
        total, moment, seen = 0.0, Vector((0.0, 0.0, 0.0)), set()
        for item in edited:
            if item.content.selected is None:
                continue
            vehicle = item.session.edit.vehicle
            rows = item.content.world
            for index in np.flatnonzero(item.content.selected).tolist():
                node_id = item.content.names[index]
                if node_id is None or node_id in seen:
                    continue
                seen.add(node_id)
                node = sessions.node_entry(item.session, node_id)
                weight = value_of(vehicle, node.props, "nodeWeight") if node is not None else None
                if weight:
                    total += weight
                    moment += Vector(rows[index].tolist()) * weight
        if total and len(seen) > 1:
            found.append((moment / total, total, style.selection_center_color))
    return found


def _draw_centres(context, style: Style, shown: list[Shown], edited: list[Shown]) -> None:
    centres = _centres(context, style, shown, edited)
    if not centres:
        return
    lines = _shader("lines")
    lines.uniform_float("viewportSize", (context.region.width, context.region.height))
    lines.uniform_float("lineWidth", 3.0 * context.preferences.system.ui_scale)
    arms: dict[tuple, list] = {}
    for centre, _total, color in centres:
        for axis in Matrix.Identity(3):
            arms.setdefault(color, []).extend((tuple(centre + axis * style.center_size),
                                               tuple(centre - axis * style.center_size)))
    gpu.state.blend_set("ALPHA")
    for color, points in arms.items():
        lines.uniform_float("color", (*color, 1.0))
        batch_for_shader(lines, "LINES", {"pos": points}).draw(lines)
    gpu.state.blend_set("NONE")
    _cache["centre labels"] = centres if style.center_label else []


# node names

def _depths(context, box: tuple[int, int, int, int]) -> np.ndarray | None:
    """The depth of the drawn scene, from 0 (near) to 1 (far), in a box (x, y, width, height) of the region.
    Blender 4.5 gives scripts the depth of another buffer than the one the scene is drawn into, so there it is
    None."""
    if bpy.app.version < (5, 0, 0):
        return None
    x, y, width, height = box
    try:
        buffer = gpu.state.active_framebuffer_get().read_depth(x, y, width, height)
        try:
            values = np.frombuffer(buffer, dtype=np.float32)
        except (TypeError, ValueError):
            values = np.array(buffer.to_list(), dtype=np.float32)
        return values.reshape(height, width)
    except (ValueError, TypeError, AttributeError, SystemError):
        return None


def _faces_tree(shown: list[Shown]):
    """A BVH tree of the faces of the shown JBeam objects in world space, built again when they change."""
    key = tuple((item.obj.name, id(item.content)) if item.obj.mode != "EDIT"
                else (item.obj.name, hash(item.content.world.tobytes())) for item in shown)
    cached = _cache.get("faces")
    if cached is not None and cached[0] == key:
        return cached[1]
    positions, polygons, offset = [], [], 0
    for item in shown:
        obj = item.obj
        if obj.mode == "EDIT":
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.index_update()
            faces = [[v.index for v in f.verts] for f in bm.faces]
        else:
            faces = [list(p.vertices) for p in obj.data.polygons]
        if not faces:
            continue
        positions.extend(item.content.world.tolist())
        polygons.extend([i + offset for i in face] for face in faces)
        offset += len(item.content.world)
    _cache["faces"] = (key, BVHTree.FromPolygons(positions, polygons) if polygons else None)
    return _cache["faces"][1]


def _hidden_by_faces(context, shown: list[Shown], world: np.ndarray) -> np.ndarray:
    """Whether a face of a shown JBeam object lies between the viewer and each point; for Blender 4.5."""
    hidden = np.zeros(len(world), dtype=bool)
    tree = _faces_tree(shown)
    region_3d = context.region_data
    if tree is None or region_3d is None:
        return hidden
    view = region_3d.view_matrix.inverted()
    toward = view.col[2].xyz.normalized()
    for index, point in enumerate(world.tolist()):
        point = Vector(point)
        if region_3d.is_perspective:
            origin = view.translation
            margin = (point - origin).length * LABEL_LIFT
        else:
            origin = point + toward * (region_3d.view_distance * 4 + 100)
            margin = region_3d.view_distance * LABEL_LIFT
        ray = point - origin
        distance = ray.length
        if distance > margin:
            hidden[index] = tree.ray_cast(origin, ray / distance, distance - margin)[0] is not None
    return hidden


def _screen(context, world: np.ndarray):
    """Window coordinates, depth (from -1 to 1) and visibility of points in world space."""
    region, region_3d = context.region, context.region_data
    if region is None or region_3d is None or not len(world):
        return np.zeros((0, 2)), np.zeros(0), np.zeros(0, bool)
    transform = np.array(region_3d.perspective_matrix, dtype=np.float64)
    points = np.c_[world.astype(np.float64), np.ones(len(world))] @ transform.T
    visible = points[:, 3] > 1e-6
    w = np.where(visible, points[:, 3], 1.0)
    x = (points[:, 0] / w + 1.0) * 0.5 * region.width
    y = (points[:, 1] / w + 1.0) * 0.5 * region.height
    z = points[:, 2] / w
    visible &= (x >= 0) & (x <= region.width) & (y >= 0) & (y <= region.height) & (z > -1) & (z < 1)
    return np.c_[x, y], z, visible


def _draw_labels(context, style: Style, shown: list[Shown]) -> None:
    """Node names, and the masses of centres of mass; a name is left out where a face in front of its node
    hides the node."""
    region = context.region
    centres = _cache.pop("centre labels", [])
    if not region.width or not region.height or (style.labels == "NONE" and not centres):
        return
    hide = not through(context)
    texts: list[tuple[float, float, str, tuple]] = []
    if style.labels != "NONE":
        items, worlds, owners, vertices = [], [], [], []
        for item in shown:
            if item.dim or (style.labels == "SELECTED" and item.obj.mode != "EDIT"):
                continue
            named = _named(item.content)
            if style.labels == "SELECTED":
                named = named[item.content.selected[named]] if item.content.selected is not None else named[:0]
            if len(named):
                owners.append(np.full(len(named), len(items), dtype=np.int32))
                vertices.append(named)
                worlds.append(item.content.world[named])
                items.append(item)
        if items:
            world = np.concatenate(worlds)
            if hide and bpy.app.version >= (5, 0, 0):
                points, ndc, visible = _screen(context, _lift(context, world, LABEL_LIFT))
            else:
                points, ndc, visible = _screen(context, world)
            if hide and visible.any():
                visible &= _not_hidden(context, shown, world, points, ndc, visible)
            owners, vertices = np.concatenate(owners), np.concatenate(vertices)
            for at in np.flatnonzero(visible)[:MAX_LABELS].tolist():
                content = items[owners[at]].content
                index = int(vertices[at])
                x, y = points[at].tolist()
                color = style.ghost_label_color if content.ghosts[index] else style.label_color
                texts.append((x + 6, y + 4, content.names[index], color))
    for centre, total, color in centres:
        points, _ndc, visible = _screen(context, np.array([centre[:]], dtype=np.float32))
        if visible[0]:
            x, y = points[0].tolist()
            texts.append((x + 10, y - 16, f"{total:,.1f} kg".replace(",", " "), color))
    if not texts:
        return
    font = 0
    blf.size(font, style.label_size * context.preferences.system.ui_scale)
    pixels = Matrix(((2.0 / region.width, 0, 0, -1), (0, 2.0 / region.height, 0, -1), (0, 0, 1, 0), (0, 0, 0, 1)))
    with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
        gpu.matrix.load_identity()
        gpu.matrix.load_projection_matrix(pixels)
        gpu.state.blend_set("ALPHA")
        for x, y, text, color in texts:
            blf.color(font, *color, 0.9 * style.opacity)
            blf.position(font, x, y, 0)
            blf.draw(font, text)
        gpu.state.blend_set("NONE")


def _named(content: Content) -> np.ndarray:
    """Indices of the vertices that stand for nodes."""
    if content.named is None:
        content.named = np.fromiter((i for i, name in enumerate(content.names) if name is not None), dtype=np.int64)
    return content.named


def _not_hidden(context, shown, world, points, ndc, visible) -> np.ndarray:
    region = context.region
    if bpy.app.version < (5, 0, 0):
        return ~_hidden_by_faces(context, shown, world)
    xs = np.clip(points[:, 0].astype(int), 0, region.width - 1)
    ys = np.clip(points[:, 1].astype(int), 0, region.height - 1)
    x0, x1 = int(xs[visible].min()), int(xs[visible].max())
    y0, y1 = int(ys[visible].min()), int(ys[visible].max())
    depths = _depths(context, (x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    if depths is None:
        return np.ones(len(world), dtype=bool)
    rows, columns = np.clip(ys - y0, 0, y1 - y0), np.clip(xs - x0, 0, x1 - x0)
    return (ndc + 1.0) * 0.5 <= depths[rows, columns] + 1e-6


# legend

def _format(value: float) -> str:
    if not math.isfinite(value):
        return "FLT_MAX"
    return f"{value:,.0f}".replace(",", " ") if abs(value) >= 100 else f"{value:.3g}"


def _gradient_rows(title: str, scale: Scale, style: Style) -> list[tuple[tuple | None, str]]:
    rows = [(None, title)]
    if scale.high > scale.low:
        rows += [(gradient_color(t, style.stops), _format(scale.value(t))) for t in (1.0, 0.75, 0.5, 0.25, 0.0)]
    elif scale.high or scale.low:
        rows.append((gradient_color(0.5, style.stops), _format(scale.low)))
    if scale.infinite:
        rows.append((style.infinite, "FLT_MAX"))
    return rows


def _named_rows(counts: dict[str, int], colors: dict[str, tuple], fallback: tuple[tuple, str, int] | None) -> list:
    tr = bpy.app.translations.pgettext_iface
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    rows = [(colors.get(name) or group_color(name), f"{name}  {count}") for name, count in ordered[:LEGEND_ROWS]]
    if len(ordered) > LEGEND_ROWS:
        rows.append(((0.5, 0.5, 0.5), tr("and {count} more").format(count=len(ordered) - LEGEND_ROWS)))
    if fallback is not None and fallback[2]:
        rows.append((fallback[0], f"{fallback[1]}  {fallback[2]}"))
    return rows


def legend_rows(session, style: Style) -> list[tuple[tuple | None, str]]:
    """What the colours of the session's objects mean: (colour, text), or (None, title)."""
    def make():
        tr = bpy.app.translations.pgettext_iface
        vehicle = session.edit.vehicle
        rows: list[tuple[tuple | None, str]] = []
        if style.extras:
            counts: dict[str, int] = {}
            for extra in vehicle.extras:
                if EXTRA_KIND[extra.section] in style.kinds:
                    counts[extra.section] = counts.get(extra.section, 0) + 1
            rails = list(_rail_colors(session, style).values())
            colors = {**style.extra_colors, "torsionbars": style.torsion[0], "torsionHydros": style.torsion[0]}
            if rails:
                colors["rails"] = colors["slidenodes"] = rails[0]
            rows += [(colors[s], f"{tr(EXTRA_TITLES[s])}  {counts[s]}") for s, _, _ in EXTRA_SECTIONS if s in counts]
        if style.beams:
            others = tr("Other beams")
            if style.beam_by == "TYPE":
                counts = {}
                for beam in vehicle.beams:
                    beam_type = beam.props.get("beamType")
                    key = beam_type if beam_color(beam_type) is not None else None
                    counts[key] = counts.get(key, 0) + 1
                rows += [(beam_color(t, style.type_colors, style.unknown), f"{t}  {n}")
                         for t, n in sorted((k, v) for k, v in counts.items() if k is not None)]
                if style.normal and counts.get(None):
                    rows.append((style.normal_color, f"|NORMAL  {counts[None]}"))
            elif style.beam_by in CATEGORY_KEYS or style.beam_by == "PART":
                counts, rest = {}, 0
                for beam in vehicle.beams:
                    name = category(beam, style.beam_by)
                    if name is None:
                        rest += 1
                    else:
                        counts[name] = counts.get(name, 0) + 1
                rows.append((None, CATEGORY_KEYS.get(style.beam_by, tr("Part"))))
                rows += _named_rows(counts, _category_colors(session, "beams", style.beam_by),
                                    (style.normal_color, others, rest) if style.normal else None)
            else:
                rows += _gradient_rows(style.beam_by, _values(session, "beams", style.beam_by)[1], style)
        if style.nodes:
            nodes = vehicle.nodes.values()
            if style.node_by == "PLAIN":
                rows.append((style.node_color, f"{tr('Nodes')}  {len(vehicle.nodes)}"))
            elif style.node_by == "FLAGS":
                counts: dict[tuple, int] = {}
                for node in nodes:
                    color = node_flag_color(node.props, style)
                    counts[color] = counts.get(color, 0) + 1
                titles = {color: ("collision false" if flag == "collision" else flag) for flag, color in style.node_flags}
                rows += [(color, f"{titles[color]}  {counts[color]}") for _, color in style.node_flags
                         if counts.get(color) and color in titles]
                if counts.get(style.node_color):
                    rows.append((style.node_color, f"{tr('Nodes')}  {counts[style.node_color]}"))
            elif style.node_by in ("GROUP", "PART"):
                counts, rest = {}, 0
                for node in nodes:
                    name = category(node, style.node_by)
                    if name is None:
                        rest += 1
                    else:
                        counts[name] = counts.get(name, 0) + 1
                rows.append((None, tr("Node groups") if style.node_by == "GROUP" else tr("Parts")))
                rows += _named_rows(counts, _category_colors(session, "nodes", style.node_by),
                                    (style.node_color, tr("Without a group"), rest))
            else:
                rows += _gradient_rows(style.node_by, _values(session, "nodes", style.node_by)[1], style)
        if style.problems:
            problems = _problems(session)[0]
            count = len(problems.beams) + len(problems.faces) + len(problems.nodes) + len(conflicts)
            if count:
                rows.append((style.problem_color, f"{tr('Problems')}  {count}"))
        return rows
    conflicts = _conflicts(session) if style.problems else frozenset()
    return _kept((session.key, session.link.rev, "legend", style.content, conflicts), make)


def draw_pixel() -> None:
    context = bpy.context
    display = settings(context)
    if not display.legend or not sessions.SESSIONS:
        return
    session = sessions.session_of(context.active_object)
    if session is None:
        return
    rows = legend_rows(session, Style(display))
    if not rows:
        return
    scale = context.preferences.system.ui_scale
    size, line = 12 * scale, 18 * scale
    x, y = 16 * scale, 40 * scale
    tools = next((r for r in context.area.regions if r.type == "TOOLS"), None) if context.area else None
    if tools is not None and tools.width > 1 and context.preferences.system.use_region_overlap:
        x += tools.width
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    blf.size(0, 12 * scale)
    gpu.state.blend_set("ALPHA")
    for color, text in reversed(rows):
        if color is not None:
            shader.uniform_float("color", (*color, 1.0))
            batch_for_shader(shader, "TRIS", {"pos": [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]},
                             indices=[(0, 1, 2), (0, 2, 3)]).draw(shader)
        blf.color(0, 1, 1, 1, 0.9)
        blf.position(0, x + (size + 6 * scale if color is not None else 0), y + 2 * scale, 0)
        blf.draw(0, text)
        y += line
    gpu.state.blend_set("NONE")


# header and handlers

def draw_header(self, context) -> None:
    """The Through faces switch and the JBeam display settings in the header of the 3D viewport, when JBeam
    objects are open."""
    if sessions.SESSIONS:
        row = self.layout.row(align=True)
        row.prop(settings(context), "through_faces", text="", icon="MOD_WIREFRAME")
        row.popover(panel="JBS_PT_overlay", text="JBeam")


def changed() -> None:
    """Makes the next redraw check what is drawn again."""
    global _generation
    _generation += 1


@persistent
def _on_depsgraph(_scene, depsgraph) -> None:
    global _generation
    _generation += 1
    for update in depsgraph.updates:
        if (update.is_updated_geometry or update.is_updated_transform) and isinstance(update.id, bpy.types.Object):
            name = update.id.name
            _object_changes[name] = _object_changes.get(name, 0) + 1


@persistent
def _on_reload(*_args) -> None:
    global _frame
    changed()
    _contents.clear()
    _cache.clear()
    _frame = Frame()


HANDLER_LISTS = ("undo_post", "redo_post", "load_post")


def register() -> None:
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_view, (), "WINDOW", "POST_VIEW"))
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_pixel, (), "WINDOW", "POST_PIXEL"))
    bpy.types.VIEW3D_HT_header.append(draw_header)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    for name in HANDLER_LISTS:
        getattr(bpy.app.handlers, name).append(_on_reload)


def unregister() -> None:
    for name in HANDLER_LISTS:
        handlers = getattr(bpy.app.handlers, name)
        if _on_reload in handlers:
            handlers.remove(_on_reload)
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    bpy.types.VIEW3D_HT_header.remove(draw_header)
    for handle in _handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
    _handles.clear()
    _on_reload()
