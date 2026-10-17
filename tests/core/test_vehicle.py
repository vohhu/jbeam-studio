from pathlib import Path

import pytest

from jbeam_studio.core.assembly import assemble_part, assemble_pc, assemble_vehicle
from jbeam_studio.core.diagnostics import Severity

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def messages(vehicle, severity):
    return [d.message for d in vehicle.diagnostics if d.severity is severity]


def write_pc(car, name, text):
    (car / name).write_text(text, encoding="utf-8")
    return car / name


def test_default_config_merges_child_parts(car):
    vehicle = assemble_vehicle(car)
    assert set(vehicle.nodes) == {"b1l", "b1r", "b2", "d1l", "e1"}
    assert vehicle.nodes["d1l"].part == "car_door_L_stock"
    assert vehicle.nodes["b2"].part == "car_body"
    assert vehicle.nodes["b1l"].props["nodeWeight"] == 10
    assert vehicle.slot_tree.children["car_door_L"].chosen_part == "car_door_L_stock"
    assert vehicle.nodes["d1l"].src.file.endswith("doors.jbeam")
    assert messages(vehicle, Severity.ERROR) == []


def test_slot_node_offset_variables_and_components(car):
    vehicle = assemble_vehicle(car)
    assert vehicle.nodes["d1l"].pos == pytest.approx((0.7, 0.0, 0.5))
    assert vehicle.nodes["b1l"].pos == pytest.approx((0.5, 0.0, 0.3))
    assert vehicle.nodes["e1"].pos == pytest.approx((0.0, 0.4, 0.2))
    assert vehicle.variables["$ride_height"]["val"] == 0.0


def test_pc_selects_parts_and_overrides_variables(car):
    vehicle = assemble_pc(write_pc(car, "sport.pc", '{"format": 2, "model": "car", "parts": {"car_door_L": '
                                                    '"car_door_L_sport"}, "vars": {"$ride_height": 0.5}}'))
    assert "d2l" in vehicle.nodes and "d1l" not in vehicle.nodes
    assert vehicle.nodes["b1l"].pos[2] == pytest.approx(0.4)
    assert any("clamped" in m for m in messages(vehicle, Severity.WARNING))


def test_slot_path_keys_and_empty_slots(car):
    vehicle = assemble_pc(write_pc(car, "a.pc", '{"format": 2, "parts": {"/car_door_L/": "car_door_L_sport", '
                                                '"car_engine": "none"}}'))
    assert "d2l" in vehicle.nodes
    assert "e1" not in vehicle.nodes


def test_missing_or_unfitting_part_falls_back_to_default(car):
    vehicle = assemble_pc(write_pc(car, "b.pc", '{"format": 2, "parts": {"car_door_L": "car_engine_small", '
                                                '"car_engine": "does_not_exist"}}'))
    assert vehicle.slot_tree.children["car_door_L"].chosen_part == "car_door_L_stock"
    assert vehicle.slot_tree.children["car_engine"].chosen_part == "car_engine_small"
    warnings = " ".join(messages(vehicle, Severity.WARNING))
    assert "does not fit" in warnings and "not found" in warnings


def test_beam_to_missing_node_is_dropped(car):
    vehicle = assemble_vehicle(car)
    pairs = {(b.id1, b.id2) for b in vehicle.beams}
    assert ("b1r", "ghost") not in pairs
    assert {("b1l", "b1r"), ("d1l", "b1l")} <= pairs
    assert any("ghost" in m for m in messages(vehicle, Severity.WARNING))
    assert [f.ids for f in vehicle.triangles] == [("b1l", "b1r", "b2")]


def test_format_4_and_legacy_configs(car):
    write_pc(car, "linked.pc", '{"format": 2, "parts": {"car_engine": ""}}')
    assert "e1" not in assemble_pc(write_pc(car, "four.pc", '{"format": 4, "vehicles": '
                                                            '[{"linkedPCFile": "/vehicles/car/linked.pc"}]}')).nodes
    assert "d2l" in assemble_pc(write_pc(car, "old.pc", '{"car_door_L": "car_door_L_sport"}')).nodes


def test_no_main_part_is_an_error(tmp_path):
    folder = tmp_path / "vehicles" / "empty"
    folder.mkdir(parents=True)
    vehicle = assemble_vehicle(folder)
    assert vehicle.diagnostics.has_errors()
    assert vehicle.nodes == {}


def test_single_part_import_shows_external_nodes(car):
    vehicle = assemble_part(car / "doors.jbeam", "car_door_L_stock")
    assert set(vehicle.nodes) == {"d1l"}
    assert set(vehicle.external_nodes) == {"b1l"}
    assert vehicle.external_nodes["b1l"].pos == pytest.approx((0.5, 0.0, 0.3))
    assert [(b.id1, b.id2) for b in vehicle.beams] == [("d1l", "b1l")]
    assert messages(vehicle, Severity.ERROR) == []


def test_overlay_mod_finds_the_base_vehicle_in_other_roots(car, tmp_path):
    mod = tmp_path / "mod" / "vehicles" / "car"
    mod.mkdir(parents=True)
    (mod / "hybrid.jbeam").write_text('{"car_engine_hybrid": {"slotType": "car_engine", '
                                      '"nodes": [["id", "posX", "posY", "posZ"], ["h1", 0, 0, 0]]}}', encoding="utf-8")
    (mod / "hybrid.pc").write_text('{"format": 2, "parts": {"car_engine": "car_engine_hybrid"}}', encoding="utf-8")
    vehicle = assemble_pc(mod / "hybrid.pc", vehicle_roots=[car.parent])
    assert {"b1l", "d1l", "h1"} <= set(vehicle.nodes)
    assert "e1" not in vehicle.nodes
    assert messages(vehicle, Severity.ERROR) == []


def test_square_donut_fixture():
    vehicle = assemble_pc(FIXTURES / "vehicles" / "square_donut" / "normal.pc")
    assert messages(vehicle, Severity.ERROR) == []
    assert vehicle.nodes["nl0"].pos == pytest.approx((1.2, -1.2, -0.2))
    assert vehicle.nodes["nl0"].props["nodeWeight"] == 25
    assert vehicle.slot_tree.children["square_donut_meshes"].chosen_part == "square_donut_mesh"
    assert len(vehicle.beams) > 0 and len(vehicle.triangles) > 0
