"""Add-on preferences: where the unpacked game vehicles are, and unpacking them."""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty

from ..blender.props import AUTO_SAVE
from ..core.edit.mirror import DEFAULT_PAIRS, parse_pairs
from .view import JBS_ViewSettings

ADDON = __package__.rpartition(".")[0]
STEAM_VEHICLES = Path(r"C:\Program Files (x86)\Steam\steamapps\common\BeamNG.drive\content\vehicles")


class JBS_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON

    vehicles_dir: StringProperty(
        name="Unpacked game vehicles", subtype="DIR_PATH",
        description="The vehicles folder of unpacked game content. Mods are assembled with the game's common "
                    "parts and vehicles from it",
    )
    game_dir: StringProperty(
        name="Game vehicle archives", subtype="DIR_PATH",
        default=str(STEAM_VEHICLES) if STEAM_VEHICLES.is_dir() else "",
        description="The content/vehicles folder of the BeamNG.drive installation",
    )
    unpack_dir: StringProperty(
        name="Unpack into", subtype="DIR_PATH",
        description="Folder that receives a vehicles folder with the .jbeam, .pc and info.json files",
    )
    auto_save: BoolProperty(**AUTO_SAVE)
    mirror_pairs_x: StringProperty(name="Side letters across X", default="l:r, ll:rr",
                                   description="Letters at the end of node ids that mirroring across X swaps")
    mirror_pairs_y: StringProperty(name="Side letters across Y", default="f:b, ff:bb",
                                   description="Letters at the end of node ids that mirroring across Y swaps")
    mirror_pairs_z: StringProperty(name="Side letters across Z", default="t:d, tt:dd",
                                   description="Letters at the end of node ids that mirroring across Z swaps")
    display: PointerProperty(type=JBS_ViewSettings)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "vehicles_dir")
        layout.prop(self, "auto_save")
        row = layout.row()
        row.label(text="Display settings are in the JBeam tab of the sidebar and in the viewport header",
                  icon="OVERLAY")
        row.operator("jbs.reset_display", icon="LOOP_BACK")
        column = layout.column(align=True)
        for axis in "xyz":
            column.prop(self, f"mirror_pairs_{axis}")
        box = layout.box()
        box.label(text="Unpack vehicles from the game", icon="PACKAGE")
        box.prop(self, "game_dir")
        box.prop(self, "unpack_dir")
        box.operator("jbs.extract_vehicles", icon="IMPORT")


def preferences():
    addon = bpy.context.preferences.addons.get(ADDON)
    return addon.preferences if addon is not None else None


def mirror_pairs(axis: str):
    """The side letters swapped across an axis, from the preferences or the built-in ones."""
    prefs = preferences()
    pairs = parse_pairs(getattr(prefs, f"mirror_pairs_{axis}", "")) if prefs is not None else ()
    return pairs or DEFAULT_PAIRS[axis]


def vehicle_roots() -> list[Path]:
    prefs = preferences()
    if prefs is None or not prefs.vehicles_dir:
        return []
    return [Path(bpy.path.abspath(prefs.vehicles_dir))]


CLASSES = (JBS_Preferences,)
