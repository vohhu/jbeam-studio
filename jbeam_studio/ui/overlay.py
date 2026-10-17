"""Drawing in the 3D viewport: node names, and nodes of other parts in another colour."""

from __future__ import annotations

import colorsys
import hashlib

import blf
import bmesh
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ..blender import mesh_io, sessions

GHOST_COLOR = (1.0, 0.55, 0.1, 1.0)
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
_handles: list = []


def beam_color(beam_type) -> tuple | None:
    if beam_type in (None, "", "|NORMAL"):
        return None
    return BEAM_COLORS.get(beam_type, UNKNOWN_BEAM_COLOR)


def group_color(name: str) -> tuple:
    """A colour of its own for each group name, the same in every session."""
    value = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:6], 16)
    return colorsys.hsv_to_rgb((value % 360) / 360.0, 0.65, 1.0)


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


def draw_beams() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if not view.beam_colors and not view.group_colors:
        return
    region = context.region
    gpu.state.blend_set("ALPHA")
    for obj, session in _shown_objects(context):
        data = _vertices(obj)
        if data is None or not len(data[0]):
            continue
        world = _world(obj, data[0]).tolist()
        if view.beam_colors:
            edges = _edges(obj)
            if edges is not None:
                types = _beam_types(session)
                lines: dict[tuple, list] = {}
                for (a, b), uid in zip(*edges):
                    color = beam_color(types.get(uid))
                    if color is not None:
                        lines.setdefault(color, []).extend((world[a], world[b]))
                shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
                shader.uniform_float("viewportSize", (region.width, region.height))
                shader.uniform_float("lineWidth", 2.5 * context.preferences.system.ui_scale)
                for color, points in lines.items():
                    shader.uniform_float("color", (*color, 1.0))
                    batch_for_shader(shader, "LINES", {"pos": points}).draw(shader)
        if view.group_colors:
            positions, uids, checks = data[0], data[1], data[2]
            points: dict[tuple, list] = {}
            for index, (uid, check) in enumerate(zip(uids.tolist(), checks.tolist())):
                node = sessions.node_entry(session, session.link.node_of(uid, check) or "")
                group = node.props.get("group") if node is not None else None
                group = group[0] if isinstance(group, list) and group else group
                if isinstance(group, str) and group:
                    points.setdefault(group_color(group), []).append(world[index])
            shader = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
            gpu.state.point_size_set(7.0 * context.preferences.system.ui_scale)
            for color, items in points.items():
                shader.uniform_float("color", (*color, 1.0))
                batch_for_shader(shader, "POINTS", {"pos": items}).draw(shader)
            gpu.state.point_size_set(1.0)
    gpu.state.blend_set("NONE")


def _node_positions(obj, session, data) -> dict[str, list]:
    world = _world(obj, data[0]).tolist()
    found = {}
    for index, (uid, check) in enumerate(zip(data[1].tolist(), data[2].tolist())):
        node_id = session.link.node_of(uid, check)
        if node_id is not None:
            found[node_id] = world[index]
    return found


def draw_extras() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if not view.extras:
        return
    region = context.region
    scale = context.preferences.system.ui_scale
    lines = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    lines.uniform_float("viewportSize", (region.width, region.height))
    points = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    for obj, session in _shown_objects(context):
        extras = session.edit.vehicle.extras
        data = _vertices(obj) if extras else None
        if data is None or not len(data[0]):
            continue
        where = _node_positions(obj, session, data)
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
            lines.uniform_float("lineWidth", (4.0 if section == "rails" else 3.0) * scale)
            lines.uniform_float("color", (*EXTRA_COLORS[section], 1.0))
            batch_for_shader(lines, "LINES", {"pos": pairs}).draw(lines)
        if spots:
            gpu.state.point_size_set(11.0 * scale)
            points.uniform_float("color", (*EXTRA_COLORS["slidenodes"], 1.0))
            batch_for_shader(points, "POINTS", {"pos": spots}).draw(points)
            gpu.state.point_size_set(1.0)
    gpu.state.blend_set("NONE")


def draw_legend() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if not view.legend or not (view.beam_colors or view.group_colors or view.extras):
        return
    obj = context.active_object
    session = sessions.session_of(obj)
    if session is None:
        return
    rows: list[tuple[tuple, str]] = []
    if view.extras:
        counts = {}
        for extra in session.edit.vehicle.extras:
            counts[extra.section] = counts.get(extra.section, 0) + 1
        rows += [(EXTRA_COLORS[s], f"{bpy.app.translations.pgettext_iface(EXTRA_TITLES[s])}  {counts[s]}")
                 for s in EXTRA_COLORS if s in counts]
    if view.beam_colors:
        counts: dict[str, int] = {}
        for beam in session.edit.vehicle.beams:
            beam_type = beam.props.get("beamType")
            if beam_color(beam_type) is not None:
                counts[beam_type] = counts.get(beam_type, 0) + 1
        rows += [(beam_color(t), f"{t}  {n}") for t, n in sorted(counts.items())]
    if view.group_colors:
        groups = sorted(session.edit.node_groups().items(), key=lambda item: -len(item[1]))
        rows += [(group_color(g), f"{g}  {len(n)}") for g, n in groups[:LEGEND_GROUPS]]
        if len(groups) > LEGEND_GROUPS:
            rows.append(((0.5, 0.5, 0.5), bpy.app.translations.pgettext_iface("and {count} more groups").format(
                count=len(groups) - LEGEND_GROUPS)))
    if not rows:
        return
    scale = context.preferences.system.ui_scale
    size, line = 12 * scale, 18 * scale
    x, y = 16 * scale, 40 * scale
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    blf.size(0, 12 * scale)
    for color, text in reversed(rows):
        shader.uniform_float("color", (*color, 1.0))
        batch_for_shader(shader, "TRIS", {"pos": [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]},
                         indices=[(0, 1, 2), (0, 2, 3)]).draw(shader)
        blf.color(0, 1, 1, 1, 0.9)
        blf.position(0, x + size + 6 * scale, y + 2 * scale, 0)
        blf.draw(0, text)
        y += line


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


def _project(context, matrix, positions):
    region, region_3d = context.region, context.region_data
    if region is None or region_3d is None or not len(positions):
        return np.zeros((0, 2)), np.zeros(0, bool)
    transform = np.array(region_3d.perspective_matrix @ matrix, dtype=np.float64)
    points = np.c_[positions.astype(np.float64), np.ones(len(positions))] @ transform.T
    visible = points[:, 3] > 1e-6
    w = np.where(visible, points[:, 3], 1.0)
    x = (points[:, 0] / w + 1.0) * 0.5 * region.width
    y = (points[:, 1] / w + 1.0) * 0.5 * region.height
    visible &= (x >= 0) & (x <= region.width) & (y >= 0) & (y <= region.height)
    return np.c_[x, y], visible


def draw_ghosts() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if not view.ghosts:
        return
    shader = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
    gpu.state.point_size_set(9.0)
    gpu.state.blend_set("ALPHA")
    for obj, session in _shown_objects(context):
        if not session.edit.vehicle.external_nodes:
            continue
        data = _vertices(obj)
        if data is None:
            continue
        positions, _uids, _checks, ghosts, _selected = data
        if not ghosts.any():
            continue
        matrix = np.array(obj.matrix_world, dtype=np.float64)
        world = (np.c_[positions[ghosts].astype(np.float64), np.ones(int(ghosts.sum()))] @ matrix.T)[:, :3]
        batch = batch_for_shader(shader, "POINTS", {"pos": world.astype(np.float32).tolist()})
        shader.uniform_float("color", GHOST_COLOR)
        batch.draw(shader)
    gpu.state.point_size_set(1.0)
    gpu.state.blend_set("NONE")


def draw_labels() -> None:
    context = bpy.context
    view = context.window_manager.jbs_view
    if view.labels == "NONE":
        return
    font = 0
    blf.size(font, view.label_size * context.preferences.system.ui_scale)
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
        points, visible = _project(context, obj.matrix_world, positions[indices])
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


def register() -> None:
    _handles.append((bpy.types.SpaceView3D.draw_handler_add(draw_beams, (), "WINDOW", "POST_VIEW"), "WINDOW"))
    _handles.append((bpy.types.SpaceView3D.draw_handler_add(draw_extras, (), "WINDOW", "POST_VIEW"), "WINDOW"))
    _handles.append((bpy.types.SpaceView3D.draw_handler_add(draw_ghosts, (), "WINDOW", "POST_VIEW"), "WINDOW"))
    _handles.append((bpy.types.SpaceView3D.draw_handler_add(draw_labels, (), "WINDOW", "POST_PIXEL"), "WINDOW"))
    _handles.append((bpy.types.SpaceView3D.draw_handler_add(draw_legend, (), "WINDOW", "POST_PIXEL"), "WINDOW"))


def unregister() -> None:
    for handle, region in _handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, region)
    _handles.clear()
