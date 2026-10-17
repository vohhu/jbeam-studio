"""Display settings of the JBeam panel, kept for the Blender session and not saved in .blend files."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty


class JBS_ViewSettings(bpy.types.PropertyGroup):
    labels: EnumProperty(
        name="Node names",
        items=[("SELECTED", "Selected", "Show the names of selected nodes in Edit Mode"),
               ("ALL", "All", "Show the names of all nodes"),
               ("NONE", "None", "Hide node names")],
        default="SELECTED",
    )
    label_size: IntProperty(name="Text size", default=12, min=6, max=40)
    ghosts: BoolProperty(name="Mark nodes of other parts", default=True,
                         description="Draw nodes that belong to other parts, which cannot be edited here, in orange")
    beam_colors: BoolProperty(name="Beam types", default=True,
                              description="Draw beams of special types in colour: SUPPORT, BOUNDED, ANISOTROPIC, "
                                          "LBEAM, PRESSURED; types the game does not know in red")
    group_colors: BoolProperty(name="Node groups", default=False,
                               description="Draw each node in the colour of its group")
    extras: BoolProperty(name="Hydros and rails", default=True,
                         description="Draw hydros, torsion bars, rails and slide nodes, which are not mesh edges")
    expanded_extra: StringProperty()
    legend: BoolProperty(name="Legend", default=True, description="Show what the colours mean in the viewport")
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
    severity: EnumProperty(
        name="Show",
        items=[("ALL", "All", ""), ("error", "Errors", ""), ("warning", "Warnings", ""), ("info", "Messages", "")],
        default="ALL",
    )
    all_diagnostics: BoolProperty(name="Show all", default=False)
    all_groups: BoolProperty(name="Groups of all parts", default=False,
                             description="List the node groups of every part, not only of the active part")


CLASSES = (JBS_ViewSettings,)


def register() -> None:
    bpy.types.WindowManager.jbs_view = bpy.props.PointerProperty(type=JBS_ViewSettings)


def unregister() -> None:
    del bpy.types.WindowManager.jbs_view
