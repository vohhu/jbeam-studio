from jbeam_studio.ui import overlay


def test_beam_colours_mark_special_and_unknown_types():
    assert overlay.beam_color("|NORMAL") is None and overlay.beam_color(None) is None
    assert overlay.beam_color("|SUPPORT") == overlay.BEAM_COLORS["|SUPPORT"]
    assert overlay.beam_color("| BOUNDED") == overlay.UNKNOWN_BEAM_COLOR


def test_a_gradient_spans_the_finite_values_on_a_log_scale_when_they_span_a_lot():
    scale = overlay.Scale([1000.0, 10000.0, 100000.0, float("inf"), None])
    assert scale.log and scale.infinite and (scale.low, scale.high) == (1000.0, 100000.0)
    assert abs(scale.at(10000.0) - 0.5) < 1e-9
    assert scale.color(1000.0) == overlay.GRADIENT[0] and scale.color(100000.0) == overlay.GRADIENT[-1]
    assert scale.color(float("inf")) == overlay.INFINITE_COLOR and scale.color(None) is None
    flat = overlay.Scale([2.0, 4.0])
    assert not flat.log and flat.at(3.0) == 0.5 and flat.value(0.5) == 3.0
    springs = overlay.Scale([0.0] + [10.0 ** (3 + i / 10) for i in range(41)] + [1e12])
    assert springs.log and springs.at(0.0) == 0.0 and springs.at(1e12) == 1.0
    assert 1e3 < springs.low < springs.high < 1e7 and 0.4 < springs.at(1e5) < 0.6


def test_values_of_beams_fall_back_to_the_vehicle_options(car):
    import bpy
    from jbeam_studio.blender import sessions
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    session = sessions.session_of(bpy.context.active_object)
    values, scale = overlay._values(session, "beams", "beamSpring")
    assert set(values.values()) == {4300000.0} and not scale.log
    weights, _ = overlay._values(session, "nodes", "nodeWeight")
    assert weights["b1l"] == 10.0


def test_group_colours_are_stable_and_differ():
    assert overlay.group_color("pickup_frame") == overlay.group_color("pickup_frame")
    assert overlay.group_color("pickup_frame") != overlay.group_color("pickup_cab")
