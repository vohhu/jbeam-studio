from jbeam_studio.core.assembly.config import VehicleConfig
from jbeam_studio.core.assembly.index import PartDef, PartIndex
from jbeam_studio.core.assembly.slots import find_parts, part_fits_slot
from jbeam_studio.core.diagnostics import DiagnosticList
from jbeam_studio.core.sjson import JDict

HEADER = '["name", "allowTypes", "denyTypes", "default", "description"]'
TREE = f'''{{
  "body": {{"slotType": "main", "slots2": [{HEADER}, ["a", ["a"], [], "a1", "A"], ["b", ["b"], [], "b1", "B"],
                                           ["e", ["e"], [], "", "E"]]}},
  "a1": {{"slotType": "a", "slots2": [{HEADER}, ["c", ["c"], [], "c1", "C"]]}},
  "b1": {{"slotType": "b"}},
  "b2": {{"slotType": "b"}},
  "c1": {{"slotType": "c"}}
}}'''


def index_of(tmp_path, text):
    folder = tmp_path / "car"
    folder.mkdir(exist_ok=True)
    (folder / "parts.jbeam").write_text(text, encoding="utf-8")
    return PartIndex([folder])


def test_tree_paths_and_journal_order(tmp_path):
    found = find_parts(index_of(tmp_path, TREE), VehicleConfig(), DiagnosticList())
    assert found.tree.children["a"].children["c"].path == "/a/c/"
    assert [e.part_def.name for e in found.journal] == ["c1", "a1", "b1"]
    assert [e.part_def.name for e in found.journal_c] == ["a1", "c1", "b1"]
    assert found.active_parts == {"/body": "body", "/a/a1": "a1", "/a/c/c1": "c1", "/b/b1": "b1"}
    assert found.tree.children["e"].decision == "default-empty"


def test_config_choices(tmp_path):
    config = VehicleConfig(parts={"a": "none", "/b/": "b2"})
    found = find_parts(index_of(tmp_path, TREE), config, DiagnosticList())
    assert found.tree.children["a"].decision == "user-empty"
    assert found.tree.children["b"].chosen_part == "b2"
    assert [e.part_def.name for e in found.journal] == ["b2"]


def test_journal_links_children_to_parent_copies(tmp_path):
    found = find_parts(index_of(tmp_path, TREE), VehicleConfig(), DiagnosticList())
    by_name = {e.part_def.name: e for e in found.journal}
    assert by_name["c1"].parent is by_name["a1"].part
    assert by_name["a1"].parent is found.root


def test_cycles_stop(tmp_path):
    text = (f'{{"body": {{"slotType": "main", "slots2": [{HEADER}, ["loop", ["loop"], [], "loopy", "L"]]}}, '
            f'"loopy": {{"slotType": "loop", "slots2": [{HEADER}, ["loop", ["loop"], [], "loopy", "L"]]}}}}')
    diags = DiagnosticList()
    find_parts(index_of(tmp_path, text), VehicleConfig(), diags)
    assert any("cycles" in d.message for d in diags.errors())


def test_part_fits_slot():
    def part(slot_type):
        return PartDef("p", None, [], JDict({"slotType": slot_type}))

    assert part_fits_slot(part(["x", "y"]), {"allowTypes": ["y"], "denyTypes": []})[0]
    assert not part_fits_slot(part(["x", "y"]), {"allowTypes": ["y"], "denyTypes": ["x"]})[0]
    assert not part_fits_slot(part("z"), {"allowTypes": ["y"], "denyTypes": []})[0]
    assert not part_fits_slot(part("y"), {})[0]
