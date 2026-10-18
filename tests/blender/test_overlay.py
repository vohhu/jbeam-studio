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


def _imported(car):
    import bpy
    from jbeam_studio.blender import sessions
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    obj = bpy.context.active_object
    return obj, sessions.session_of(obj)


def test_what_an_object_shows_has_its_beams_and_its_problems(car):
    from jbeam_studio.ui import view
    obj, session = _imported(car)
    display = view.settings()
    display.normal_beams = True
    style = overlay.Style(display)
    content = overlay._content(obj, session, overlay._read(obj), style)
    assert ("beam", style.normal_color) in content.lines
    assert content.points[("problem", style.problem_color)].shape == (1, 3)
    display.beam_color_by = "PART"
    style = overlay.Style(display)
    content = overlay._content(obj, session, overlay._read(obj), style)
    assert ("beam", overlay.group_color("car_body")) in content.lines
    display.beam_color_by = "TYPE"
    assert overlay._object_key(obj, session, style) != overlay._object_key(obj, session, overlay.Style(display))


def test_in_edit_mode_the_selection_is_drawn_over_and_has_one_centre_of_mass(car):
    import bpy
    from jbeam_studio.ui import view
    obj, session = _imported(car)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    style = overlay.Style(view.settings())
    content = overlay._content(obj, session, overlay._read(obj), style)
    assert ("selection", style.selection_color) in content.lines and ("selection", style.selection_color) in content.points
    shown = overlay.Shown(obj, session, False, content)
    centres = overlay._centres(bpy.context, style, [shown], [shown])
    selected = [c for c in centres if c[2] == style.selection_center_color]
    assert len(selected) == 1 and selected[0][1] == 30.0
    assert abs(selected[0][0].y - 1 / 3) < 1e-4


def test_display_settings_go_back_to_their_defaults():
    from jbeam_studio.ui import view
    display = view.settings()
    display.line_width, display.scope = 6.0, "ACTIVE"
    view.reset(display)
    assert display.line_width == 2.5 and display.scope == "ALL"
