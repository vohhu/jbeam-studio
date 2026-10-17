from jbeam_studio.core.sjson.tokens import (
    COMMENT, EXPRESSION, KEY, LITERAL, NUMBER, PART, SECTION, STRING, VARIABLE, tokenize, tokens_by_line,
)

TEXT = """{
"car_body": {
    // the body
    "information": {"name": "Body", "authors": "me"},
    "nodes": [
        ["id", "posX", "posY", "posZ"],
        {"collision": true, "nodeWeight": "$weight"},
        ["b1", 0.5, -1e2, "$=$ride + 0.1"],
    ],
    /* block
       comment */
    "value": null,
},
}"""


def kinds(text):
    return [(t.kind, text[t.start:t.end]) for t in tokenize(text)]


def test_tokens_know_parts_sections_keys_and_values():
    found = kinds(TEXT)
    assert found[:6] == [(PART, '"car_body"'), (COMMENT, "// the body"), (SECTION, '"information"'),
                         (KEY, '"name"'), (STRING, '"Body"'), (KEY, '"authors"')]
    assert (KEY, '"collision"') in found and (LITERAL, "true") in found
    assert (VARIABLE, '"$weight"') in found and (EXPRESSION, '"$=$ride + 0.1"') in found
    assert (NUMBER, "-1e2") in found and (STRING, '"posX"') in found
    assert (SECTION, '"value"') in found and (LITERAL, "null") in found


def test_braceless_files_and_unquoted_keys():
    found = kinds('part_a: {nodes: [["id"]], flag = false}')
    assert found == [(PART, "part_a"), (SECTION, "nodes"), (STRING, '"id"'), (SECTION, "flag"), (LITERAL, "false")]


def test_text_being_typed_still_gets_tokens():
    found = kinds('{"p": {"nodes": [["a", 1.0, "unfinished\n  "b": 2')
    assert (PART, '"p"') in found and (SECTION, '"nodes"') in found and (NUMBER, "1.0") in found
    assert (STRING, '"unfinished') in found


def test_tokens_by_line_splits_block_comments():
    lines = tokens_by_line(TEXT)
    assert lines[2] == [(4, 15, COMMENT)]
    assert lines[9] == [(4, 12, COMMENT)] and lines[10][0][2] == COMMENT
    assert lines[1] == [(0, 10, PART)]
