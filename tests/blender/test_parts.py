import bmesh
import bpy
import pytest

from jbeam_studio.blender import handlers, mesh_io, sessions

BODY, DOOR = "car_body", "car_door_L_stock"


def import_pc(car):
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    return {name: (bpy.data.objects[name], sessions.session_of(bpy.data.objects[name])) for name in (BODY, DOOR)}


def vertex(session, bm, node_id):
    layer = bm.verts.layers.int[mesh_io.NODE_UID]
    return next(v for v in bm.verts if v[layer] == session.link.map.nodes[node_id])


def edit_all(*objects):
    for obj in bpy.data.objects:
        obj.select_set(obj in objects)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode="EDIT")


def test_parts_in_edit_mode_together_are_applied_together(car):
    parts = import_pc(car)
    (body, body_session), (door, door_session) = parts[BODY], parts[DOOR]
    edit_all(body, door)
    assert body.mode == door.mode == "EDIT"
    bm = bmesh.from_edit_mesh(body.data)
    vertex(body_session, bm, "b2").co = (0.2, 1.0, 0.3)
    bmesh.update_edit_mesh(body.data)
    bm = bmesh.from_edit_mesh(door.data)
    vertex(door_session, bm, "d1l").co = (0.9, 0.0, 0.5)
    bmesh.update_edit_mesh(door.data)
    assert sessions.apply_live(body, body_session)
    nodes = body_session.edit.vehicle.nodes
    assert nodes["b2"].pos == pytest.approx((0.2, 1.0, 0.3)) and nodes["d1l"].pos == pytest.approx((0.9, 0.0, 0.5))
    assert len(body_session.edit.history) == 2
    rev = body_session.link.rev
    assert mesh_io.mesh_rev(body) == mesh_io.mesh_rev(door) == rev
    assert body_session.link.plan(mesh_io.read_mesh(body), BODY).empty
    assert door_session.link.plan(mesh_io.read_mesh(door), DOOR).empty


def test_undo_in_one_part_brings_the_other_parts_back_too(car):
    parts = import_pc(car)
    (body, body_session), (door, door_session) = parts[BODY], parts[DOOR]
    first = body_session.link.rev
    bpy.context.view_layer.objects.active = body
    edit_all(body)
    bm = bmesh.from_edit_mesh(body.data)
    vertex(body_session, bm, "b1l").co = (0.7, 0.0, 0.3)
    bmesh.update_edit_mesh(body.data)
    sessions.apply_live(body, body_session)
    assert mesh_io.mesh_rev(door) == body_session.link.rev != first
    bm = bmesh.from_edit_mesh(body.data)
    vertex(body_session, bm, "b1l").co = (0.5, 0.0, 0.3)
    bmesh.update_edit_mesh(body.data)
    mesh_io.set_rev(body, first)
    handlers.on_undo_post()
    assert body_session.link.rev == first and mesh_io.mesh_rev(door) == first
    ghost = next(v.co for v, a in zip(door.data.vertices, door.data.attributes[mesh_io.GHOST].data) if a.value)
    assert tuple(ghost) == pytest.approx(body_session.edit.vehicle.nodes["b1l"].pos)


def test_a_part_can_show_every_node_of_the_vehicle(car):
    parts = import_pc(car)
    door, session = parts[DOOR]
    assert len(door.data.vertices) == 2
    door.jbs.all_nodes = True
    assert len(door.data.vertices) == 5 and sessions.in_sync(door, session)
    door.jbs.all_nodes = False
    assert len(door.data.vertices) == 2


def test_a_new_beam_of_a_part_to_a_node_of_another_part_goes_to_that_part(car):
    parts = import_pc(car)
    door, session = parts[DOOR]
    door.jbs.all_nodes = True
    edit_all(door)
    bm = bmesh.from_edit_mesh(door.data)
    bm.edges.new((vertex(session, bm, "d1l"), vertex(session, bm, "b2")))
    bmesh.update_edit_mesh(door.data)
    sessions.apply_live(door, session)
    beam = next(b for b in session.edit.vehicle.beams if {b.id1, b.id2} == {"d1l", "b2"})
    assert beam.part == DOOR and '["d1l", "b2"]' in session.edit.text_of(car / "doors.jbeam")
    body, body_session = parts[BODY]
    assert mesh_io.mesh_rev(body) == session.link.rev


def test_parts_of_one_file_imported_on_their_own_take_each_other_s_edits(car):
    path = car / "doors.jbeam"
    objects = {}
    for part in ("car_door_L_stock", "car_door_L_sport"):
        assert bpy.ops.jbs.import_jbeam(filepath=str(path), part_name=part) == {"FINISHED"}
        objects[part] = bpy.context.active_object
    stock, sport = (sessions.session_of(objects[p]) for p in ("car_door_L_stock", "car_door_L_sport"))
    assert stock.group is not sport.group
    assert [c.name for c in objects["car_door_L_sport"].users_collection] == ["doors.jbeam"]
    assert objects["car_door_L_stock"].users_collection[0] == objects["car_door_L_sport"].users_collection[0]
    bpy.context.window_manager.jbs_auto_save = True
    first = stock.link.rev
    edit_all(objects["car_door_L_stock"])
    bm = bmesh.from_edit_mesh(objects["car_door_L_stock"].data)
    vertex(stock, bm, "d1l").co = (0.65, 0.0, 0.5)
    bmesh.update_edit_mesh(objects["car_door_L_stock"].data)
    sessions.apply_live(objects["car_door_L_stock"], stock)
    moved = stock.edit.text_of(path)
    assert '["d1l", 0.650,' in moved and sport.edit.text_of(path) == moved
    assert sport.edit.dirty_files() == [] and not sessions.check_disk(sport)
    assert mesh_io.mesh_rev(objects["car_door_L_sport"]) == sport.link.rev
    bm = bmesh.from_edit_mesh(objects["car_door_L_stock"].data)
    vertex(stock, bm, "d1l").co = (0.6, 0.0, 0.5)
    bmesh.update_edit_mesh(objects["car_door_L_stock"].data)
    mesh_io.set_rev(objects["car_door_L_stock"], first)
    handlers.on_undo_post()
    assert '["d1l", 0.6,' in stock.edit.text_of(path) and sport.edit.text_of(path) == stock.edit.text_of(path)


def test_a_part_made_a_plain_mesh_leaves_the_other_parts_linked(car):
    parts = import_pc(car)
    (body, body_session), (door, _) = parts[BODY], parts[DOOR]
    bpy.context.view_layer.objects.active = door
    assert bpy.ops.jbs.detach() == {"FINISHED"}
    assert sessions.session_of(door) is None and sessions.session_of(body) is body_session
    assert body_session.key in sessions.SESSIONS and DOOR not in body_session.group.views
