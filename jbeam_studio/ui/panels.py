"""The JBeam panel in the sidebar of the 3D viewport."""

from __future__ import annotations

import textwrap
from collections import Counter
from pathlib import Path

import bpy

from ..blender import mesh_io, sessions
from ..core import docs
from ..core.diagnostics import Severity
from ..core.edit import fixes
from ..core.physics import mass
from ..core.sjson import Kind
from . import view
from .operators import (
    EXTRA_ICONS, FIX_GROUPS, entries_of_kind, extra_key, extra_label, extra_properties, fixable, kind_of_select_mode,
    saved_time, summary, tr, value_text,
)
from .view import BEAM_TYPES, CATEGORIES, NODE_FLAGS

HIDDEN_KEYS = {"slotType", "partName", "partOrigin", "partPath", "skinName", "globalSkin", "name",
               "posX", "posY", "posZ", "id1:", "id2:", "id3:", "id4:"}
ICONS = {Severity.ERROR: "ERROR", Severity.WARNING: "ERROR", Severity.INFO: "INFO"}
DIAGNOSTICS_SHOWN = 30
EXTRAS_SHOWN = 25


_masses: dict = {}


def _mass(session, part: str | None) -> float:
    """The weight of the nodes of a part, or of the whole vehicle, worked out once for each state."""
    key = (session.key, session.link.rev, part)
    if key not in _masses:
        if len(_masses) > 64:
            _masses.clear()
        nodes = session.edit.vehicle.nodes.values()
        _masses[key] = mass(session.edit.vehicle, [n for n in nodes if part is None or n.part == part])[0]
    return _masses[key]


def _kg(value: float) -> str:
    return f"{value:,.1f}".replace(",", " ")


def wrapped(layout, text: str, width: int = 46, icon: str = "NONE") -> None:
    column = layout.column(align=True)
    for index, line in enumerate(textwrap.wrap(text, width) or [""]):
        column.label(text=line, icon=icon if index == 0 else "BLANK1" if icon != "NONE" else "NONE")


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "JBeam"


class _SessionPanel(_Panel):
    @classmethod
    def poll(cls, context):
        return sessions.session_of(context.active_object) is not None


class JBS_PT_main(_Panel, bpy.types.Panel):
    bl_idname = "JBS_PT_main"
    bl_label = "JBeam Studio"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("jbs.import_pc", text="Vehicle (.pc)", icon="IMPORT")
        row.operator("jbs.import_jbeam", text="Parts (.jbeam)", icon="IMPORT")
        obj = context.active_object
        session = sessions.session_of(obj)
        if session is None:
            if sessions.is_copy(obj):
                box = layout.box()
                wrapped(box, tr("This object is a copy of a JBeam object, so it is not linked to the files."),
                        icon="INFO")
                box.operator("jbs.detach")
            elif obj is not None and obj.type == "MESH" and obj.jbs.kind != "NONE":
                box = layout.box()
                wrapped(box, tr("The JBeam files of this object are not loaded."), icon="INFO")
                box.operator("jbs.load_object", icon="FILE_REFRESH")
                box.operator("jbs.detach")
            else:
                layout.label(text="Import a vehicle or a part to edit it", icon="INFO")
            return
        settings = obj.jbs
        box = layout.box()
        column = box.column(align=True)
        column.label(text=Path(settings.path).name, icon="FILE_3D" if settings.kind == "PC" else "FILE")
        column.label(text=summary(session))
        total = _mass(session, None)
        if session.scope is None:
            column.label(text=tr("Mass: {mass} kg").format(mass=_kg(total)))
            box.prop(settings, "active_part", icon="OBJECT_DATA")
        else:
            column.label(text=tr("Mass: {mass} kg, this part {part} kg").format(
                mass=_kg(total), part=_kg(_mass(session, session.scope))))
            row = box.row(align=True)
            row.label(text=tr("Part: {part}").format(part=session.scope), icon="OBJECT_DATA")
            row.prop(settings, "all_nodes", text="", icon="OUTLINER_OB_POINTCLOUD", toggle=True)

        if session.stale:
            alert = layout.box()
            alert.alert = True
            wrapped(alert, tr(sessions.STALE), icon="ERROR")
            alert.operator("jbs.rebuild", icon="FILE_REFRESH")
        elif session.error:
            alert = layout.box()
            alert.alert = True
            wrapped(alert, tr("Mesh edits were not applied") + ": " + session.error, icon="ERROR")
        if session.cursor_warning:
            alert = layout.box()
            alert.alert = True
            row = alert.row()
            wrapped(row, tr(session.cursor_warning), icon="QUESTION")
            row.operator("jbs.dismiss_cursor_warning", text="", icon="X")
        if obj.mode == "EDIT":
            if settings.live_apply:
                layout.label(text="Edits are applied right away", icon="INFO")
            elif settings.apply_on_exit:
                layout.label(text="Edits are applied when leaving Edit Mode", icon="INFO")
        elif not session.stale and not sessions.in_sync(obj, session):
            layout.label(text="The mesh has edits that are not applied", icon="ERROR")
        plan = session.last_plan
        if plan is not None:
            for count, text in ((plan.ghosts_moved, "{} nodes of other parts were moved back"),
                                (plan.ghosts_deleted, "{} nodes of other parts were restored"),
                                (plan.ngons, "{} faces with more than four corners were dropped")):
                if count:
                    layout.label(text=tr(text).format(count), icon="INFO")
        for note in list(session.edit.notes)[:3]:
            wrapped(layout, note.message, icon="INFO")

        box_actions = layout.box()
        col = box_actions.column(align=True)
        row = col.row(align=True)
        row.scale_y = 1.15
        row.operator("jbs.apply_mesh", text="Apply", icon="CHECKMARK")
        row.operator("jbs.save", text="Save", icon="FILE_TICK")

        row = col.row(align=True)
        owner, name = sessions.auto_save_owner()
        row.prop(owner, name, text="Auto Save", icon="AUTO", toggle=True)
        row.prop(settings, "place_at_cursor", text="At Cursor", icon="TEXT", toggle=True)
        if not sessions.auto_save_enabled():
            for text in sessions.edited_texts(session):
                box = layout.box()
                box.alert = True
                wrapped(box, tr("Text edits in {name} are not applied yet").format(name=text.name), icon="TEXT")
                row = box.row(align=True)
                row.operator("jbs.apply_text", text="Apply", icon="CHECKMARK").text_name = text.name
                row.operator("jbs.discard_text", text="Discard", icon="X").text_name = text.name
        if sessions.auto_save_enabled() and session.save_error:
            alert = layout.box()
            alert.alert = True
            wrapped(alert, tr("Files were not saved") + ": " + session.save_error, icon="ERROR")
        dirty = session.edit.dirty_files()
        if dirty:
            layout.label(text=tr("Unsaved files: {files}").format(files=", ".join(p.name for p in dirty[:3])
                                                                   + (" \u2026" if len(dirty) > 3 else "")),
                         icon="FILE_BLEND")
        elif session.saved_at is not None:
            wrapped(layout, tr("Saved at {time}: {files}").format(time=saved_time(session),
                                                                  files=", ".join(session.saved_files)),
                    icon="CHECKMARK")
        if session.changed_on_disk:
            alert = layout.box()
            alert.alert = True
            wrapped(alert, tr("Changed on disk: {files}").format(
                files=", ".join(p.name for p in session.changed_on_disk)), icon="ERROR")
            row = alert.row(align=True)
            row.operator("jbs.reload", icon="FILE_REFRESH")
            row.operator("jbs.save", text="Save Anyway").overwrite = True
        row = layout.row(align=True)
        row.operator("jbs.rebuild", text="Rebuild", icon="FILE_REFRESH")
        row.operator("jbs.rescan", text="Find Files", icon="VIEWZOOM")


class JBS_PT_settings(_SessionPanel, bpy.types.Panel):
    bl_idname = "JBS_PT_settings"
    bl_label = "Editing"
    bl_parent_id = "JBS_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.active_object.jbs

        box_place = layout.box()
        box_place.label(text="Where New Rows Go", icon="PLUS")
        row = box_place.row(align=True)
        row.prop(settings, "place_at_cursor", toggle=True, icon="TEXT")
        box_place.prop(settings, "placement", expand=True)
        if settings.placement == "group":
            box_place.prop(settings, "new_group", icon="GROUP_VERTEX")

        box_node = layout.box()
        box_node.label(text="Node Naming & Coords", icon="SORTALPHA")
        box_node.prop(settings, "move_mode", expand=True)
        col = box_node.column(align=True)
        col.prop(settings, "auto_names")
        col.prop(settings, "node_prefix")

        box_sync = layout.box()
        box_sync.label(text="Synchronization", icon="FILE_REFRESH")
        col = box_sync.column(align=True)
        col.prop(settings, "live_apply")
        col.prop(settings, "apply_on_exit")
        col.prop(settings, "allow_shared")


def _raw_cell(entry, key: str) -> str | None:
    """The text of the row cell that sets `key`, when it is a variable or an expression."""
    columns = getattr(entry.props, "columns", None)
    src = entry.src
    if not columns or key not in columns or src is None or src.node.kind is not Kind.ARRAY:
        return None
    index = columns.index(key)
    if index >= len(src.node.items):
        return None
    cell = src.node.items[index]
    if cell.kind is Kind.STRING and isinstance(cell.value, str) and cell.value.startswith("$"):
        return cell.value
    return None


def _format(value) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        return ", ".join(_format(v) for v in value)
    return str(value)


_MISSING = object()
SECTIONS = {"nodes": "nodes", "beams": "beams", "faces": "triangles"}
TITLES = {"nodes": "{count} nodes selected", "beams": "{count} beams selected",
          "faces": "{count} triangles and quads selected"}


def _properties(layout, kind: str, entries: list) -> None:
    """The properties of the entries, with their common value or "mixed", each with an edit button."""
    keys: dict[str, None] = {}
    for entry in entries:
        keys.update(dict.fromkeys(k for k in entry.props if isinstance(k, str) and k not in HIDDEN_KEYS))
    column = layout.column(align=True)
    for key in keys:
        values = [entry.props.get(key, _MISSING) for entry in entries]
        same = all(v == values[0] for v in values[1:])
        shown = _format(values[0]) if same and values[0] is not _MISSING else tr("mixed")
        raw = _raw_cell(entries[0], key) if len(entries) == 1 else None
        row = column.row(align=True)
        row.label(text=f"{key}: {shown}" + (f"  ({raw})" if raw else ""))
        edit = row.operator("jbs.set_property", text="", icon="GREASEPENCIL")
        edit.kind, edit.key = kind, key
        edit.value = value_text(values[0]) if same and values[0] is not _MISSING else ""
        doc = docs.lookup(SECTIONS[kind], key)
        if doc is not None and doc.url:
            row.operator("wm.url_open", text="", icon="QUESTION").url = doc.url
    row = layout.row(align=True)
    row.operator("jbs.set_property", text="Set Property", icon="ADD").kind = kind
    row.operator("jbs.select_by_property", icon="RESTRICT_SELECT_OFF").kind = kind


class JBS_PT_selection(_SessionPanel, bpy.types.Panel):
    bl_idname = "JBS_PT_selection"
    bl_label = "Selection"
    bl_parent_id = "JBS_PT_main"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        session = sessions.session_of(obj)
        if obj.mode != "EDIT":
            layout.label(text="Select nodes and beams in Edit Mode", icon="INFO")
            return
        kind = kind_of_select_mode(context)
        entries = entries_of_kind(obj, session, kind)
        if not entries:
            layout.label(text="Nothing selected")
            layout.operator("jbs.select_by_property", icon="RESTRICT_SELECT_OFF").kind = kind
            return
        layout.label(text=tr(TITLES[kind]).format(count=len(entries)))
        if kind == "nodes":
            layout.label(text=tr("Mass of the selection: {mass} kg").format(
                mass=_kg(mass(session.edit.vehicle, entries)[0])), icon="PHYSICS")
        if kind == "nodes" and len(entries) > 1:
            layout.label(text=", ".join(e.id for e in entries[:12]) + (" \u2026" if len(entries) > 12 else ""))
        if kind == "nodes" and len(entries) == 1:
            node = entries[0]
            box = layout.box()
            box.label(text=node.id, icon="DOT")
            if node.id in session.edit.vehicle.external_nodes or session.scope not in (None, node.part):
                box.label(text="Node of another part, shown for reference", icon="INFO")
            box.label(text=tr("Part: {part}").format(part=node.part or "?"))
            box.label(text="X {:.3f}   Y {:.3f}   Z {:.3f}".format(*node.pos))
            raw = [r for r in (_raw_cell(node, k) for k in ("posX", "posY", "posZ")) if r]
            if raw:
                wrapped(box, tr("Position from: {expressions}").format(expressions=", ".join(raw)))
        elif kind == "beams" and len(entries) <= 4:
            layout.label(text=", ".join(f"{b.id1} \u2013 {b.id2}" for b in entries), icon="IPO_LINEAR")
        elif kind == "faces" and len(entries) <= 3:
            layout.label(text="; ".join(", ".join(f.ids) for f in entries), icon="MESH_DATA")
        _properties(layout.box(), kind, entries)


class JBS_PT_groups(_SessionPanel, bpy.types.Panel):
    bl_idname = "JBS_PT_groups"
    bl_label = "Groups"
    bl_parent_id = "JBS_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        session = sessions.session_of(obj)
        state = view.panel_state(context)
        layout.prop(state, "all_groups")
        groups = session.edit.node_groups(None if state.all_groups else obj.jbs.active_part or None)
        if not groups:
            layout.label(text="No node groups", icon="INFO")
            return
        hidden = _hidden_nodes(obj, session) if obj.mode == "EDIT" else set()
        column = layout.column(align=True)
        for name, members in sorted(groups.items()):
            row = column.row(align=True)
            row.label(text=f"{name}  ({len(members)})", icon="GROUP_VERTEX")
            if obj.mode == "EDIT":
                row.operator("jbs.group_select", text="", icon="RESTRICT_SELECT_OFF").group = name
                is_hidden = all(m in hidden for m in members)
                toggle = row.operator("jbs.group_hide", text="", icon="HIDE_ON" if is_hidden else "HIDE_OFF")
                toggle.group, toggle.hide = name, not is_hidden
            row.operator("jbs.rename_group", text="", icon="SORTALPHA").group = name


class JBS_PT_extras(_SessionPanel, bpy.types.Panel):
    bl_idname = "JBS_PT_extras"
    bl_label = "Hydros and Rails"
    bl_parent_id = "JBS_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        session = sessions.session_of(obj)
        if obj.mode == "EDIT":
            grid = layout.grid_flow(columns=2, align=True)
            grid.operator("jbs.add_extra", text="Hydro", icon=EXTRA_ICONS["hydros"]).section = "hydros"
            grid.operator("jbs.add_extra", text="Torsion Bar", icon=EXTRA_ICONS["torsionbars"]).section = "torsionbars"
            grid.operator("jbs.add_rail", text="Rail", icon=EXTRA_ICONS["rails"])
            grid.operator("jbs.add_slidenodes", text="Slide Nodes", icon=EXTRA_ICONS["slidenodes"])
        else:
            layout.label(text="Add them from selected nodes in Edit Mode", icon="INFO")
        extras = session.edit.vehicle.extras
        if not extras:
            layout.label(text="No hydros, torsion bars or rails")
            return
        selected = set(sessions.selected_node_ids(obj, session)) if obj.mode == "EDIT" else set()
        shown = [(i, e) for i, e in enumerate(extras) if not selected or selected & set(e.ids)]
        layout.label(text=tr("Using the selected nodes: {count}").format(count=len(shown)) if selected
                     else tr("All: {count}").format(count=len(shown)))
        column = layout.column(align=True)
        expanded = view.panel_state(context).expanded_extra
        for index, extra in shown[:EXTRAS_SHOWN]:
            key = extra_key(extra)
            row = column.row(align=True)
            row.operator("jbs.expand_extra", text="", emboss=False,
                         icon="TRIA_DOWN" if key == expanded else "TRIA_RIGHT").key = key
            row.label(text=extra_label(extra), icon=EXTRA_ICONS[extra.section])
            if obj.mode == "EDIT":
                row.operator("jbs.select_extra", text="", icon="RESTRICT_SELECT_OFF").index = index
            row.operator("jbs.delete_extra", text="", icon="X").index = index
            if key == expanded:
                box = column.box()
                box.label(text=tr("Part: {part}").format(part=session.edit.extra_part(extra) or "?"))
                for name, value in extra_properties(extra):
                    line = box.row(align=True)
                    line.label(text=f"{name}: {_format(value)}")
                    edit = line.operator("jbs.set_extra_property", text="", icon="GREASEPENCIL")
                    edit.extra, edit.key, edit.value = key, name, value_text(value)
                box.operator("jbs.set_extra_property", text="Set Property", icon="ADD").extra = key
        if len(shown) > EXTRAS_SHOWN:
            column.label(text=tr("and {count} more").format(count=len(shown) - EXTRAS_SHOWN))


def _hidden_nodes(obj, session) -> set[str]:
    bm, uid_layer, check_layer, _ = mesh_io.edit_mesh_uids(obj)
    if uid_layer is None or check_layer is None:
        return set()
    return {session.link.node_of(v[uid_layer], v[check_layer]) for v in bm.verts if v.hide}


class JBS_PT_tools(_SessionPanel, bpy.types.Panel):
    bl_idname = "JBS_PT_tools"
    bl_label = "Tools"
    bl_parent_id = "JBS_PT_main"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        session = sessions.session_of(obj)

        box_edit = layout.box()
        box_edit.label(text="Edit & Clipboard", icon="EDITMODE_HLT")
        row = box_edit.row(align=True)
        row.operator("jbs.copy_nodes", icon="COPYDOWN", text="Copy")
        row.operator("jbs.cut_nodes", icon="REMOVE", text="Cut")
        row.operator("jbs.delete_nodes", icon="TRASH", text="Delete")
        row = box_edit.row(align=True)
        row.operator("jbs.rename_node", icon="SORTALPHA", text="Rename")
        row.operator("jbs.rename_nodes", icon="LINENUMBERS_ON", text="Batch Rename")

        box_mirror = layout.box()
        box_mirror.label(text="Symmetry & Mirror", icon="MOD_MIRROR")
        col = box_mirror.column(align=True)
        row = col.row(align=True)
        row.prop(obj.jbs, "mirror_axis", expand=True)
        row.prop(obj.jbs, "mirror_plane", text="")
        col.operator("jbs.mirror", icon="MOD_MIRROR", text="Mirror Selected Nodes")
        if obj.mode == "EDIT":
            col_sym = box_mirror.column(align=True)
            col_sym.label(text="Live Mesh Symmetry:")
            row = col_sym.row(align=True)
            for axis in "xyz":
                row.prop(obj.data, f"use_mirror_{axis}", text=axis.upper(), toggle=True)

        box_mesh = layout.box()
        box_mesh.label(text="Mesh Operations", icon="MESH_DATA")
        col_mesh = box_mesh.column(align=True)
        col_mesh.operator("jbs.flip_faces", icon="UV_SYNC_SELECT")
        col_mesh.operator("jbs.select_part", icon="RESTRICT_SELECT_OFF")
        col_mesh.operator("jbs.add_resets", icon="LOOP_BACK")


class JBS_PT_diagnostics(_SessionPanel, bpy.types.Panel):
    bl_idname = "JBS_PT_diagnostics"
    bl_label = "Diagnostics"
    bl_parent_id = "JBS_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        session = sessions.session_of(context.active_object)
        diagnostics = session.edit.vehicle.diagnostics
        errors, warnings = len(diagnostics.errors()), len(diagnostics.warnings())
        if errors or warnings:
            self.layout.label(text=f"{errors} / {warnings}", icon="ERROR" if errors else "INFO")

    def draw(self, context):
        layout = self.layout
        state = view.panel_state(context)
        session = sessions.session_of(context.active_object)
        layout.prop(state, "severity", expand=True)
        shown = [(i, d) for i, d in enumerate(session.edit.vehicle.diagnostics)
                 if state.severity == "ALL" or d.severity.value == state.severity]
        if not shown:
            layout.label(text="No problems found", icon="CHECKMARK")
            return
        groups = Counter(fixes.group_of(d) for d in fixable(session))
        if groups:
            column = layout.column(align=True)
            for group, (label, _) in FIX_GROUPS.items():
                if groups[group]:
                    column.operator("jbs.fix", text=tr(label).format(count=groups[group]),
                                    icon="TOOL_SETTINGS").group = group
        limit = len(shown) if state.all_diagnostics else DIAGNOSTICS_SHOWN
        for index, diagnostic in shown[:limit]:
            box = layout.box()
            row = box.row()
            row.alert = diagnostic.severity is Severity.ERROR
            column = row.column(align=True)
            where = Path(diagnostic.file).name + (f":{diagnostic.line}" if diagnostic.line else "") if diagnostic.file else ""
            wrapped(column, (f"{where}: " if where else "") + diagnostic.message, width=40,
                    icon=ICONS[diagnostic.severity])
            if fixes.group_of(diagnostic):
                row.operator("jbs.fix", text="", icon="TOOL_SETTINGS").index = index
            if diagnostic.file:
                operator = row.operator("jbs.show_text", text="", icon="TEXT")
                operator.path = diagnostic.file
                operator.line = diagnostic.line or 0
        if len(shown) > DIAGNOSTICS_SHOWN:
            layout.prop(state, "all_diagnostics", text=tr("Show all {count}").format(count=len(shown)))


class JBS_PT_text(_Panel, bpy.types.Panel):
    bl_idname = "JBS_PT_text"
    bl_label = "Text Editor"
    bl_parent_id = "JBS_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        session = sessions.session_of(context.active_object)
        if session is not None:
            layout.operator("jbs.show_text", icon="TEXT")
        display = view.settings(context)
        box = layout.box()
        box.label(text="Text Sync & Highlighting", icon="TEXT")
        column = box.column(align=True)
        row = column.row(align=True)
        row.prop(display, "text_highlight", toggle=True, icon="SELECT_SET")
        row.prop(display, "text_follow", toggle=True, icon="VIEWZOOM")
        row = column.row(align=True)
        row.prop(display, "text_select", toggle=True, icon="RESTRICT_SELECT_OFF")
        row.prop(display, "text_syntax", toggle=True, icon="COLOR")
        column.prop(display, "text_problems", toggle=True, icon="ERROR")
        if session is None:
            return
        for text in bpy.data.texts:
            if text.get(sessions.TEXT_SESSION) == session.key and sessions.text_edited(text):
                layout.operator("jbs.apply_text", text=tr("Apply {name}").format(name=text.name),
                                icon="CHECKMARK").text_name = text.name


# display settings, in the sidebar and in the viewport header

def _split(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False
    return layout


def _gradient(layout, display) -> None:
    layout.prop(display, "palette")
    if display.palette == "CUSTOM":
        layout.prop(display, "gradient_low")
        layout.prop(display, "gradient_high")
    layout.prop(display, "infinite_color")


def draw_display(layout, display) -> None:
    box = layout.box()
    box.label(text="Visibility & Scope", icon="RESTRICT_VIEW_OFF")
    box.prop(display, "scope", expand=True)
    row = box.row(align=True)
    row.active = display.scope != "ALL"
    row.prop(display, "dim_others", toggle=True, icon="GHOST_ENABLED")
    sub = row.row(align=True)
    sub.active = display.dim_others and display.scope != "ALL"
    sub.prop(display, "dim_opacity", text="", slider=True)

    col = box.column(align=True)
    row = col.row(align=True)
    row.prop(display, "occlude_selection", text="Only Visible", toggle=True, icon="VIS_SEL_11")
    row.prop(display, "through_faces", text="Through Faces", toggle=True, icon="MOD_WIREFRAME")
    row = col.row(align=True)
    row.prop(display, "legend", text="Show Legend", toggle=True, icon="PRESET")
    row.prop(display, "line_opacity", text="Opacity", slider=True)


def draw_display_beams(layout, display) -> None:
    layout = _split(layout)
    layout.active = display.beam_colors
    layout.prop(display, "beam_color_by", text="Colour by")
    by = display.beam_color_by
    if by == "TYPE" or by in CATEGORIES:
        row = layout.row(heading=tr("Normal beams") if by == "TYPE" else tr("Without a group"))
        row.prop(display, "normal_beams", text="")
        sub = row.row()
        sub.active = display.normal_beams
        sub.prop(display, "normal_color", text="")
    if by == "TYPE":
        column = layout.column(align=True)
        for _beam_type, name in BEAM_TYPES:
            column.prop(display, name)
        column.prop(display, "color_unknown")
    elif by not in CATEGORIES:
        _gradient(layout, display)
    layout.prop(display, "line_width")


def draw_display_nodes(layout, display) -> None:
    layout = _split(layout)
    column = layout.column()
    column.active = display.node_colors
    column.prop(display, "node_color_by", text="Colour by")
    if display.node_color_by == "nodeWeight":
        _gradient(column, display)
    if display.node_color_by == "FLAGS":
        flags = column.column(align=True)
        for _flag, name in NODE_FLAGS:
            flags.prop(display, name)
        flags.prop(display, "node_color", text="Other nodes")
    else:
        column.prop(display, "node_color", text="Colour" if display.node_color_by == "PLAIN" else "Without a group")
    column.prop(display, "node_size")
    row = layout.row(heading=tr("Other parts"))
    row.prop(display, "ghosts", text="")
    sub = row.row(align=True)
    sub.active = display.ghosts
    sub.prop(display, "ghost_color", text="")
    sub.prop(display, "ghost_size", text="")


def draw_display_extras(layout, display) -> None:
    layout.active = display.extras
    layout.row(align=True).prop(display, "extra_kinds", expand=True)
    layout = _split(layout)
    layout.prop(display, "color_hydros")
    column = layout.column(align=True)
    for name in ("color_torsionbars", "color_torsionbars_second", "color_torsion_axis", "color_torsion_anisotropic",
                 "color_torsion_anisotropic_second"):
        column.prop(display, name)
    layout.prop(display, "rail_colors")
    if display.rail_colors == "ONE":
        layout.prop(display, "color_rails")
    layout.prop(display, "extra_width")


def draw_display_highlights(layout, display) -> None:
    layout = _split(layout)
    for switch, color in (("selection", "selection_color"), ("problems", "problem_color")):
        row = layout.row(heading=display.bl_rna.properties[switch].name)
        row.prop(display, switch, text="")
        sub = row.row()
        sub.active = getattr(display, switch)
        sub.prop(display, color, text="")


def draw_display_names(layout, display) -> None:
    layout.row(align=True).prop(display, "labels", expand=True)
    layout = _split(layout)
    layout.active = display.labels != "NONE"
    layout.prop(display, "label_size")
    layout.prop(display, "label_color", text="Colour")
    layout.prop(display, "ghost_label_color", text="Other parts")


def draw_display_center(layout, display) -> None:
    layout = _split(layout)
    row = layout.row()
    row.active = display.center_of_mass
    row.prop(display, "center_color")
    row = layout.row(heading=tr("Selected nodes"))
    row.prop(display, "selection_center", text="")
    sub = row.row()
    sub.active = display.selection_center
    sub.prop(display, "selection_center_color", text="")
    layout.prop(display, "center_label")
    layout.prop(display, "center_size")


DISPLAY_SECTIONS = (
    ("beams", "Beams", draw_display_beams, "beam_colors", False),
    ("nodes", "Nodes", draw_display_nodes, "node_colors", False),
    ("extras", "Hydros and Rails", draw_display_extras, "extras", True),
    ("highlights", "Selection and Problems", draw_display_highlights, None, True),
    ("names", "Node Names", draw_display_names, None, True),
    ("center", "Centre of Mass", draw_display_center, "center_of_mass", True),
)
"""Parts of the display settings: name, title, how to draw them, the switch in their header, closed at first."""


class JBS_PT_display(_Panel, bpy.types.Panel):
    bl_idname = "JBS_PT_display"
    bl_label = "Display"
    bl_parent_id = "JBS_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header_preset(self, _context):
        self.layout.operator("jbs.reset_display", text="", icon="LOOP_BACK", emboss=False)

    def draw(self, context):
        draw_display(self.layout, view.settings(context))


class JBS_PT_overlay(bpy.types.Panel):
    bl_idname = "JBS_PT_overlay"
    bl_label = "JBeam Display"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 14

    def draw(self, context):
        row = self.layout.row()
        row.label(text="JBeam Display", icon="OVERLAY")
        row.operator("jbs.reset_display", text="", icon="LOOP_BACK", emboss=False)
        draw_display(self.layout, view.settings(context))


def _drawer(draw):
    def method(self, context):
        draw(self.layout, view.settings(context))
    return method


def _switch(name: str):
    def method(self, context):
        self.layout.prop(view.settings(context), name, text="")
    return method


def _section_panels(parent: type, prefix: str) -> list[type]:
    classes = []
    for name, title, draw, switch, closed in DISPLAY_SECTIONS:
        attributes = {
            "bl_idname": f"{prefix}_{name}", "bl_label": title, "bl_space_type": "VIEW_3D",
            "bl_region_type": parent.bl_region_type, "bl_parent_id": parent.bl_idname,
            "bl_options": {"DEFAULT_CLOSED"} if closed else set(), "draw": _drawer(draw),
        }
        if parent.bl_region_type == "UI":
            attributes["bl_category"] = _Panel.bl_category
        if switch is not None:
            attributes["draw_header"] = _switch(switch)
        classes.append(type(f"{prefix}_{name}", (bpy.types.Panel,), attributes))
    return classes


CLASSES = (JBS_PT_main, JBS_PT_selection, JBS_PT_display, *_section_panels(JBS_PT_display, "JBS_PT_display"),
           JBS_PT_text, JBS_PT_settings, JBS_PT_tools, JBS_PT_groups, JBS_PT_extras, JBS_PT_diagnostics,
           JBS_PT_overlay, *_section_panels(JBS_PT_overlay, "JBS_PT_overlay"))
