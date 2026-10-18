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
    assert ("beam", overlay.contrast_color(0)) in content.lines
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


def test_the_colours_are_those_of_the_game_s_debug_view():
    from jbeam_studio.ui import view
    display = view.settings()
    view.reset(display)
    style = overlay.Style(display)
    assert style.normal_color == overlay._color(view.game(0, 223, 0))
    assert style.type_colors["|SUPPORT"] == overlay._color(view.game(223, 0, 223))
    assert overlay.contrast_color(0) == (0.0, 0.0, 1.0) and overlay.contrast_color(16) == (1.0, 0.0, 0.0)
    assert overlay.node_flag_color({"fixed": True, "selfCollision": True}, style) == style.node_flags[0][1]
    assert overlay.node_flag_color({"collision": False}, style) == style.node_flags[2][1]
    assert overlay.node_flag_color({"collision": True}, style) == style.node_color


DOORS = """{
"door_FL": {"information": {"name": "Front"}, "slotType": "door_FL",
    "nodes": [["id", "posX", "posY", "posZ"], ["d1l", 0.6, 0, 0.5], ["d2l", 0.6, 0.5, 0.5]]},
"door_FL_alt": {"information": {"name": "Front, other"}, "slotType": "door_FL",
    "nodes": [["id", "posX", "posY", "posZ"], ["d1l", 0.6, 0, 0.6], ["d2l", 0.6, 0.5, 0.6]]},
"door_RL": {"information": {"name": "Rear"}, "slotType": "door_RL",
    "nodes": [["id", "posX", "posY", "posZ"], ["d2l", 0.6, 1.0, 0.5], ["d3l", 0.6, 1.5, 0.5]]},
}"""


def test_nodes_that_parts_which_can_be_fitted_together_both_define_are_reported(tmp_path):
    import bpy
    from jbeam_studio.blender import sessions
    folder = tmp_path / "vehicles" / "two_doors"
    folder.mkdir(parents=True)
    (folder / "doors.jbeam").write_text(DOORS, encoding="utf-8")
    assert bpy.ops.jbs.import_jbeam_part(paths=str(folder / "doors.jbeam"), all_parts=True) == {"FINISHED"}
    found = {sessions.session_of(o).scope: sessions.scene_conflicts(sessions.session_of(o))
             for o in bpy.data.objects if sessions.session_of(o) is not None}
    assert found == {"door_FL": {"d2l": ["door_RL"]}, "door_FL_alt": {"d2l": ["door_RL"]},
                     "door_RL": {"d2l": ["door_FL", "door_FL_alt"]}}
