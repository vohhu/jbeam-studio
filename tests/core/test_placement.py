import pytest

from jbeam_studio.core.edit import EditSession
from jbeam_studio.core.mesh_sync import PLACE_GROUP, PLACE_SOURCE, MeshLink
from jbeam_studio.core.sjson import parse, to_python

ROTOR = """{
"rotor": {
    "information": {"name": "Rotor"},
    "slotType": "main",
    "slots2": [
        ["name", "allowTypes", "denyTypes", "default", "description"],
        ["tail", ["tail"], [], "tail_stock", "Tail"],
    ],
    "nodes": [
        ["id", "posX", "posY", "posZ"],
        {"group": "mast"},
        ["m1", 0.0, 0.0, 1.0],
        ["m2", 0.0, 0.0, 2.0],
        {"group": "blade", "nodeWeight": 2},
        ["b1l", 1.0, 0.0, 2.0],
        ["b1r", -1.0, 0.0, 2.0],
        {"group": ""},
    ],
    "beams": [
        ["id1:", "id2:"],
        {"beamSpring": 1000},
        ["m1", "m2"],
        {"beamSpring": 500},
        ["m2", "b1l"], ["m2", "b1r"],
        {"beamPrecompression": 1, "beamType": "|NORMAL"},
    ],
    "triangles": [
        ["id1:", "id2:", "id3:"],
        {"dragCoef": 5},
        ["m2", "b1l", "b1r"],
    ],
},
}"""

TAIL = """{
"tail_stock": {
    "information": {"name": "Tail"},
    "slotType": "tail",
    "nodes": [["id", "posX", "posY", "posZ"], ["t1", 0.0, 3.0, 1.0]],
    "triangles": [["id1:", "id2:", "id3:"], ["t1", "m1", "m2"]],
},
}"""


@pytest.fixture
def rotor(tmp_path):
    folder = tmp_path / "vehicles" / "heli"
    folder.mkdir(parents=True)
    (folder / "rotor.jbeam").write_text(ROTOR, encoding="utf-8")
    (folder / "tail.jbeam").write_text(TAIL, encoding="utf-8")
    (folder / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return folder


def link_for(folder):
    return MeshLink(EditSession.for_pc(folder / "base.pc"))


def section(link, folder, name):
    return to_python(parse(link.session.text_of(folder / "rotor.jbeam")))["rotor"][name]


def vertex(link, data, node_id):
    return data.node_uids.index(link.map.nodes[node_id])


def extrude(link, data, node_id, position):
    source = vertex(link, data, node_id)
    data.positions.append(position)
    data.node_uids.append(data.node_uids[source])
    data.node_checks.append(data.node_checks[source])
    new = len(data.positions) - 1
    data.edges.append((source, new))
    data.edge_uids.append(0)
    return new


def test_next_to_the_source_inherits_the_modifiers_of_the_source(rotor):
    link = link_for(rotor)
    data = link.build()
    new = extrude(link, data, "b1l", (2.0, 0.0, 2.0))
    new_id = link.apply(link.plan(data), "rotor", auto_names=True, placement=PLACE_SOURCE)[new]
    nodes = section(link, rotor, "nodes")
    assert [row[0] for row in nodes if isinstance(row, list)][1:] == ["m1", "m2", "b1l", new_id, "b1r"]
    vehicle = link.session.vehicle
    assert vehicle.nodes[new_id].props["group"] == "blade" and vehicle.nodes[new_id].props["nodeWeight"] == 2
    beam = next(b for b in vehicle.beams if {b.id1, b.id2} == {"b1l", new_id})
    assert beam.props["beamSpring"] == 500
    assert '["m2", "b1l"], ["b1l", "' + new_id + '"], ["m2", "b1r"]' in link.session.text_of(rotor / "rotor.jbeam")


def test_at_the_end_new_rows_follow_the_resets(rotor):
    link = link_for(rotor)
    data = link.build()
    new = extrude(link, data, "b1l", (2.0, 0.0, 2.0))
    new_id = link.apply(link.plan(data), "rotor", auto_names=True)[new]
    assert section(link, rotor, "nodes")[-1][0] == new_id
    assert link.session.vehicle.nodes[new_id].props.get("group") == ""


def test_into_a_group_goes_to_the_end_of_its_block(rotor):
    link = link_for(rotor)
    data = link.build()
    data.positions.append((0.0, 0.0, 3.0))
    data.node_uids.append(0)
    data.node_checks.append(0)
    new_id = link.apply(link.plan(data), "rotor", placement=PLACE_GROUP, group="mast")[len(data.positions) - 1]
    nodes = [row[0] for row in section(link, rotor, "nodes") if isinstance(row, list)][1:]
    assert nodes == ["m1", "m2", new_id, "b1l", "b1r"]
    assert link.session.vehicle.nodes[new_id].props["group"] == "mast"


def test_a_group_the_part_does_not_have_gets_its_own_block(rotor):
    link = link_for(rotor)
    data = link.build()
    data.positions.append((0.0, 0.0, 3.0))
    data.node_uids.append(0)
    data.node_checks.append(0)
    new_id = link.apply(link.plan(data), "rotor", placement=PLACE_GROUP, group="skid")[len(data.positions) - 1]
    assert section(link, rotor, "nodes")[-3:] == [{"group": "skid"}, [new_id, 0.0, 0.0, 3.0], {"group": ""}]
    assert link.session.vehicle.nodes[new_id].props["group"] == "skid"
    assert link.session.vehicle.nodes["t1"].props.get("group") == ""


def test_a_copied_beam_goes_right_after_its_original(rotor):
    link = link_for(rotor)
    data = link.build()
    m1, m2 = vertex(link, data, "m1"), vertex(link, data, "m2")
    edge = next(i for i, e in enumerate(data.edges) if set(e) == {m1, m2})
    data.positions += [(0.5, 0.0, 1.0), (0.5, 0.0, 2.0)]
    data.node_uids += [0, 0]
    data.node_checks += [0, 0]
    data.edges.append((len(data.positions) - 2, len(data.positions) - 1))
    data.edge_uids.append(data.edge_uids[edge])
    link.apply(link.plan(data), "rotor", placement=PLACE_SOURCE)
    beams = [row for row in section(link, rotor, "beams") if isinstance(row, list)]
    assert beams[1] == ["m1", "m2"] and beams[2] == ["n1", "n2"]
    copied = next(b for b in link.session.vehicle.beams if {b.id1, b.id2} == {"n1", "n2"})
    assert copied.props["beamSpring"] == 1000


def test_leaked_modifiers_are_reported_and_add_resets_fixes_them(rotor):
    link = link_for(rotor)
    session = link.session
    found = [d for d in session.vehicle.diagnostics if "Add Resets" in d.message]
    assert len(found) == 1 and 'part "rotor" leaves dragCoef = 5' in found[0].message and '"tail_stock"' in found[0].message
    assert session.add_resets("rotor") == {"triangles": ["dragCoef"]}
    assert section(link, rotor, "triangles")[-1] == {"dragCoef": 100}
    assert '    {"dragCoef":100},' in session.text_of(rotor / "rotor.jbeam")
    assert not [d for d in session.vehicle.diagnostics if "Add Resets" in d.message]
    assert session.add_resets("rotor") == {}


def test_node_groups_and_group_rename(rotor):
    session = EditSession.for_pc(rotor / "base.pc")
    flex = '"flexbodies": [["mesh", "[group]:", "nonFlexMaterials"], ["blades", ["blade", "mast"], []]],\n    "nodes"'
    session.replace_text(rotor / "rotor.jbeam", session.text_of(rotor / "rotor.jbeam").replace('"nodes"', flex, 1))
    assert session.node_groups("rotor") == {"mast": ["m1", "m2"], "blade": ["b1l", "b1r"]}
    assert session.rename_group("blade", "rotor_blade") == 2
    assert session.node_groups("rotor")["rotor_blade"] == ["b1l", "b1r"]
    assert '["blades", ["rotor_blade", "mast"], []]' in session.text_of(rotor / "rotor.jbeam")


def test_placement_survives_moves_in_the_same_change(rotor):
    link = link_for(rotor)
    data = link.build()
    data.positions[vertex(link, data, "m1")] = (0.0, 0.0, 1.5)
    new = extrude(link, data, "b1r", (-2.0, 0.0, 2.0))
    new_id = link.apply(link.plan(data), "rotor", auto_names=True, placement=PLACE_SOURCE)[new]
    nodes = [row[0] for row in section(link, rotor, "nodes") if isinstance(row, list)][1:]
    assert nodes == ["m1", "m2", "b1l", "b1r", new_id]
    assert link.session.vehicle.nodes["m1"].pos == pytest.approx((0.0, 0.0, 1.5))
