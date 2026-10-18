import bmesh
import bpy
import pytest

from jbeam_studio.blender import handlers, mesh_io, sessions
from jbeam_studio.core.model.files import read_text

ORIGINAL_ROW = '["b2", 0.0, 1.0, 0.3]'
MOVED_ROW = '["b2", 0.100, 1.0, 0.3]'


def import_pc(car):
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    obj = bpy.context.active_object
    return obj, sessions.session_of(obj)


def edit_mesh(obj):
    if obj.mode != "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    return bm


def vertex(session, bm, node_id):
    layer = bm.verts.layers.int[mesh_io.NODE_UID]
    return next(v for v in bm.verts if v[layer] == session.link.map.nodes[node_id])


def set_b2(obj, session, x):
    bm = edit_mesh(obj)
    layer = bm.verts.layers.int[mesh_io.NODE_UID]
    target = next(v for v in bm.verts if v[layer] == session.link.map.nodes.get("b2", -1))
    target.co.x = x
    bmesh.update_edit_mesh(obj.data)


def test_edit_mode_edits_reach_the_text_and_the_file_right_away(car):
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    base_rev = mesh_io.mesh_rev(obj)
    text = sessions.show_text(session, car / "body.jbeam")
    set_b2(obj, session, 0.1)
    assert sessions.apply_live(obj, session)
    assert obj.mode == "EDIT" and mesh_io.mesh_rev(obj) == session.link.rev != base_rev
    assert MOVED_ROW in text.as_string() and MOVED_ROW in read_text(car / "body.jbeam")
    assert session.link.plan(mesh_io.read_mesh(obj), session.scope).empty


def restore(obj, session, x, rev):
    """What Blender's undo does in Edit Mode: it brings back the edit mesh of a step, with the state number the
    mesh had when the step was pushed."""
    set_b2(obj, session, x)
    mesh_io.set_rev(obj, rev)


def test_undo_and_redo_of_an_edit_mode_step_follow_the_mesh(car):
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    base_rev = mesh_io.mesh_rev(obj)
    set_b2(obj, session, 0.1)
    sessions.apply_live(obj, session)
    moved_rev = session.link.rev
    restore(obj, session, 0.0, base_rev)
    handlers.on_undo_post()
    assert ORIGINAL_ROW in read_text(car / "body.jbeam") and session.link.rev == base_rev
    restore(obj, session, 0.1, base_rev)
    handlers.on_undo_post()
    assert session.link.rev == moved_rev and MOVED_ROW in read_text(car / "body.jbeam")
    assert mesh_io.mesh_rev(obj) == moved_rev


def test_new_node_can_be_renamed_in_edit_mode(car):
    obj, session = import_pc(car)
    bm = edit_mesh(obj)
    source = vertex(session, bm, "b2")
    new = bmesh.ops.extrude_vert_indiv(bm, verts=[source])["verts"][0]
    new.co = (0.0, 2.0, 0.3)
    for element in bm.verts:
        element.select = element is new
    bm.select_history.clear()
    bm.select_history.add(new)
    bmesh.update_edit_mesh(obj.data)
    sessions.apply_live(obj, session)
    assert "b3" in session.edit.vehicle.nodes
    assert sessions.active_node_id(obj, session) == "b3"
    session.edit.rename_node("b3", "x1")
    sessions.after_change(obj, session, renames={"x1": "b3"})
    assert session.link.plan(mesh_io.read_mesh(obj), session.scope).empty
    assert any({b.id1, b.id2} == {"b2", "x1"} for b in session.edit.vehicle.beams)


def test_new_nodes_get_their_ids_in_the_edit_mesh_right_away(car):
    obj, session = import_pc(car)
    bm = edit_mesh(obj)
    left = vertex(session, bm, "b1l")
    new = bmesh.ops.extrude_vert_indiv(bm, verts=[left])["verts"][0]
    new.co = (0.8, 0.5, 0.3)
    for element in bm.verts:
        element.select = element is new
    bmesh.update_edit_mesh(obj.data)
    sessions.apply_live(obj, session)
    assert sessions.selected_node_ids(obj, session) == ["b3l"]
    assert [e.id for e in sessions.selected_entries(obj, session, (True, False, False))] == ["b3l"]


def test_leaving_edit_mode_after_live_edits_rebuilds_the_mesh(car):
    obj, session = import_pc(car)
    set_b2(obj, session, 0.1)
    sessions.apply_live(obj, session)
    rev = session.link.rev
    bpy.ops.object.mode_set(mode="OBJECT")
    sessions.apply_mesh(obj, session)
    assert session.link.rev == rev and mesh_io.mesh_rev(obj) == rev and sessions.in_sync(obj, session)
    assert session.edit.vehicle.nodes["b2"].pos == pytest.approx((0.1, 1.0, 0.3))


def door_of(car):
    import_pc(car)
    obj = bpy.data.objects["car_door_L_stock"]
    bpy.context.view_layer.objects.active = obj
    return obj, sessions.session_of(obj)


def test_mirror_button_adds_the_counterpart_in_edit_mode(car):
    obj, session = door_of(car)
    bm = edit_mesh(obj)
    door = vertex(session, bm, "d1l")
    for element in bm.verts:
        element.select = element is door
    bm.select_flush(False)
    bmesh.update_edit_mesh(obj.data)
    assert bpy.ops.jbs.mirror() == {"FINISHED"}
    assert obj.mode == "EDIT" and session.edit.vehicle.nodes["d1r"].part == "car_door_L_stock"
    assert sorted(sessions.selected_node_ids(obj, session)) == ["d1l", "d1r"]
    assert session.link.plan(mesh_io.read_mesh(obj), session.scope).empty
    assert len(bmesh.from_edit_mesh(obj.data).verts) == len(session.link.build(session.scope).positions) == 4


def test_mirror_button_across_y_through_the_active_node(car):
    obj, session = door_of(car)
    obj.jbs.mirror_axis, obj.jbs.mirror_plane = "y", "active"
    obj.jbs.all_nodes = True
    bm = edit_mesh(obj)
    for element in bm.verts:
        element.select = False
    door, center = vertex(session, bm, "d1l"), vertex(session, bm, "b2")
    door.select = center.select = True
    bm.select_history.clear()
    bm.select_history.add(door)
    bm.select_history.add(center)
    bmesh.update_edit_mesh(obj.data)
    door_y = session.edit.vehicle.nodes["d1l"].pos[1]
    assert bpy.ops.jbs.mirror() == {"FINISHED"}
    new = session.edit.vehicle.nodes["d2l"]
    assert new.pos[1] == pytest.approx(2 * session.edit.vehicle.nodes["b2"].pos[1] - door_y)


def test_new_rows_can_go_next_to_their_source(car):
    obj, session = import_pc(car)
    obj.jbs.placement = "source"
    bm = edit_mesh(obj)
    new = bmesh.ops.extrude_vert_indiv(bm, verts=[vertex(session, bm, "b1l")])["verts"][0]
    new.co = (0.8, 0.5, 0.3)
    bmesh.update_edit_mesh(obj.data)
    sessions.apply_live(obj, session)
    text = session.edit.text_of(car / "body.jbeam")
    assert text.index('["b1l"') < text.index('["b3l"') < text.index('["b1r"')
    assert session.edit.vehicle.nodes["b3l"].props["nodeWeight"] == 10


def test_add_resets_from_a_fix_button(car):
    obj, session = import_pc(car)
    path = car / "body.jbeam"
    text = session.edit.text_of(path).replace('"beams": [["id1:", "id2:"],',
                                              '"beams": [["id1:", "id2:"], {"beamPrecompression": 1.1},', 1)
    session.edit.replace_text(path, text)
    session.link.changed()
    [leak] = [i for i, d in enumerate(session.edit.vehicle.diagnostics) if d.fix[:1] == ("add_resets",)]
    assert bpy.ops.jbs.fix(index=leak) == {"FINISHED"}
    assert '{"beamPrecompression":1}' in session.edit.text_of(path)
    assert mesh_io.mesh_rev(obj) == session.link.rev


def fix_indices(session, kind):
    return [i for i, d in enumerate(session.edit.vehicle.diagnostics) if d.fix[:1] == (kind,)]


def test_fix_buttons_delete_repeated_rows_and_keep_broken_ones_as_optional_in_edit_mode(car):
    obj, session = import_pc(car)
    path = car / "body.jbeam"
    session.edit.replace_text(path, session.edit.text_of(path).replace(
        '["b1r", "ghost"]]', '["b1r", "ghost"], ["b2", "b1l"], ["b1r", "b1l"]]', 1))
    session.link.changed()
    sessions.rebuild(obj, session)
    edit_mesh(obj)
    assert len(fix_indices(session, "delete_duplicate")) == 2
    assert bpy.ops.jbs.fix(group="duplicates") == {"FINISHED"}
    text = session.edit.text_of(path)
    assert obj.mode == "EDIT" and '["b2", "b1l"]' not in text and '["b1r", "b1l"]' not in text
    assert mesh_io.mesh_rev(obj) == session.link.rev
    [broken] = fix_indices(session, "mark_optional")
    assert bpy.ops.jbs.fix(index=broken) == {"FINISHED"}
    assert '["b1r", "ghost", {"optional":true}]' in session.edit.text_of(path)
    assert not [d for d in session.edit.vehicle.diagnostics if d.fix]
    assert len(session.edit.history) == 3
    assert session.link.plan(mesh_io.read_mesh(obj), session.scope).empty


def test_live_applying_can_be_turned_off(car):
    obj, session = import_pc(car)
    obj.jbs.live_apply = False
    set_b2(obj, session, 0.1)
    handlers.on_undo_post()
    assert session.edit.history == []
