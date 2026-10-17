import pytest

from jbeam_studio.core.diagnostics import Severity
from jbeam_studio.core.edit import (
    DependentsError, EditError, EditSession, ExternalChangeError, MoveMode, SharedRowError, TemplateIdError,
)
from jbeam_studio.core.model.files import read_text
from jbeam_studio.core.sjson import parse, to_python


def session_for(car, **kwargs):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return EditSession.for_pc(car / "base.pc", **kwargs)


def part_data(session, car, file, part):
    return to_python(parse(session.text_of(car / file)))[part]


def test_move_node_overwrites_numbers_and_keeps_formatting(car):
    session = session_for(car)
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    assert session.vehicle.nodes["b2"].pos == pytest.approx((0.1, 1.0, 0.3))
    assert '["b2", 0.100, 1.0, 0.3]' in session.text_of(car / "body.jbeam")
    assert session.dirty_files() == [(car / "body.jbeam").absolute()]


def test_move_node_under_slot_offset_writes_the_value_before_the_offset(car):
    session = session_for(car)
    session.move_nodes({"d1l": (0.9, 0.0, 0.5)})
    assert session.vehicle.nodes["d1l"].pos == pytest.approx((0.9, 0.0, 0.5))
    assert part_data(session, car, "doors.jbeam", "car_door_L_stock")["nodes"][1] == ["d1l", 0.8, 0.0, 0.5]


def test_overwrite_mode_replaces_expressions_with_numbers(car):
    session = session_for(car)
    session.move_nodes({"b1l": (0.5, 0.0, 0.4)})
    assert part_data(session, car, "body.jbeam", "car_body")["nodes"][2] == ["b1l", 0.5, 0.0, 0.4]
    assert [d.severity for d in session.notes] == [Severity.INFO]


def test_keep_expressions_mode_shifts_the_expression(car):
    session = session_for(car, move_mode=MoveMode.KEEP_EXPRESSIONS)
    session.move_nodes({"b1l": (0.5, 0.0, 0.4)})
    session.move_nodes({"b1l": (0.5, 0.0, 0.45)})
    row = part_data(session, car, "body.jbeam", "car_body")["nodes"][2]
    assert row == ["b1l", 0.5, 0.0, "$=(0.3 + $ride_height) + 0.150"]
    assert session.vehicle.nodes["b1l"].pos[2] == pytest.approx(0.45)


def test_rename_updates_references_in_all_parts(car):
    session = session_for(car)
    result = session.rename_node("b1l", "body_1l")
    assert len(result.references) == 4
    assert "body_1l" in session.vehicle.nodes and "b1l" not in session.vehicle.nodes
    assert {(b.id1, b.id2) for b in session.vehicle.beams} >= {("body_1l", "b1r"), ("d1l", "body_1l")}
    assert session.vehicle.triangles[0].ids == ("body_1l", "b1r", "b2")


def test_rename_rejects_existing_ids(car):
    with pytest.raises(EditError):
        session_for(car).rename_node("b1l", "b2")


def test_add_node_beam_and_faces(car):
    session = session_for(car)
    node_id = session.add_node("car_door_L_stock", (0.8, 0.2, 0.5))
    assert node_id == "n1"
    assert session.vehicle.nodes["n1"].pos == pytest.approx((0.8, 0.2, 0.5))
    assert session.vehicle.nodes["n1"].part == "car_door_L_stock"
    session.add_beam("car_door_L_stock", "n1", "d1l")
    session.add_triangle("car_door_L_stock", ["n1", "d1l", "b1l"])
    session.add_quad("car_body", ["b1l", "b1r", "b2", "n1"])
    assert ("n1", "d1l") in {(b.id1, b.id2) for b in session.vehicle.beams}
    assert ("n1", "d1l", "b1l") in [f.ids for f in session.vehicle.triangles]
    assert [f.ids for f in session.vehicle.quads] == [("b1l", "b1r", "b2", "n1")]
    door = part_data(session, car, "doors.jbeam", "car_door_L_stock")
    assert door["triangles"] == [["id1:", "id2:", "id3:"], ["n1", "d1l", "b1l"]]


def test_delete_nodes_needs_confirmation_for_dependents(car):
    session = session_for(car)
    with pytest.raises(DependentsError) as raised:
        session.delete_nodes(["b2"])
    assert len(raised.value.dependents) == 2
    session.delete_nodes(["b2"], cascade=True)
    assert "b2" not in session.vehicle.nodes
    assert session.vehicle.triangles == []
    assert ("b1l", "b2") not in {(b.id1, b.id2) for b in session.vehicle.beams}


def test_delete_and_flip_entries(car):
    session = session_for(car)
    session.flip_faces(session.vehicle.triangles)
    assert session.vehicle.triangles[0].ids == ("b1l", "b2", "b1r")
    beam = next(b for b in session.vehicle.beams if (b.id1, b.id2) == ("b1l", "b2"))
    session.delete_entries([beam])
    assert ("b1l", "b2") not in {(b.id1, b.id2) for b in session.vehicle.beams}


def test_set_property_in_column_and_options(car):
    session = session_for(car)
    nodes = [session.vehicle.nodes["b2"], session.vehicle.nodes["d1l"]]
    session.set_property(nodes, "nodeWeight", 12)
    assert session.vehicle.nodes["b2"].props["nodeWeight"] == 12
    assert session.vehicle.nodes["d1l"].props["nodeWeight"] == 12
    session.set_property([session.vehicle.nodes["b2"]], "nodeWeight", 15)
    assert session.vehicle.nodes["b2"].props["nodeWeight"] == 15
    session.set_property([session.vehicle.nodes["b2"]], "posZ", 0.5)
    assert session.vehicle.nodes["b2"].pos[2] == pytest.approx(0.5)


def test_undo_redo_restores_exact_text(car):
    session = session_for(car)
    original = session.text_of(car / "body.jbeam")
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    session.rename_node("b2", "b3")
    session.undo()
    session.undo()
    assert session.text_of(car / "body.jbeam") == original
    assert "b2" in session.vehicle.nodes
    session.redo()
    assert session.vehicle.nodes["b2"].pos[0] == pytest.approx(0.1)
    assert session.can_redo


def test_transaction_is_one_change_and_rolls_back_on_error(car):
    session = session_for(car)
    with session.transaction("two edits"):
        session.move_nodes({"b2": (0.2, 1.0, 0.3)})
        session.add_node("car_body", (0, 0, 0), "x1")
    assert len(session.history) == 1
    with pytest.raises(EditError):
        with session.transaction("broken"):
            session.move_nodes({"b2": (0.4, 1.0, 0.3)})
            session.rename_node("x1", "b1l")
    assert session.vehicle.nodes["b2"].pos[0] == pytest.approx(0.2)
    assert len(session.history) == 1


def test_save_writes_atomically_with_backup(car):
    session = session_for(car)
    original = read_text(car / "body.jbeam")
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    assert session.save() == [(car / "body.jbeam").absolute()]
    assert read_text(car / "body.jbeam") == session.text_of(car / "body.jbeam")
    assert read_text(car / "body.jbeam.bak") == original
    assert session.dirty_files() == []
    session.move_nodes({"b2": (0.2, 1.0, 0.3)})
    session.save()
    assert read_text(car / "body.jbeam.bak") == original


def test_save_detects_external_changes(car):
    session = session_for(car)
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    (car / "body.jbeam").write_text(read_text(car / "body.jbeam") + "\n// edited elsewhere\n", encoding="utf-8")
    with pytest.raises(ExternalChangeError):
        session.save()
    session.save(overwrite_external=True)
    assert "edited elsewhere" not in read_text(car / "body.jbeam")


def test_single_part_session_cannot_move_external_nodes(car):
    session = EditSession.for_part(car / "doors.jbeam", "car_door_L_stock")
    with pytest.raises(EditError):
        session.move_nodes({"b1l": (0, 0, 0)})
    session.add_beam("car_door_L_stock", "d1l", "b1l")
    assert sum(1 for b in session.vehicle.beams if {b.id1, b.id2} == {"d1l", "b1l"}) == 2


MIRRORED = """{
"frame": {"slotType": "main",
    "slots2": [["name", "allowTypes", "denyTypes", "default", "description"],
               ["arm_l", ["arm"], [], "arm", "Left", {"variables": {"$prefix": "l_"}}],
               ["arm_r", ["arm"], [], "arm", "Right", {"variables": {"$prefix": "r_"}}]],
    "nodes": [["id", "posX", "posY", "posZ"], ["f1", 0, 0, 0]]},
"arm": {"slotType": "arm",
    "nodes": [["id", "posX", "posY", "posZ"], ["$.a", 0.5, 0, 0], ["$.b", 0.5, 1, 0]],
    "beams": [["id1:", "id2:"], ["$.a", "$.b"]]}
}"""


def test_rows_of_parts_used_in_several_slots_need_confirmation(tmp_path):
    folder = tmp_path / "vehicles" / "frame"
    folder.mkdir(parents=True)
    (folder / "frame.jbeam").write_text(MIRRORED, encoding="utf-8")
    (folder / "a.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    session = EditSession.for_pc(folder / "a.pc")
    assert {"l_a", "r_a", "l_b", "r_b"} <= set(session.vehicle.nodes)
    with pytest.raises(SharedRowError) as raised:
        session.move_nodes({"l_a": (0.5, 0, 0.2)})
    assert raised.value.users == ["l_a", "r_a"]
    with pytest.raises(TemplateIdError):
        session.rename_node("l_a", "left_a")
    with pytest.raises(SharedRowError):
        session.delete_entries(session.vehicle.beams)
    with pytest.raises(SharedRowError):
        session.add_beam("arm", "l_a", "f1")
    session.move_nodes({"l_a": (0.5, 0, 0.2)}, allow_shared=True)
    assert session.vehicle.nodes["r_a"].pos == pytest.approx((0.5, 0, 0.2))


REDEFINED = """{
"body": {"slotType": "main",
    "slots2": [["name", "allowTypes", "denyTypes", "default", "description"], ["door", ["door"], [], "door", "Door"]],
    "nodes": [["id", "posX", "posY", "posZ"], ["d1", 0, 0, 0], ["b1", 1, 0, 0]],
    "beams": [["id1:", "id2:"], ["d1", "b1"]]},
"door": {"slotType": "door", "nodes": [["id", "posX", "posY", "posZ"], ["d1", 0.1, 0, 0]]}
}"""


def test_nodes_redefined_by_another_part_are_renamed_and_deleted_everywhere(tmp_path):
    folder = tmp_path / "vehicles" / "body"
    folder.mkdir(parents=True)
    (folder / "body.jbeam").write_text(REDEFINED, encoding="utf-8")
    (folder / "a.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    session = EditSession.for_pc(folder / "a.pc")
    assert session.vehicle.nodes["d1"].part == "door"
    session.rename_node("d1", "d9")
    assert "d1" not in session.vehicle.nodes
    assert [(b.id1, b.id2) for b in session.vehicle.beams] == [("d9", "b1")]
    session.delete_nodes(["d9"], cascade=True)
    assert "d9" not in session.vehicle.nodes and session.vehicle.beams == []


def test_replace_text_is_undoable(car):
    session = session_for(car)
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path).replace('"b2"', '"b9"'))
    assert "b9" in session.vehicle.nodes
    session.undo()
    assert "b2" in session.vehicle.nodes
    with pytest.raises(EditError):
        session.replace_text(path, "{ broken")
