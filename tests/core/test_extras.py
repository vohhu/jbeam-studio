import pytest

from jbeam_studio.core.edit import EditError, EditSession
from jbeam_studio.core.edit.mirror import DEFAULT_PAIRS, mirror, mirror_label
from jbeam_studio.core.edit.text import apply_edits, insert_member
from jbeam_studio.core.sjson import parse, to_python


def session_for(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return EditSession.for_pc(car / "base.pc")


def body(session, car):
    return to_python(parse(session.text_of(car / "body.jbeam")))["car_body"]


def extras(session, section):
    return [(e.ids, e.name) for e in session.vehicle.extras if e.section == section]


def test_hydros_and_torsion_bars_get_a_table_of_their_own(car):
    session = session_for(car)
    session.add_extras("car_body", "hydros", [("b1l", "b2")])
    session.add_extras("car_body", "torsionbars", [("b1l", "b1r", "b2", "d1l")])
    assert body(session, car)["hydros"] == [["id1:", "id2:"], ["b1l", "b2"]]
    assert body(session, car)["torsionbars"][1] == ["b1l", "b1r", "b2", "d1l"]
    assert extras(session, "hydros") == [(("b1l", "b2"), None)]
    assert extras(session, "torsionbars") == [(("b1l", "b1r", "b2", "d1l"), None)]
    assert len(session.history) == 2
    session.add_extras("car_body", "hydros", [("b1r", "b2")])
    assert body(session, car)["hydros"][-1] == ["b1r", "b2"]


@pytest.mark.parametrize("row, problem", [(("b1l",), "needs 2"), (("b1l", "b1l"), "more than once"),
                                          (("b1l", "nowhere"), "not found")])
def test_bad_hydros_are_refused(car, row, problem):
    session = session_for(car)
    with pytest.raises(EditError, match=problem):
        session.add_extras("car_body", "hydros", [row])
    assert session.history == []


def test_rails_go_into_a_rails_object_and_slide_nodes_onto_them(car):
    session = session_for(car)
    session.add_rail("car_body", "track", ["b1l", "b2", "b1r"])
    session.add_rail("car_body", "track2", ["b1r", "b2"], looped=True)
    rails = body(session, car)["rails"]
    assert rails == {"track": {"links:": ["b1l", "b2", "b1r"], "broken:": [], "looped": False, "capped": True},
                     "track2": {"links:": ["b1r", "b2"], "broken:": [], "looped": True, "capped": True}}
    assert session.rail_names() == ["track", "track2"]
    session.add_extras("car_body", "slidenodes", [("d1l", "track")])
    assert body(session, car)["slidenodes"] == [
        ["id:", "railName", "attached", "fixToRail", "tolerance", "spring", "strength", "capStrength"],
        ["d1l", "track"]]
    assert extras(session, "slidenodes") == [(("d1l",), "track")]
    with pytest.raises(EditError, match="already exists"):
        session.add_rail("car_body", "track", ["b1l", "b2"])
    with pytest.raises(EditError, match="not found"):
        session.add_extras("car_body", "slidenodes", [("b2", "nowhere")])


def test_deleting_a_rail_takes_its_slide_nodes_with_it(car):
    session = session_for(car)
    session.add_rail("car_body", "track", ["b1l", "b2"])
    session.add_rail("car_body", "other", ["b1r", "b2"])
    session.add_extras("car_body", "slidenodes", [("d1l", "track"), ("e1", "other")])
    [track] = [e for e in session.vehicle.extras if e.name == "track" and e.section == "rails"]
    session.delete_extras([track])
    assert session.rail_names() == ["other"]
    assert extras(session, "slidenodes") == [(("e1",), "other")]
    assert "track" not in session.text_of(car / "body.jbeam")


def test_a_rail_read_before_the_vehicle_was_assembled_again_is_still_deleted(car):
    session = session_for(car)
    session.add_rail("car_body", "track", ["b1l", "b2"])
    [track] = [e for e in session.vehicle.extras if e.section == "rails"]
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path))
    session.delete_extras([track])
    assert session.rail_names() == []


def test_rows_of_hydros_are_deleted(car):
    session = session_for(car)
    session.add_extras("car_body", "hydros", [("b1l", "b2"), ("b1r", "b2")])
    first = next(e for e in session.vehicle.extras if e.ids == ("b1l", "b2"))
    session.delete_extras([first])
    assert extras(session, "hydros") == [(("b1r", "b2"), None)]


def test_a_rails2_table_gets_a_row(car):
    path = car / "body.jbeam"
    text = path.read_text(encoding="utf-8").replace(
        '"triangles":', '"rails2": [["id", "links:", "broken:", "looped", "capped"], ["old", ["b1l", "b1r"], [], false, true]],\n    "triangles":', 1)
    path.write_text(text, encoding="utf-8")
    session = session_for(car)
    assert session.rail_names() == ["old"]
    session.add_rail("car_body", "new", ["b2", "b1l"])
    assert body(session, car)["rails2"][-1] == ["new", ["b2", "b1l"], [], False, True]
    assert sorted(session.rail_names()) == ["new", "old"]
    [old] = [e for e in session.vehicle.extras if e.name == "old"]
    session.delete_extras([old])
    assert session.rail_names() == ["new"]


def test_mirroring_copies_hydros_torsion_bars_rails_and_slide_nodes(car):
    session = session_for(car)
    path = car / "body.jbeam"
    session.add_rail("car_body", "track_l", ["b1l", "b2"])
    session.add_extras("car_body", "slidenodes", [("d1l", "track_l")])
    session.add_extras("car_body", "torsionbars", [("b1l", "b2", "e1", "d1l")])
    session.replace_text(path, session.text_of(path).replace(
        '"rails":', '"hydros": [["id1:", "id2:"], {"inputSource": "steering"}, ["b1l", "b2", {"factor": 0.1}]],\n'
        '    "rails":', 1))
    result = mirror(session, ["b1l", "d1l"])
    assert result.mirrors == {"b1l": "b1r", "d1l": "d1r"}
    assert result.extras == 4
    assert sorted(extras(session, "rails")) == [(("b1l", "b2"), "track_l"), (("b1r", "b2"), "track_r")]
    assert sorted(extras(session, "slidenodes")) == [(("d1l",), "track_l"), (("d1r",), "track_r")]
    assert sorted(extras(session, "torsionbars")) == [(("b1l", "b2", "e1", "d1l"), None), (("b1r", "b2", "e1", "d1r"), None)]
    hydros = {e.ids: e.props for e in session.vehicle.extras if e.section == "hydros"}
    assert hydros[("b1r", "b2")]["factor"] == 0.1 and hydros[("b1r", "b2")]["inputSource"] == "steering"
    text = session.text_of(path)
    assert text.index('["b1l", "b2", {"factor": 0.1}]') < text.index('["b1r", "b2", {"factor": 0.1}]')
    assert len(session.history) == 5
    assert mirror(session, ["b1l", "d1l"]).extras == 0


def test_mirroring_knows_a_torsion_bar_written_in_another_order(car):
    session = session_for(car)
    session.add_nodes("car_body", [(0.3, 0.5, 0.3), (-0.3, 0.5, 0.3)], node_ids=["c1l", "c1r"])
    session.add_extras("car_body", "torsionbars", [("b1l", "b2", "e1", "c1l"), ("c1r", "b2", "e1", "b1r")])
    before = sorted(extras(session, "torsionbars"))
    assert mirror(session, ["b1l", "c1l"]).extras == 0
    assert sorted(extras(session, "torsionbars")) == before


def test_mirroring_skips_a_row_that_would_join_a_node_to_itself(car):
    session = session_for(car)
    session.add_extras("car_body", "hydros", [("b1l", "b1r")])
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path).replace('["b1l", 0.5, 0.0,', '["b1l", 0.002, 0.0,', 1))
    mirror(session, ["b1l"])
    assert extras(session, "hydros") == [(("b1l", "b1r"), None)]


@pytest.mark.parametrize("name, expected", [("boxside_R", "boxside_L"), ("leaf_RL", "leaf_RR"), ("track_l", "track_r"),
                                            ("e3l", "e3r"), ("rail", "rail_mirrored"), ("ant1", "ant1_mirrored")])
def test_the_name_of_a_mirrored_rail_swaps_its_side_letter(name, expected):
    assert mirror_label(name, DEFAULT_PAIRS["x"], set()) == expected


def test_properties_of_hydros_and_rails_are_set_where_the_game_reads_them(car):
    session = session_for(car)
    path = car / "body.jbeam"
    session.add_extras("car_body", "hydros", [("b1l", "b2")])
    session.add_rail("car_body", "track", ["b1l", "b2"])
    [hydro] = [e for e in session.vehicle.extras if e.section == "hydros"]
    session.set_property([hydro], "factor", 0.3)
    assert '["b1l", "b2", {"factor": 0.3}]' in session.text_of(path)
    [rail] = [e for e in session.vehicle.extras if e.section == "rails"]
    session.set_property([rail], "looped", True)
    [rail] = [e for e in session.vehicle.extras if e.section == "rails"]
    session.set_property([rail], "broken:", ["b2"])
    [rail] = [e for e in session.vehicle.extras if e.section == "rails"]
    assert rail.props["looped"] is True and rail.props["broken:"] == ["b2"]
    assert '"looped":true' in session.text_of(path)


def test_new_slide_nodes_copy_the_other_cells_of_a_full_row_of_their_table(car):
    session = session_for(car)
    session.add_rail("car_body", "track", ["b1l", "b2"])
    session.add_extras("car_body", "slidenodes", [("b1r", "track")])
    [short] = [e for e in session.vehicle.extras if e.section == "slidenodes"]
    with pytest.raises(EditError, match="no \"spring\" cell"):
        session.set_property([short], "spring", 1000)
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path).replace(
        '["b1r", "track"]', '["b1r", "track", true, false, 0.01, 50000, "FLT_MAX", "FLT_MAX"]', 1))
    session.add_extras("car_body", "slidenodes", [("d1l", "track")])
    assert body(session, car)["slidenodes"][-1] == ["d1l", "track", True, False, 0.01, 50000, "FLT_MAX", "FLT_MAX"]
    [new] = [e for e in session.vehicle.extras if e.ids == ("d1l",)]
    session.set_property([new], "spring", 1000)
    assert body(session, car)["slidenodes"][-1][5] == 1000


@pytest.mark.parametrize("source, expected", [
    ('{"a": {}}', {"a": 1, "b": 2}),
    ('{"a": {"x": 1}}', {"x": 1, "b": 2}),
    ('{"a": {\n    "x": 1,\n}}', {"x": 1, "b": 2}),
    ('{"a": {\n    "x": 1\n}}', {"x": 1, "b": 2}),
    ('{"a": {\n    "x": 1 // note\n  }}', {"x": 1, "b": 2}),
    ('{"a": {\n    "x": 1}}', {"x": 1, "b": 2}),
])
def test_a_member_is_added_to_any_layout_of_object(source, expected):
    doc = parse(source)
    obj = doc.root.members[0].value
    if not obj.members:
        source = source.replace("{}", '{"a": 1}')
        doc = parse(source)
        obj = doc.root.members[0].value
    text = apply_edits(source, insert_member(doc, obj, "b", "2"))
    result = parse(text)
    assert not result.diagnostics.errors(), text
    assert to_python(result)["a"] == expected
