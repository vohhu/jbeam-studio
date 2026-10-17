from jbeam_studio.ui import overlay


def test_beam_colours_mark_special_and_unknown_types():
    assert overlay.beam_color("|NORMAL") is None and overlay.beam_color(None) is None
    assert overlay.beam_color("|SUPPORT") == overlay.BEAM_COLORS["|SUPPORT"]
    assert overlay.beam_color("| BOUNDED") == overlay.UNKNOWN_BEAM_COLOR


def test_group_colours_are_stable_and_differ():
    assert overlay.group_color("pickup_frame") == overlay.group_color("pickup_frame")
    assert overlay.group_color("pickup_frame") != overlay.group_color("pickup_cab")
