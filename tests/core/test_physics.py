import math

import pytest

from jbeam_studio.core.edit import EditSession
from jbeam_studio.core.physics import mass, option, value_of


def session_for(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return EditSession.for_pc(car / "base.pc")


def test_mass_and_centre_of_mass_use_the_node_weights(car):
    vehicle = session_for(car).vehicle
    body = [n for n in vehicle.nodes.values() if n.part == "car_body"]
    total, centre = mass(vehicle, body)
    assert total == 30
    assert centre == pytest.approx((0.0, 1 / 3, 0.3))
    assert mass(vehicle, [])[1] is None


def test_values_missing_on_a_row_come_from_the_options_or_the_game_defaults(car):
    vehicle = session_for(car).vehicle
    assert option(vehicle, "beamSpring") == 4300000 and option(vehicle, "beamStrength") == math.inf
    assert value_of(vehicle, {"beamSpring": 1000}, "beamSpring") == 1000
    assert value_of(vehicle, {}, "beamDeform") == 220000
    assert value_of(vehicle, {}, "unknownKey") is None
    vehicle.data["options"] = {"nodeWeight": 3}
    assert value_of(vehicle, {}, "nodeWeight") == 3
