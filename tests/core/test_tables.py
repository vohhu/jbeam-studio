import math

from jbeam_studio.core.diagnostics import DiagnosticList
from jbeam_studio.core.model.tables import process_table, process_vehicle_tables
from jbeam_studio.core.sjson import parse, to_python


def data(text):
    return to_python(parse(text))


def test_rows_become_entries_keyed_by_id():
    diags = DiagnosticList()
    entries = process_table(data('[["id", "posX"], ["n1", 1], ["n2", 2]]'), None, diags, "nodes")
    assert entries == {"n1": {"name": "n1", "posX": 1}, "n2": {"name": "n2", "posX": 2}}
    assert diags == []
    assert entries["n2"].src.line == 1


def test_option_rows_apply_to_following_rows():
    entries = process_table(
        data('[["id", "w"], {"group": "a"}, ["n1", 1], {"group": "b", "x": 5}, ["n2", 2]]'), None, DiagnosticList(), "nodes")
    assert entries["n1"] == {"group": "a", "name": "n1", "w": 1}
    assert entries["n2"] == {"group": "b", "x": 5, "name": "n2", "w": 2}


def test_inline_options_apply_to_their_row_only():
    entries = process_table(data('[["id1:", "id2:"], ["a", "b", {"beamSpring": 0}], ["b", "c"]]'), None, DiagnosticList(), "beams")
    assert entries == {1: {"id1:": "a", "id2:": "b", "beamSpring": 0}, 2: {"id1:": "b", "id2:": "c"}}


def test_row_counter_counts_option_rows():
    entries = process_table(data('[["id1:", "id2:"], {"x": 1}, ["a", "b"]]'), None, DiagnosticList(), "beams")
    assert list(entries) == [2]


def test_input_options_and_special_values():
    entries = process_table(data('[["id", "s"], ["n1", "FLT_MAX"]]'), {"nodeWeight": 25}, DiagnosticList(), "nodes")
    assert entries["n1"] == {"nodeWeight": 25, "name": "n1", "s": math.inf}


def test_disabled_rows_are_skipped():
    entries = process_table(data('[["id"], ["n1", {"disable": true}], ["n2"]]'), None, DiagnosticList(), "nodes")
    assert list(entries) == ["n2"]


def test_too_long_row_is_skipped_with_warning():
    diags = DiagnosticList()
    assert process_table(data('[["id"], ["n1", 1, 2]]'), None, diags, "nodes") == {}
    assert diags.warnings()


def test_invalid_header():
    diags = DiagnosticList()
    assert process_table(data('[{"id": 1}, ["n1"]]'), None, diags, "nodes") is None
    assert diags.has_errors()


def test_nil_cell_stops_the_row():
    entries = process_table(data('[["id", "a", "b"], ["n1", null, 2]]'), None, DiagnosticList(), "nodes")
    assert entries["n1"] == {"name": "n1"}


def test_duplicate_id_warns_and_later_row_wins():
    diags = DiagnosticList()
    entries = process_table(data('[["id", "x"], ["n1", 1], ["n1", 2]]'), None, diags, "nodes")
    assert entries["n1"]["x"] == 2
    assert diags.warnings()


def test_redefinition_by_another_part_is_info():
    diags = DiagnosticList()
    rows = data('[["id", "x"], {"partOrigin": "a"}, ["n1", 1], {"partOrigin": "b"}, ["n1", 2]]')
    assert process_table(rows, None, diags, "nodes")["n1"]["x"] == 2
    assert [d.severity.value for d in diags] == ["info"]


def test_vehicle_tables_and_options():
    vehicle = data('{"slotType": "main", "nodes": [["id"], ["n1"]], "information": {"name": "x"}, "bad-name": [["a"]]}')
    diags = DiagnosticList()
    process_vehicle_tables(vehicle, diags)
    assert vehicle["options"] == {"slotType": "main"}
    assert vehicle["nodes"] == {"n1": {"slotType": "main", "name": "n1"}}
    assert vehicle["information"] == {"name": "x"}
    assert diags.has_errors()
