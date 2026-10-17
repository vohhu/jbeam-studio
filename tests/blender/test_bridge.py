import bmesh
import bpy
import pytest

from jbeam_studio.blender import handlers, mesh_io, sessions
from jbeam_studio.core.edit import EditError
from jbeam_studio.core.model.files import read_text
from jbeam_studio.core.sjson import parse, to_python


def import_pc(car):
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    obj = bpy.context.active_object
    return obj, sessions.session_of(obj)


def edit(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    return bm


def leave(obj):
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")


def vertex(obj, session, bm, node_id):
    uid = session.link.map.nodes[node_id]
    layer = bm.verts.layers.int[mesh_io.NODE_UID]
    return next(v for v in bm.verts if v[layer] == uid)


def body(session, car):
    return to_python(parse(session.edit.text_of(car / "body.jbeam")))["car_body"]


def test_import_builds_one_mesh_with_uids(car):
    obj, session = import_pc(car)
    vehicle = session.edit.vehicle
    assert len(obj.data.vertices) == len(vehicle.nodes)
    assert len(obj.data.polygons) == len(vehicle.triangles)
    beam_uids = [a.value for a in obj.data.attributes[mesh_io.BEAM_UID].data]
    assert sorted(u for u in beam_uids if u > 0) == sorted(session.link.map.beams)
    assert mesh_io.mesh_rev(obj) == session.link.rev
    assert obj.jbs.active_part == "car_body"
    assert sessions.in_sync(obj, session)


def test_moved_vertex_is_written_on_apply(car):
    obj, session = import_pc(car)
    bm = edit(obj)
    vertex(obj, session, bm, "b2").co = (0.1, 1.0, 0.3)
    leave(obj)
    assert not sessions.in_sync(obj, session)
    assert bpy.ops.jbs.apply_mesh() == {"FINISHED"}
    assert body(session, car)["nodes"][-1] == ["b2", 0.1, 1.0, 0.3]
    assert mesh_io.mesh_rev(obj) == session.link.rev and sessions.in_sync(obj, session)


def test_apply_from_edit_mode_stays_in_edit_mode(car):
    obj, session = import_pc(car)
    bm = edit(obj)
    vertex(obj, session, bm, "b2").co = (0.1, 1.0, 0.3)
    bmesh.update_edit_mesh(obj.data)
    assert bpy.ops.jbs.apply_mesh() == {"FINISHED"}
    assert obj.mode == "EDIT" and session.edit.vehicle.nodes["b2"].pos == pytest.approx((0.1, 1.0, 0.3))


def test_extruded_vertex_becomes_a_node_with_a_beam(car):
    obj, session = import_pc(car)
    bm = edit(obj)
    source = vertex(obj, session, bm, "b2")
    result = bmesh.ops.extrude_vert_indiv(bm, verts=[source])
    result["verts"][0].co = (0.0, 2.0, 0.3)
    leave(obj)
    obj.jbs.auto_names = False
    obj.jbs.node_prefix = "x"
    sessions.apply_mesh(obj, session)
    vehicle = session.edit.vehicle
    assert vehicle.nodes["x1"].pos == pytest.approx((0.0, 2.0, 0.3))
    assert any({b.id1, b.id2} == {"b2", "x1"} for b in vehicle.beams)
    assert len(obj.data.vertices) == len(vehicle.nodes)


def test_subdivided_edge_adds_a_node_between(car):
    obj, session = import_pc(car)
    bm = edit(obj)
    a, b = vertex(obj, session, bm, "b1l"), vertex(obj, session, bm, "b2")
    edge = next(e for e in bm.edges if set(e.verts) == {a, b})
    bmesh.ops.subdivide_edges(bm, edges=[edge], cuts=1)
    leave(obj)
    before = dict((k, n.pos) for k, n in session.edit.vehicle.nodes.items())
    sessions.apply_mesh(obj, session)
    vehicle = session.edit.vehicle
    new = set(vehicle.nodes) - set(before)
    assert len(new) == 1
    middle = new.pop()
    assert all(vehicle.nodes[k].pos == pytest.approx(p) for k, p in before.items())
    links = {frozenset((b.id1, b.id2)) for b in vehicle.beams}
    assert {frozenset(("b1l", middle)), frozenset((middle, "b2"))} <= links
    assert frozenset(("b1l", "b2")) not in links


def test_deleted_vertex_deletes_the_node(car):
    obj, session = import_pc(car)
    bm = edit(obj)
    bmesh.ops.delete(bm, geom=[vertex(obj, session, bm, "b2")], context="VERTS")
    leave(obj)
    sessions.apply_mesh(obj, session)
    assert "b2" not in session.edit.vehicle.nodes and not session.edit.vehicle.triangles


def test_flipped_face_flips_the_triangle(car):
    obj, session = import_pc(car)
    edit(obj)
    bpy.ops.mesh.select_all(action="SELECT")
    assert bpy.ops.jbs.flip_faces() == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    sessions.apply_mesh(obj, session)
    assert body(session, car)["triangles"][1] == ["b1l", "b2", "b1r"]


def test_failed_apply_keeps_the_mesh_edits(car):
    obj, session = import_pc(car)
    obj.jbs.active_part = "no_such_part"
    bm = edit(obj)
    bm.verts.new((0.0, 9.0, 9.0))
    leave(obj)
    count = len(obj.data.vertices)
    with pytest.raises(EditError):
        sessions.apply_mesh(obj, session)
    assert len(obj.data.vertices) == count and session.error and session.edit.history == []


def test_undo_handler_returns_the_session_to_the_mesh_state(car):
    obj, session = import_pc(car)
    obj.jbs.live_apply = False
    first = session.link.rev
    bm = edit(obj)
    vertex(obj, session, bm, "b2").co = (0.1, 1.0, 0.3)
    leave(obj)
    sessions.apply_mesh(obj, session)
    second = session.link.rev
    mesh_io.set_rev(obj, first)
    handlers.on_undo_post()
    assert session.edit.position == 0 and session.link.rev == first
    mesh_io.set_rev(obj, second)
    handlers.on_undo_post()
    assert session.edit.position == 1


def test_unknown_state_marks_the_mesh_stale(car):
    obj, session = import_pc(car)
    mesh_io.set_rev(obj, 12345)
    handlers.on_undo_post()
    assert session.stale
    with pytest.raises(EditError):
        sessions.apply_mesh(obj, session)
    bpy.ops.jbs.rebuild()
    assert not session.stale and sessions.in_sync(obj, session)


def test_rename_keeps_the_mesh_and_marks_the_new_state(car):
    obj, session = import_pc(car)
    edit(obj)
    session.edit.rename_node("b2", "b9")
    sessions.after_change(obj, session, renames={"b9": "b2"})
    assert mesh_io.mesh_rev(obj) == session.link.rev
    bpy.ops.object.mode_set(mode="OBJECT")
    assert session.link.plan(mesh_io.read_mesh(obj)).empty


def test_save_writes_the_file_and_a_backup(car):
    obj, session = import_pc(car)
    original = read_text(car / "body.jbeam")
    bm = edit(obj)
    vertex(obj, session, bm, "b2").co = (0.1, 1.0, 0.3)
    leave(obj)
    assert bpy.ops.jbs.save() == {"FINISHED"}
    assert read_text(car / "body.jbeam.bak") == original
    assert '["b2", 0.100, 1.0, 0.3]' in read_text(car / "body.jbeam")
    assert session.edit.dirty_files() == []


def test_external_change_is_reported_and_reloaded(car):
    obj, session = import_pc(car)
    path = car / "body.jbeam"
    path.write_text(read_text(path).replace('["b2", 0.0, 1.0, 0.3]', '["b2", 0.0, 1.5, 0.3]'), encoding="utf-8")
    assert sessions.check_disk(session) and session.changed_on_disk == [path.absolute()]
    assert bpy.ops.jbs.reload() == {"FINISHED"}
    assert session.edit.vehicle.nodes["b2"].pos == pytest.approx((0.0, 1.5, 0.3)) and sessions.in_sync(obj, session)


def test_part_import_shows_ghosts_and_ignores_their_moves(car):
    assert bpy.ops.jbs.import_jbeam(filepath=str(car / "doors.jbeam"), part_name="car_door_L_stock") == {"FINISHED"}
    obj = bpy.context.active_object
    session = sessions.session_of(obj)
    ghosts = [a.value for a in obj.data.attributes[mesh_io.GHOST].data]
    assert ghosts.count(True) == 1
    bm = edit(obj)
    vertex(obj, session, bm, "b1l").co = (3.0, 3.0, 3.0)
    leave(obj)
    sessions.apply_mesh(obj, session)
    assert session.edit.history == [] and session.last_plan.ghosts_moved == 1
    assert sessions.in_sync(obj, session)


def test_copy_of_an_object_is_not_linked(car):
    obj, session = import_pc(car)
    copy = obj.copy()
    copy.data = obj.data.copy()
    bpy.context.collection.objects.link(copy)
    assert sessions.session_of(obj) is session and sessions.session_of(copy) is None and sessions.is_copy(copy)


def test_text_view_shows_and_applies_edits(car):
    obj, session = import_pc(car)
    text = sessions.show_text(session, car / "body.jbeam")
    assert not sessions.text_edited(text)
    content = text.as_string().replace('["b2", 0.0, 1.0, 0.3]', '["b2", 0.0, 1.2, 0.3]')
    text.clear()
    text.write(content)
    assert sessions.text_edited(text)
    assert bpy.ops.jbs.apply_text(text_name=text.name) == {"FINISHED"}
    assert session.edit.vehicle.nodes["b2"].pos == pytest.approx((0.0, 1.2, 0.3))
    assert not sessions.text_edited(text) and sessions.in_sync(obj, session)


def test_reopened_blend_file_loads_the_files_again(car, tmp_path):
    obj, session = import_pc(car)
    name = obj.name
    blend = tmp_path / "car.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    obj = bpy.data.objects[name]
    session = sessions.session_of(obj)
    assert session is not None and sessions.in_sync(obj, session)
    assert len(obj.data.vertices) == len(session.edit.vehicle.nodes)
