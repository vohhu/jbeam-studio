"""Display settings of the viewport and the text editor, kept in the add-on preferences so they last between
Blender sessions (in the window manager when the add-on is not installed), and the state of the panels."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty


def _color(name: str, default: tuple, description: str = ""):
    return FloatVectorProperty(name=name, subtype="COLOR", size=3, min=0.0, max=1.0, default=default,
                               description=description)


BEAM_TYPES = (("|SUPPORT", "color_support"), ("|BOUNDED", "color_bounded"), ("|ANISOTROPIC", "color_anisotropic"),
              ("|LBEAM", "color_lbeam"), ("|PRESSURED", "color_pressured"))
"""Beam types with a colour of their own, and the setting that holds it."""
EXTRA_SECTIONS = (("hydros", "color_hydros", "Hydros"), ("torsionbars", "color_torsionbars", "Torsion bars"),
                  ("torsionHydros", "color_torsion_hydros", "Torsion hydros"), ("rails", "color_rails", "Rails"),
                  ("slidenodes", "color_slidenodes", "Slide nodes"))
VALUE_KEYS = ("beamSpring", "beamDamp", "beamDeform", "beamStrength", "nodeWeight")
CATEGORIES = ("BREAK_GROUP", "DEFORM_GROUP", "GROUP", "PART")


class JBS_ViewSettings(bpy.types.PropertyGroup):
    # where
    scope: EnumProperty(
        name="Show on",
        items=[("ALL", "All", "Colour every JBeam object"),
               ("SELECTED", "Selected", "Colour the selected JBeam objects"),
               ("ACTIVE", "Active", "Colour only the active object, the part being edited")],
        default="ALL",
    )
    dim_others: BoolProperty(name="Dim the others", default=True,
                             description="Draw the colours of the other JBeam objects faintly instead of hiding them")
    dim_opacity: FloatProperty(name="Their opacity", default=0.2, min=0.02, max=1.0, subtype="FACTOR",
                               description="Opacity of the colours of the other JBeam objects")
    through_faces: BoolProperty(
        name="Through faces", default=False,
        description="Draw coloured beams and nodes, hydros, rails and node names of JBeam objects through faces; "
                    "otherwise faces hide them, except in X-ray and wireframe",
    )
    line_opacity: FloatProperty(name="Opacity", default=1.0, min=0.1, max=1.0, subtype="FACTOR",
                                description="Opacity of everything drawn over the objects")
    legend: BoolProperty(name="Legend", default=True, description="Show what the colours mean in the viewport")

    # beams
    beam_colors: BoolProperty(name="Beams", default=True, description="Draw beams in colour, by what Colour by says")
    beam_color_by: EnumProperty(
        name="Colour beams by",
        items=[("TYPE", "Type", "Beams of special types: SUPPORT, BOUNDED, ANISOTROPIC, LBEAM, PRESSURED; types the "
                                "game does not know in red"),
               ("beamSpring", "beamSpring", "Stiffness, on the gradient from low to high"),
               ("beamDamp", "beamDamp", "Damping, on the gradient from low to high"),
               ("beamDeform", "beamDeform", "Force that bends a beam for good, on the gradient from low to high"),
               ("beamStrength", "beamStrength", "Force that breaks a beam, on the gradient from low to high"),
               ("BREAK_GROUP", "breakGroup", "A colour for each break group"),
               ("DEFORM_GROUP", "deformGroup", "A colour for each deform group"),
               ("PART", "Part", "A colour for each part")],
        default="TYPE",
    )
    normal_beams: BoolProperty(name="Other beams", default=False,
                               description="Also draw the beams that Colour by gives no colour, such as beams of the "
                                           "normal type, in their own colour")
    normal_color: _color("Colour of other beams", (0.62, 0.68, 0.76))
    color_support: _color("SUPPORT", (1.0, 0.62, 0.15))
    color_bounded: _color("BOUNDED", (0.25, 0.55, 1.0))
    color_anisotropic: _color("ANISOTROPIC", (0.75, 0.4, 1.0))
    color_lbeam: _color("LBEAM", (0.35, 0.9, 0.35))
    color_pressured: _color("PRESSURED", (0.2, 0.9, 0.9))
    color_unknown: _color("Unknown type", (1.0, 0.25, 0.25), "Beam types the game does not know, such as \"| BOUNDED\"")
    line_width: FloatProperty(name="Width", default=2.5, min=1.0, max=10.0, step=50,
                              description="Width of coloured beams, in pixels")

    # gradient
    palette: EnumProperty(
        name="Gradient",
        items=[("RAINBOW", "Rainbow", "Blue, cyan, green, yellow, red"),
               ("COOLWARM", "Cool to warm", "Blue, grey, red"),
               ("VIRIDIS", "Viridis", "Purple, teal, yellow; easy to read for colour-blind people"),
               ("HEAT", "Heat", "Dark red, orange, yellow, white"),
               ("CUSTOM", "Custom", "From the low colour to the high colour")],
        default="RAINBOW",
    )
    gradient_low: _color("Low", (0.1, 0.2, 0.9))
    gradient_high: _color("High", (1.0, 0.2, 0.1))
    infinite_color: _color("FLT_MAX", (0.8, 0.45, 1.0), "Values such as FLT_MAX, which do not fit a gradient")

    # nodes
    node_colors: BoolProperty(name="Nodes", default=False, description="Draw nodes in colour, by what Colour by says")
    node_color_by: EnumProperty(
        name="Colour nodes by",
        items=[("PLAIN", "One colour", "Every node in the node colour"),
               ("GROUP", "Group", "A colour for each node group; nodes without one in the node colour"),
               ("PART", "Part", "A colour for each part"),
               ("nodeWeight", "nodeWeight", "Weight, on the gradient from light to heavy")],
        default="PLAIN",
    )
    node_color: _color("Node colour", (0.92, 0.92, 0.96))
    node_size: FloatProperty(name="Size", default=7.0, min=2.0, max=30.0, description="Size of nodes, in pixels")
    ghosts: BoolProperty(name="Nodes of other parts", default=True,
                         description="Mark nodes that belong to other parts, which cannot be edited here")
    ghost_color: _color("Colour of nodes of other parts", (1.0, 0.55, 0.1))
    ghost_size: FloatProperty(name="Their size", default=9.0, min=2.0, max=30.0)

    # hydros and rails
    extras: BoolProperty(name="Hydros and rails", default=True,
                         description="Draw hydros, torsion bars, rails and slide nodes, which are not mesh edges")
    extra_kinds: EnumProperty(
        name="Kinds", options={"ENUM_FLAG"},
        items=[("hydros", "Hydros", "Draw hydros"),
               ("torsionbars", "Torsion bars", "Draw torsion bars and torsion hydros"),
               ("rails", "Rails", "Draw rails and the slide nodes on them")],
        default={"hydros", "torsionbars", "rails"},
    )
    color_hydros: _color("Hydros", (0.25, 0.75, 1.0))
    color_torsionbars: _color("Torsion bars", (1.0, 0.85, 0.2))
    color_torsion_hydros: _color("Torsion hydros", (1.0, 0.5, 0.2))
    color_rails: _color("Rails", (1.0, 0.3, 0.75))
    color_slidenodes: _color("Slide nodes", (1.0, 0.3, 0.75))
    extra_width: FloatProperty(name="Width", default=3.0, min=1.0, max=12.0, step=50,
                               description="Width of hydros, torsion bars and rails, in pixels")

    # highlights
    selection: BoolProperty(name="Selection", default=True,
                            description="In Edit Mode, draw the selected beams and nodes over the colours")
    selection_color: _color("Selection colour", (1.0, 1.0, 1.0))
    problems: BoolProperty(name="Problems", default=True,
                           description="Mark repeated beams, flat triangles and quads, and nodes whose beams lead to "
                                       "nodes that do not exist")
    problem_color: _color("Problem colour", (1.0, 0.1, 0.1))

    # names
    labels: EnumProperty(
        name="Node names",
        items=[("SELECTED", "Selected", "Show the names of selected nodes in Edit Mode"),
               ("ALL", "All", "Show the names of all nodes"),
               ("NONE", "None", "Hide node names")],
        default="SELECTED",
    )
    label_size: IntProperty(name="Text size", default=12, min=6, max=40)
    label_color: _color("Name colour", (1.0, 1.0, 1.0))
    ghost_label_color: _color("Names of nodes of other parts", (1.0, 0.7, 0.35))

    # centre of mass
    center_of_mass: BoolProperty(name="Centre of mass", default=True,
                                 description="Mark the centre of mass of the vehicle or part of the active object, "
                                             "from the weights of its nodes")
    center_color: _color("Colour", (1.0, 1.0, 1.0))
    selection_center: BoolProperty(name="Of the selected nodes", default=True,
                                   description="In Edit Mode, also mark the centre of mass of all selected nodes")
    selection_center_color: _color("Colour of the selected nodes' centre", (0.3, 1.0, 0.45))
    center_label: BoolProperty(name="Show the mass", default=True, description="Write the mass next to the cross")
    center_size: FloatProperty(name="Size", default=0.12, min=0.01, max=2.0, unit="LENGTH",
                               description="Half the length of the arms of the cross")

    # text editor
    text_syntax: BoolProperty(
        name="JBeam colours", default=True,
        description="Colour parts, sections, keys, strings, variables, expressions, numbers and comments of JBeam "
                    "files in the text editor",
    )
    text_problems: BoolProperty(
        name="Show problems", default=True,
        description="Underline problems of JBeam files in the text editor and describe them after the line: syntax "
                    "errors as you type, and problems found when assembling the vehicle",
    )
    text_highlight: BoolProperty(
        name="Highlight in text", default=True,
        description="Highlight the rows of the selection in the text editor: nodes in vertex select mode, beams in "
                    "edge mode, triangles and quads in face mode",
    )
    text_select: BoolProperty(
        name="Select from text", default=True,
        description="Putting the text cursor on the row of a node, beam or face selects it in Edit Mode",
    )
    text_follow: BoolProperty(
        name="Follow selection", default=True,
        description="Scroll the text editor to the row of the active element and open its file",
    )


class JBS_PanelState(bpy.types.PropertyGroup):
    expanded_extra: StringProperty()
    severity: EnumProperty(
        name="Show",
        items=[("ALL", "All", ""), ("error", "Errors", ""), ("warning", "Warnings", ""), ("info", "Messages", "")],
        default="ALL",
    )
    all_diagnostics: BoolProperty(name="Show all", default=False)
    all_groups: BoolProperty(name="Groups of all parts", default=False,
                             description="List the node groups of every part, not only of the active part")


def settings(context=None) -> JBS_ViewSettings:
    """The display settings in use: the add-on preferences' when the add-on is installed."""
    from .preferences import preferences
    prefs = preferences()
    display = getattr(prefs, "display", None)
    return display if display is not None else (context or bpy.context).window_manager.jbs_view


def panel_state(context=None) -> JBS_PanelState:
    return (context or bpy.context).window_manager.jbs_panels


def reset(display: JBS_ViewSettings) -> None:
    for prop in display.bl_rna.properties:
        if prop.identifier != "rna_type":
            display.property_unset(prop.identifier)


CLASSES = (JBS_ViewSettings, JBS_PanelState)


def register() -> None:
    bpy.types.WindowManager.jbs_view = bpy.props.PointerProperty(type=JBS_ViewSettings)
    bpy.types.WindowManager.jbs_panels = bpy.props.PointerProperty(type=JBS_PanelState)


def unregister() -> None:
    del bpy.types.WindowManager.jbs_panels
    del bpy.types.WindowManager.jbs_view
