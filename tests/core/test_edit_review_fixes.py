"""Regression tests for problems found in the review of the edit session."""

import random

import pytest

from jbeam_studio.core.assembly import assemble_pc
from jbeam_studio.core.edit import EditError, EditSession, ExternalChangeError
from jbeam_studio.core.edit import SharedRowError
from jbeam_studio.core.edit.text import TextEdit, apply_edits, delete_value, outside_target
from jbeam_studio.core.model.files import read_text
from jbeam_studio.core.sjson import parse, to_python


def session_for(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return EditSession.for_pc(car / "base.pc")


def test_undo_after_save_restores_the_saved_over_text(car):
    session = session_for(car)
    original = read_text(car / "body.jbeam")
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    session.save()
    session.undo()
    assert session.vehicle.nodes["b2"].pos[0] == pytest.approx(0.0)
    assert session.text_of(car / "body.jbeam") == original
    assert session.dirty_files() == [(car / "body.jbeam").absolute()]


def test_edits_use_the_text_read_at_load_and_disk_changes_are_detected(car):
    session = session_for(car)
    path = car / "body.jbeam"
    path.write_text("// added outside\n" + read_text(path), encoding="utf-8")
    session.set_property([session.vehicle.nodes["b2"]], "nodeWeight", 99)
    assert session.vehicle.nodes["b2"].props["nodeWeight"] == 99
    assert session.vehicle.nodes["b1r"].pos == pytest.approx((-0.5, 0.0, 0.3))
    assert session.changed_on_disk() == [path.absolute()]
    with pytest.raises(ExternalChangeError):
        session.save()
    session.reload_file(path)
    assert "// added outside" in session.text_of(path)
    assert session.vehicle.nodes["b2"].props["nodeWeight"] == 10


ROTATED = """{
"frame": {"slotType": "main",
    "slots2": [["name", "allowTypes", "denyTypes", "default", "description"],
               ["arm", ["arm"], [], "arm", "Arm", {"nodeRotate": {"x": 0, "y": 0, "z": 45}}]],
    "nodes": [["id", "posX", "posY", "posZ"], ["f1", 0, 0, 0]]},
"arm": {"slotType": "arm", "nodes": [["id", "posX", "posY", "posZ"], ["a1", 0.5, 0.25, 0.1]]}
}"""


def test_moves_of_rotated_nodes_are_accepted(tmp_path):
    folder = tmp_path / "vehicles" / "frame"
    folder.mkdir(parents=True)
    (folder / "frame.jbeam").write_text(ROTATED, encoding="utf-8")
    (folder / "a.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    session = EditSession.for_pc(folder / "a.pc")
    rng = random.Random(1)
    for _ in range(40):
        target = (rng.uniform(0.1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        session.move_nodes({"a1": target})
        assert session.vehicle.nodes["a1"].pos == pytest.approx(target, abs=1e-3)


def test_deleting_a_row_keeps_a_neighbour_between_comments():
    text = '{"p": {"nodes": [\n  ["id"],\n  ["n1"], /* a */ ["n2"] /* b */\n]}}'
    doc = parse(text)
    table = doc.root.members[0].value.members[0].value
    new = apply_edits(text, [delete_value(doc, table.items[1])])
    assert to_python(parse(new))["p"]["nodes"] == [["id"], ["n2"]]


def test_overlay_mods_see_every_common_folder(tmp_path):
    stock = tmp_path / "game" / "vehicles"
    (stock / "car").mkdir(parents=True)
    (stock / "common").mkdir()
    (stock / "car" / "car.jbeam").write_text(
        '{"car": {"slotType": "main", "slots2": [["name", "allowTypes", "denyTypes", "default", "description"], '
        '["wheel", ["wheel"], [], "stock_wheel", "Wheel"]], "nodes": [["id", "posX", "posY", "posZ"], ["c1", 0, 0, 0]]}}',
        encoding="utf-8")
    (stock / "common" / "wheel.jbeam").write_text(
        '{"stock_wheel": {"slotType": "wheel", "nodes": [["id", "posX", "posY", "posZ"], ["w1", 1, 0, 0]]}}',
        encoding="utf-8")
    mod = tmp_path / "mod" / "vehicles"
    (mod / "car").mkdir(parents=True)
    (mod / "common").mkdir()
    (mod / "common" / "extra.jbeam").write_text('{"mod_thing": {"slotType": "thing"}}', encoding="utf-8")
    (mod / "car" / "a.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    vehicle = assemble_pc(mod / "car" / "a.pc", vehicle_roots=[stock])
    assert {"c1", "w1"} <= set(vehicle.nodes)
    assert not vehicle.diagnostics.has_errors()


def test_edits_may_not_reach_beyond_their_target():
    text = '[\n  ["n1"],  // one\n  ["n2"]\n]'
    row = (text.index('["n1"]'), text.index('["n1"]') + 6)
    line_start, next_line = text.index("  [\"n1\"]"), text.index("  [\"n2\"]")
    assert outside_target(text, TextEdit(line_start, next_line, "", row)) is None
    assert outside_target(text, TextEdit(line_start, len(text) - 1, "", row)) is not None
    assert outside_target(text, TextEdit(row[0] + 1, row[0] + 3, "x", row)) is None
    assert outside_target(text, TextEdit(0, 0, "x", row)) is not None
    assert outside_target(text, TextEdit(0, 1, "x")) is not None


SLOT_VARIABLE = """{
"post": {"slotType": "main",
    "slots2": [["name", "allowTypes", "denyTypes", "default", "description"],
               ["bulb", ["bulb"], [], "bulb", "Bulb", {"variables": {"$nodeRef": "lamp", "$group": "lamp"}}]],
    "nodes": [["id", "posX", "posY", "posZ"], ["lamp", 0, 0, 3], ["base", 0, 0, 0]]},
"bulb": {"slotType": "bulb", "props": [["func", "mesh", "idRef:"], ["$electric", "SPOTLIGHT", "$nodeRef"]],
         "flexbodies": [["mesh", "[group]:"], ["bulb_mesh", ["$group"]]]}
}"""


def test_rename_follows_node_ids_handed_over_by_slot_variables(tmp_path):
    folder = tmp_path / "vehicles" / "post"
    folder.mkdir(parents=True)
    (folder / "post.jbeam").write_text(SLOT_VARIABLE, encoding="utf-8")
    (folder / "a.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    session = EditSession.for_pc(folder / "a.pc")
    assert len(session.vehicle.data["props"]) == 1
    result = session.rename_node("lamp", "lamp_top")
    assert len(session.vehicle.data["props"]) == 1
    assert '{"$nodeRef": "lamp_top", "$group": "lamp"}' in session.text_of(folder / "post.jbeam")
    assert [m.kind for m in result.other_matches] == ["text"]


def test_allow_shared_keeps_the_model_checks(tmp_path):
    folder = tmp_path / "vehicles" / "frame"
    folder.mkdir(parents=True)
    (folder / "frame.jbeam").write_text(MIRRORED, encoding="utf-8")
    (folder / "a.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    session = EditSession.for_pc(folder / "a.pc")
    session.add_beam("arm", "l_a", "f1", allow_shared=True)
    assert sum(1 for b in session.vehicle.beams if b.id2 == "f1") == 2
    session.delete_entries([b for b in session.vehicle.beams if b.id2 == "f1"][:1], allow_shared=True)
    assert sum(1 for b in session.vehicle.beams if b.id2 == "f1") == 0
    session.delete_nodes(["l_b"], cascade=True, allow_shared=True)
    assert not {"l_b", "r_b"} & set(session.vehicle.nodes)


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


def test_reload_of_a_deleted_file_keeps_the_edits(car):
    session = session_for(car)
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    (car / "body.jbeam").unlink()
    assert session.changed_on_disk() == [(car / "body.jbeam").absolute()]
    with pytest.raises(EditError):
        session.reload_file(car / "body.jbeam")
    assert session.dirty_files() == [(car / "body.jbeam").absolute()]
    assert session.vehicle.nodes["b2"].pos[0] == pytest.approx(0.1)


def test_files_added_on_disk_wait_for_a_rescan(car):
    session = session_for(car)
    extra = car / "extra.jbeam"
    extra.write_text('{"car_door_L_stock": {"slotType": "car_door_L", "nodes": [["id", "posX", "posY", "posZ"], '
                     '["zz", 0, 0, 0]]}}', encoding="utf-8")
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    assert "zz" not in session.vehicle.nodes
    assert session.files_added_on_disk() == [extra]
    session.rescan()
    assert session.files_added_on_disk() == []
    assert session.vehicle.nodes["b2"].pos[0] == pytest.approx(0.1)


def test_rename_preview_and_chosen_other_matches(car):
    session = session_for(car)
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path).replace('"information": {"name": "Body"}',
                                                            '"information": {"name": "Body", "note": "b2"}'))
    preview = session.rename_preview("b2")
    assert len(preview.references) == 2
    assert [m.kind for m in preview.other_matches] == ["text"]
    result = session.rename_node("b2", "b9", also=preview.other_matches)
    assert result.other_matches == []
    assert '"note": "b9"' in session.text_of(path)
    stale = session.rename_preview("b9").other_matches
    session.replace_text(path, "// shifted\n" + session.text_of(path))
    with pytest.raises(EditError):
        session.rename_node("b9", "b10", also=stale)


def test_failed_save_leaves_no_temporary_files(car, monkeypatch):
    session = session_for(car)
    session.move_nodes({"b2": (0.1, 1.0, 0.3)})
    path = car / "body.jbeam"

    def refuse(source, target):
        raise PermissionError("target is locked")

    monkeypatch.setattr("jbeam_studio.core.edit.session.os.replace", refuse)
    with pytest.raises(OSError):
        session.save()
    assert not list(car.glob("*.jbs-tmp"))
    assert session.dirty_files() == [path.absolute()]
