import math

import pytest

from jbeam_studio.core.sjson import parse, to_python

SAMPLE = (
    '{\r\n  // comment\r\n  "nodes": [\r\n    ["id", "posX"],\r\n    ["n1", 1.5] ["n2", -2]\r\n'
    '    /* block\r\n    */ {"w": 2,},\r\n  ],\r\n}\r\n'
)


def test_serialize_returns_the_original_text():
    doc = parse(SAMPLE)
    assert doc.root is not None
    assert doc.serialize() == SAMPLE


def test_values_follow_sjson_rules():
    assert to_python(parse(SAMPLE)) == {"nodes": [["id", "posX"], ["n1", 1.5], ["n2", -2], {"w": 2}]}


@pytest.mark.parametrize("text, expected", [
    ('{"a":1 "b":2}', {"a": 1, "b": 2}),
    ("[1 2 3,]", [1, 2, 3]),
    ('a=1 b=2 c="x"', {"a": 1, "b": 2, "c": "x"}),
    ('{a = 1, b: "x"}', {"a": 1, "b": "x"}),
    ('{"n": [1.5, 1e3, +7, -2, .5]}', {"n": [1.5, 1000.0, 7, -2, 0.5]}),
    ('{"s": "a\\n\\t\\\\\\"\\u0041"}', {"s": 'a\n\t\\"A'}),
    ('{"t": true, "f": false, "n": null}', {"t": True, "f": False}),
    ("[1, null, 3]", [1, None, 3]),
    ("// only a comment\n", {}),
])
def test_decoding(text, expected):
    doc = parse(text)
    assert not doc.diagnostics.has_errors()
    assert to_python(doc) == expected


def test_infinity_spellings():
    data = to_python(parse('{"a": Infinity, "b": -Infinity, "c": 1#INF00}'))
    assert data == {"a": math.inf, "b": -math.inf, "c": math.inf}


@pytest.mark.parametrize("text", [
    '{"x":+Infinity}', '{"x":1#INF01}', '{"x":1e+}', '{"x":-}', '{"x":+}', '{"a" 1}', '{"a": [1, 2}', '{"a": 1',
    '{"a":"unterminated}', "{a; 1}", "/ not-a-comment", '/* outer /* inner */ */ {"a":1}', '{"a": truee}',
    '{"a": fals}', '{"a": nul}', "{bad",
])
def test_malformed_documents_fail(text):
    doc = parse(text)
    assert doc.root is None
    assert doc.diagnostics.has_errors()


def test_duplicate_keys_warn_and_last_wins():
    doc = parse('{"a": 1, "a": 2}')
    assert to_python(doc) == {"a": 2}
    assert [d.severity.value for d in doc.diagnostics] == ["warning"]


def test_positions():
    doc = parse('{\n  "a": [1,\n    {"b": 2}]}', "x.jbeam")
    inner = to_python(doc)["a"][1]
    assert (inner.src.file, inner.src.line, inner.src.column) == ("x.jbeam", 3, 5)


def test_error_position():
    doc = parse('{\n  "a": [1, 2}\n}')
    error = doc.diagnostics.errors()[0]
    assert (error.line, error.column) == (2, 13)


def test_unbraced_file_with_extra_closing_brace():
    doc = parse('// parts\n"a": {"x": 1},\n}\n')
    assert to_python(doc) == {"a": {"x": 1}}
    assert doc.diagnostics.warnings() and not doc.diagnostics.has_errors()


def test_trailing_content_is_a_warning():
    doc = parse('{"a": 1} garbage')
    assert to_python(doc) == {"a": 1}
    assert doc.diagnostics.warnings()
