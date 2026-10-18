import copy

from jbeam_studio.core.edit import EditSession
from jbeam_studio.core.mesh_sync import MeshLink

BODY, DOOR = "car_body", "car_door_L_stock"


def link_for(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return MeshLink(EditSession.for_pc(car / "base.pc"))


def ids(link, data):
    return [link.map.ids[uid] for uid in data.node_uids]


def index_of(link, data, node_id):
    return data.node_uids.index(link.map.nodes[node_id])


def test_a_part_shows_its_nodes_beams_and_faces_with_the_nodes_of_other_parts_they_use(car):
    link = link_for(car)
    door = link.build(DOOR)
    assert ids(link, door) == ["b1l", "d1l"]
    assert door.ghosts == [True, False]
    assert len(door.edges) == 1 and door.faces == []
    body = link.build(BODY)
    assert sorted(ids(link, body)) == ["b1l", "b1r", "b2"] and not any(body.ghosts)
    assert len(body.edges) == 2 and len(body.faces) == 1
    everything = link.build(DOOR, all_nodes=True)
    assert sorted(ids(link, everything)) == ["b1l", "b1r", "b2", "d1l", "e1"]
    assert sum(not g for g in everything.ghosts) == 1 and len(everything.edges) == 1


def test_a_part_moves_only_its_own_nodes(car):
    link = link_for(car)
    door = link.build(DOOR)
    door.positions[index_of(link, door, "d1l")] = (0.9, 0.0, 0.5)
    door.positions[index_of(link, door, "b1l")] = (0.0, 0.0, 0.0)
    plan = link.plan(door, DOOR)
    assert list(plan.moves) == ["d1l"] and plan.ghosts_moved == 1 and plan.needs_rebuild
    assert link.plan(link.build(BODY), BODY).empty
    assert link.plan(link.build(DOOR, all_nodes=True), DOOR).empty


def test_nodes_and_beams_of_other_parts_are_not_deleted_by_leaving_them_out(car):
    link = link_for(car)
    plan = link.plan(link.build(BODY), BODY)
    assert not plan.deleted_nodes and not plan.deleted_beams
    door = link.build(DOOR)
    ghost = index_of(link, door, "b1l")
    door.positions.pop(ghost), door.node_uids.pop(ghost), door.node_checks.pop(ghost), door.ghosts.pop(ghost)
    door.parts.pop(ghost)
    door.edges, door.edge_uids = [], []
    plan = link.plan(door, DOOR)
    assert not plan.deleted_beams and not plan.deleted_nodes and plan.ghosts_deleted == 1


def test_deleting_a_beam_of_a_part_deletes_only_that_part_s_row(car):
    link = link_for(car)
    path = car / "body.jbeam"
    link.session.replace_text(path, link.session.text_of(path).replace(
        '["b1r", "ghost"]]', '["b1r", "ghost"], ["b1l", "d1l"]]', 1))
    link.changed()
    door = link.build(DOOR)
    door.edges, door.edge_uids = [], []
    plan = link.plan(door, DOOR)
    assert len(plan.deleted_beams) == 1
    link.apply(plan, DOOR)
    beams = [(b.id1, b.id2, b.part) for b in link.session.vehicle.beams]
    assert ("b1l", "d1l", BODY) in beams and ("d1l", "b1l", DOOR) not in beams


def test_new_nodes_and_beams_of_a_part_go_to_that_part_even_from_a_node_of_another_part(car):
    link = link_for(car)
    door = link.build(DOOR)
    ghost = index_of(link, door, "b1l")
    door.positions.append((0.5, 0.4, 0.3))
    door.node_uids.append(door.node_uids[ghost])
    door.node_checks.append(door.node_checks[ghost])
    door.ghosts.append(True)
    door.parts.append(-1)
    door.edges.append((ghost, len(door.positions) - 1))
    door.edge_uids.append(0)
    plan = link.plan(door, DOOR)
    assert list(plan.new_nodes) == [2] and plan.new_sources[2] == "b1l"
    new_ids = link.apply(plan, BODY)
    node = link.session.vehicle.nodes[new_ids[2]]
    assert node.part == DOOR
    assert any(b.part == DOOR and {b.id1, b.id2} == {"b1l", new_ids[2]} for b in link.session.vehicle.beams)


def test_a_ghost_whose_node_is_gone_does_not_come_back_as_a_new_node(car):
    link = link_for(car)
    door = link.build(DOOR)
    link.session.delete_nodes(["b1l"], cascade=True)
    link.changed()
    door = copy.deepcopy(door)
    plan = link.plan(door, DOOR)
    assert not plan.new_nodes and not plan.new_beams and plan.needs_rebuild
