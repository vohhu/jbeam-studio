import pytest

from jbeam_studio.core.assembly.links import drop_broken_links
from jbeam_studio.core.assembly.merge import merge_named_sections, unify
from jbeam_studio.core.assembly.positions import node_position, raw_position_for
from jbeam_studio.core.diagnostics import DiagnosticList
from jbeam_studio.core.sjson import JDict, parse, to_python


def data(text):
    return to_python(parse(text))


def test_new_list_section_gets_slot_options_and_reset_row():
    target = data('{"partName": "body"}')
    source = data('{"partName": "door", "nodes": [["id"], ["d1"]]}')
    unify(target, source, JDict({"nodeOffset": {"x": 1, "y": 0, "z": 0}}), "/door/door", DiagnosticList())
    assert target["nodes"] == [
        ["id"],
        {"nodeOffset": {"x": 1, "y": 0, "z": 0}, "partOrigin": "door", "partPath": "/door/door"},
        ["d1"],
        {"nodeOffset": "", "partOrigin": "", "partPath": ""},
    ]


def test_existing_list_section_appends_rows_without_header():
    target = data('{"nodes": [["id"], ["b1"]]}')
    unify(target, data('{"partName": "door", "nodes": [["id", "posX"], ["d1", 1]]}'), JDict(), "/d/door", DiagnosticList())
    assert target["nodes"] == [["id"], ["b1"], {"partOrigin": "door", "partPath": "/d/door"}, ["d1", 1],
                               {"partOrigin": "", "partPath": ""}]


def test_dict_sections_merge_with_modifier_keys():
    target = data('{"engine": {"torque": 100, "idle": 800, "$+mass": 5}}')
    unify(target, data('{"engine": {"$+torque": 50, "$*idle": 2, "$+mass": 1, "$<limit": 3, "name": "v8"}}'),
          JDict(), "/e/e", DiagnosticList())
    assert target["engine"] == {"torque": 150, "idle": 1600, "$+mass": 6, "$<limit": 3, "name": "v8"}


def test_scalars_overwrite_except_identity_keys():
    target = data('{"partName": "body", "slotType": "main", "scale": 1}')
    unify(target, data('{"partName": "x", "slotType": "x", "scale": 2, "information": {"name": "X"}, "slots2": []}'),
          JDict(), "/x/x", DiagnosticList())
    assert target == {"partName": "body", "slotType": "main", "scale": 2}


def test_merge_named_sections():
    vehicle = {"rails": {"a": {"x": 1}}, "rails2": {"b": {"x": 2}}}
    merge_named_sections(vehicle, "rails", "rails2", DiagnosticList())
    assert vehicle == {"rails": {"a": {"x": 1}, "b": {"x": 2, "originSection": "rails2"}}}


def test_rows_with_missing_targets_are_dropped():
    vehicle = {
        "nodes": {"a": {"name": "a"}, "b": {"name": "b"}},
        "beams": {1: {"id1:": "a", "id2:": "b"}, 2: {"id1:": "a", "id2:": "zz"}, 3: {"id1:": "a", "id2:": "zz", "optional": True}},
        "wheels": {1: {"node1:": "a", "nodeArm:": "zz"}},
        "rails": {"r": {"links:": ["a", "zz"]}},
        "engine": {"torqueReactionNodes:": ["a", "b"], "bad:": ["zz"]},
        "props": {1: {"idRef:": "a", "[group]:": ["g"]}},
    }
    diags = DiagnosticList()
    drop_broken_links(vehicle, diags)
    assert list(vehicle["beams"]) == [1]
    assert list(vehicle["wheels"]) == [1]
    assert vehicle["rails"] == {}
    assert vehicle["engine"] == {"torqueReactionNodes_nodes": ["a", "b"], "bad_nodes": ["zz"]}
    assert list(vehicle["props"]) == [1]
    assert len(diags) == 3


def node(**values):
    base = {"posX": 0.5, "posY": 1.0, "posZ": 2.0}
    base.update(values)
    return base


@pytest.mark.parametrize("row, expected", [
    (node(), (0.5, 1.0, 2.0)),
    (node(nodeOffset={"x": 0.1, "y": 0.2, "z": 0.3}), (0.6, 1.2, 2.3)),
    (node(posX=-0.5, nodeOffset={"x": 0.1, "y": 0, "z": 0}), (-0.6, 1.0, 2.0)),
    (node(posX=0, nodeOffset={"x": 0.1, "y": 0, "z": 0}), (0.0, 1.0, 2.0)),
    (node(posX=-0.5, nodeMove={"x": 0.1, "y": 0, "z": 0}), (-0.4, 1.0, 2.0)),
    (node(nodeOffset1={"x": 0.1, "y": 0, "z": 0}, nodeMove2={"x": 0, "y": 0, "z": 1}), (0.6, 1.0, 3.0)),
    (node(nodeOffset={"x": 0.1, "y": 0, "z": 0}, ignoreNodeOffset=True), (0.5, 1.0, 2.0)),
    (node(nodeOffset="", nodeMove={"x": "a", "y": 0, "z": 0}), (0.5, 1.0, 2.0)),
    (node(posX=1, posY=0, posZ=0, nodeRotate={"x": 0, "y": 0, "z": 90}), (0.0, 1.0, 0.0)),
    (node(posX=0, posY=1, posZ=0, nodeRotate={"x": 90, "y": 0, "z": 0}), (0.0, 0.0, 1.0)),
    (node(posX=0, posY=0, posZ=1, nodeRotate={"x": 0, "y": 90, "z": 0}), (1.0, 0.0, 0.0)),
    (node(posX=2, posY=0, posZ=0, nodeRotate={"x": 0, "y": 0, "z": 180, "px": 1}), (0.0, 0.0, 0.0)),
    (node(posX=1, posY=0, posZ=0, nodeRotate={"x": 0, "y": 0, "z": 90}, nodeOffset={"x": 1, "y": 0, "z": 0}),
     (0.0, 2.0, 0.0)),
])
def test_node_position(row, expected):
    assert node_position(row) == pytest.approx(expected, abs=1e-12)


def test_positions_inside_an_x_offset_are_unreachable():
    assert raw_position_for(node(nodeOffset={"x": 0.25, "y": 0, "z": 0}), (0.2, 1.0, 2.0)) is None
    assert raw_position_for(node(nodeOffset={"x": 0.25, "y": 0, "z": 0}), (0.3, 1.0, 2.0)) == pytest.approx((0.05, 1.0, 2.0))


@pytest.mark.parametrize("row", [
    node(),
    node(nodeOffset={"x": 0.1, "y": 0.2, "z": 0.3}),
    node(posX=-0.5, nodeOffset={"x": 0.1, "y": 0, "z": 0}, nodeMove={"x": 0.3, "y": 0, "z": 0}),
    node(nodeRotate={"x": 10, "y": 20, "z": 30, "px": 0.2}, nodeOffset={"x": 0.1, "y": 0.2, "z": 0}),
])
@pytest.mark.parametrize("target", [(0.7, 1.1, 2.2), (-0.7, -1.0, 0.0)])
def test_raw_position_round_trips(row, target):
    raw = raw_position_for(row, target)
    moved = dict(row, posX=raw[0], posY=raw[1], posZ=raw[2])
    assert node_position(moved) == pytest.approx(target, abs=1e-9)
