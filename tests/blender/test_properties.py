import bmesh
import bpy

from jbeam_studio.blender import mesh_io, sessions


def import_pc(car):
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    obj = bpy.context.active_object
    return obj, sessions.session_of(obj)


def edit_mesh(obj):
    if obj.mode != "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    return bmesh.from_edit_mesh(obj.data)


def select_nodes(obj, session, node_ids):
    bpy.context.tool_settings.mesh_select_mode = (True, False, False)
    bm = edit_mesh(obj)
    layer = bm.verts.layers.int[mesh_io.NODE_UID]
    uids = {session.link.map.nodes[i] for i in node_ids}
    for element in (*bm.verts, *bm.edges, *bm.faces):
        element.select = False
    for vertex in bm.verts:
        vertex.select = vertex[layer] in uids
    bm.select_flush(True)
    bmesh.update_edit_mesh(obj.data)


def selected(obj, session):
    return sorted(sessions.selected_node_ids(obj, session))


def test_set_property_on_selected_beams(car):
    obj, session = import_pc(car)
    select_nodes(obj, session, ["b1l", "b2"])
    bpy.context.tool_settings.mesh_select_mode = (False, True, False)
    assert bpy.ops.jbs.set_property(kind="beams", key="beamSpring", value="1234") == {"FINISHED"}
    beam = next(b for b in session.edit.vehicle.beams if {b.id1, b.id2} == {"b1l", "b2"})
    assert beam.props["beamSpring"] == 1234
    assert '["b1l", "b2", {"beamSpring": 1234}]' in session.edit.text_of(car / "body.jbeam")
    assert mesh_io.mesh_rev(obj) == session.link.rev


def test_select_by_property(car):
    obj, session = import_pc(car)
    edit_mesh(obj)
    assert bpy.ops.jbs.select_by_property(kind="nodes", key="nodeWeight", value="10") == {"FINISHED"}
    assert selected(obj, session) == ["b1l", "b1r", "b2", "d1l", "e1"]
    assert bpy.ops.jbs.select_by_property(kind="nodes", key="name", value='"b2"') == {"FINISHED"}
    assert selected(obj, session) == ["b2"]


def test_groups_can_be_set_selected_hidden_and_renamed(car):
    obj, session = import_pc(car)
    select_nodes(obj, session, ["b1l", "b1r"])
    assert bpy.ops.jbs.set_property(kind="nodes", key="group", value="frame") == {"FINISHED"}
    assert session.edit.node_groups() == {"frame": ["b1l", "b1r"]}
    select_nodes(obj, session, ["b2"])
    assert bpy.ops.jbs.group_select(group="frame") == {"FINISHED"}
    assert selected(obj, session) == ["b1l", "b1r"]
    assert bpy.ops.jbs.group_hide(group="frame", hide=True) == {"FINISHED"}
    bm = edit_mesh(obj)
    assert sum(v.hide for v in bm.verts) == 2
    bpy.ops.jbs.group_hide(group="frame", hide=False)
    assert bpy.ops.jbs.rename_group("EXEC_DEFAULT", group="frame", new_name="chassis") == {"FINISHED"}
    assert session.edit.node_groups() == {"chassis": ["b1l", "b1r"]}
