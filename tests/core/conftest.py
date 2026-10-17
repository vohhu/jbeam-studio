import pytest

HEADER = '["name", "allowTypes", "denyTypes", "default", "description"]'

BODY = f"""{{
"car_body": {{
    "information": {{"name": "Body"}},
    "slotType": "main",
    "slots2": [
        {HEADER},
        ["car_door_L", ["car_door_L"], [], "car_door_L_stock", "Left door", {{"nodeOffset": {{"x": 0.1, "y": 0, "z": 0}}}}],
        ["car_engine", ["car_engine"], [], "car_engine_small", "Engine", {{"variables": {{"$cyl_count": 4}}}}],
    ],
    "variables": [
        ["name", "type", "unit", "category", "default", "min", "max", "title", "description"],
        ["$ride_height", "range", "m", "Suspension", 0.0, -0.1, 0.1, "Ride height", "Ride height"],
    ],
    "nodes": [
        ["id", "posX", "posY", "posZ"],
        {{"nodeWeight": 10}},
        ["b1l", 0.5, 0.0, "$=0.3 + $ride_height"],
        ["b1r", -0.5, 0.0, "$=0.3 + $ride_height"],
        ["b2", 0.0, 1.0, 0.3],
    ],
    "beams": [["id1:", "id2:"], ["b1l", "b1r"], ["b1l", "b2"], ["b1r", "ghost"]],
    "triangles": [["id1:", "id2:", "id3:"], ["b1l", "b1r", "b2"]],
}},
}}"""

DOORS = """{
"car_door_L_stock": {
    "information": {"name": "Stock door"},
    "slotType": "car_door_L",
    "nodes": [["id", "posX", "posY", "posZ"], ["d1l", 0.6, 0.0, 0.5]],
    "beams": [["id1:", "id2:"], ["d1l", "b1l"]],
},
"car_door_L_sport": {
    "information": {"name": "Sport door"},
    "slotType": "car_door_L",
    "nodes": [["id", "posX", "posY", "posZ"], ["d2l", 0.7, 0.0, 0.5]],
},
}"""

ENGINE = """{
"car_engine_small": {
    "information": {"name": "Small engine"},
    "slotType": "car_engine",
    "components": {"engine": {"cylinders": "$cyl_count"}},
    "nodes": [["id", "posX", "posY", "posZ"], ["e1", 0.0, "$=$components.engine.cylinders * 0.1", 0.2]],
},
}"""


@pytest.fixture
def car(tmp_path):
    folder = tmp_path / "vehicles" / "car"
    folder.mkdir(parents=True)
    (folder / "body.jbeam").write_text(BODY, encoding="utf-8")
    (folder / "doors.jbeam").write_text(DOORS, encoding="utf-8")
    (folder / "engine.jbeam").write_text(ENGINE, encoding="utf-8")
    return folder
