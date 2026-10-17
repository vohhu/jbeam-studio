from jbeam_studio.core.assembly.index import PartIndex
from jbeam_studio.core.diagnostics import Severity

SLOTS2_HEADER = '["name", "allowTypes", "denyTypes", "default", "description"]'


def write(folder, name, text):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def messages(index, severity=None):
    return [d.message for d in index.diagnostics if severity is None or d.severity is severity]


def test_model_folder_wins_over_common(tmp_path):
    write(tmp_path / "car", "a.jbeam", '{"wheel": {"slotType": "wheel", "nodes": [["id"], ["car"]]}}')
    write(tmp_path / "common", "a.jbeam", '{"wheel": {"slotType": "wheel"}, "tire": {"slotType": "tire"}}')
    index = PartIndex([tmp_path / "car", tmp_path / "common"])
    assert index.get("wheel").file.path.parent.name == "car"
    assert index.get("tire") is not None
    assert index.get("missing") is None


def test_main_part_and_missing_slot_type(tmp_path):
    write(tmp_path / "car", "a.jbeam", '{"body": {"slotType": "main"}, "junk": {"nodes": []}}')
    index = PartIndex([tmp_path / "car"])
    assert index.main_part_name() == "body"
    assert index.get("junk") is None
    assert any("slotType" in m for m in messages(index, Severity.ERROR))


def test_legacy_slots_become_slots2(tmp_path):
    write(tmp_path / "car", "a.jbeam",
          '{"body": {"slotType": "main", "slots": [["type", "default", "description"], ["car_door", "door_a", "Door"]]}}')
    slots = PartIndex([tmp_path / "car"]).get("body").data["slots2"]
    assert slots == [{"name": "car_door", "allowTypes": ["car_door"], "denyTypes": [], "default": "door_a", "description": "Door"}]


def test_legacy_slots_without_header(tmp_path):
    write(tmp_path / "car", "a.jbeam", '{"body": {"slotType": "main", "slots": [["car_door", "door_a", "Door"]]}}')
    index = PartIndex([tmp_path / "car"])
    assert index.get("body").data["slots2"][0]["name"] == "car_door"
    assert any("header" in m for m in messages(index))


def test_slots_win_over_slots2(tmp_path):
    write(tmp_path / "car", "a.jbeam",
          '{"body": {"slotType": "main", "slots": [["type", "default"], ["a", ""]], '
          f'"slots2": [{SLOTS2_HEADER}, ["b", ["b"], [], "", "B"]]}}}}')
    index = PartIndex([tmp_path / "car"])
    assert [s["name"] for s in index.get("body").data["slots2"]] == ["a"]
    assert any("slots2" in m for m in messages(index, Severity.WARNING))


def test_slots2_checks(tmp_path):
    write(tmp_path / "car", "a.jbeam",
          f'{{"body": {{"slotType": "main", "slots2": [{SLOTS2_HEADER}, ["a", "a", [], "", "A"], ["a", [], [], "", "B"]]}}}}')
    found = messages(PartIndex([tmp_path / "car"]))
    assert any('"allowTypes" must be a list' in m for m in found)
    assert any("more than once" in m for m in found)
    assert any("no part fits" in m for m in found)


def test_slots2_without_header_is_an_error(tmp_path):
    write(tmp_path / "car", "a.jbeam", '{"body": {"slotType": "main", "slots2": [["a", ["a"], [], "", "A"]]}}')
    assert any("table header" in m for m in messages(PartIndex([tmp_path / "car"]), Severity.ERROR))


def test_duplicate_part_in_one_folder(tmp_path):
    write(tmp_path / "car", "a.jbeam", '{"door": {"slotType": "door", "nodes": [["id"], ["a"]]}}')
    write(tmp_path / "car", "b.jbeam", '{"door": {"slotType": "door", "nodes": [["id"], ["b"]]}}')
    index = PartIndex([tmp_path / "car"])
    assert index.get("door").file.path.name == "a.jbeam"
    assert any("duplicate part" in m for m in messages(index))
