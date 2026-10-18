"""Drawing in the 3D viewport: coloured beams and nodes, hydros and rails, nodes of other parts, node names, the
centre of mass and a legend. Faces hide what is behind them, except in X-ray, in wireframe and with Through faces."""

from __future__ import annotations

import colorsys
import contextlib
import hashlib
import math

import blf
import bmesh
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from ..blender import mesh_io, sessions
from ..core.physics import mass, value_of

GHOST_COLOR = (1.0, 0.55, 0.1)
LABEL_COLOR = (1.0, 1.0, 1.0, 0.9)
GHOST_LABEL_COLOR = (1.0, 0.7, 0.35, 0.9)
MAX_LABELS = 4000
BEAM_COLORS = {
    "|SUPPORT": (1.0, 0.62, 0.15),
    "|BOUNDED": (0.25, 0.55, 1.0),
    "|ANISOTROPIC": (0.75, 0.4, 1.0),
    "|LBEAM": (0.35, 0.9, 0.35),
    "|PRESSURED": (0.2, 0.9, 0.9),
}
LEGEND_GROUPS = 12
UNKNOWN_BEAM_COLOR = (1.0, 0.25, 0.25)
"""Beam types the game does not know, such as "| BOUNDED"."""
EXTRA_COLORS = {
    "hydros": (0.25, 0.75, 1.0),
    "torsionbars": (1.0, 0.85, 0.2),
    "torsionHydros": (1.0, 0.5, 0.2),
    "rails": (1.0, 0.3, 0.75),
    "slidenodes": (1.0, 0.3, 0.75),
}
EXTRA_TITLES = {"hydros": "Hydros", "torsionbars": "Torsion bars", "torsionHydros": "Torsion hydros",
                "rails": "Rails", "slidenodes": "Slide nodes"}
EXTRA_KIND = {"hydros": "hydros", "torsionbars": "torsionbars", "torsionHydros": "torsionbars",
              "rails": "rails", "slidenodes": "rails"}
"""Which switch of the Kinds setting each section follows."""
GRADIENT = ((0.15, 0.35, 1.0), (0.1, 0.8, 0.95), (0.3, 0.9, 0.3), (1.0, 0.85, 0.2), (1.0, 0.25, 0.2))
"""Colours of a gradient from low to high values."""
GRADIENT_STEPS = 16
INFINITE_COLOR = (0.8, 0.45, 1.0)
"""Values such as FLT_MAX, which do not fit a gradient."""
CENTER_COLOR = (1.0, 1.0, 1.0)
CENTER_SIZE = 0.12
"""Half the length of the arms of the centre of mass cross, in metres."""
LINE_LIFT = 0.002
"""How far lines and points come towards the viewer, as a part of their distance, so the faces they lie on do not
hide them."""
LABEL_LIFT = 0.015
_handles: list = []
_cache: dict = {}


def beam_color(beam_type) -> tuple | None:
    if beam_type in (None, "", "|NORMAL"):
        return None
    return BEAM_COLORS.get(beam_type, UNKNOWN_BEAM_COLOR)


def group_color(name: str) -> tuple:
    """A colour of its own for each group name, the same in every session."""
    value = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:6], 16)
    return colorsys.hsv_to_rgb((value % 360) / 360.0, 0.65, 1.0)


def gradient_color(t: float) -> tuple:
    """The colour at `t` between 0 (low) and 1 (high)."""
    t = min(max(t, 0.0), 1.0) * (len(GRADIENT) - 1)
    index = min(int(t), len(GRADIENT) - 2)
    a, b, f = GRADIENT[index], GRADIENT[index + 1], t - index
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

    def color(self, value: float | None) -> tuple | None:
        if value is None:
            return None
        if not math.isfinite(value):
            return INFINITE_COLOR
        step = round(self.at(value) * (GRADIENT_STEPS - 1))
        return gradient_color(step / (GRADIENT_STEPS - 1))


def _values(session, kind: str, key: str) -> tuple[dict, Scale]:
    """Values of a key for each beam uid or node id of the session's vehicle, and their scale."""
    cache_key = (session.key, session.link.rev, kind, key)
    if cache_key not in _cache:
        if len(_cache) > 32:
            _cache.clear()
        vehicle = session.edit.vehicle
        if kind == "beams":
            values = {uid: value_of(vehicle, vehicle.beams[g.indices[0]].props, key)
                      for uid, g in session.link.map.beams.items()}
        else:
            values = {node_id: value_of(vehicle, node.props, key)
                      for nodes in (vehicle.nodes, vehicle.external_nodes) for node_id, node in nodes.items()}
        _cache[cache_key] = (values, Scale(list(values.values())))
    return _cache[cache_key]


def _format(value: float) -> str:
    if not math.isfinite(value):
        return "FLT_MAX"
    return f"{value:,.0f}".replace(",", " ") if abs(value) >= 100 else f"{value:.3g}"


def through(context) -> bool:
    """Whether faces let what is drawn show through: in X-ray, in wireframe, or with Through faces."""
    shading = getattr(context.space_data, "shading", None)
    if context.window_manager.jbs_view.through_faces or shading is None:
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


def _lift(context, points: np.ndarray, amount: float) -> np.ndarray:
    """Points moved towards the viewer by `amount` of their distance."""
    region_3d = context.region_data
    if region_3d is None or not len(points):
        return points
    view = np.array(region_3d.view_matrix.inverted(), dtype=np.float64)
    if region_3d.is_perspective:
        return (points + (view[:3, 3] - points) * amount).astype(np.float32)
    return (points + view[:3, 2] * (region_3d.view_distance * amount)).astype(np.float32)


def _edges(obj):
    """Vertex index pairs and beam uids of the object's edges."""
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.index_update()
        layer = bm.edges.layers.int.get(mesh_io.BEAM_UID)
        if layer is None:
            return None
        return [(e.verts[0].index, e.verts[1].index) for e in bm.edges], [e[layer] for e in bm.edges]
    mesh = obj.data
    pairs = np.zeros(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", pairs)
    return pairs.reshape(-1, 2).tolist(), mesh_io._read(mesh, mesh_io.BEAM_UID, "EDGE", len(mesh.edges)).tolist()


def _beam_types(session) -> dict[int, str]:
    beams = session.edit.vehicle.beams
    return {uid: beams[g.indices[0]].props.get("beamType") for uid, g in session.link.map.beams.items()}


def _world(obj, positions):
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    return (np.c_[positions.astype(np.float64), np.ones(len(positions))] @ matrix.T)[:, :3].astype(np.float32)


def _lines(context, by_color: dict[tuple, list], width: float) -> None:
    view = context.window_manager.jbs_view
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    shader.uniform_float("viewportSize", (context.region.width, context.region.height))
    shader.uniform_float("lineWidth", width * context.preferences.system.ui_scale)
    for color, points in by_color.items():
        shader.uniform_float("color", (*color, view.line_opacity))
        batch_for_shader(shader, "LINES", {"pos": points}).draw(shader)


def _points(context, by_color: dict[tuple, list], size: float) -> None:
    view = context.window_manager.jbs_view
    shader = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
    gpu.state.point_size_set(size * context.preferences.system.ui_scale)
    for color, items in by_color.items():
        shader.uniform_float("color", (*color, view.line_opacity))
        batch_for_shader(shader, "POINTS", {"pos": items}).draw(shader)
    gpu.state.point_size_set(1.0)


def draw_beams() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if not view.beam_colors and not view.group_colors:
        return
    with _faces_hide(context) as hidden:
        for obj, session in _shown_objects(context):
            data = _vertices(obj)
            if data is None or not len(data[0]):
                continue
            world = _world(obj, data[0])
            world = (_lift(context, world, LINE_LIFT) if hidden else world).tolist()
            if view.beam_colors:
                edges = _edges(obj)
                if edges is not None:
                    if view.beam_color_by == "TYPE":
                        types = _beam_types(session)
                        color_of = lambda uid: beam_color(types.get(uid))  # noqa: E731
                    else:
                        values, scale = _values(session, "beams", view.beam_color_by)
                        color_of = lambda uid: scale.color(values.get(uid))  # noqa: E731
                    lines: dict[tuple, list] = {}
                    for (a, b), uid in zip(*edges):
                        color = color_of(uid)
                        if color is not None:
                            lines.setdefault(color, []).extend((world[a], world[b]))
                    _lines(context, lines, view.line_width)
            if view.group_colors:
                points: dict[tuple, list] = {}
                if view.node_color_by != "GROUP":
                    values, scale = _values(session, "nodes", view.node_color_by)
                for index, (uid, check) in enumerate(zip(data[1].tolist(), data[2].tolist())):
                    node_id = session.link.node_of(uid, check) or ""
                    if view.node_color_by == "GROUP":
                        node = sessions.node_entry(session, node_id)
                        group = node.props.get("group") if node is not None else None
                        group = group[0] if isinstance(group, list) and group else group
                        color = group_color(group) if isinstance(group, str) and group else None
                    else:
                        color = scale.color(values.get(node_id))
                    if color is not None:
                        points.setdefault(color, []).append(world[index])
                _points(context, points, 7.0)


def _node_positions(obj, session, data, world) -> dict[str, list]:
    found = {}
    for index, (uid, check) in enumerate(zip(data[1].tolist(), data[2].tolist())):
        node_id = session.link.node_of(uid, check)
        if node_id is not None:
            found[node_id] = world[index]
    return found


def draw_extras() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if not view.extras or not view.extra_kinds:
        return
    with _faces_hide(context) as hidden:
        for obj, session in _shown_objects(context):
            extras = [e for e in session.edit.vehicle.extras if EXTRA_KIND[e.section] in view.extra_kinds]
            data = _vertices(obj) if extras else None
            if data is None or not len(data[0]):
                continue
            world = _world(obj, data[0])
            where = _node_positions(obj, session, data, (_lift(context, world, LINE_LIFT) if hidden else world).tolist())
            segments: dict[str, list] = {}
            spots: list = []
            for extra in extras:
                chain = [where.get(node_id) for node_id in extra.ids]
                if None in chain:
                    continue
                if extra.section == "slidenodes":
                    spots.extend(chain)
                    continue
                if extra.section == "rails" and extra.props.get("looped") in (True, 1) and len(chain) > 2:
                    chain.append(chain[0])
                for a, b in zip(chain, chain[1:]):
                    segments.setdefault(extra.section, []).extend((a, b))
            for section, pairs in segments.items():
                _lines(context, {EXTRA_COLORS[section]: pairs}, view.line_width * (1.6 if section == "rails" else 1.2))
            if spots:
                _points(context, {EXTRA_COLORS["slidenodes"]: spots}, 11.0)


def _gradient_rows(title: str, scale: Scale) -> list[tuple[tuple | None, str]]:
    rows = [(None, title)]
    if scale.high > scale.low:
        rows += [(gradient_color(t), _format(scale.value(t))) for t in (1.0, 0.75, 0.5, 0.25, 0.0)]
    elif scale.high or scale.low:
        rows.append((gradient_color(0.5), _format(scale.low)))
    if scale.infinite:
        rows.append((INFINITE_COLOR, "FLT_MAX"))
    return rows


def draw_legend() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if not view.legend or not (view.beam_colors or view.group_colors or view.extras):
        return
    obj = context.active_object
    session = sessions.session_of(obj)
    if session is None:
        return
    rows: list[tuple[tuple | None, str]] = []
    if view.extras:
        counts = {}
        for extra in session.edit.vehicle.extras:
            if EXTRA_KIND[extra.section] in view.extra_kinds:
                counts[extra.section] = counts.get(extra.section, 0) + 1
        rows += [(EXTRA_COLORS[s], f"{bpy.app.translations.pgettext_iface(EXTRA_TITLES[s])}  {counts[s]}")
                 for s in EXTRA_COLORS if s in counts]
    if view.beam_colors and view.beam_color_by == "TYPE":
        counts: dict[str, int] = {}
        for beam in session.edit.vehicle.beams:
            beam_type = beam.props.get("beamType")
            if beam_color(beam_type) is not None:
                counts[beam_type] = counts.get(beam_type, 0) + 1
        rows += [(beam_color(t), f"{t}  {n}") for t, n in sorted(counts.items())]
    elif view.beam_colors:
        rows += _gradient_rows(view.beam_color_by, _values(session, "beams", view.beam_color_by)[1])
    if view.group_colors and view.node_color_by == "GROUP":
        groups = sorted(session.edit.node_groups().items(), key=lambda item: -len(item[1]))
        rows += [(group_color(g), f"{g}  {len(n)}") for g, n in groups[:LEGEND_GROUPS]]
        if len(groups) > LEGEND_GROUPS:
            rows.append(((0.5, 0.5, 0.5), bpy.app.translations.pgettext_iface("and {count} more groups").format(
                count=len(groups) - LEGEND_GROUPS)))
    elif view.group_colors:
        rows += _gradient_rows(view.node_color_by, _values(session, "nodes", view.node_color_by)[1])
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
    for color, text in reversed(rows):
        if color is not None:
            shader.uniform_float("color", (*color, 1.0))
            batch_for_shader(shader, "TRIS", {"pos": [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]},
                             indices=[(0, 1, 2), (0, 2, 3)]).draw(shader)
        blf.color(0, 1, 1, 1, 0.9)
        blf.position(0, x + (size + 6 * scale if color is not None else 0), y + 2 * scale, 0)
        blf.draw(0, text)
        y += line


def draw_center() -> None:
    """A cross at the centre of mass of each shown vehicle, drawn over everything."""
    context = bpy.context
    if not context.window_manager.jbs_view.center_of_mass:
        return
    shown: dict[str, tuple] = {}
    for obj, session in _shown_objects(context):
        if session.key not in shown or obj == context.active_object:
            shown[session.key] = (obj, session)
    lines: list = []
    for obj, session in shown.values():
        cache_key = (session.key, session.link.rev, "center")
        if cache_key not in _cache:
            _cache[cache_key] = mass(session.edit.vehicle, session.edit.vehicle.nodes.values())[1]
        center = _cache[cache_key]
        if center is None:
            continue
        middle = obj.matrix_world @ Vector(center)
        for axis in Matrix.Identity(3):
            lines += [tuple(middle + axis * CENTER_SIZE), tuple(middle - axis * CENTER_SIZE)]
    if lines:
        gpu.state.blend_set("ALPHA")
        _lines(context, {CENTER_COLOR: lines}, 3.0)
        gpu.state.blend_set("NONE")


def _vertices(obj):
    """Positions, uids, checks, ghost flags and selection of the object's vertices."""
    mesh = obj.data
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(mesh)
        layers = bm.verts.layers
        uid, check = layers.int.get(mesh_io.NODE_UID), layers.int.get(mesh_io.NODE_CHECK)
        ghost = layers.bool.get(mesh_io.GHOST) if hasattr(layers, "bool") else None
        if uid is None or check is None:
            return None
        verts = bm.verts
        positions = np.array([v.co for v in verts], dtype=np.float32).reshape(-1, 3)
        uids = np.array([v[uid] for v in verts], dtype=np.int64)
        checks = np.array([v[check] for v in verts], dtype=np.int64)
        ghosts = np.array([bool(v[ghost]) for v in verts], dtype=bool) if ghost is not None else np.zeros(len(verts), bool)
        selected = np.array([v.select for v in verts], dtype=bool)
        return positions, uids, checks, ghosts, selected
    count = len(mesh.vertices)
    positions = np.zeros(count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)
    uids = mesh_io._read(mesh, mesh_io.NODE_UID, "POINT", count).astype(np.int64)
    checks = mesh_io._read(mesh, mesh_io.NODE_CHECK, "POINT", count).astype(np.int64)
    ghosts = np.zeros(count, dtype=bool)
    attribute = mesh.attributes.get(mesh_io.GHOST)
    if attribute is not None and attribute.domain == "POINT" and count:
        attribute.data.foreach_get("value", ghosts)
    return positions.reshape(-1, 3), uids, checks, ghosts, np.zeros(count, dtype=bool)


def _shown_objects(context):
    for obj in context.visible_objects:
        session = sessions.session_of(obj)
        if session is not None:
            yield obj, session


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


def draw_ghosts() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if not view.ghosts:
        return
    with _faces_hide(context) as hidden:
        for obj, _session in _shown_objects(context):
            data = _vertices(obj)
            if data is None:
                continue
            positions, _uids, _checks, ghosts, _selected = data
            if not ghosts.any():
                continue
            world = _world(obj, positions[ghosts])
            if hidden:
                world = _lift(context, world, LINE_LIFT)
            _points(context, {GHOST_COLOR: world.tolist()}, 9.0)


def _depths(context) -> np.ndarray | None:
    """The depth of the drawn scene at each pixel of the region, from 0 (near) to 1 (far). Blender 4.5 gives
    scripts the depth of another buffer than the one the scene is drawn into, so there it is None."""
    region = context.region
    if bpy.app.version < (5, 0, 0):
        return None
    try:
        buffer = gpu.state.active_framebuffer_get().read_depth(0, 0, region.width, region.height)
        return np.asarray(buffer, dtype=np.float32).reshape(region.height, region.width)
    except (ValueError, TypeError, AttributeError, SystemError):
        return None


def _faces_tree(context):
    """A BVH tree of the faces of the shown JBeam objects in world space, built again when they change."""
    key, positions, polygons, offset = [], [], [], 0
    for obj, _session in _shown_objects(context):
        if obj.mode == "EDIT":
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.index_update()
            local = np.array([v.co for v in bm.verts], dtype=np.float32).reshape(-1, 3)
            faces = [[v.index for v in f.verts] for f in bm.faces]
        else:
            mesh = obj.data
            local = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", local)
            local = local.reshape(-1, 3)
            faces = [list(p.vertices) for p in mesh.polygons]
        if not faces:
            continue
        world = _world(obj, local)
        key.append((obj.name, len(faces), hash(world.tobytes())))
        positions.extend(world.tolist())
        polygons.extend([i + offset for i in face] for face in faces)
        offset += len(world)
    key = tuple(key)
    cached = _cache.get("faces")
    if cached is None or cached[0] != key:
        _cache["faces"] = (key, BVHTree.FromPolygons(positions, polygons) if polygons else None)
    return _cache["faces"][1]


def _hidden_by_faces(context, world: np.ndarray) -> np.ndarray:
    """Whether a face of a shown JBeam object lies between the viewer and each point; for Blender 4.5."""
    hidden = np.zeros(len(world), dtype=bool)
    tree = _faces_tree(context)
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


def draw_labels() -> None:
    """Node names; a name is left out where a face in front of its node hides the node."""
    context = bpy.context
    view = context.window_manager.jbs_view
    region = context.region
    if view.labels == "NONE" or region is None or not region.width or not region.height:
        return
    font = 0
    blf.size(font, view.label_size * context.preferences.system.ui_scale)
    pixels = Matrix(((2.0 / region.width, 0, 0, -1), (0, 2.0 / region.height, 0, -1), (0, 0, 1, 0), (0, 0, 0, 1)))
    hide = not through(context)
    depths = _depths(context) if hide else None
    with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
        gpu.matrix.load_identity()
        gpu.matrix.load_projection_matrix(pixels)
        gpu.state.blend_set("ALPHA")
        for obj, session in _shown_objects(context):
            if view.labels == "SELECTED" and obj.mode != "EDIT":
                continue
            data = _vertices(obj)
            if data is None:
                continue
            positions, uids, checks, ghosts, selected = data
            chosen = selected if view.labels == "SELECTED" else np.ones(len(uids), dtype=bool)
            indices = np.flatnonzero(chosen)
            if not len(indices):
                continue
            world = _world(obj, positions[indices])
            if depths is not None:
                points, ndc, visible = _screen(context, _lift(context, world, LABEL_LIFT))
                columns = np.clip(points[:, 0].astype(int), 0, region.width - 1)
                rows = np.clip(points[:, 1].astype(int), 0, region.height - 1)
                visible &= (ndc + 1.0) * 0.5 <= depths[rows, columns] + 1e-6
            else:
                points, ndc, visible = _screen(context, world)
                if hide:
                    visible &= ~_hidden_by_faces(context, world)
            ids = session.link.map.ids
            drawn = 0
            for index, (x, y), shown in zip(indices.tolist(), points.tolist(), visible.tolist()):
                if not shown:
                    continue
                node_id = session.link.node_of(int(uids[index]), int(checks[index]))
                if node_id is None or int(uids[index]) not in ids:
                    continue
                blf.color(font, *(GHOST_LABEL_COLOR if ghosts[index] else LABEL_COLOR))
                blf.position(font, x + 6, y + 4, 0)
                blf.draw(font, node_id)
                drawn += 1
                if drawn >= MAX_LABELS:
                    break
        gpu.state.blend_set("NONE")


def draw_header(self, context) -> None:
    """The Through faces switch in the header of the 3D viewport, when JBeam objects are open."""
    if sessions.SESSIONS:
        self.layout.prop(context.window_manager.jbs_view, "through_faces", text="", icon="MOD_WIREFRAME")


def register() -> None:
    for function, kind in ((draw_beams, "POST_VIEW"), (draw_extras, "POST_VIEW"), (draw_ghosts, "POST_VIEW"),
                           (draw_labels, "POST_VIEW"), (draw_center, "POST_VIEW"), (draw_legend, "POST_PIXEL")):
        _handles.append((bpy.types.SpaceView3D.draw_handler_add(function, (), "WINDOW", kind), "WINDOW"))
    bpy.types.VIEW3D_HT_header.append(draw_header)


def unregister() -> None:
    bpy.types.VIEW3D_HT_header.remove(draw_header)
    for handle, region in _handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, region)
    _handles.clear()
