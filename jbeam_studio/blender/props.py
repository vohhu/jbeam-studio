"""Settings stored on JBeam objects, saved with the .blend file."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import sessions


def auto_save_changed(_self, _context) -> None:
    if sessions.auto_save_enabled():
        for obj, session in sessions.jbeam_objects():
            sessions.autosave(obj, session)


def _search_groups(self, context, edit_text):
    session = sessions.SESSIONS.get(self.session_key)
    if session is None:
        return []
    found: dict[str, None] = {}
    for node in session.edit.vehicle.nodes.values():
        if node.part != self.active_part and self.active_part:
            continue
        value = node.props.get("group")
        for name in (value if isinstance(value, list) else [value]):
            if isinstance(name, str) and name:
                found[name] = None
    text = edit_text.lower()
    return [name for name in found if text in name.lower()]


def _search_parts(self, context, edit_text):
    session = sessions.SESSIONS.get(self.session_key)
    if session is None:
        return []
    text = edit_text.lower()
    return [name for name in session.link.part_names if text in name.lower()]


class JBS_ObjectSettings(bpy.types.PropertyGroup):
    kind: EnumProperty(
        name="Source",
        items=[("NONE", "None", "Not a JBeam object"),
               ("PC", "Vehicle", "A vehicle assembled from a part config (.pc)"),
               ("PART", "Part", "One part of a .jbeam file")],
        default="NONE",
    )
    path: StringProperty(name="File", subtype="FILE_PATH")
    part_name: StringProperty(name="Part")
    vehicle_roots: StringProperty(name="Other vehicles folders", description="Folders separated by ;")
    session_key: StringProperty()
    active_part: StringProperty(
        name="Active part", search=_search_parts,
        description="Part that new nodes, beams, triangles and quads are added to when they do not come from a node "
                    "of a part; a node extruded or copied from a node goes to that node's part",
    )
    auto_names: BoolProperty(
        name="Name new nodes after their neighbours", default=True,
        description="Name a new node like the node it was extruded or copied from, or the node it is joined to: "
                    "the same prefix, the next number and the side letter of its position, as e3l gives e5l or e5r",
    )
    node_prefix: StringProperty(name="New node prefix", default="n",
                                description="New nodes without neighbours are named with this prefix and a number")
    placement: EnumProperty(
        name="Where new rows go",
        items=[("end", "End of table", "After the last row and the resets, with the default values"),
               ("source", "Next to the source",
                "Right after the row of the node, beam or face they come from, with its group and values"),
               ("group", "Into a group", "At the end of the rows of the chosen node group, with its values")],
        default="end",
    )
    new_group: StringProperty(name="Group", search=_search_groups,
                              description="Node group that new nodes, and beams and faces between its nodes, join")
    mirror_axis: EnumProperty(
        name="Mirror axis",
        items=[("x", "X", "Mirror left and right (l and r)"), ("y", "Y", "Mirror front and back (f and b)"),
               ("z", "Z", "Mirror top and down (t and d)")],
        default="x",
    )
    mirror_plane: EnumProperty(
        name="Mirror plane",
        items=[("origin", "Origin", "The plane through 0 of the vehicle"),
               ("cursor", "3D Cursor", "The plane through the 3D cursor"),
               ("active", "Active node", "The plane through the active node, such as the mast of a rotor")],
        default="origin",
    )
    move_mode: EnumProperty(
        name="Moving nodes",
        items=[("overwrite", "Overwrite coordinates",
                "Write the new position as plain numbers, replacing variables and expressions"),
               ("keep_expressions", "Keep expressions",
                "Keep variables and expressions and add the shift to them")],
        default="overwrite",
    )
    allow_shared: BoolProperty(
        name="Edit shared rows",
        description="Allow edits of rows that also define entries in other slots, which then change too",
    )
    live_apply: BoolProperty(
        name="Apply right away", default=True,
        description="Write mesh edits to the JBeam files in memory after every operation in Edit Mode, so the text "
                    "and, with Auto, the files follow the mesh as you edit",
    )
    apply_on_exit: BoolProperty(name="Apply when leaving Edit Mode", default=True,
                                description="Write mesh edits to the JBeam files in memory when leaving Edit Mode")


AUTO_SAVE = dict(
    name="Save after changes", update=auto_save_changed,
    description="Write the changed files to disk after every applied edit, rename, undo and redo",
)
CLASSES = (JBS_ObjectSettings,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.jbs = bpy.props.PointerProperty(type=JBS_ObjectSettings)
    bpy.types.WindowManager.jbs_auto_save = BoolProperty(**AUTO_SAVE)


def unregister() -> None:
    del bpy.types.WindowManager.jbs_auto_save
    del bpy.types.Object.jbs
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
