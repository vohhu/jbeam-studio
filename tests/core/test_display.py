from jbeam_studio.core.display import category, find_problems
from jbeam_studio.core.edit import EditSession

PART = """{
"p": {
    "information": {"name": "P"},
    "slotType": "main",
    "nodes": [["id", "posX", "posY", "posZ"], {"group": ["frame", "body"]}, ["a", 0, 0, 0], ["b", 1, 0, 0],
              {"group": ""}, ["c", 0, 1, 0], ["d", 2, 0, 0]],
    "beams": [["id1:", "id2:"], {"breakGroup": "door"}, ["a", "b"], ["b", "a"], {"breakGroup": ""},
              ["b", "c"], ["c", "far"], {"optional": true}, ["a", "gone"]],
    "triangles": [["id1:", "id2:", "id3:"], ["a", "b", "c"], ["a", "b", "d"]],
},
}"""


def vehicle_of(tmp_path):
    folder = tmp_path / "vehicles" / "p"
    folder.mkdir(parents=True)
    (folder / "p.jbeam").write_text(PART, encoding="utf-8")
    return EditSession.for_part(folder / "p.jbeam", "p").vehicle


def test_entries_are_coloured_by_their_part_or_the_first_name_of_a_group_key(tmp_path):
    vehicle = vehicle_of(tmp_path)
    assert category(vehicle.nodes["a"], "GROUP") == "frame" and category(vehicle.nodes["c"], "GROUP") is None
    assert category(vehicle.nodes["a"], "PART") == "p"
    assert [category(b, "BREAK_GROUP") for b in vehicle.beams[:3]] == ["door", "door", None]


def test_problems_are_repeated_beams_flat_faces_and_nodes_whose_beams_lead_nowhere(tmp_path):
    vehicle = vehicle_of(tmp_path)
    problems = find_problems(vehicle)
    assert problems.beams == {0, 1}
    assert problems.faces == [("a", "b", "d")]
    assert problems.nodes == {"c"}


def test_a_vehicle_marks_the_nodes_of_rows_the_game_discards_for_their_missing_nodes(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    vehicle = EditSession.for_pc(car / "base.pc").vehicle
    assert [row.get("id2:") for _, row in vehicle.dropped] == ["ghost"]
    assert find_problems(vehicle).nodes == {"b1r"}
