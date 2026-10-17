import pytest

from jbeam_studio.core.edit.text import (
    TextEdit, TextEditError, apply_edits, delete_value, format_number, insert_row, insert_section, json_literal,
    shift_expression,
)
from jbeam_studio.core.sjson import parse, to_python


def table_of(text, part="p", section="nodes"):
    doc = parse(text)
    part_node = next(m.value for m in doc.root.members if m.key == part)
    return doc, part_node, next(m.value for m in part_node.members if m.key == section)


def test_apply_edits_rejects_overlaps():
    assert apply_edits("abcdef", [TextEdit(1, 2, "X"), TextEdit(4, 5, "Y")]) == "aXcdYf"
    with pytest.raises(TextEditError):
        apply_edits("abcdef", [TextEdit(1, 4, "X"), TextEdit(3, 5, "Y")])


def test_format_and_literals():
    assert format_number(0.3) == "0.300"
    assert format_number(-0.0001) == "0.000"
    assert format_number(1.23456, 5) == "1.23456"
    assert json_literal("a\"b") == '"a\\"b"'
    assert json_literal(float("inf")) == "Infinity"
    assert json_literal(True) == "true"


@pytest.mark.parametrize("expression, delta, expected", [
    ("$=$a * 2", 0.1, "$=($a * 2) + 0.100"),
    ("$=($a * 2) + 0.100", 0.05, "$=($a * 2) + 0.150"),
    ("$=($a * 2) + 0.100", -0.1, "$=$a * 2"),
    ("$height", -0.25, "$=$height - 0.250"),
    ("$=$height - 0.250", 0.25, "$height"),
])
def test_shift_expression(expression, delta, expected):
    assert shift_expression(expression, delta) == expected


def test_insert_row_matches_neighbours():
    text = '{"p": {\n    "nodes": [\n        ["id",   "posX"],\n        ["n1",   1.000],  // first\n    ],\n}}'
    doc, _, table = table_of(text)
    new = apply_edits(text, [insert_row(doc, table, ['"n2"', "2.000"])])
    assert new == ('{"p": {\n    "nodes": [\n        ["id",   "posX"],\n        ["n1",   1.000],  // first\n'
                   '        ["n2",   2.000],\n    ],\n}}')


def test_insert_row_into_one_line_table():
    text = '{"p": {"beams": [["id1:", "id2:"]]}}'
    doc, _, table = table_of(text, section="beams")
    new = apply_edits(text, [insert_row(doc, table, ['"a"', '"b"'])])
    assert to_python(parse(new))["p"]["beams"] == [["id1:", "id2:"], ["a", "b"]]


def test_delete_row_with_its_line_and_comment():
    text = '{"p": {"nodes": [\n  ["id"],\n  ["n1"],  /* note */\n  ["n2"], ["n3"],\n]}}'
    doc, _, table = table_of(text)
    without_n1 = apply_edits(text, [delete_value(doc, table.items[1])])
    assert without_n1 == '{"p": {"nodes": [\n  ["id"],\n  ["n2"], ["n3"],\n]}}'
    without_n2 = apply_edits(text, [delete_value(doc, table.items[2])])
    assert '["n3"]' in without_n2 and '["n2"]' not in without_n2
    assert to_python(parse(without_n2))["p"]["nodes"] == [["id"], ["n1"], ["n3"]]


def test_insert_section():
    text = '{\n"p": {\n    "slotType": "x",\n    "nodes": [["id"]]\n},\n}'
    doc = parse(text)
    part = doc.root.members[0].value
    new = apply_edits(text, insert_section(doc, part, "beams", ['"id1:"', '"id2:"'], [['"a"', '"b"']]))
    assert to_python(parse(new))["p"]["beams"] == [["id1:", "id2:"], ["a", "b"]]
    assert '    "beams": [\n        ["id1:", "id2:"],\n        ["a", "b"],\n    ],' in new
