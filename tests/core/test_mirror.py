import pytest

from jbeam_studio.core.edit import EditError, EditSession
from jbeam_studio.core.edit.mirror import mirror, mirror_name, parse_pairs


def session_for(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return EditSession.for_pc(car / "base.pc")


def links(session):
    return {frozenset((b.id1, b.id2)) for b in session.vehicle.beams}


def test_mirror_names_swap_the_side_after_the_number():
    assert [mirror_name(i) for i in ("e3l", "e3r", "f1ll", "f1rr", "b2", "hl", "tl1")] == \
        ["e3r", "e3l", "f1rr", "f1ll", None, None, None]


def test_mirroring_a_node_adds_its_counterpart_and_beams_in_the_same_part(car):
    session = session_for(car)
    result = mirror(session, ["d1l"])
    vehicle = session.vehicle
    assert result.mirrors == {"d1l": "d1r"} and result.added == ["d1r"] and result.beams == 1
    assert vehicle.nodes["d1r"].pos == pytest.approx((-0.7, 0.0, 0.5))
    assert vehicle.nodes["d1r"].part == "car_door_L_stock"
    assert frozenset(("d1r", "b1r")) in links(session)
    assert len(session.history) == 1


def test_existing_counterpart_is_moved_to_the_mirrored_place(car):
    session = session_for(car)
    z = session.vehicle.nodes["b1r"].pos[2]
    session.move_nodes({"b1r": (-0.6, 0.1, z)})
    result = mirror(session, ["b1l"])
    assert result.moved == ["b1r"] and session.vehicle.nodes["b1r"].pos == pytest.approx((-0.5, 0.0, z))
    assert frozenset(("b1r", "b2")) in links(session)
    assert len(session.vehicle.triangles) == 1


def test_a_node_and_its_counterpart_both_selected_stay(car):
    session = session_for(car)
    result = mirror(session, ["b1l", "b1r", "b2"])
    assert result.moved == [] and result.added == []
    assert frozenset(("b1r", "b2")) in links(session)


def test_mirrored_faces_face_the_other_way(car):
    session = session_for(car)
    session.add_node("car_body", (0.4, 2.0, 0.3), node_id="t1l")
    session.add_triangle("car_body", ("b1l", "t1l", "b2"))
    mirror(session, ["t1l"])
    assert session.vehicle.triangles[-1].ids == ("b1r", "b2", "t1r")


def test_nodes_without_a_side_letter_get_the_next_free_number(car):
    session = session_for(car)
    session.add_node("car_body", (0.4, 2.0, 0.3), node_id="n1")
    assert mirror(session, ["n1"]).added == ["n2"]
    assert session.vehicle.nodes["n2"].pos == pytest.approx((-0.4, 2.0, 0.3))


def test_mirroring_across_y_through_a_plane_off_the_origin(car):
    session = session_for(car)
    session.add_node("car_body", (0.2, -5.7, 0.3), node_id="e3f")
    result = mirror(session, ["e3f"], axis="y", center=-0.7)
    assert result.added == ["e3b"]
    assert session.vehicle.nodes["e3b"].pos == pytest.approx((0.2, 4.3, 0.3))


def test_mirroring_across_z_swaps_top_and_down(car):
    session = session_for(car)
    session.add_nodes("car_body", [(0.0, 1.0, 2.0), (0.0, 2.0, 1.0)], node_ids=["rp3t", "mast"])
    session.add_beams("car_body", [("rp3t", "mast"), ("rp3t", "b2")])
    result = mirror(session, ["rp3t"], axis="z", center=1.0)
    assert result.added == ["rp3d"] and result.beams == 1
    assert session.vehicle.nodes["rp3d"].pos == pytest.approx((0.0, 1.0, 0.0))
    assert frozenset(("rp3d", "mast")) in links(session) and frozenset(("rp3d", "b2")) not in links(session)


def test_pairs_are_read_from_text():
    assert parse_pairs("l:r, ll:rr,bad, x:x") == (("l", "r"), ("ll", "rr"))
    assert mirror_name("a1u", parse_pairs("u:d")) == "a1d"


def test_nothing_selected_is_an_error(car):
    with pytest.raises(EditError):
        mirror(session_for(car), [])
