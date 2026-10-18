import bpy

from jbeam_studio.blender import sessions


def files_of(paths):
    return [{"name": p.name} for p in paths]


def collections():
    root = bpy.data.collections["JBeam"]
    return {c.name: sorted(o.jbs.part_name for o in c.objects) for c in root.children}


def test_several_part_configs_give_several_vehicles(car):
    (car / "sport.pc").write_text('{"format": 2, "parts": {"car_door_L": "car_door_L_sport"}}', encoding="utf-8")
    assert bpy.ops.jbs.import_pc(directory=str(car), files=files_of([car / "base.pc", car / "sport.pc"])) == {"FINISHED"}
    assert len(sessions.SESSIONS) == 2
    assert collections() == {"body.jbeam": ["car_body"], "doors.jbeam": ["car_door_L_stock"],
                             "engine.jbeam": ["car_engine_small"], "body.jbeam.001": ["car_body"],
                             "doors.jbeam.001": ["car_door_L_sport"], "engine.jbeam.001": ["car_engine_small"]}
    assert len(bpy.context.selected_objects) == 6
    assert bpy.context.active_object.jbs.part_name == "car_body"


def test_the_parts_of_several_files_are_chosen_or_all_imported(car):
    paths = "\n".join(str(car / name) for name in ("doors.jbeam", "engine.jbeam"))
    chosen = [{"name": "car_door_L_sport", "path": str(car / "doors.jbeam"), "chosen": True},
              {"name": "car_door_L_stock", "path": str(car / "doors.jbeam"), "chosen": False},
              {"name": "car_engine_small", "path": str(car / "engine.jbeam"), "chosen": True}]
    assert bpy.ops.jbs.import_jbeam_part(paths=paths, parts=chosen) == {"FINISHED"}
    assert collections() == {"doors.jbeam": ["car_door_L_sport"], "engine.jbeam": ["car_engine_small"]}
    assert bpy.ops.jbs.import_jbeam_part(paths=paths, all_parts=True) == {"FINISHED"}
    assert collections() == {"doors.jbeam": ["car_door_L_sport", "car_door_L_sport", "car_door_L_stock"],
                             "engine.jbeam": ["car_engine_small", "car_engine_small"]}


def test_choosing_no_part_imports_nothing(car):
    paths = str(car / "doors.jbeam")
    chosen = [{"name": "car_door_L_stock", "path": paths, "chosen": False}]
    try:
        bpy.ops.jbs.import_jbeam_part(paths=paths, parts=chosen)
    except RuntimeError as error:
        assert "Choose the parts" in str(error)
    assert not sessions.SESSIONS


def test_a_named_part_is_found_in_any_of_the_chosen_files(car):
    files = files_of([car / "doors.jbeam", car / "engine.jbeam"])
    assert bpy.ops.jbs.import_jbeam(directory=str(car), files=files, part_name="car_engine_small") == {"FINISHED"}
    assert collections() == {"engine.jbeam": ["car_engine_small"]}
