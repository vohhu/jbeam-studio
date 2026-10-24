import copy
import struct

import pytest

from jbeam_studio.core.edit import EditError, EditSession
from jbeam_studio.core.mesh_sync import MeshLink, name_like, uid_check


def link_for(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return MeshLink(EditSession.for_pc(car / "base.pc"))


def vertex_of(link, data, node_id):
    return data.node_uids.index(link.map.nodes[node_id])


def without_vertex(data, index):
    """The mesh with one vertex and everything that uses it deleted, as Blender's Delete Vertices does."""
    data = copy.deepcopy(data)
    shift = lambda v: v - (v > index)  # noqa: E731
    for name in ("positions", "node_uids", "node_checks", "ghosts", "parts"):
        values = getattr(data, name)
        if values:
            del values[index]
    kept = [i for i, edge in enumerate(data.edges) if index not in edge]
    data.edges = [tuple(map(shift, data.edges[i])) for i in kept]
    data.edge_uids = [data.edge_uids[i] for i in kept]
    kept = [i for i, face in enumerate(data.faces) if index not in face]
    data.faces = [tuple(map(shift, data.faces[i])) for i in kept]
    data.face_uids = [data.face_uids[i] for i in kept]
    return data


def add_vertex(data, position, uid=0, check=0):
    data.positions.append(position)
    data.node_uids.append(uid)
    data.node_checks.append(check)
    return len(data.positions) - 1


def test_build_has_a_vertex_per_node_and_an_edge_per_beam(car):
    link = link_for(car)
    data = link.build()
    vehicle = link.session.vehicle
    assert len(data.positions) == len(vehicle.nodes)
    assert len(data.edges) == len(vehicle.beams)
    assert len(data.faces) == len(vehicle.triangles) == 1
    assert all(check == uid_check(uid) for uid, check in zip(data.node_uids, data.node_checks))
    assert {link.part_names[p] for p in data.parts} == set(vehicle.parts)


def test_unchanged_mesh_gives_an_empty_plan(car):
    link = link_for(car)
    plan = link.plan(link.build())
    assert plan.empty and not plan.needs_rebuild


def test_moved_vertex_moves_the_node(car):
    link = link_for(car)
    data = link.build()
    data.positions[vertex_of(link, data, "b2")] = (0.1, 1.0, 0.3)
    plan = link.plan(data)
    assert plan.moves == {"b2": pytest.approx((0.1, 1.0, 0.3))}
    link.apply(plan, "car_body")
    assert link.session.vehicle.nodes["b2"].pos == pytest.approx((0.1, 1.0, 0.3))
    assert link.plan(link.build()).empty


def test_axes_that_did_not_move_keep_their_exact_values(car):
    link = link_for(car)
    data = link.build()
    as_float32 = lambda x: struct.unpack("f", struct.pack("f", x))[0]  # noqa: E731
    data.positions[vertex_of(link, data, "b2")] = tuple(map(as_float32, (0.1, 1.0, 0.3)))
    plan = link.plan(data)
    assert plan.moves["b2"][1:] == (1.0, 0.3)
    link.apply(plan, "car_body")
    assert '["b2", 0.100, 1.0, 0.3]' in link.session.text_of(car / "body.jbeam")


def test_deleted_vertex_deletes_the_node_and_its_beams(car):
    link = link_for(car)
    data = without_vertex(link.build(), vertex_of(link, link.build(), "b2"))
    plan = link.plan(data)
    assert plan.deleted_nodes == ["b2"]
    link.apply(plan, "car_body")
    vehicle = link.session.vehicle
    assert "b2" not in vehicle.nodes
    assert not [b for b in vehicle.beams if "b2" in (b.id1, b.id2)] and not vehicle.triangles


def test_deleted_vertex_keeps_beams_when_keep_dependents(car):
    link = link_for(car)
    data = without_vertex(link.build(), vertex_of(link, link.build(), "b2"))
    plan = link.plan(data)
    assert plan.deleted_nodes == ["b2"]
    link.apply(plan, "car_body", keep_dependents=True)
    assert '["b2"' not in link.session.text_of(car / "body.jbeam")
    assert '["b1l", "b2"]' in link.session.text_of(car / "body.jbeam")
    assert '["b1l", "b1r", "b2"]' in link.session.text_of(car / "body.jbeam")
    assert any("b2" in d.message for d in link.session.vehicle.diagnostics)


def test_new_vertex_and_edge_become_a_node_and_a_beam(car):
    link = link_for(car)
    data = link.build()
    new = add_vertex(data, (0.0, 2.0, 0.3))
    data.edges.append((vertex_of(link, data, "b2"), new))
    data.edge_uids.append(0)
    new_ids = link.apply(link.plan(data), "car_body", prefix="nb")
    assert new_ids == {new: "nb1"}
    vehicle = link.session.vehicle
    assert vehicle.nodes["nb1"].part == "car_body"
    assert any({b.id1, b.id2} == {"b2", "nb1"} for b in vehicle.beams)
    assert len(link.session.history) == 1


def test_new_face_becomes_a_triangle_and_its_new_edges_beams(car):
    link = link_for(car)
    data = link.build()
    b2, e1, d1l = (vertex_of(link, data, i) for i in ("b2", "e1", "d1l"))
    data.faces.append((b2, e1, d1l))
    data.face_uids.append(0)
    data.edges += [(b2, e1), (e1, d1l), (d1l, b2)]
    data.edge_uids += [0, 0, 0]
    plan = link.plan(data)
    assert plan.new_faces == [("b2", "e1", "d1l")] and len(plan.new_beams) == 3
    link.apply(plan, "car_body")
    assert link.session.vehicle.triangles[-1].ids == ("b2", "e1", "d1l")


def test_face_edges_without_beams_stay_without_beams(car):
    link = link_for(car)
    data = link.build()
    data.edges.append(data.faces[0][1:])
    data.edge_uids.append(-2)
    assert link.plan(data).empty


def test_ngon_is_dropped(car):
    link = link_for(car)
    data = link.build()
    data.faces.append(tuple(vertex_of(link, data, i) for i in ("b1l", "b1r", "b2", "e1", "d1l")))
    data.face_uids.append(0)
    plan = link.plan(data)
    assert plan.ngons == 1 and plan.needs_rebuild and not plan.new_faces


def test_duplicated_vertex_becomes_a_new_node(car):
    link = link_for(car)
    data = link.build()
    index = vertex_of(link, data, "b2")
    copy_index = add_vertex(data, (0.0, 1.5, 0.3), data.node_uids[index], data.node_checks[index])
    plan = link.plan(data)
    assert plan.vertex_nodes[index] == "b2" and list(plan.new_nodes) == [copy_index] and not plan.moves


def test_blended_uid_is_not_taken_for_another_node(car):
    link = link_for(car)
    data = link.build()
    uids = sorted(data.node_uids)
    blended = (uids[0] + uids[2]) // 2
    assert blended in data.node_uids
    new = add_vertex(data, (0.0, 0.5, 0.3), blended, (uid_check(uids[0]) + uid_check(uids[2])) // 2)
    plan = link.plan(data)
    assert list(plan.new_nodes) == [new] and not plan.moves


def test_reversed_face_flips_the_triangle(car):
    link = link_for(car)
    data = link.build()
    a, b, c = data.faces[0]
    data.faces[0] = (a, c, b)
    plan = link.plan(data)
    assert plan.flipped_faces == [data.face_uids[0]]
    before = link.session.vehicle.triangles[0].ids
    link.apply(plan, "car_body")
    assert link.session.vehicle.triangles[0].ids == (before[0], before[2], before[1])
    assert link.plan(link.build()).empty


def test_recreated_edge_keeps_its_beam(car):
    link = link_for(car)
    data = link.build()
    data.edge_uids[0] = 0
    assert link.plan(data).empty


def test_goto_returns_to_a_state_with_the_same_uids(car):
    link = link_for(car)
    first_rev, first = link.rev, link.build()
    data = copy.deepcopy(first)
    data.positions[vertex_of(link, data, "b2")] = (0.1, 1.0, 0.3)
    link.apply(link.plan(data), "car_body")
    assert link.rev != first_rev
    assert link.goto(first_rev) and link.session.position == 0
    assert link.plan(first).empty
    assert link.build().node_uids == first.node_uids


def test_reaching_the_same_texts_again_gives_the_same_state_and_uids(car):
    link = link_for(car)
    base_rev, base = link.rev, link.build()
    edited = copy.deepcopy(base)
    new = add_vertex(edited, (0.0, 2.0, 0.3))
    edited.edges.append((vertex_of(link, edited, "b2"), new))
    edited.edge_uids.append(0)
    link.apply(link.plan(edited), "car_body")
    first_rev, first = link.rev, link.build()
    assert link.goto(base_rev) and link.plan(base).empty
    link.apply(link.plan(edited), "car_body")
    assert link.rev == first_rev
    assert link.build().node_uids == first.node_uids and link.build().edge_uids == first.edge_uids


def test_states_the_history_lost_can_be_reached_again(car):
    link = link_for(car)
    base_rev, base = link.rev, link.build()
    moved = copy.deepcopy(base)
    moved.positions[vertex_of(link, moved, "b2")] = (0.1, 1.0, 0.3)
    link.apply(link.plan(moved), "car_body")
    moved_rev, uid = link.rev, link.map.nodes["b2"]
    link.session.rename_node("b2", "b9")
    link.changed(renames={"b9": "b2"})
    renamed_rev = link.rev
    assert link.goto(base_rev)
    link.apply(link.plan(moved), "car_body")
    assert link.rev == moved_rev and link.position_of(renamed_rev) is None
    assert link.goto(renamed_rev) and link.rev == renamed_rev
    assert "b9" in link.session.vehicle.nodes and link.map.nodes["b9"] == uid
    assert link.goto(base_rev) and link.session.vehicle.nodes["b2"].pos == pytest.approx((0.0, 1.0, 0.3))


def test_saving_keeps_the_state_number(car):
    link = link_for(car)
    data = link.build()
    data.positions[vertex_of(link, data, "b2")] = (0.1, 1.0, 0.3)
    link.apply(link.plan(data), "car_body")
    rev = link.rev
    link.session.save()
    assert link.rev == rev and link.position_of(rev) == 1


def test_going_back_reuses_the_assembled_vehicle(car):
    link = link_for(car)
    base_rev = link.rev
    data = link.build()
    data.positions[vertex_of(link, data, "b2")] = (0.1, 1.0, 0.3)
    link.apply(link.plan(data), "car_body")
    calls = []
    assemble = link.session._assemble_with
    link.session._assemble_with = lambda texts, closed: calls.append(1) or assemble(texts, closed)
    assert link.goto(base_rev) and calls == []
    assert link.session.vehicle.nodes["b2"].pos == pytest.approx((0.0, 1.0, 0.3))


def test_name_like_follows_the_naming_scheme_and_the_side():
    taken = {"e1l", "e1r", "e2l", "e2r", "e3l", "e3r", "e4l", "e4r", "em", "rp1t", "rp3t", "f1ll", "f1rr"}
    assert name_like("e3l", (5.0, 0, 0), taken) == "e5l"
    assert name_like("e3l", (-5.0, 0, 0), taken) == "e5r"
    assert name_like("e3l", (0.0, 0, 0), taken) == "e5"
    assert name_like("rp3t", (1.0, 0, 0), taken) == "rp4t"
    assert name_like("em", (1.0, 0, 0), taken) == "em1"
    assert name_like("f1ll", (-1.0, 0, 0), taken) == "f2rr"


def test_new_nodes_are_named_after_the_nodes_they_came_from(car):
    link = link_for(car)
    data = link.build()
    b2, b1l = vertex_of(link, data, "b2"), vertex_of(link, data, "b1l")
    copied = add_vertex(data, (0.3, 1.5, 0.3), data.node_uids[b2], data.node_checks[b2])
    joined = add_vertex(data, (-0.6, 0.0, 0.3))
    chained = add_vertex(data, (0.0, 2.5, 0.3))
    alone = add_vertex(data, (0.0, 9.0, 9.0))
    data.edges += [(b1l, joined), (copied, chained)]
    data.edge_uids += [0, 0]
    new_ids = link.apply(link.plan(data), "car_body", auto_names=True)
    assert new_ids == {copied: "b3", joined: "b4r", chained: "b5", alone: "n1"}
    assert link.plan(link.build()).empty


def test_new_entries_go_to_the_part_of_the_nodes_they_come_from(car):
    link = link_for(car)
    data = link.build()
    d1l, b2 = vertex_of(link, data, "d1l"), vertex_of(link, data, "b2")
    door_copy = add_vertex(data, (0.8, 0.0, 0.5), data.node_uids[d1l], data.node_checks[d1l])
    data.edges.append((door_copy, b2))
    data.edge_uids.append(0)
    new_ids = link.apply(link.plan(data), "car_body", auto_names=True)
    vehicle = link.session.vehicle
    assert vehicle.nodes[new_ids[door_copy]].part == "car_door_L_stock"
    beam = next(b for b in vehicle.beams if {b.id1, b.id2} == {new_ids[door_copy], "b2"})
    assert beam.part == "car_door_L_stock"


def test_rename_keeps_the_uid_of_the_node(car):
    link = link_for(car)
    uid = link.map.nodes["b2"]
    link.session.rename_node("b2", "b9")
    link.changed(renames={"b9": "b2"})
    assert link.map.nodes["b9"] == uid
    assert link.plan(link.build()).empty


def test_states_cut_from_the_history_are_restored_from_their_texts(car):
    link = link_for(car)
    data = link.build()
    data.positions[vertex_of(link, data, "b2")] = (0.1, 1.0, 0.3)
    link.apply(link.plan(data), "car_body")
    moved_rev = link.rev
    link.session.undo()
    link.changed()
    data = link.build()
    data.positions[vertex_of(link, data, "b2")] = (0.2, 1.0, 0.3)
    link.apply(link.plan(data), "car_body")
    assert link.position_of(moved_rev) is None
    assert link.goto(moved_rev) and link.session.vehicle.nodes["b2"].pos == pytest.approx((0.1, 1.0, 0.3))


def test_unknown_states_are_not_reached(car):
    link = link_for(car)
    assert not link.goto(12345)


def test_reset_starts_a_new_base_state(car):
    link = link_for(car)
    base = link.rev
    link.reload_file(car / "body.jbeam")
    assert link.rev != base and link.position_of(base) is None


def test_additions_need_a_part(car):
    link = link_for(car)
    data = link.build()
    add_vertex(data, (0.0, 2.0, 0.3))
    with pytest.raises(EditError):
        link.apply(link.plan(data), None)
    assert link.session.history == []


def test_failed_plan_changes_nothing(car):
    link = link_for(car)
    data = link.build()
    data.positions[vertex_of(link, data, "b2")] = (0.1, 1.0, 0.3)
    add_vertex(data, (0.0, 2.0, 0.3))
    rev = link.rev
    with pytest.raises(EditError):
        link.apply(link.plan(data), "no_such_part")
    assert link.rev == rev and link.session.vehicle.nodes["b2"].pos == pytest.approx((0.0, 1.0, 0.3))


def test_part_import_shows_other_parts_nodes_as_ghosts(car):
    link = MeshLink(EditSession.for_part(car / "doors.jbeam", "car_door_L_stock"))
    data = link.build()
    assert data.ghosts.count(True) == 1 and data.parts[data.ghosts.index(True)] == -1
    ghost = data.ghosts.index(True)
    moved = copy.deepcopy(data)
    moved.positions[ghost] = (5.0, 5.0, 5.0)
    plan = link.plan(moved)
    assert plan.empty and plan.ghosts_moved == 1 and plan.needs_rebuild
    deleted = link.plan(without_vertex(data, ghost))
    assert deleted.empty and deleted.ghosts_deleted == 1
