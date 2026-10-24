"""Operators of the JBeam panel and the import menu."""

from __future__ import annotations

import contextlib
import json
import math
import time
from pathlib import Path

import bmesh
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from ..blender import mesh_io, sessions
from ..core import docs
from ..core.edit import EditError, ExternalChangeError, fixes
from ..core.edit.mirror import AXES, mirror
from ..core.edit.session import EXTRA_COLUMNS
from ..core.extract import extract_vehicles
from . import preferences, view


def tr(text: str) -> str:
    return bpy.app.translations.pgettext_iface(text)


def active(context):
    """The active object and its session, which first takes changes other sessions made to its files."""
    obj = context.active_object
    session = sessions.session_of(obj)
    if session is not None:
        sessions.ensure_current(session.group)
    return obj, session


class _SessionPoll:
    @classmethod
    def poll(cls, context):
        return sessions.session_of(context.active_object) is not None


class _EditModePoll:
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.mode == "EDIT" and sessions.session_of(obj) is not None


@contextlib.contextmanager
def object_mode(obj):
    """Runs the block in Object Mode and returns to Edit Mode afterwards if the object was in it."""
    was_editing = obj.mode == "EDIT"
    if was_editing:
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        yield
    finally:
        if was_editing:
            bpy.ops.object.mode_set(mode="EDIT")


def summary(session) -> str:
    vehicle = session.edit.vehicle
    return tr("{nodes} nodes, {beams} beams, {triangles} triangles, {quads} quads").format(
        nodes=len(vehicle.nodes), beams=len(vehicle.beams), triangles=len(vehicle.triangles), quads=len(vehicle.quads))


def plan_summary(plan) -> str:
    parts = []
    for count, text in ((len(plan.moves), "moved {} nodes"), (len(plan.new_nodes), "added {} nodes"),
                        (len(plan.deleted_nodes), "deleted {} nodes"), (len(plan.new_beams), "added {} beams"),
                        (len(plan.deleted_beams), "deleted {} beams"), (len(plan.new_faces), "added {} faces"),
                        (len(plan.deleted_faces), "deleted {} faces"), (len(plan.flipped_faces), "flipped {} faces")):
        if count:
            parts.append(tr(text).format(count))
    return ", ".join(parts)


def saved_time(session) -> str:
    return time.strftime("%H:%M:%S", time.localtime(session.saved_at))


def report_save_problem(operator, session) -> None:
    if session.save_error:
        operator.report({"WARNING"}, tr("Files were not saved") + ": " + session.save_error)


def _commit(operator, obj, session) -> bool:
    """Before an operator changes the session in Edit Mode: applies the mesh edits into the mesh and session."""
    if obj.mode != "EDIT":
        return True
    try:
        sessions.commit_edit_mesh(obj, session)
    except EditError as error:
        operator.report({"ERROR"}, str(error))
        return False
    return True


def _start_in_object_mode(context) -> None:
    obj = context.active_object
    if obj is not None and obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _select_only(context, obj) -> None:
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _finish_import(operator, context, imports: list[tuple[str, Path, list[str]]], skip_empty: bool = False):
    """Imports vehicles (kind "PC") and parts of .jbeam files (kind "PART" with part names), selects what was
    imported with the main part of the first vehicle active, and reports what was loaded. With `skip_empty`
    parts without nodes, beams or faces are left out."""
    _start_in_object_mode(context)
    objects = []
    requested = sum(len(parts) for _, _, parts in imports)
    for kind, path, parts in imports:
        try:
            objects += sessions.create_objects(context, kind, path, parts, preferences.vehicle_roots(), skip_empty)
        except (OSError, EditError) as error:
            operator.report({"ERROR"}, f"{path.name}: {error}")
    if not objects:
        if skip_empty:
            operator.report({"WARNING"}, tr("None of the parts has nodes, beams or faces"))
        return {"CANCELLED"}
    session = sessions.session_of(objects[0])
    main = session.edit.vehicle.main_part
    obj = next((o for o in objects if o.jbs.part_name == main and sessions.session_of(o).group is session.group),
               objects[0])
    _select_only(context, obj)
    for other in objects:
        other.select_set(True)
    groups = list({id(s.group): s.group for s in map(sessions.session_of, objects)}.values())
    errors = sum(len(g.edit.vehicle.diagnostics.errors()) for g in groups)
    warnings = sum(len(g.edit.vehicle.diagnostics.warnings()) for g in groups)
    if len(imports) == 1:
        kind, path, _ = imports[0]
        name = f"{path.parent.name} ({path.stem})" if kind == "PC" else obj.name
        message = tr("Loaded {name}: {summary}; {errors} errors, {warnings} warnings").format(
            name=name, summary=summary(session), errors=errors, warnings=warnings)
    else:
        message = tr("Loaded {count} parts from {files} files; {errors} errors, {warnings} warnings").format(
            count=len(objects), files=len({p for _, p, _ in imports}), errors=errors, warnings=warnings)
        skipped = requested - len(objects) if skip_empty else 0
        if skipped > 0:
            message += "; " + tr("{count} parts without nodes, beams or faces left out").format(count=skipped)
    operator.report({"WARNING" if errors else "INFO"}, message)
    return {"FINISHED"}


def _chosen_paths(operator) -> list[Path]:
    """The files chosen in the file browser: several with Shift or Ctrl, or the one of `filepath`."""
    names = [f.name for f in operator.files if f.name]
    if names:
        directory = Path(operator.directory) if operator.directory else Path(operator.filepath).parent
        return [directory / name for name in names]
    return [Path(operator.filepath)]


class JBS_OT_import_pc(bpy.types.Operator, ImportHelper):
    bl_idname = "jbs.import_pc"
    bl_label = "Import JBeam Vehicle"
    bl_description = ("Assemble a vehicle from a part config (.pc) and show each of its parts as an object, in a "
                      "collection of its .jbeam file under the JBeam collection; several files give several "
                      "vehicles")
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".pc"
    filter_glob: StringProperty(default="*.pc", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        return _finish_import(self, context, [("PC", path, []) for path in _chosen_paths(self)])


class JBS_PartChoice(bpy.types.PropertyGroup):
    name: StringProperty()
    path: StringProperty()
    chosen: BoolProperty(name="Import")


class JBS_UL_parts(bpy.types.UIList):
    def draw_item(self, _context, layout, data, item, _icon, _active_data, _active_property, _index):
        row = layout.row(align=True)
        row.enabled = not data.all_parts
        row.prop(item, "chosen", text=item.name)
        file = row.row()
        file.alignment = "RIGHT"
        file.enabled = False
        file.label(text=Path(item.path).name)


class JBS_OT_import_jbeam_part(bpy.types.Operator):
    bl_idname = "jbs.import_jbeam_part"
    bl_label = "Import JBeam Parts"
    bl_description = "Choose the parts of the .jbeam files to import"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    paths: StringProperty(options={"HIDDEN"}, description="The .jbeam files, one per line")
    all_parts: BoolProperty(name="All parts", description="Import every part of the chosen files")
    parts: CollectionProperty(type=JBS_PartChoice, options={"HIDDEN", "SKIP_SAVE"})
    active: IntProperty(options={"HIDDEN", "SKIP_SAVE"})

    def _fill(self) -> None:
        self.parts.clear()
        for path in (Path(p) for p in self.paths.splitlines() if p.strip()):
            try:
                names = sessions.parts_of_file(path)
            except OSError as error:
                self.report({"ERROR"}, f"{path.name}: {error}")
                continue
            for name in names:
                item = self.parts.add()
                item.name, item.path = name, str(path)

    def invoke(self, context, _event):
        self._fill()
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "all_parts")
        layout.template_list("JBS_UL_parts", "", self, "parts", self, "active",
                             rows=min(14, max(5, len(self.parts))))
        chosen = len(self.parts) if self.all_parts else sum(p.chosen for p in self.parts)
        layout.label(text=tr("{count} of {total} parts").format(count=chosen, total=len(self.parts)))

    def execute(self, context):
        if not self.parts:
            self._fill()
        files: dict[Path, list[str]] = {}
        for item in self.parts:
            if self.all_parts or item.chosen:
                files.setdefault(Path(item.path), []).append(item.name)
        if not files:
            self.report({"ERROR"}, tr("Choose the parts to import"))
            return {"CANCELLED"}
        return _finish_import(self, context, [("PART", path, names) for path, names in files.items()],
                              skip_empty=self.all_parts)


class JBS_OT_import_jbeam(bpy.types.Operator, ImportHelper):
    bl_idname = "jbs.import_jbeam"
    bl_label = "Import JBeam Parts"
    bl_description = ("Show parts of .jbeam files as objects, with the nodes of other parts they use; with several "
                      "parts, choose which ones")
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".jbeam"
    filter_glob: StringProperty(default="*.jbeam", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})
    part_name: StringProperty(name="Part", description="Leave empty to choose from the parts of the files")

    def execute(self, context):
        choices: list[tuple[Path, str]] = []
        paths = _chosen_paths(self)
        for path in paths:
            try:
                parts = sessions.parts_of_file(path)
            except OSError as error:
                self.report({"ERROR"}, f"{path.name}: {error}")
                continue
            if not parts:
                self.report({"WARNING"}, tr("{name} has no parts").format(name=path.name))
            choices += [(path, part) for part in parts]
        if self.part_name:
            choices = [c for c in choices if c[1] == self.part_name]
            if not choices:
                self.report({"ERROR"}, tr('Part "{part}" is not in {name}').format(
                    part=self.part_name, name=", ".join(p.name for p in paths)))
                return {"CANCELLED"}
        if not choices:
            return {"CANCELLED"}
        if len(choices) == 1 or self.part_name:
            return _finish_import(self, context, [("PART", path, [part]) for path, part in choices])
        bpy.ops.jbs.import_jbeam_part("INVOKE_DEFAULT", paths="\n".join(str(p) for p in paths))
        return {"FINISHED"}


class JBS_OT_apply_mesh(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.apply_mesh"
    bl_label = "Apply Mesh Edits"
    bl_description = "Write the edits of the mesh into the JBeam files in memory"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj, session = active(context)
        try:
            if obj.mode == "EDIT":
                sessions.commit_edit_mesh(obj, session)
                sessions.autosave(obj, session)
            else:
                sessions.apply_mesh(obj, session)
        except EditError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        plan = session.last_plan
        self.report({"INFO"}, plan_summary(plan) if plan is not None and not plan.empty else tr("Nothing to apply"))
        report_save_problem(self, session)
        if session.cursor_warning:
            self.report({"WARNING"}, tr(session.cursor_warning))
        return {"FINISHED"}


class JBS_OT_save(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.save"
    bl_label = "Save JBeam Files"
    bl_description = "Apply the mesh edits and write the changed files; the first save keeps the original as .bak"
    bl_options = {"REGISTER", "UNDO"}

    overwrite: BoolProperty(name="Overwrite files changed on disk", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        obj, session = active(context)
        try:
            if obj.mode == "EDIT":
                sessions.mirror(obj, session)
            else:
                sessions.apply_mesh(obj, session)
        except EditError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        try:
            saved = session.edit.save(overwrite_external=self.overwrite)
        except ExternalChangeError as error:
            session.changed_on_disk = error.paths
            self.report({"ERROR"}, tr("{error}. Reload them, or save anyway to overwrite them").format(error=error))
            return {"CANCELLED"}
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        session.changed_on_disk = []
        sessions.note_saved(session, saved)
        edited = sessions.edited_texts(session)
        if edited:
            self.report({"WARNING"}, tr("Text edits in {names} are not applied, so they were not saved").format(
                names=", ".join(t.name for t in edited)))
        if saved:
            self.report({"INFO"}, tr("Saved {files}").format(files=", ".join(p.name for p in saved)))
        elif session.saved_at is not None:
            self.report({"INFO"}, tr("All changes are saved (saved at {time}: {files})").format(
                time=saved_time(session), files=", ".join(session.saved_files)))
        else:
            self.report({"INFO"}, tr("There are no changes to save"))
        return {"FINISHED"}


class JBS_OT_rebuild(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.rebuild"
    bl_label = "Rebuild Mesh"
    bl_description = "Build the mesh again from the JBeam files in memory, dropping mesh edits that were not applied"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj, session = active(context)
        with object_mode(obj):
            sessions.rebuild(obj, session)
        return {"FINISHED"}


class JBS_OT_reload(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.reload"
    bl_label = "Reload Changed Files"
    bl_description = "Read the files that changed on disk again; unsaved edits of these files and the undo history are lost"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        _obj, session = active(context)
        if set(session.edit.dirty_files()) & set(session.changed_on_disk):
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        obj, session = active(context)
        with object_mode(obj):
            try:
                for path in session.changed_on_disk:
                    session.link.reload_file(path)
            except EditError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            session.changed_on_disk = []
            sessions.rebuild(obj, session)
        return {"FINISHED"}


class JBS_OT_rescan(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.rescan"
    bl_label = "Find New Files"
    bl_description = "Take in .jbeam files added to the vehicle folders since loading; the undo history is cleared"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj, session = active(context)
        added = session.edit.files_added_on_disk()
        with object_mode(obj):
            session.link.rescan()
            sessions.rebuild(obj, session)
        self.report({"INFO"}, tr("{count} new files").format(count=len(added)))
        return {"FINISHED"}


class JBS_OT_load_object(bpy.types.Operator):
    bl_idname = "jbs.load_object"
    bl_label = "Load from Files"
    bl_description = "Open the JBeam files of this object again and rebuild its mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.jbs.kind != "NONE" and sessions.session_of(obj) is None

    def execute(self, context):
        obj = context.active_object
        with object_mode(obj):
            try:
                sessions.load_object(obj)
            except (OSError, EditError) as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
        return {"FINISHED"}


class JBS_OT_detach(bpy.types.Operator):
    bl_idname = "jbs.detach"
    bl_label = "Make Plain Mesh"
    bl_description = "Turn this object into a plain mesh that is not linked to JBeam files"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.jbs.kind != "NONE"

    def execute(self, context):
        sessions.detach(context.active_object)
        return {"FINISHED"}


class JBS_OT_rename_node(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.rename_node"
    bl_label = "Rename Node"
    bl_description = "Rename the active node and every beam, triangle and other reference to it"
    bl_options = {"REGISTER", "UNDO"}

    old_id: StringProperty(name="Node", options={"HIDDEN"})
    new_id: StringProperty(name="New name")

    def invoke(self, context, _event):
        obj, session = active(context)
        if not _commit(self, obj, session):
            return {"CANCELLED"}
        node_id = sessions.active_node_id(obj, session)
        if node_id is None:
            self.report({"ERROR"}, tr("Select a node"))
            return {"CANCELLED"}
        try:
            self._preview = session.edit.rename_preview(node_id)
        except EditError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.old_id = self.new_id = node_id
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context):
        layout = self.layout
        layout.label(text=tr('Node "{node}"').format(node=self.old_id))
        layout.prop(self, "new_id")
        preview = getattr(self, "_preview", None)
        if preview is not None:
            layout.label(text=tr("References renamed with it: {count}").format(count=len(preview.references)))
            if preview.other_matches:
                layout.label(text=tr("Equal strings that stay as they are: {count}").format(
                    count=len(preview.other_matches)), icon="INFO")

    def execute(self, context):
        obj, session = active(context)
        if self.new_id == self.old_id:
            return {"CANCELLED"}
        try:
            session.edit.rename_node(self.old_id, self.new_id)
        except EditError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        sessions.after_change(obj, session, renames={self.new_id: self.old_id})
        report_save_problem(self, session)
        if session.cursor_warning:
            self.report({"WARNING"}, tr(session.cursor_warning))
        return {"FINISHED"}


class JBS_OT_rename_nodes(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.rename_nodes"
    bl_label = "Rename Selected Nodes"
    bl_description = "Give the selected nodes names made of a prefix, a number and a suffix, in the order of selection"
    bl_options = {"REGISTER", "UNDO"}

    prefix: StringProperty(name="Prefix", default="n")
    start: IntProperty(name="First number", default=1, min=0)
    suffix: StringProperty(name="Suffix")

    def invoke(self, context, _event):
        obj, session = active(context)
        if not _commit(self, obj, session):
            return {"CANCELLED"}
        self._ids = sessions.selected_node_ids(obj, session)
        if not self._ids:
            self.report({"ERROR"}, tr("Select nodes"))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)

    def _renames(self) -> dict[str, str]:
        return {old: f"{self.prefix}{self.start + i}{self.suffix}" for i, old in enumerate(self._ids)}

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "prefix")
        layout.prop(self, "start")
        layout.prop(self, "suffix")
        for old, new in list(self._renames().items())[:4]:
            layout.label(text=f"{old}  \u2192  {new}")
        if len(self._ids) > 4:
            layout.label(text="\u2026")

    def execute(self, context):
        obj, session = active(context)
        if not hasattr(self, "_ids"):
            self._ids = sessions.selected_node_ids(obj, session)
        renames = {old: new for old, new in self._renames().items() if old != new}
        if not renames:
            return {"CANCELLED"}
        try:
            session.edit.rename_nodes(renames)
        except EditError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        sessions.after_change(obj, session, renames={new: old for old, new in renames.items()})
        report_save_problem(self, session)
        if session.cursor_warning:
            self.report({"WARNING"}, tr(session.cursor_warning))
        return {"FINISHED"}


class JBS_OT_mirror(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.mirror"
    bl_label = "Mirror Selected Nodes"
    bl_description = ("Copy the selected nodes, and the beams, triangles and quads that use them, to the other side of "
                      "the mirror plane with mirrored names (e3l to e3r); counterparts that exist are moved to the "
                      "mirrored place")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj, session = active(context)
        if not _commit(self, obj, session):
            return {"CANCELLED"}
        ids = sessions.selected_node_ids(obj, session)
        settings = obj.jbs
        axis = AXES[settings.mirror_axis]
        if settings.mirror_plane == "cursor":
            center = (obj.matrix_world.inverted() @ context.scene.cursor.location)[axis]
        elif settings.mirror_plane == "active":
            node = sessions.node_entry(session, sessions.active_node_id(obj, session) or "")
            if node is None:
                self.report({"ERROR"}, tr("Select the node the mirror plane goes through last"))
                return {"CANCELLED"}
            center = node.pos[axis]
        else:
            center = 0.0
        try:
            result = mirror(session.edit, ids, settings.allow_shared, settings.mirror_axis, center,
                            preferences.mirror_pairs(settings.mirror_axis))
        except EditError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if not (result.added or result.moved or result.beams or result.faces or result.extras):
            self.report({"INFO"}, tr("The selection is already mirrored"))
            return {"FINISHED"}
        session.link.changed()
        with object_mode(obj):
            sessions.rebuild(obj, session, set(ids) | set(result.mirrors.values()))
        sessions.autosave(obj, session)
        self.report({"INFO"}, tr("Mirrored: {added} nodes added, {moved} moved, {beams} beams, {faces} faces, "
                                 "{extras} hydros, torsion bars, slide nodes and rails").format(
            added=len(result.added), moved=len(result.moved), beams=result.beams, faces=result.faces,
            extras=result.extras))
        report_save_problem(self, session)
        if session.cursor_warning:
            self.report({"WARNING"}, tr(session.cursor_warning))
        return {"FINISHED"}


def _change_session(operator, obj, session, change) -> bool:
    """Runs a session operation that leaves the geometry as it is and marks the mesh with the new state."""
    if not _commit(operator, obj, session):
        return False
    try:
        result = change()
    except EditError as error:
        operator.report({"ERROR"}, str(error))
        return False
    sessions.after_change(obj, session)
    report_save_problem(operator, session)
    return result if result is not None else True


class JBS_OT_add_resets(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.add_resets"
    bl_label = "Add Resets"
    bl_description = ("Add a row at the end of each table of the part that sets the modifiers it changes, such as "
                      "group or beamType, back to their defaults, so the rows of parts after it do not get them")
    bl_options = {"REGISTER", "UNDO"}

    part_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        obj, session = active(context)
        part = self.part_name or obj.jbs.active_part
        done = _change_session(self, obj, session, lambda: session.edit.add_resets(part))
        if done is False:
            return {"CANCELLED"}
        if done is True or not done:
            self.report({"INFO"}, tr('Part "{part}" already resets what it changes').format(part=part))
        else:
            self.report({"INFO"}, tr("Added resets: {resets}").format(
                resets="; ".join(f"{s}: {', '.join(keys)}" for s, keys in done.items())))
        return {"FINISHED"}


FIX_DESCRIPTIONS = {
    fixes.MARK_OPTIONAL: ('Mark this row "optional": true. The row stays: the game skips it without a warning while '
                          "the node is missing, and uses it when another part or mod provides the node"),
    fixes.DELETE_DUPLICATE: "Delete this copy of the beam; the row it repeats stays",
    fixes.ADD_RESETS: ("Add a row at the end of each table of the part that sets the modifiers it changes back to "
                       "their defaults"),
}
FIX_GROUPS = {
    "missing": ("Mark Optional ({count})",
                'Mark every row that references a missing node "optional": true; the rows stay for the parts and '
                "mods that provide those nodes"),
    "duplicates": ("Delete Duplicate Beams ({count})", "Delete every repeated beam; the first row of each stays"),
    "resets": ("Add Resets to Parts ({count})",
               "Add resets to every part that leaves modifiers set for the parts after it"),
}


def _fix_key(diagnostic) -> tuple:
    return diagnostic.category, diagnostic.message, diagnostic.file, diagnostic.fix[:1]


def fixable(session, group: str = "") -> list:
    return [d for d in session.edit.vehicle.diagnostics if fixes.group_of(d) and group in ("", fixes.group_of(d))]


class JBS_OT_fix(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.fix"
    bl_label = "Fix"
    bl_description = "Fix this problem in the JBeam files in memory"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})
    group: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        if properties.group in FIX_GROUPS:
            return tr(FIX_GROUPS[properties.group][1])
        session = sessions.session_of(context.active_object)
        diagnostics = session.edit.vehicle.diagnostics if session else []
        if 0 <= properties.index < len(diagnostics) and diagnostics[properties.index].fix:
            return tr(FIX_DESCRIPTIONS.get(diagnostics[properties.index].fix[0], cls.bl_description))
        return tr(cls.bl_description)

    def _chosen(self, session) -> list:
        if self.group:
            return fixable(session, self.group)
        diagnostics = session.edit.vehicle.diagnostics
        if 0 <= self.index < len(diagnostics) and fixes.group_of(diagnostics[self.index]):
            return [diagnostics[self.index]]
        return []

    def execute(self, context):
        obj, session = active(context)
        chosen = self._chosen(session)
        if not chosen:
            self.report({"ERROR"}, tr("This problem has no automatic fix"))
            return {"CANCELLED"}
        before = session.edit.vehicle
        if not _commit(self, obj, session):
            return {"CANCELLED"}
        if session.edit.vehicle is not before:
            pool, wanted, chosen = fixable(session), [_fix_key(d) for d in chosen], []
            for key in wanted:
                match = next((d for d in pool if _fix_key(d) == key), None)
                if match is not None:
                    pool.remove(match)
                    chosen.append(match)
            if not chosen:
                self.report({"INFO"}, tr("The problem is gone"))
                return {"FINISHED"}
        selected = set(sessions.selected_node_ids(obj, session))
        try:
            result = fixes.fix(session.edit, chosen, obj.jbs.allow_shared)
        except EditError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        session.link.changed()
        with object_mode(obj):
            sessions.rebuild(obj, session, selected)
        sessions.autosave(obj, session)
        done = []
        if result.optional:
            done.append(tr("{count} rows marked optional").format(count=result.optional))
        if result.deleted:
            done.append(tr("{count} rows deleted").format(count=result.deleted))
        if result.resets:
            done.append(tr("resets added to {parts}").format(parts=", ".join(result.resets)))
        self.report({"INFO"}, tr("Fixed: {done}").format(done="; ".join(done)) if done else tr("Nothing to fix"))
        report_save_problem(self, session)
        if session.cursor_warning:
            self.report({"WARNING"}, tr(session.cursor_warning))
        return {"FINISHED"}


EXTRA_KINDS = {"hydros": "hydro", "torsionbars": "torsion bar", "torsionHydros": "torsion hydro",
               "rails": "rail", "slidenodes": "slide node"}
EXTRA_ICONS = {"hydros": "DRIVER", "torsionbars": "CON_ROTLIKE", "torsionHydros": "CON_ROTLIKE",
               "rails": "CURVE_PATH", "slidenodes": "CON_FOLLOWPATH"}
LINKS_SHOWN = 4


def extra_label(extra) -> str:
    kind = tr(EXTRA_KINDS[extra.section])
    if extra.section == "slidenodes":
        return f"{kind}  {extra.ids[0]} → {extra.name or '?'}"
    ids = list(extra.ids[:LINKS_SHOWN]) + (["…"] if len(extra.ids) > LINKS_SHOWN else [])
    return f"{kind} {extra.name}:  {' – '.join(ids)}" if extra.name else f"{kind}  {' – '.join(ids)}"


def _extra_at(session, index: int):
    extras = session.edit.vehicle.extras
    return extras[index] if 0 <= index < len(extras) else None


ADD_EXTRA = {
    "hydros": ("Hydro", "Add a hydro between the two selected nodes, to the active part"),
    "torsionbars": ("Torsion Bar", "Add a torsion bar through the four selected nodes in the order they were "
                                   "selected, to the active part; it twists about the second and third"),
}


class JBS_OT_add_extra(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.add_extra"
    bl_label = "Add Hydro or Torsion Bar"
    bl_options = {"REGISTER", "UNDO"}

    section: EnumProperty(items=[(k, label, text) for k, (label, text) in ADD_EXTRA.items()], options={"HIDDEN"})

    @classmethod
    def description(cls, context, properties):
        return tr(ADD_EXTRA[properties.section][1])

    def execute(self, context):
        obj, session = active(context)
        ids = sessions.selected_node_ids(obj, session)
        needed = len(EXTRA_COLUMNS[self.section])
        if len(ids) != needed:
            self.report({"ERROR"}, tr("Select {count} nodes, in order").format(count=needed))
            return {"CANCELLED"}
        part = obj.jbs.active_part
        if _change_session(self, obj, session, lambda: session.edit.add_extras(
                part, self.section, [tuple(ids)], obj.jbs.allow_shared)) is False:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Added {what}").format(what=f"{tr(EXTRA_KINDS[self.section])} {' – '.join(ids)}"))
        return {"FINISHED"}


class JBS_OT_add_rail(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.add_rail"
    bl_label = "Add Rail"
    bl_description = ("Add a rail through the selected nodes in the order they were selected, to the active part; "
                      "slide nodes can then slide along it")
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name")
    looped: BoolProperty(name="Looped", description="The rail closes from its last node back to the first")
    capped: BoolProperty(name="Capped", default=True, description="Slide nodes cannot leave the rail at its ends")

    def invoke(self, context, event):
        _, session = active(context)
        taken = set(session.edit.rail_names())
        self.name = next(f"rail{i}" for i in range(1, len(taken) + 2) if f"rail{i}" not in taken)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj, session = active(context)
        ids = sessions.selected_node_ids(obj, session)
        if len(ids) < 2:
            self.report({"ERROR"}, tr("Select at least two nodes, in order"))
            return {"CANCELLED"}
        part = obj.jbs.active_part
        if _change_session(self, obj, session, lambda: session.edit.add_rail(
                part, self.name, ids, self.looped, self.capped, obj.jbs.allow_shared)) is False:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Added {what}").format(what=f'{tr("rail")} "{self.name}"'))
        return {"FINISHED"}


_rail_items: list = []


def _rails(self, context):
    session = sessions.session_of(context.active_object)
    _rail_items[:] = [(n, n, "") for n in (session.edit.rail_names() if session else [])] or [("", "", "")]
    return _rail_items


class JBS_OT_add_slidenodes(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.add_slidenodes"
    bl_label = "Add Slide Nodes"
    bl_description = "Make the selected nodes slide along a rail, in the active part"
    bl_options = {"REGISTER", "UNDO"}

    rail: EnumProperty(name="Rail", items=_rails)

    def invoke(self, context, event):
        _, session = active(context)
        if not session.edit.rail_names():
            self.report({"ERROR"}, tr("The vehicle has no rails yet; add one first"))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj, session = active(context)
        ids = sessions.selected_node_ids(obj, session)
        if not ids or not self.rail:
            self.report({"ERROR"}, tr("Select the nodes that slide, and a rail"))
            return {"CANCELLED"}
        part = obj.jbs.active_part
        if _change_session(self, obj, session, lambda: session.edit.add_extras(
                part, "slidenodes", [(i, self.rail) for i in ids], obj.jbs.allow_shared)) is False:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Added {what}").format(what=f"{len(ids)} × {tr('slide node')} → {self.rail}"))
        return {"FINISHED"}


class JBS_OT_select_extra(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.select_extra"
    bl_label = "Select Nodes"
    bl_description = "Select the nodes this joins; with Shift, add them to the selection"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: IntProperty(default=-1, options={"HIDDEN"})
    extend: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        obj, session = active(context)
        extra = _extra_at(session, self.index)
        if extra is None:
            return {"CANCELLED"}
        nodes = [n for n in (sessions.node_entry(session, i) for i in extra.ids) if n is not None]
        select_entries(obj, session, "nodes", nodes, self.extend)
        context.tool_settings.mesh_select_mode = (True, False, False)
        return {"FINISHED"}


class JBS_OT_delete_extra(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.delete_extra"
    bl_label = "Delete"
    bl_description = "Delete this row from the JBeam file; a rail takes the slide nodes on it with it"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: IntProperty(default=-1, options={"HIDDEN"})

    def execute(self, context):
        obj, session = active(context)
        extra = _extra_at(session, self.index)
        if extra is None:
            return {"CANCELLED"}
        key = extra.section, extra.ids, extra.name
        if not _commit(self, obj, session):
            return {"CANCELLED"}
        extra = next((e for e in session.edit.vehicle.extras if (e.section, e.ids, e.name) == key), None)
        if extra is None:
            return {"CANCELLED"}
        label = extra_label(extra)
        if _change_session(self, obj, session, lambda: session.edit.delete_extras([extra])) is False:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Deleted {what}").format(what=label))
        return {"FINISHED"}


_HYDRO_KEYS = ("inputSource", "inputFactor", "factor", "inRate", "outRate", "inLimit", "outLimit", "inputCenter",
               "inputInLimit", "inputOutLimit")
_TORSION_KEYS = ("spring", "spring2", "damp", "damp2", "deform", "strength", "precompressionAngle",
                 "precompressionTime")
EXTRA_KEYS = {
    "hydros": _HYDRO_KEYS + ("extentFactor", "inExtent", "outExtent", "autoCenterRate", "analogue", "beamSpring",
                             "beamDamp", "beamDeform", "beamStrength"),
    "torsionbars": _TORSION_KEYS,
    "torsionHydros": _TORSION_KEYS + _HYDRO_KEYS,
    "slidenodes": ("railName", "attached", "fixToRail", "tolerance", "spring", "strength", "capStrength"),
    "rails": ("looped", "capped", "broken:"),
}
"""Keys the game reads for each kind, offered when setting a property."""
EXTRA_HIDDEN = {"partOrigin", "partPath", "originSection", "id", "name", "slotType", "partName", "skinName",
                "globalSkin"}


def extra_key(extra) -> str:
    """What an entry is, kept across assembling the vehicle again: its section, name and nodes."""
    return "\t".join((extra.section, extra.name or "", *extra.ids))


def find_extra(session, key: str):
    return next((e for e in session.edit.vehicle.extras if extra_key(e) == key), None)


def extra_properties(extra) -> list[tuple[str, object]]:
    return [(k, v) for k, v in extra.props.items()
            if isinstance(k, str) and k not in EXTRA_HIDDEN and (not k.endswith(":") or k == "broken:")]


class JBS_OT_expand_extra(bpy.types.Operator):
    bl_idname = "jbs.expand_extra"
    bl_label = "Show Properties"
    bl_description = "Show or hide the properties of this entry"
    bl_options = {"INTERNAL"}

    key: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        state = view.panel_state(context)
        state.expanded_extra = "" if state.expanded_extra == self.key else self.key
        return {"FINISHED"}


class JBS_OT_reset_display(bpy.types.Operator):
    bl_idname = "jbs.reset_display"
    bl_label = "Reset Display Settings"
    bl_description = "Set every colour, size and switch of the display back to its default"
    bl_options = {"INTERNAL"}

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(self, _event)

    def execute(self, context):
        view.reset(view.settings(context))
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {"FINISHED"}


def _search_extra_keys(self, context, edit_text):
    session = sessions.session_of(context.active_object)
    extra = find_extra(session, self.extra) if session is not None else None
    if extra is None:
        return []
    keys = dict.fromkeys(EXTRA_KEYS.get(extra.section, ()))
    keys.update(dict.fromkeys(k for k, _ in extra_properties(extra)))
    return [k for k in keys if edit_text.lower() in k.lower()]


class JBS_OT_set_extra_property(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.set_extra_property"
    bl_label = "Set Property"
    bl_description = ("Set a property of this hydro, torsion bar, slide node or rail: in its column when the table "
                      "has one, otherwise in the options of its row")
    bl_options = {"REGISTER", "UNDO"}

    extra: StringProperty(options={"HIDDEN"})
    key: StringProperty(name="Key", search=_search_extra_keys)
    value: StringProperty(name="Value", description='A number, true, false, a list such as ["n1", "n2"], or text '
                                                    "such as steering")

    def invoke(self, context, _event):
        obj, session = active(context)
        if not _commit(self, obj, session):
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj, session = active(context)
        key, value = self.key.strip(), parse_value(self.value)
        if not key:
            self.report({"ERROR"}, tr("Give a key"))
            return {"CANCELLED"}

        def change():
            extra = find_extra(session, self.extra)
            if extra is None:
                raise EditError(tr("This entry no longer exists"))
            session.edit.set_property([extra], key, value, obj.jbs.allow_shared)

        if _change_session(self, obj, session, change) is False:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("{key} = {value} on {count} rows").format(key=key, value=self.value, count=1))
        return {"FINISHED"}


KINDS = [("nodes", "Nodes", ""), ("beams", "Beams", ""), ("faces", "Triangles and quads", "")]


def kind_of_select_mode(context) -> str:
    vertex, edge, face = context.tool_settings.mesh_select_mode
    return "beams" if edge and not vertex else "faces" if face and not vertex and not edge else "nodes"


def entries_of_kind(obj, session, kind: str) -> list:
    mode = {"nodes": (True, False, False), "beams": (False, True, False), "faces": (False, False, True)}[kind]
    if obj.mode == "EDIT":
        return sessions.selected_entries(obj, session, mode)
    if kind == "nodes":
        return [n for n in map(lambda i: sessions.node_entry(session, i), sessions.selected_node_ids(obj, session)) if n]
    return []


def parse_value(text: str):
    """A typed value: JSON such as 1.5, true or "|NORMAL", and anything else as a string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def value_text(value) -> str:
    """The text of a value for editing, which `parse_value` reads back; unbreakable strengths as "FLT_MAX"."""
    if value == math.inf:
        return '"FLT_MAX"'
    if value == -math.inf:
        return '"MINUS_FLT_MAX"'
    return json.dumps(value, ensure_ascii=False)


def _search_keys(self, context, edit_text):
    section = {"nodes": "nodes", "beams": "beams", "faces": "triangles"}[self.kind]
    keys = dict.fromkeys(entry.key for entry in docs.all_entries() if entry.section == section)
    obj = context.active_object
    session = sessions.session_of(obj)
    if session is not None:
        for entry in entries_of_kind(obj, session, self.kind):
            keys.update(dict.fromkeys(k for k in entry.props if isinstance(k, str)))
    text = edit_text.lower()
    return [k for k in keys if text in k.lower() and not k.endswith(":")]


class JBS_OT_set_property(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.set_property"
    bl_label = "Set Property"
    bl_description = ("Set a property on the selected nodes, beams or faces: in its column when the table has one, "
                      "otherwise in the options of each row")
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(name="Of", items=KINDS)
    key: StringProperty(name="Key", search=_search_keys)
    value: StringProperty(name="Value", description='A number, true, false, or text such as |NORMAL or "name"')

    def invoke(self, context, _event):
        obj, session = active(context)
        if not _commit(self, obj, session):
            return {"CANCELLED"}
        if not self.properties.is_property_set("kind"):
            self.kind = kind_of_select_mode(context)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj, session = active(context)
        entries = entries_of_kind(obj, session, self.kind)
        if not entries or not self.key.strip():
            self.report({"ERROR"}, tr("Select what to change and give a key"))
            return {"CANCELLED"}
        value = parse_value(self.value)
        done = _change_session(self, obj, session,
                               lambda: session.edit.set_property(entries, self.key.strip(), value, obj.jbs.allow_shared))
        if done is False:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("{key} = {value} on {count} rows").format(key=self.key, value=self.value,
                                                                         count=len(entries)))
        return {"FINISHED"}


class JBS_OT_select_by_property(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.select_by_property"
    bl_label = "Select by Property"
    bl_description = "Select the nodes, beams or faces whose property has a value, such as beamType = |SUPPORT"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(name="Of", items=KINDS)
    key: StringProperty(name="Key", search=_search_keys)
    value: StringProperty(name="Value", description="Leave empty to select everything that has the key")
    extend: BoolProperty(name="Extend", description="Add to the selection")

    @classmethod
    def poll(cls, context):
        return _EditModePoll.poll(context)

    def invoke(self, context, _event):
        if not self.properties.is_property_set("kind"):
            self.kind = kind_of_select_mode(context)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj, session = active(context)
        key, wanted = self.key.strip(), parse_value(self.value) if self.value.strip() else None
        vehicle = session.edit.vehicle
        items = (list(vehicle.nodes.values()) if self.kind == "nodes" else vehicle.beams if self.kind == "beams"
                 else vehicle.triangles + vehicle.quads)
        matching = [e for e in items if key in e.props and (wanted is None or e.props[key] == wanted
                                                            or (isinstance(e.props[key], list) and wanted in e.props[key]))]
        count = select_entries(obj, session, self.kind, matching, self.extend)
        context.tool_settings.mesh_select_mode = {"nodes": (True, False, False), "beams": (False, True, False),
                                                  "faces": (False, False, True)}[self.kind]
        self.report({"INFO"}, tr("Selected {count}").format(count=count))
        return {"FINISHED"}


def select_entries(obj, session, kind: str, entries, extend: bool = False) -> int:
    """Selects the mesh elements of entries in Edit Mode and returns how many were selected."""
    bm = bmesh.from_edit_mesh(obj.data)
    link = session.link
    vertex_layer = bm.verts.layers.int.get(mesh_io.NODE_UID)
    if vertex_layer is None:
        return 0
    if not extend:
        for element in (*bm.verts, *bm.edges, *bm.faces):
            element.select = False
    count = 0
    if kind == "nodes":
        uids = {link.map.nodes.get(e.id) for e in entries}
        for vertex in bm.verts:
            if vertex[vertex_layer] in uids and not vertex.hide:
                vertex.select = True
                count += 1
    else:
        groups = link.map.beams if kind == "beams" else link.map.faces
        vehicle = session.edit.vehicle
        listing = vehicle.beams if kind == "beams" else vehicle.triangles + vehicle.quads
        wanted = {id(e) for e in entries}
        uids = {uid for uid, g in groups.items() if any(id(listing[i]) in wanted for i in g.indices)}
        layer = (bm.edges.layers.int.get(mesh_io.BEAM_UID) if kind == "beams"
                 else bm.faces.layers.int.get(mesh_io.FACE_UID))
        if layer is not None:
            for element in bm.edges if kind == "beams" else bm.faces:
                if element[layer] in uids and not element.hide:
                    element.select_set(True)
                    count += 1
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return count


class JBS_OT_group_select(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.group_select"
    bl_label = "Select Group"
    bl_description = "Select the nodes of this group; with Shift, add them to the selection"
    bl_options = {"REGISTER", "UNDO"}

    group: StringProperty(options={"HIDDEN"})
    extend: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        obj, session = active(context)
        nodes = [session.edit.vehicle.nodes[i] for i in session.edit.node_groups().get(self.group, [])]
        select_entries(obj, session, "nodes", nodes, self.extend)
        context.tool_settings.mesh_select_mode = (True, False, False)
        return {"FINISHED"}


class JBS_OT_group_hide(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.group_hide"
    bl_label = "Hide or Show Group"
    bl_description = "Hide the nodes of this group in Edit Mode, or show them again"
    bl_options = {"REGISTER", "UNDO"}

    group: StringProperty(options={"HIDDEN"})
    hide: BoolProperty(options={"HIDDEN"})

    def execute(self, context):
        obj, session = active(context)
        uids = {session.link.map.nodes.get(i) for i in session.edit.node_groups().get(self.group, [])}
        bm = bmesh.from_edit_mesh(obj.data)
        layer = bm.verts.layers.int.get(mesh_io.NODE_UID)
        for vertex in bm.verts:
            if layer is not None and vertex[layer] in uids:
                vertex.hide_set(self.hide)
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return {"FINISHED"}


class JBS_OT_rename_group(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.rename_group"
    bl_label = "Rename Group"
    bl_description = "Rename a node group in every part, together with the flexbodies that use it"
    bl_options = {"REGISTER", "UNDO"}

    group: StringProperty(options={"HIDDEN"})
    new_name: StringProperty(name="New name")

    def invoke(self, context, _event):
        self.new_name = self.group
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj, session = active(context)
        done = _change_session(self, obj, session, lambda: session.edit.rename_group(self.group, self.new_name))
        if done is False:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Renamed {count} places").format(count=done))
        return {"FINISHED"}


class JBS_OT_flip_faces(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.flip_faces"
    bl_label = "Flip Faces"
    bl_description = "Reverse the winding of the selected triangles and quads; written when the mesh edits are applied"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, _context):
        bpy.ops.mesh.flip_normals()
        return {"FINISHED"}


class JBS_OT_select_part(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.select_part"
    bl_label = "Select Part"
    bl_description = "Add the nodes of the active part to the selection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj, session = active(context)
        names = session.link.part_names
        if obj.jbs.active_part not in names:
            self.report({"ERROR"}, tr("Choose the active part"))
            return {"CANCELLED"}
        index = names.index(obj.jbs.active_part)
        bm = bmesh.from_edit_mesh(obj.data)
        layer = bm.verts.layers.int.get(mesh_io.PART)
        if layer is None:
            return {"CANCELLED"}
        for vertex in bm.verts:
            if vertex[layer] == index:
                vertex.select = True
        bm.select_flush(True)
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return {"FINISHED"}


def open_in_text_editor(context, text, line: int = 0) -> None:
    area = window = None
    for candidate in [context.window, *context.window_manager.windows]:
        if candidate is None:
            continue
        area = next((a for a in candidate.screen.areas if a.type == "TEXT_EDITOR"), None)
        if area is not None:
            window = candidate
            break
    if area is None:
        bpy.ops.wm.window_new()
        window = context.window_manager.windows[-1]
        area = max(window.screen.areas, key=lambda a: a.width * a.height)
        area.type = "TEXT_EDITOR"
    area.spaces.active.text = text
    if line > 0:
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.text.jump(line=line)


class JBS_OT_show_text(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.show_text"
    bl_label = "Show Text"
    bl_description = "Open the file in Blender's text editor as it is in memory, with unsaved edits"

    path: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    line: IntProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        obj, session = active(context)
        path = self.path
        if not path:
            part = session.edit.vehicle.parts.get(obj.jbs.active_part)
            if part is None:
                self.report({"ERROR"}, tr("Choose the active part"))
                return {"CANCELLED"}
            path = part.file.path
        try:
            text = sessions.show_text(session, Path(path))
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        open_in_text_editor(context, text, self.line)
        return {"FINISHED"}


class JBS_OT_apply_text(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.apply_text"
    bl_label = "Apply Text"
    bl_description = "Replace the file in memory with the text edited in Blender's text editor"
    bl_options = {"REGISTER", "UNDO"}

    text_name: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        obj, session = active(context)
        text = bpy.data.texts.get(self.text_name)
        if text is None or text.get(sessions.TEXT_SESSION) != session.key:
            return {"CANCELLED"}
        with object_mode(obj):
            try:
                sessions.apply_text(obj, session, text)
            except EditError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
        report_save_problem(self, session)
        if session.cursor_warning:
            self.report({"WARNING"}, tr(session.cursor_warning))
        return {"FINISHED"}


class JBS_OT_discard_text(_SessionPoll, bpy.types.Operator):
    bl_idname = "jbs.discard_text"
    bl_label = "Discard Text Edits"
    bl_description = "Show the file as it is in memory again, dropping the edits made in the text editor"
    bl_options = {"REGISTER", "UNDO"}

    text_name: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        _obj, session = active(context)
        text = bpy.data.texts.get(self.text_name)
        if text is None or text.get(sessions.TEXT_SESSION) != session.key:
            return {"CANCELLED"}
        sessions.show_text(session, Path(text[sessions.TEXT_PATH]))
        return {"FINISHED"}


class JBS_OT_filter_visible_selection(_EditModePoll, bpy.types.Operator):
    bl_idname = "jbs.filter_visible_selection"
    bl_label = "Select Visible Only"
    bl_description = "Deselect nodes that are hidden behind other objects or faces from the current view"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..blender import selection
        region_3d, _space, _win = selection.find_viewport(context)
        if region_3d is None:
            self.report({"WARNING"}, tr("No active 3D viewport found"))
            return {"CANCELLED"}
        obj = context.active_object
        changed = selection.filter_visible_selection(obj, region_3d)
        if changed:
            context.area.tag_redraw()
        return {"FINISHED"}


class JBS_OT_extract_vehicles(bpy.types.Operator):
    bl_idname = "jbs.extract_vehicles"
    bl_label = "Unpack Vehicles"
    bl_description = "Copy the .jbeam, .pc and info.json files out of the game's vehicle archives"

    def execute(self, context):
        prefs = preferences.preferences()
        if prefs is None or not prefs.game_dir or not prefs.unpack_dir:
            self.report({"ERROR"}, tr("Set the game vehicle archives and the folder to unpack into"))
            return {"CANCELLED"}
        source = Path(bpy.path.abspath(prefs.game_dir))
        target = Path(bpy.path.abspath(prefs.unpack_dir))
        archives = sorted(source.glob("*.zip"))
        if not archives:
            self.report({"ERROR"}, tr("No .zip archives in {folder}").format(folder=source))
            return {"CANCELLED"}
        wm = context.window_manager
        wm.progress_begin(0, len(archives))
        count = 0
        try:
            for index, archive in enumerate(archives):
                count += extract_vehicles(source, target, {archive.stem})
                wm.progress_update(index + 1)
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            wm.progress_end()
        prefs.vehicles_dir = str(target / "vehicles")
        self.report({"INFO"}, tr("Unpacked {count} files into {folder}").format(count=count, folder=target))
        return {"FINISHED"}


_last_copied: str = ""


def _get_target_nodes(context):
    obj, session = active(context)
    if session is None:
        space = getattr(context, "space_data", None)
        if space and getattr(space, "type", "") == "TEXT_EDITOR" and space.text:
            key = space.text.get(sessions.TEXT_SESSION)
            if key in sessions.SESSIONS:
                group = sessions.SESSIONS[key]
                if group.views:
                    target_view = next(iter(group.views.values()), None)
                    if target_view:
                        obj = sessions.object_of(target_view)
                        session = target_view

    if session is None or obj is None:
        return obj, session, []

    texts = []
    space = getattr(context, "space_data", None)
    if space and getattr(space, "type", "") == "TEXT_EDITOR" and space.text:
        texts.append(space.text)
    for t in list(bpy.data.texts):
        if t not in texts and t.get(sessions.TEXT_SESSION) == session.key:
            texts.append(t)

    # 1. Selection in Text Editor
    for text in texts:
        if (text.select_end_line_index != text.current_line_index or
                text.select_end_character != text.current_character):
            from . import text_highlight
            matched = text_highlight.entries_in_range(
                session, text[sessions.TEXT_PATH],
                text.select_end_line_index, text.select_end_character,
                text.current_line_index, text.current_character
            )
            elements = list(dict.fromkeys(e for k, e in matched))
            if elements:
                return obj, session, elements

    # 2. Selected elements in 3D Viewport (vertices, edges, or faces)
    tool_settings = getattr(context, "tool_settings", None)
    mesh_sel = getattr(tool_settings, "mesh_select_mode", (True, False, False)) if tool_settings else (True, False, False)
    mode = tuple(mesh_sel) if obj.mode == "EDIT" else (True, False, False)
    entries = sessions.selected_entries(obj, session, mode)
    if entries:
        return obj, session, entries

    # 3. Text Editor: highlighted rows from 3D View selection
    from . import text_highlight
    if text_highlight._highlights:
        path = str(session.path) if hasattr(session, "path") else ""
        if texts:
            path = texts[0].get(sessions.TEXT_PATH, path)
        key = (session.key, text_highlight.path_key(path))
        rows = text_highlight._highlights.get(key, [])
        if rows:
            all_matched = []
            for sl, sc, el, ec in rows:
                all_matched.extend(text_highlight.entries_in_range(session, path, sl, sc, el, ec))
            elements = list(dict.fromkeys(e for k, e in all_matched))
            if elements:
                return obj, session, elements

    return obj, session, []


class JBS_OT_copy_nodes(bpy.types.Operator):
    bl_idname = "jbs.copy_nodes"
    bl_label = "Copy Selected Elements"
    bl_description = "Copy the JBeam text of the selected nodes, beams, or faces to clipboard"

    @classmethod
    def poll(cls, context):
        obj, session = active(context)
        if session is not None:
            return True
        space = getattr(context, "space_data", None)
        return bool(space and getattr(space, "type", "") == "TEXT_EDITOR" and space.text
                    and space.text.get(sessions.TEXT_SESSION))

    def invoke(self, context, event):
        obj, session, elements = _get_target_nodes(context)
        if not elements:
            if getattr(context.space_data, "type", "") == "TEXT_EDITOR":
                return {"PASS_THROUGH"}
            self.report({"WARNING"}, tr("No elements selected"))
            return {"CANCELLED"}
        return self.execute(context)

    def execute(self, context):
        global _last_copied
        obj, session, elements = _get_target_nodes(context)
        if not elements:
            self.report({"WARNING"}, tr("No elements selected"))
            return {"CANCELLED"}
        lines = []
        for e in elements:
            if getattr(e, "src", None) is not None and e.src.doc is not None:
                lines.append(e.src.doc.text[e.src.node.start:e.src.node.end])
            elif hasattr(e, "id") and hasattr(e, "pos"):
                lines.append(f'["{e.id}", {e.pos[0]:.4f}, {e.pos[1]:.4f}, {e.pos[2]:.4f}]')
            elif hasattr(e, "id1") and hasattr(e, "id2"):
                lines.append(f'["{e.id1}", "{e.id2}"]')
            elif hasattr(e, "ids"):
                inner = ", ".join(f'"{i}"' for i in e.ids)
                lines.append(f'[{inner}]')
        if not lines:
            self.report({"WARNING"}, tr("No text found for selection"))
            return {"CANCELLED"}
        _last_copied = "\n".join(lines)
        context.window_manager.clipboard = _last_copied
        self.report({"INFO"}, tr("Copied {count} elements").format(count=len(lines)))
        return {"FINISHED"}


class JBS_OT_delete_nodes(bpy.types.Operator):
    bl_idname = "jbs.delete_nodes"
    bl_label = "Delete Selected Elements"
    bl_description = "Delete the selected nodes, beams, or faces"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj, session = active(context)
        if session is not None:
            return True
        space = getattr(context, "space_data", None)
        return bool(space and getattr(space, "type", "") == "TEXT_EDITOR" and space.text
                    and space.text.get(sessions.TEXT_SESSION))

    def invoke(self, context, event):
        obj, session, elements = _get_target_nodes(context)
        if not elements:
            if getattr(context.space_data, "type", "") == "TEXT_EDITOR":
                return {"PASS_THROUGH"}
            self.report({"WARNING"}, tr("No elements selected"))
            return {"CANCELLED"}
        return self.execute(context)

    def execute(self, context):
        obj, session, elements = _get_target_nodes(context)
        if not elements:
            self.report({"WARNING"}, tr("No elements selected"))
            return {"CANCELLED"}

        nodes = [e for e in elements if hasattr(e, "id") and hasattr(e, "pos")]
        beams_and_faces = [e for e in elements if (hasattr(e, "id1") and hasattr(e, "id2")) or hasattr(e, "ids")]

        has_dependents = False
        if nodes:
            ids = [e.id for e in nodes]
            dependents = session.edit.dependents(ids)
            if dependents:
                has_dependents = True
            session.edit.delete_nodes(ids, keep_dependents=True)

        if beams_and_faces:
            session.edit.delete_entries(beams_and_faces)

        session.link.changed()
        sessions.rebuild(obj, session)
        sessions.autosave(obj, session)
        sessions.refresh_texts(session)

        count = len(nodes) + len(beams_and_faces)
        if has_dependents:
            self.report({"WARNING"}, tr("Deleted {count} elements; beams/faces reference missing nodes").format(count=count))
        else:
            self.report({"INFO"}, tr("Deleted {count} elements").format(count=count))
        return {"FINISHED"}


_left_idx_cache: dict[int, int] = {}


def _get_left_index(st) -> int:
    ptr = st.as_pointer()
    if ptr in _left_idx_cache:
        return _left_idx_cache[ptr]
    import ctypes
    buf = (ctypes.c_int32 * 64).from_address(ptr)
    old_top = st.top
    test_val = 123456
    try:
        st.top = test_val
        for i in range(64):
            if buf[i] == test_val:
                _left_idx_cache[ptr] = i + 1
                return i + 1
    finally:
        st.top = old_top
    _left_idx_cache[ptr] = 13
    return 13


class JBS_OT_text_scroll_horizontal(bpy.types.Operator):
    bl_idname = "jbs.text_scroll_horizontal"
    bl_label = "Scroll Text Horizontally"
    bl_description = "Scroll the text editor horizontally"

    direction: bpy.props.EnumProperty(
        items=[
            ("LEFT", "Left", ""),
            ("RIGHT", "Right", ""),
        ],
        default="RIGHT",
    )
    step: bpy.props.IntProperty(default=50)

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return bool(space and getattr(space, "type", "") == "TEXT_EDITOR" and space.text)

    def execute(self, context):
        st = context.space_data
        idx = _get_left_index(st)
        import ctypes
        buf = (ctypes.c_int32 * 64).from_address(st.as_pointer())
        delta = self.step if self.direction == "RIGHT" else -self.step
        buf[idx] = max(0, buf[idx] + delta)
        area = getattr(context, "area", None)
        if area:
            area.tag_redraw()
        return {"FINISHED"}


class JBS_OT_cut_nodes(bpy.types.Operator):
    bl_idname = "jbs.cut_nodes"
    bl_label = "Cut Selected Nodes"
    bl_description = "Copy the JBeam text of the selected nodes to clipboard and delete them"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj, session = active(context)
        if session is not None:
            return True
        space = getattr(context, "space_data", None)
        return bool(space and getattr(space, "type", "") == "TEXT_EDITOR" and space.text
                    and space.text.get(sessions.TEXT_SESSION))

    def invoke(self, context, event):
        obj, session, nodes = _get_target_nodes(context)
        if not nodes:
            if getattr(context.space_data, "type", "") == "TEXT_EDITOR":
                return {"PASS_THROUGH"}
            self.report({"WARNING"}, tr("No elements selected"))
            return {"CANCELLED"}
        return self.execute(context)

    def execute(self, context):
        res = bpy.ops.jbs.copy_nodes()
        if res == {"FINISHED"}:
            bpy.ops.jbs.delete_nodes()
            return {"FINISHED"}
        return {"CANCELLED"}


addon_keymaps = []


def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon if wm is not None else None
    if not kc:
        return
    # Mesh (3D View in Edit Mode)
    km_mesh = kc.keymaps.new(name="Mesh", space_type="EMPTY")
    kmi = km_mesh.keymap_items.new(JBS_OT_copy_nodes.bl_idname, type="C", value="PRESS", ctrl=True)
    addon_keymaps.append((km_mesh, kmi))
    kmi = km_mesh.keymap_items.new(JBS_OT_cut_nodes.bl_idname, type="X", value="PRESS", ctrl=True)
    addon_keymaps.append((km_mesh, kmi))
    kmi = km_mesh.keymap_items.new(JBS_OT_delete_nodes.bl_idname, type="DEL", value="PRESS")
    addon_keymaps.append((km_mesh, kmi))

    # 3D View (Object Mode)
    km_view3d = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    kmi = km_view3d.keymap_items.new(JBS_OT_copy_nodes.bl_idname, type="C", value="PRESS", ctrl=True)
    addon_keymaps.append((km_view3d, kmi))
    kmi = km_view3d.keymap_items.new(JBS_OT_cut_nodes.bl_idname, type="X", value="PRESS", ctrl=True)
    addon_keymaps.append((km_view3d, kmi))
    kmi = km_view3d.keymap_items.new(JBS_OT_delete_nodes.bl_idname, type="DEL", value="PRESS")
    addon_keymaps.append((km_view3d, kmi))

    # Text Editor
    km_text = kc.keymaps.new(name="Text", space_type="TEXT_EDITOR")
    kmi = km_text.keymap_items.new(JBS_OT_copy_nodes.bl_idname, type="C", value="PRESS", ctrl=True)
    addon_keymaps.append((km_text, kmi))
    kmi = km_text.keymap_items.new(JBS_OT_cut_nodes.bl_idname, type="X", value="PRESS", ctrl=True)
    addon_keymaps.append((km_text, kmi))
    kmi = km_text.keymap_items.new(JBS_OT_delete_nodes.bl_idname, type="DEL", value="PRESS")
    addon_keymaps.append((km_text, kmi))
    # Horizontal scroll with mouse wheel (tilt wheel / horizontal wheel and Shift+Wheel)
    kmi = km_text.keymap_items.new(JBS_OT_text_scroll_horizontal.bl_idname, type="WHEELRIGHTMOUSE", value="PRESS")
    kmi.properties.direction = "RIGHT"
    addon_keymaps.append((km_text, kmi))
    kmi = km_text.keymap_items.new(JBS_OT_text_scroll_horizontal.bl_idname, type="WHEELLEFTMOUSE", value="PRESS")
    kmi.properties.direction = "LEFT"
    addon_keymaps.append((km_text, kmi))
    kmi = km_text.keymap_items.new(JBS_OT_text_scroll_horizontal.bl_idname, type="WHEELDOWNMOUSE", value="PRESS", shift=True)
    kmi.properties.direction = "RIGHT"
    addon_keymaps.append((km_text, kmi))
    kmi = km_text.keymap_items.new(JBS_OT_text_scroll_horizontal.bl_idname, type="WHEELUPMOUSE", value="PRESS", shift=True)
    kmi.properties.direction = "LEFT"
    addon_keymaps.append((km_text, kmi))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()


def menu_import(self, _context):
    self.layout.operator(JBS_OT_import_pc.bl_idname, text="JBeam Vehicle (.pc)")
    self.layout.operator(JBS_OT_import_jbeam.bl_idname, text="JBeam Parts (.jbeam)")


class JBS_OT_dismiss_cursor_warning(bpy.types.Operator):
    bl_idname = "jbs.dismiss_cursor_warning"
    bl_label = "Dismiss warning"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        obj, session = active(context)
        if session:
            session.cursor_warning = None
        return {"FINISHED"}


CLASSES = (
    JBS_PartChoice, JBS_UL_parts,
    JBS_OT_import_pc, JBS_OT_import_jbeam_part, JBS_OT_import_jbeam, JBS_OT_apply_mesh, JBS_OT_save,
    JBS_OT_rebuild, JBS_OT_reload, JBS_OT_rescan, JBS_OT_load_object, JBS_OT_detach, JBS_OT_rename_node,
    JBS_OT_rename_nodes, JBS_OT_mirror, JBS_OT_add_resets, JBS_OT_fix, JBS_OT_add_extra, JBS_OT_add_rail,
    JBS_OT_add_slidenodes, JBS_OT_select_extra, JBS_OT_delete_extra, JBS_OT_expand_extra, JBS_OT_reset_display,
    JBS_OT_set_extra_property, JBS_OT_set_property,
    JBS_OT_select_by_property, JBS_OT_group_select, JBS_OT_group_hide, JBS_OT_rename_group, JBS_OT_flip_faces,
    JBS_OT_select_part, JBS_OT_show_text, JBS_OT_apply_text,
    JBS_OT_discard_text, JBS_OT_extract_vehicles, JBS_OT_filter_visible_selection,
    JBS_OT_copy_nodes, JBS_OT_cut_nodes, JBS_OT_delete_nodes, JBS_OT_text_scroll_horizontal, JBS_OT_dismiss_cursor_warning,
)
