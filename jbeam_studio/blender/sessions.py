"""JBeam objects: the edit session behind each one, and moving edits between its mesh and the session."""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

import bpy

from ..core.assembly import BeamEntry, FaceEntry, NodeEntry
from ..core.assembly.index import parts_in_file
from ..core.edit import EditError, EditSession, ExternalChangeError, MoveMode
from ..core.mesh_sync import MeshLink, SyncPlan
from ..core.model.files import load_source_file
from . import mesh_io

ADDON = __package__.rpartition(".")[0]
TEXT_PATH = "jbs_path"
TEXT_SESSION = "jbs_session"
TEXT_SHOWN = "jbs_shown"


class ObjectSession:
    """The edit session of one JBeam object, kept in memory while Blender runs."""

    def __init__(self, key: str, edit: EditSession, kind: str, path: Path, part_name: str):
        self.key = key
        self.edit = edit
        self.link = MeshLink(edit)
        self.kind = kind
        self.path = Path(path)
        self.part_name = part_name
        self.object_name = ""
        self.mode = "OBJECT"
        self.error: str | None = None
        """Why the last attempt to apply the mesh failed; the mesh then still has the edits."""
        self.stale = False
        """The mesh was built from a state the history no longer has, so its edits cannot be matched."""
        self.last_plan: SyncPlan | None = None
        self.built: tuple | None = None
        """Fingerprint of the mesh as last built or applied."""
        self.changed_on_disk: list[Path] = []
        self.save_error: str | None = None
        """Why the last automatic save failed."""
        self.saved_at: float | None = None
        """When files were last written, by a save or an automatic save."""
        self.saved_files: list[str] = []
        self.new_ids: dict[int, str] = {}
        """Ids given to new nodes by the last `mirror`, by vertex index."""
        self.mirrored: tuple | None = None
        """Fingerprint of the mesh the session was last brought in line with."""


SESSIONS: dict[str, ObjectSession] = {}


# opening

def parse_roots(text: str) -> list[Path]:
    return [Path(p.strip()) for p in text.split(";") if p.strip()]


def open_edit_session(kind: str, path: Path, part_name: str = "", roots=()) -> EditSession:
    roots = [Path(r) for r in roots if Path(r).is_dir()]
    if kind == "PC":
        return EditSession.for_pc(Path(path), vehicle_roots=roots)
    return EditSession.for_part(Path(path), part_name, vehicle_roots=roots)


def parts_of_file(path: Path) -> list[str]:
    parts, _ = parts_in_file(load_source_file(Path(path)))
    return list(parts)


def object_name_for(kind: str, path: Path, part_name: str) -> str:
    path = Path(path)
    if kind == "PC":
        return f"{path.parent.name} ({path.stem})"
    return part_name


def create_object(context, kind: str, path: Path, part_name: str = "", roots=()) -> bpy.types.Object:
    """Opens a vehicle or part and adds an object showing it to the active collection."""
    edit = open_edit_session(kind, path, part_name, roots)
    name = object_name_for(kind, path, part_name)
    obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    context.collection.objects.link(obj)
    settings = obj.jbs
    settings.kind = kind
    settings.path = str(Path(path).absolute())
    settings.part_name = part_name
    settings.vehicle_roots = ";".join(str(r) for r in roots)
    session = attach(obj, edit)
    settings.active_part = part_name if kind == "PART" else (edit.vehicle.main_part or next(iter(session.link.part_names), ""))
    return obj


def attach(obj, edit: EditSession) -> ObjectSession:
    settings = obj.jbs
    key = uuid.uuid4().hex
    session = ObjectSession(key, edit, settings.kind, Path(settings.path), settings.part_name)
    SESSIONS[key] = session
    settings.session_key = key
    session.object_name = obj.name
    session.mode = obj.mode
    if obj.mode == "EDIT":
        session.stale = True
    else:
        rebuild(obj, session)
    return session


def load_object(obj) -> ObjectSession:
    """Opens the files of an object saved in a .blend file and rebuilds its mesh from them (in Object Mode)."""
    settings = obj.jbs
    edit = open_edit_session(settings.kind, Path(settings.path), settings.part_name, parse_roots(settings.vehicle_roots))
    return attach(obj, edit)


# finding

def session_of(obj) -> ObjectSession | None:
    """The session of a JBeam object; None for other objects and for copies of a JBeam object."""
    if obj is None or obj.type != "MESH":
        return None
    session = SESSIONS.get(obj.jbs.session_key)
    if session is None:
        return None
    if session.object_name != obj.name:
        owner = bpy.data.objects.get(session.object_name)
        if owner is not None and owner != obj and owner.jbs.session_key == session.key:
            return None
        session.object_name = obj.name
    return session


def is_copy(obj) -> bool:
    return obj is not None and obj.type == "MESH" and obj.jbs.session_key in SESSIONS and session_of(obj) is None


def object_of(session: ObjectSession):
    obj = bpy.data.objects.get(session.object_name)
    if obj is not None and obj.jbs.session_key == session.key:
        return obj
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.jbs.session_key == session.key:
            session.object_name = obj.name
            return obj
    return None


def jbeam_objects() -> list[tuple[bpy.types.Object, ObjectSession]]:
    found = []
    for session in list(SESSIONS.values()):
        obj = object_of(session)
        if obj is not None:
            found.append((obj, session))
    return found


# mesh

def selected_node_ids(obj, session: ObjectSession) -> list[str]:
    """Nodes of the selected vertices; in Edit Mode in the order they were selected."""
    if obj.mode == "EDIT":
        bm, uid_layer, check_layer, _ = mesh_io.edit_mesh_uids(obj)
        if uid_layer is None or check_layer is None:
            return []
        ordered = [e for e in bm.select_history if hasattr(e, "co") and e.select]
        seen = {v.index for v in ordered}
        rest = [v for v in bm.verts if v.select and v.index not in seen]
        ids = [session.link.node_of(v[uid_layer], v[check_layer]) for v in ordered + rest]
        return list(dict.fromkeys(i for i in ids if i is not None))
    data = mesh_io.read_mesh(obj)
    ids = [session.link.node_of(data.node_uids[i], data.node_checks[i]) for i in mesh_io.selected_vertices(obj)]
    return list(dict.fromkeys(i for i in ids if i is not None))


def active_vertex(obj) -> int | None:
    """Index of the active vertex in Edit Mode, the one selected last."""
    if obj.mode != "EDIT":
        return None
    bm, _, _, _ = mesh_io.edit_mesh_uids(obj)
    active = bm.select_history.active
    if active is None or not hasattr(active, "co"):
        return None
    bm.verts.index_update()
    return active.index


def active_node_id(obj, session: ObjectSession) -> str | None:
    if obj.mode == "EDIT":
        bm, uid_layer, check_layer, _ = mesh_io.edit_mesh_uids(obj)
        active = bm.select_history.active
        if uid_layer is not None and check_layer is not None and active is not None and hasattr(active, "co"):
            return session.link.node_of(active[uid_layer], active[check_layer])
    ids = selected_node_ids(obj, session)
    return ids[-1] if ids else None


def selected_beams(obj, session: ObjectSession) -> list[BeamEntry]:
    if obj.mode != "EDIT":
        return []
    bm, _, _, edge_layer = mesh_io.edit_mesh_uids(obj)
    if edge_layer is None:
        return []
    beams = session.edit.vehicle.beams
    groups = session.link.map.beams
    found = []
    for edge in bm.edges:
        group = groups.get(edge[edge_layer]) if edge.select else None
        if group is not None:
            found.extend(beams[i] for i in group.indices)
    return found


def selected_entries(obj, session: ObjectSession, select_mode) -> list[NodeEntry | BeamEntry | FaceEntry]:
    """What is selected in Edit Mode, by select mode: vertices give nodes, edges beams, faces triangles and quads.

    Entries of the active element come first. Edges and faces count only while they still join the nodes of
    their beams and faces, so unapplied mesh edits do not point at the wrong rows.
    """
    bm, uid_layer, check_layer, edge_layer = mesh_io.edit_mesh_uids(obj)
    if uid_layer is None or check_layer is None:
        return []
    link, vehicle = session.link, session.edit.vehicle
    active = bm.select_history.active

    def ordered(elements):
        selected = [e for e in elements if e.select]
        if active is not None and active in selected:
            selected.remove(active)
            selected.insert(0, active)
        return selected

    def node_uids(element) -> frozenset:
        return frozenset(v[uid_layer] for v in element.verts if link.node_of(v[uid_layer], v[check_layer]))

    found: list = []
    vertex_mode, edge_mode, face_mode = select_mode
    if vertex_mode:
        for vertex in ordered(bm.verts):
            node_id = link.node_of(vertex[uid_layer], vertex[check_layer])
            entry = node_entry(session, node_id) if node_id else None
            if entry is not None:
                found.append(entry)
    if edge_mode and edge_layer is not None:
        groups = link.map.beams
        for edge in ordered(bm.edges):
            group = groups.get(edge[edge_layer])
            if group is not None and frozenset(group.nodes) == node_uids(edge):
                found.extend(vehicle.beams[i] for i in group.indices)
    face_layer = bm.faces.layers.int.get(mesh_io.FACE_UID)
    if face_mode and face_layer is not None:
        groups, faces = link.map.faces, vehicle.triangles + vehicle.quads
        for face in ordered(bm.faces):
            group = groups.get(face[face_layer])
            if group is not None and frozenset(group.nodes) == node_uids(face):
                found.extend(faces[i] for i in group.indices)
    return list({id(e): e for e in found}.values())


def node_entry(session: ObjectSession, node_id: str) -> NodeEntry | None:
    vehicle = session.edit.vehicle
    return vehicle.nodes.get(node_id) or vehicle.external_nodes.get(node_id)


def rebuild(obj, session: ObjectSession, selected: set[str] | None = None) -> None:
    """Builds the mesh from the session's current state, keeping the selection of nodes. Needs Object Mode."""
    if selected is None and len(obj.data.vertices):
        selected = set(selected_node_ids(obj, session))
    data = session.link.build()
    mesh_io.write_mesh(obj.data, data, session.link.rev)
    if selected:
        ids = session.link.map.ids
        mesh_io.select_vertices(obj.data, [i for i, uid in enumerate(data.node_uids) if ids.get(uid) in selected])
    session.built = mesh_io.fingerprint(obj)
    session.error = None
    session.stale = False
    refresh_texts(session)


STALE = ("The mesh was built from a state of the files that the edit history no longer has. "
         "Rebuild the mesh to continue; its unapplied edits are lost.")


def catch_up(obj, session: ObjectSession) -> bool:
    """Moves the session to the state the mesh was built from, which differs after Blender's undo."""
    rev = mesh_io.mesh_rev(obj)
    if rev is not None and rev != session.link.rev:
        if not session.link.goto(rev):
            session.stale = True
            return False
        refresh_texts(session)
        autosave(obj, session)
    session.stale = False
    return True


def auto_save_owner():
    """Where the "save after changes" setting lives, and its name: the add-on preferences, so undo does not
    turn it off and it lasts between Blender sessions, or the window manager when the add-on is not installed."""
    addon = bpy.context.preferences.addons.get(ADDON)
    preferences = addon.preferences if addon is not None else None
    if preferences is not None and hasattr(preferences, "auto_save"):
        return preferences, "auto_save"
    return bpy.context.window_manager, "jbs_auto_save"


def auto_save_enabled() -> bool:
    owner, name = auto_save_owner()
    return bool(getattr(owner, name, False))


def autosave(obj, session: ObjectSession) -> list[Path]:
    """Saves the changed files when "save after changes" is on; problems go to `save_error`."""
    if not auto_save_enabled():
        return []
    saved: list[Path] = []
    try:
        if session.edit.dirty_files():
            saved = session.edit.save()
    except ExternalChangeError as error:
        session.changed_on_disk = error.paths
        session.save_error = str(error)
        return []
    except OSError as error:
        session.save_error = str(error)
        return []
    session.save_error = None
    note_saved(session, saved)
    return saved


def note_saved(session: ObjectSession, saved: list[Path]) -> None:
    if saved:
        session.saved_at = time.time()
        session.saved_files = [p.name for p in saved]


def in_sync(obj, session: ObjectSession) -> bool:
    """Whether the mesh shows the session as it is (checked roughly, in Object Mode)."""
    return obj.mode != "EDIT" and session.built == mesh_io.fingerprint(obj) and mesh_io.mesh_rev(obj) == session.link.rev


def mirror(obj, session: ObjectSession) -> bool:
    """Brings the session to what the mesh shows: the state the mesh was built from, plus the mesh's edits.

    Leaves the mesh as it is and works in both modes, so it can run after every operation and after Blender's
    undo and redo. Returns whether the session changed. Raises EditError when the edits cannot be applied; the
    session then shows the state the mesh was built from.
    """
    before = session.link.rev
    rev = mesh_io.mesh_rev(obj)
    if rev is not None and rev != before and not session.link.goto(rev):
        session.stale = True
        raise EditError(STALE)
    session.stale = False
    data = mesh_io.read_mesh(obj)
    plan = session.link.plan(data)
    session.last_plan = plan
    session.new_ids = {}
    try:
        if not plan.empty:
            settings = obj.jbs
            session.edit.move_mode = MoveMode(settings.move_mode)
            session.new_ids = session.link.apply(
                plan, settings.active_part or None, settings.node_prefix or "n", settings.allow_shared,
                settings.auto_names, settings.placement, settings.new_group.strip() or None, active_vertex(obj))
    except EditError as error:
        session.error = str(error)
        raise
    finally:
        session.mirrored = mesh_io.fingerprint(obj)
        if session.link.rev != before:
            refresh_texts(session)
    session.error = None
    return session.link.rev != before


def apply_mesh(obj, session: ObjectSession) -> bool:
    """Writes the edits of the mesh into the session and builds the mesh again; True if the mesh was rebuilt.

    Needs Object Mode. Raises EditError, and keeps the mesh as it is, when the edits cannot be applied.
    """
    selected_vertices = mesh_io.selected_vertices(obj)
    mirror(obj, session)
    plan = session.last_plan
    if plan.empty and not plan.needs_rebuild:
        session.built = mesh_io.fingerprint(obj)
        autosave(obj, session)
        return False
    selected = {plan.vertex_nodes[v] for v in selected_vertices if v in plan.vertex_nodes}
    selected.update(session.new_ids[v] for v in selected_vertices if v in session.new_ids)
    rebuild(obj, session, selected)
    autosave(obj, session)
    return True


def apply_live(obj, session: ObjectSession) -> bool:
    """Writes the mesh edits into the session and saves if asked; in Edit Mode the result is also written into
    the edit mesh, so new nodes get their ids and show up in labels and text highlights right away."""
    if obj.mode == "EDIT":
        changed = commit_edit_mesh(obj, session)
    else:
        changed = mirror(obj, session)
    autosave(obj, session)
    return changed


def commit_edit_mesh(obj, session: ObjectSession) -> bool:
    """In Edit Mode: applies the mesh edits and writes the resulting uids and positions into the edit mesh,
    so the mesh matches the session exactly. Returns whether the session changed.

    The edit mesh then differs from Blender's last undo step, which holds the mesh as the user left it; undoing
    to that step or redoing it applies the same edits again and reaches the same state, so this is safe.
    """
    changed = mirror(obj, session)
    plan = session.last_plan
    if plan.empty and mesh_io.mesh_rev(obj) == session.link.rev:
        return changed
    mesh_io.stamp(obj, session.link, plan, session.new_ids)
    session.mirrored = mesh_io.fingerprint(obj)
    return changed


def after_change(obj, session: ObjectSession, renames=None, rebuild_mesh: bool = False) -> None:
    """Takes in a change made to the session outside the mesh, such as a rename."""
    session.link.changed(renames)
    if rebuild_mesh and obj.mode != "EDIT":
        rebuild(obj, session)
    else:
        mesh_io.set_rev(obj, session.link.rev)
        if obj.mode != "EDIT":
            session.built = mesh_io.fingerprint(obj)
        refresh_texts(session)
    autosave(obj, session)


# files

def watched_files(session: ObjectSession) -> list[Path]:
    vehicle = session.edit.vehicle
    paths = {Path(part.file.path).absolute() for part in vehicle.parts.values()}
    if vehicle.config is not None and vehicle.config.path:
        paths.add(Path(vehicle.config.path).absolute())
    paths.add(session.path.absolute())
    return sorted(paths)


def check_disk(session: ObjectSession) -> bool:
    """Updates `changed_on_disk`; True if it changed."""
    changed = session.edit.changed_on_disk(watched_files(session))
    if changed != session.changed_on_disk:
        session.changed_on_disk = changed
        return True
    return False


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def find_text(session: ObjectSession, path: Path):
    for text in bpy.data.texts:
        if text.get(TEXT_SESSION) == session.key and text.get(TEXT_PATH) == str(path):
            return text
    return None


def show_text(session: ObjectSession, path: Path):
    """Shows the file as the session has it, unsaved edits included, in a Blender text."""
    path = Path(path).absolute()
    text = find_text(session, path) or bpy.data.texts.new(path.name)
    content = session.edit.text_of(path).replace("\r\n", "\n")
    if text.as_string() != content:
        _rewrite(text, content)
    text[TEXT_PATH] = str(path)
    text[TEXT_SESSION] = session.key
    text[TEXT_SHOWN] = _digest(text.as_string())
    return text


def _rewrite(text, content: str) -> None:
    """Replaces the content of a Blender text, keeping its cursor, selection and scroll position."""
    cursor = (text.current_line_index, text.current_character, text.select_end_line_index, text.select_end_character)
    wm = bpy.context.window_manager
    spaces = [(area.spaces.active, area.spaces.active.top) for window in (wm.windows if wm else ())
              for area in window.screen.areas
              if area.type == "TEXT_EDITOR" and area.spaces.active.text == text]
    text.clear()
    text.write(content)
    lines = text.lines

    def clamp(line, character):
        line = min(max(line, 0), len(lines) - 1)
        return line, min(max(character, 0), len(lines[line].body))

    start, end = clamp(*cursor[:2]), clamp(*cursor[2:])
    text.select_set(start[0], start[1], end[0], end[1])
    for space, top in spaces:
        space.top = top


def edited_texts(session: ObjectSession) -> list:
    """Blender texts of the session that were edited in the text editor and not applied."""
    return [t for t in bpy.data.texts if t.get(TEXT_SESSION) == session.key and text_edited(t)]


def text_edited(text) -> bool:
    return TEXT_SHOWN in text and _digest(text.as_string()) != text[TEXT_SHOWN]


def refresh_texts(session: ObjectSession) -> None:
    for text in list(bpy.data.texts):
        if text.get(TEXT_SESSION) == session.key and not text_edited(text):
            show_text(session, Path(text[TEXT_PATH]))


def apply_text(obj, session: ObjectSession, text) -> None:
    """Replaces the file with the text edited in Blender; needs Object Mode."""
    path = Path(text[TEXT_PATH])
    content = text.as_string()
    if "\r\n" in session.edit.text_of(path):
        content = content.replace("\n", "\r\n")
    session.edit.replace_text(path, content)
    session.link.changed()
    text[TEXT_SHOWN] = _digest(text.as_string())
    rebuild(obj, session)
    autosave(obj, session)
