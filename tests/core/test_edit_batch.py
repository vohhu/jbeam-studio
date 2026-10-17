import pytest

from jbeam_studio.core.edit import EditError, EditSession
from jbeam_studio.core.sjson import parse, to_python


def session_for(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return EditSession.for_pc(car / "base.pc")


def body(session, car):
    return to_python(parse(session.text_of(car / "body.jbeam")))["car_body"]


def test_add_nodes_adds_every_row_in_one_change(car):
    session = session_for(car)
    ids = session.add_nodes("car_body", [(0.0, 2.0, 0.3), (0.0, 3.0, 0.3)], prefix="x")
    assert ids == ["x1", "x2"]
    assert body(session, car)["nodes"][-2:] == [["x1", 0.0, 2.0, 0.3], ["x2", 0.0, 3.0, 0.3]]
    assert len(session.history) == 1


def test_add_nodes_skips_taken_ids(car):
    session = session_for(car)
    session.add_node("car_body", (0.0, 2.0, 0.3), node_id="n2")
    assert session.add_nodes("car_body", [(0, 0, 1), (0, 0, 2)]) == ["n1", "n3"]


def test_add_nodes_rejects_repeated_ids(car):
    session = session_for(car)
    with pytest.raises(EditError):
        session.add_nodes("car_body", [(0, 0, 1), (0, 0, 2)], node_ids=["z", "z"])


def test_add_nodes_under_an_offset_land_where_placed(car):
    session = session_for(car)
    ids = session.add_nodes("car_door_L_stock", [(0.9, 0.0, 0.5), (1.0, 0.0, 0.5)])
    assert [session.vehicle.nodes[i].pos for i in ids] == [pytest.approx((0.9, 0.0, 0.5)), pytest.approx((1.0, 0.0, 0.5))]


def test_add_beams_and_faces_in_one_change_each(car):
    session = session_for(car)
    session.add_beams("car_body", [("b2", "b1r"), ("b2", "e1")])
    session.add_faces("car_body", [("b1l", "b2", "e1"), ("b1l", "b1r", "b2", "e1")])
    data = body(session, car)
    assert data["beams"][-2:] == [["b2", "b1r"], ["b2", "e1"]]
    assert data["triangles"][-1] == ["b1l", "b2", "e1"]
    assert data["quads"] == [["id1:", "id2:", "id3:", "id4:"], ["b1l", "b1r", "b2", "e1"]]
    assert len(session.history) == 2


def test_rename_nodes_renames_references_in_one_change(car):
    session = session_for(car)
    session.rename_nodes({"b1l": "c1l", "b2": "c2"})
    data = body(session, car)
    assert data["beams"][1:3] == [["c1l", "b1r"], ["c1l", "c2"]]
    assert data["triangles"][1] == ["c1l", "b1r", "c2"]
    assert len(session.history) == 1


def test_rename_nodes_rejects_clashes(car):
    session = session_for(car)
    with pytest.raises(EditError):
        session.rename_nodes({"b1l": "x", "b2": "x"})
    with pytest.raises(EditError):
        session.rename_nodes({"b1l": "b2"})


def test_goto_moves_several_steps_at_once(car):
    session = session_for(car)
    original = session.text_of(car / "body.jbeam")
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    session.add_node("car_body", (0.0, 2.0, 0.3))
    after = session.text_of(car / "body.jbeam")
    session.goto(0)
    assert session.text_of(car / "body.jbeam") == original and session.position == 0
    session.goto(2)
    assert session.text_of(car / "body.jbeam") == after and "n1" in session.vehicle.nodes
    with pytest.raises(EditError):
        session.goto(3)
