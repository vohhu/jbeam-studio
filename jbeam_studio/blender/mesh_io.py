"""Writing `MeshData` into Blender meshes and reading it back."""

from __future__ import annotations

from collections import Counter

import bmesh
import numpy as np

from ..core.mesh_sync import FACE_EDGE, MeshData, uid_check

NODE_UID = "jbs_node_uid"
NODE_CHECK = "jbs_node_check"
BEAM_UID = "jbs_beam_uid"
FACE_UID = "jbs_face_uid"
PART = "jbs_part"
GHOST = "jbs_ghost"
REV = "jbs_rev"
"""Session state the mesh was built from, on every vertex: Blender's undo restores it with the mesh."""


def _attribute(mesh, name: str, data_type: str, domain: str):
    attribute = mesh.attributes.get(name)
    if attribute is not None and (attribute.data_type != data_type or attribute.domain != domain):
        mesh.attributes.remove(attribute)
        attribute = None
    if attribute is None:
        attribute = mesh.attributes.new(name, data_type, domain)
    return attribute


def _read(mesh, name: str, domain: str, count: int) -> np.ndarray:
    values = np.zeros(count, dtype=np.int32)
    attribute = mesh.attributes.get(name)
    if attribute is not None and attribute.domain == domain and attribute.data_type == "INT" and count:
        attribute.data.foreach_get("value", values)
    return values


def write_mesh(mesh, data: MeshData, rev: int) -> None:
    """Replaces the mesh's geometry with `data`."""
    mesh.clear_geometry()
    mesh.from_pydata(data.positions, data.edges, data.faces)
    count = len(data.positions)
    _attribute(mesh, NODE_UID, "INT", "POINT").data.foreach_set("value", data.node_uids)
    _attribute(mesh, NODE_CHECK, "INT", "POINT").data.foreach_set("value", data.node_checks)
    _attribute(mesh, PART, "INT", "POINT").data.foreach_set("value", data.parts or [-1] * count)
    _attribute(mesh, GHOST, "BOOLEAN", "POINT").data.foreach_set("value", data.ghosts or [False] * count)
    _attribute(mesh, REV, "INT", "POINT").data.foreach_set("value", [rev] * count)
    pairs = np.zeros(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", pairs)
    by_pair = {(min(a, b), max(a, b)): uid for (a, b), uid in zip(data.edges, data.edge_uids)}
    edge_uids = [by_pair.get((min(a, b), max(a, b)), FACE_EDGE) for a, b in pairs.reshape(-1, 2).tolist()]
    _attribute(mesh, BEAM_UID, "INT", "EDGE").data.foreach_set("value", edge_uids)
    if len(mesh.polygons) != len(data.faces):
        raise RuntimeError("Blender did not keep every face of the vehicle")
    _attribute(mesh, FACE_UID, "INT", "FACE").data.foreach_set("value", data.face_uids)
    mesh[REV] = rev
    mesh.update()


def _read_edit_mesh(obj) -> MeshData:
    """The edit mesh of `obj`; in Edit Mode attribute data is only reachable through BMesh layers."""
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.index_update()
    verts, edges, faces = bm.verts, bm.edges, bm.faces
    ints = verts.layers.int
    uid, check = ints.get(NODE_UID), ints.get(NODE_CHECK)
    ghost = verts.layers.bool.get(GHOST) if hasattr(verts.layers, "bool") else None
    edge_uid, face_uid = edges.layers.int.get(BEAM_UID), faces.layers.int.get(FACE_UID)
    return MeshData(
        positions=[tuple(v.co) for v in verts],
        node_uids=[v[uid] for v in verts] if uid is not None else [0] * len(verts),
        node_checks=[v[check] for v in verts] if check is not None else [0] * len(verts),
        edges=[(e.verts[0].index, e.verts[1].index) for e in edges],
        edge_uids=[e[edge_uid] for e in edges] if edge_uid is not None else [0] * len(edges),
        faces=[tuple(v.index for v in f.verts) for f in faces],
        face_uids=[f[face_uid] for f in faces] if face_uid is not None else [0] * len(faces),
        ghosts=[bool(v[ghost]) for v in verts] if ghost is not None else [],
    )


def read_mesh(obj) -> MeshData:
    """The mesh of `obj` with its uids, or its edit mesh in Edit Mode."""
    if obj.mode == "EDIT":
        return _read_edit_mesh(obj)
    mesh = obj.data
    vertex_count, edge_count, face_count = len(mesh.vertices), len(mesh.edges), len(mesh.polygons)
    positions = np.zeros(vertex_count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)
    pairs = np.zeros(edge_count * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", pairs)
    starts = np.zeros(face_count, dtype=np.int32)
    totals = np.zeros(face_count, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    mesh.polygons.foreach_get("loop_total", totals)
    corners = np.zeros(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", corners)
    corner_list = corners.tolist()
    faces = [tuple(corner_list[s:s + t]) for s, t in zip(starts.tolist(), totals.tolist())]
    ghosts = np.zeros(vertex_count, dtype=bool)
    attribute = mesh.attributes.get(GHOST)
    if attribute is not None and attribute.domain == "POINT" and vertex_count:
        attribute.data.foreach_get("value", ghosts)
    return MeshData(
        positions=[tuple(p) for p in positions.reshape(-1, 3).astype(float).tolist()],
        node_uids=_read(mesh, NODE_UID, "POINT", vertex_count).tolist(),
        node_checks=_read(mesh, NODE_CHECK, "POINT", vertex_count).tolist(),
        edges=[tuple(p) for p in pairs.reshape(-1, 2).tolist()],
        edge_uids=_read(mesh, BEAM_UID, "EDGE", edge_count).tolist(),
        faces=faces,
        face_uids=_read(mesh, FACE_UID, "FACE", face_count).tolist(),
        ghosts=ghosts.tolist(),
    )


def fingerprint(obj) -> tuple:
    """Cheap summary of the geometry, to tell whether the mesh changed since it was built or applied."""
    if obj.mode == "EDIT":
        data = _read_edit_mesh(obj)
        corners = [v for face in data.faces for v in face]
        return ("edit", len(data.positions), len(data.edges), len(data.faces), hash(tuple(data.positions)),
                sum(v * (i % 7919 + 1) for i, v in enumerate(corners)), sum(data.node_uids), sum(data.edge_uids))
    mesh = obj.data
    positions = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)
    corners = np.zeros(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", corners)
    weights = np.arange(1, len(corners) + 1, dtype=np.int64) % 7919
    return (len(mesh.vertices), len(mesh.edges), len(mesh.polygons),
            hash(positions.tobytes()), int((corners * weights).sum()),
            int(_read(mesh, NODE_UID, "POINT", len(mesh.vertices)).sum(dtype=np.int64)),
            int(_read(mesh, BEAM_UID, "EDGE", len(mesh.edges)).sum(dtype=np.int64)))


def write_edit_mesh(obj, data: MeshData, rev: int, selected: set[int] = frozenset()) -> None:
    """Replaces the geometry of the edit mesh of `obj` with `data`, selecting the vertices of the node uids
    `selected`; the edit mesh counterpart of `write_mesh`."""
    bm = bmesh.from_edit_mesh(obj.data)
    bm.clear()
    ints = bm.verts.layers.int
    uid_layer, check_layer = ints.get(NODE_UID) or ints.new(NODE_UID), ints.get(NODE_CHECK) or ints.new(NODE_CHECK)
    part_layer, rev_layer = ints.get(PART) or ints.new(PART), ints.get(REV) or ints.new(REV)
    ghost_layer = (bm.verts.layers.bool.get(GHOST) or bm.verts.layers.bool.new(GHOST)) \
        if hasattr(bm.verts.layers, "bool") else None
    edge_layer = bm.edges.layers.int.get(BEAM_UID) or bm.edges.layers.int.new(BEAM_UID)
    face_layer = bm.faces.layers.int.get(FACE_UID) or bm.faces.layers.int.new(FACE_UID)
    verts = []
    for index, position in enumerate(data.positions):
        vertex = bm.verts.new(position)
        vertex[uid_layer], vertex[check_layer] = data.node_uids[index], data.node_checks[index]
        vertex[part_layer] = data.parts[index] if data.parts else -1
        vertex[rev_layer] = rev
        if ghost_layer is not None:
            vertex[ghost_layer] = bool(data.ghosts[index]) if data.ghosts else False
        vertex.select = data.node_uids[index] in selected
        verts.append(vertex)
    for (a, b), uid in zip(data.edges, data.edge_uids):
        bm.edges.new((verts[a], verts[b]))[edge_layer] = uid
    for corners, uid in zip(data.faces, data.face_uids):
        bm.faces.new([verts[i] for i in corners])[face_layer] = uid
    for edge in bm.edges:
        if edge[edge_layer] == 0:
            edge[edge_layer] = FACE_EDGE
    bm.select_flush(True)
    bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
    obj.data[REV] = rev


def stamp(obj, link, plan, new_ids) -> None:
    """Writes the uids, positions and state number of the session into the edit mesh it was just matched with
    (by `MeshLink.plan` and `apply`), so the mesh shows the session exactly without being rebuilt. Nodes outside
    the plan's part are ghosts."""
    bm = bmesh.from_edit_mesh(obj.data)
    ints = bm.verts.layers.int
    uid_layer, check_layer = ints.get(NODE_UID) or ints.new(NODE_UID), ints.get(NODE_CHECK) or ints.new(NODE_CHECK)
    part_layer, rev_layer = ints.get(PART) or ints.new(PART), ints.get(REV) or ints.new(REV)
    ghost_layer = bm.verts.layers.bool.get(GHOST) if hasattr(bm.verts.layers, "bool") else None
    edge_layer = bm.edges.layers.int.get(BEAM_UID) or bm.edges.layers.int.new(BEAM_UID)
    face_layer = bm.faces.layers.int.get(FACE_UID) or bm.faces.layers.int.new(FACE_UID)
    vehicle, uid_map, rev = link.session.vehicle, link.map, link.rev
    part_index = {name: i for i, name in enumerate(link.part_names)}
    own = link.own_nodes(plan.scope)
    for index, vertex in enumerate(bm.verts):
        vertex[rev_layer] = rev
        node_id = plan.vertex_nodes.get(index) or new_ids.get(index)
        node = (vehicle.nodes.get(node_id) or vehicle.external_nodes.get(node_id)) if node_id else None
        if node is None:
            continue
        ghost = node_id not in own
        uid = uid_map.nodes[node_id]
        vertex[uid_layer] = uid
        vertex[check_layer] = uid_check(uid)
        vertex[part_layer] = -1 if ghost else part_index.get(node.part, -1)
        vertex.co = node.pos
        if ghost_layer is not None:
            vertex[ghost_layer] = ghost
    beams = {frozenset(g.nodes): g.uid for g in uid_map.beams.values()}
    for edge in bm.edges:
        edge[edge_layer] = beams.get(frozenset(v[uid_layer] for v in edge.verts), FACE_EDGE)
    faces = {frozenset(g.nodes): g.uid for g in uid_map.faces.values()}
    for face in bm.faces:
        face[face_layer] = faces.get(frozenset(v[uid_layer] for v in face.verts), 0)
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    obj.data[REV] = rev


def mesh_rev(obj) -> int | None:
    """The session state the mesh was built from, as Blender's undo left it."""
    mesh = obj.data
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(mesh)
        layer = bm.verts.layers.int.get(REV)
        values = [v[layer] for v in bm.verts] if layer is not None else []
    else:
        values = _read(mesh, REV, "POINT", len(mesh.vertices)).tolist()
    counts = Counter(v for v in values if v > 0)
    if counts:
        return counts.most_common(1)[0][0]
    return mesh.get(REV)


def set_rev(obj, rev: int) -> None:
    """Marks the mesh as matching session state `rev` without changing its geometry."""
    mesh = obj.data
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(mesh)
        layer = bm.verts.layers.int.get(REV) or bm.verts.layers.int.new(REV)
        for vertex in bm.verts:
            vertex[layer] = rev
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        _attribute(mesh, REV, "INT", "POINT").data.foreach_set("value", [rev] * len(mesh.vertices))
    mesh[REV] = rev


def selected_vertices(obj) -> list[int]:
    mesh = obj.data
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.index_update()
        return [v.index for v in bm.verts if v.select]
    flags = np.zeros(len(mesh.vertices), dtype=bool)
    mesh.vertices.foreach_get("select", flags)
    return np.flatnonzero(flags).tolist()


def select_vertices(mesh, indices) -> None:
    """Selects exactly these vertices, and the edges and faces between them, in Object Mode."""
    flags = np.zeros(len(mesh.vertices), dtype=bool)
    flags[list(indices)] = True
    mesh.vertices.foreach_set("select", flags)
    pairs = np.zeros(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", pairs)
    pairs = pairs.reshape(-1, 2)
    mesh.edges.foreach_set("select", flags[pairs[:, 0]] & flags[pairs[:, 1]] if len(pairs) else np.zeros(0, bool))
    corners = np.zeros(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", corners)
    starts = np.zeros(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    if len(starts):
        faces = np.logical_and.reduceat(flags[corners], starts)
        mesh.polygons.foreach_set("select", faces)


def edit_mesh_uids(obj):
    """The edit mesh of `obj` with its vertex uid, check and edge uid layers (None when missing)."""
    bm = bmesh.from_edit_mesh(obj.data)
    return (bm, bm.verts.layers.int.get(NODE_UID), bm.verts.layers.int.get(NODE_CHECK),
            bm.edges.layers.int.get(BEAM_UID))
