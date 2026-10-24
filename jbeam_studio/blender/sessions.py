"""JBeam objects: the edit session behind each one, and moving edits between its mesh and the session."""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

import bmesh
import bpy

from ..core.assembly import BeamEntry, FaceEntry, NodeEntry
from ..core.assembly.index import parts_in_file
from ..core.edit import EditError, EditSession, ExternalChangeError, MoveMode
from ..core import mesh_sync
from ..core.mesh_sync import MeshLink, SyncPlan
from ..core.edit.text import merge_texts
from ..core.model.files import load_source_file, read_text
from . import mesh_io

ADDON = __package__.rpartition(".")[0]
TEXT_PATH = "jbs_path"
TEXT_SESSION = "jbs_session"
TEXT_SHOWN = "jbs_shown"


class Group:
    """The edit session of one imported vehicle or part, kept in memory while Blender runs, and the objects that
    show its parts."""

    def __init__(self, key: str, edit: EditSession, kind: str, path: Path):
        self.key = key
        self.edit = edit
        self.link = MeshLink(edit)
        self.kind = kind
        self.path = Path(path)
        self.views: dict[str, ObjectSession] = {}
        """The object of each part, by part name; "" for an object of the whole vehicle from an older version."""
        self.changed_on_disk: list[Path] = []
        self.save_error: str | None = None
        self.cursor_warning: str | None = None
        """Why the last automatic save failed."""
        self.saved_at: float | None = None
        """When files were last written, by a save or an automatic save."""
        self.saved_files: list[str] = []
        self.shared: dict[Path, str] = {}
        """Text of each file as last passed between sessions, for files the session changed since reading them."""
        self.pending: dict[Path, tuple[str, str]] = {}
        """Changes other sessions made to files of this one and it has not taken yet: its text, and theirs."""
        self.quiet: dict[Path, tuple] = {}
        """File states on disk that are only the changes it has still to take, so they are not reported."""


def _shared(name: str):
    return property(lambda self: getattr(self.group, name), lambda self, value: setattr(self.group, name, value))


class ObjectSession:
    """One JBeam object: the part of its group's vehicle that it shows, and the state of its mesh."""

    key = _shared("key")
    edit = _shared("edit")
    link = _shared("link")
    kind = _shared("kind")
    path = _shared("path")
    changed_on_disk = _shared("changed_on_disk")
    save_error = _shared("save_error")
    cursor_warning = _shared("cursor_warning")
    saved_at = _shared("saved_at")
    saved_files = _shared("saved_files")

    def __init__(self, group: Group, scope: str | None):
        self.group = group
        self.scope = scope
        """The part the object shows and edits; None for the whole vehicle."""
        self.object_name = ""
        self.mode = "OBJECT"
        self.error: str | None = None
        """Why the last attempt to apply the mesh failed; the mesh then still has the edits."""
        self.stale = False
        """The mesh was built from a state the history no longer has, so its edits cannot be matched."""
        self.last_plan: SyncPlan | None = None
        self.built: tuple | None = None
        """Fingerprint of the mesh as last built or applied."""
        self.new_ids: dict[int, str] = {}
        """Ids given to new nodes by the last `mirror`, by vertex index."""
        self.mirrored: tuple | None = None
        """Fingerprint of the mesh the session was last brought in line with."""
        self.shown: int | None = None
        """What the mesh showed when it was last built, to tell whether building it again would change it."""

    @property
    def part_name(self) -> str:
        return self.scope or ""


SESSIONS: dict[str, Group] = {}
ROOT_COLLECTION = "JBeam"
COLLECTION_ROOT = "jbs_root"
COLLECTION_PATH = "jbs_path"
COLLECTION_GROUP = "jbs_group"


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


def has_geometry(edit: EditSession, part: str) -> bool:
    """Whether a part has nodes, or rows of beams, faces, hydros or rails, to show as an object."""
    vehicle = edit.vehicle
    return any(e.part == part for e in (*vehicle.nodes.values(), *vehicle.beams, *vehicle.triangles,
                                        *vehicle.quads, *vehicle.extras))


def root_collection(context):
    """The JBeam collection of the scene, which holds a collection for each file."""
    root = next((c for c in bpy.data.collections if c.get(COLLECTION_ROOT)), None)
    if root is None:
        root = bpy.data.collections.new(ROOT_COLLECTION)
        root[COLLECTION_ROOT] = True
    scene = context.scene.collection
    if root.name not in scene.children and root not in scene.children_recursive:
        scene.children.link(root)
    return root


def file_collection(context, path: Path, group_key: str = ""):
    """The collection of a .jbeam file under the JBeam collection: one for the parts a vehicle uses from the file,
    or one shared by parts imported on their own (`group_key` empty)."""
    root = root_collection(context)
    for child in root.children:
        if child.get(COLLECTION_PATH) == str(path) and child.get(COLLECTION_GROUP, "") == group_key:
            return child
    collection = bpy.data.collections.new(Path(path).name)
    collection[COLLECTION_PATH] = str(path)
    collection[COLLECTION_GROUP] = group_key
    root.children.link(collection)
    return collection


def create_objects(context, kind: str, path: Path, part_names=(), roots=(), skip_empty: bool = False) -> list[bpy.types.Object]:
    """Opens a vehicle, or parts of a .jbeam file, and adds an object for each part to the collection of its
    file under the JBeam collection. A vehicle gets one object for each of its parts that has something to show,
    and so do the parts of a file with `skip_empty`."""
    path = Path(path).absolute()
    objects = []
    if kind == "PC":
        edit = open_edit_session(kind, path, "", roots)
        group = _new_group(edit, kind, path)
        for part, definition in edit.vehicle.parts.items():
            if has_geometry(edit, part):
                file = Path(definition.file.path).absolute()
                objects.append(_new_object(context, group, part, file_collection(context, file, group.key), roots))
        if not objects:
            SESSIONS.pop(group.key, None)
            raise EditError(f"{path.name} has no parts with nodes, beams or faces")
        return objects
    for part in part_names:
        group = _new_group(open_edit_session(kind, path, part, roots), kind, path)
        if skip_empty and not has_geometry(group.edit, part):
            SESSIONS.pop(group.key, None)
            continue
        objects.append(_new_object(context, group, part, file_collection(context, path), roots))
    return objects


def _new_group(edit: EditSession, kind: str, path: Path, key: str | None = None) -> Group:
    group = Group(key or uuid.uuid4().hex, edit, kind, path)
    SESSIONS[group.key] = group
    return group


def _new_object(context, group: Group, part: str, collection, roots) -> bpy.types.Object:
    obj = bpy.data.objects.new(part, bpy.data.meshes.new(part))
    collection.objects.link(obj)
    settings = obj.jbs
    settings.kind = group.kind
    settings.path = str(group.path)
    settings.part_name = part
    settings.vehicle_roots = ";".join(str(r) for r in roots)
    settings.session_key = group.key
    settings.active_part = part
    attach(obj, group, part)
    return obj


def attach(obj, group: Group, scope: str | None) -> ObjectSession:
    session = ObjectSession(group, scope)
    group.views[session.part_name] = session
    session.object_name = obj.name
    session.mode = obj.mode
    if obj.mode == "EDIT":
        session.stale = True
    else:
        rebuild(obj, session, others=False)
    return session


def load_object(obj) -> ObjectSession:
    """Opens the files of an object saved in a .blend file and rebuilds its mesh from them (in Object Mode). Objects
    that showed parts of one vehicle share its session again."""
    settings = obj.jbs
    group = SESSIONS.get(settings.session_key) if settings.session_key else None
    if group is None or group.kind != settings.kind or group.path != Path(settings.path):
        part = settings.part_name if settings.kind == "PART" else ""
        edit = open_edit_session(settings.kind, Path(settings.path), part, parse_roots(settings.vehicle_roots))
        group = _new_group(edit, settings.kind, Path(settings.path), settings.session_key or None)
        settings.session_key = group.key
    return attach(obj, group, settings.part_name or None)


def detach(obj) -> None:
    session = session_of(obj)
    if session is not None:
        session.group.views.pop(session.part_name, None)
        if not session.group.views:
            SESSIONS.pop(session.key, None)
    obj.jbs.kind = "NONE"
    obj.jbs.session_key = ""


# finding

def session_of(obj) -> ObjectSession | None:
    """The session of a JBeam object; None for other objects and for copies of a JBeam object."""
    if obj is None or obj.type != "MESH":
        return None
    group = SESSIONS.get(obj.jbs.session_key)
    session = group.views.get(obj.jbs.part_name) if group is not None else None
    if session is None:
        return None
    if session.object_name != obj.name:
        owner = bpy.data.objects.get(session.object_name)
        if owner is not None and owner != obj and _shows(owner, session):
            return None
        session.object_name = obj.name
    return session


def _shows(obj, session: ObjectSession) -> bool:
    return obj.type == "MESH" and obj.jbs.session_key == session.key and obj.jbs.part_name == session.part_name


def is_copy(obj) -> bool:
    return obj is not None and obj.type == "MESH" and obj.jbs.session_key in SESSIONS and session_of(obj) is None


def object_of(session: ObjectSession):
    obj = bpy.data.objects.get(session.object_name)
    if obj is not None and _shows(obj, session):
        return obj
    for obj in bpy.data.objects:
        if _shows(obj, session):
            session.object_name = obj.name
            return obj
    return None


def views_of(session: ObjectSession) -> list[tuple[bpy.types.Object, ObjectSession]]:
    """The objects of every part of the session's vehicle, the session's own first."""
    found = []
    for view in [session, *(v for v in session.group.views.values() if v is not session)]:
        obj = object_of(view)
        if obj is not None:
            found.append((obj, view))
    return found


def jbeam_objects() -> list[tuple[bpy.types.Object, ObjectSession]]:
    found = []
    for group in list(SESSIONS.values()):
        for session in list(group.views.values()):
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
    if obj.mode != "EDIT":
        selected_indices = mesh_io.selected_vertices(obj)
        if not selected_indices:
            return []
        data_uids = mesh_io._read(obj.data, mesh_io.NODE_UID, "POINT", len(obj.data.vertices)).tolist()
        uids = {data_uids[i] for i in selected_indices if i < len(data_uids)}
        id_map = session.link.map.ids
        vehicle = session.edit.vehicle
        return [vehicle.nodes[id_map[u]] for u in uids if u in id_map and id_map[u] in vehicle.nodes]
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


def scene_key() -> tuple:
    """The state of every open session; what depends on all of them is worked out again when it changes."""
    return tuple((group.key, group.link.rev) for group in SESSIONS.values() if group.views)


def rebuild(obj, session: ObjectSession, selected: set[str] | None = None, others: bool = True, data=None) -> None:
    """Builds the mesh from the session's current state, keeping the selection of nodes; with `others`, the
    meshes of the other parts of the vehicle that show another state are built again too."""
    if selected is None:
        selected = set(selected_node_ids(obj, session)) if _vertex_count(obj) else set()
    if data is None:
        data = session.link.build(session.scope, obj.jbs.all_nodes)
    session.shown = _shape(data)
    rev = session.link.rev
    nodes = session.link.map.nodes
    if obj.mode == "EDIT":
        mesh_io.write_edit_mesh(obj, data, rev, {nodes[i] for i in selected if i in nodes})
        session.mirrored = mesh_io.fingerprint(obj)
    else:
        mesh_io.write_mesh(obj.data, data, rev)
        if selected:
            ids = session.link.map.ids
            mesh_io.select_vertices(obj.data, [i for i, uid in enumerate(data.node_uids) if ids.get(uid) in selected])
    session.built = mesh_io.fingerprint(obj)
    session.error = None
    session.stale = False
    if others:
        sync_others(session)
    refresh_texts(session)


def _vertex_count(obj) -> int:
    return len(bmesh.from_edit_mesh(obj.data).verts) if obj.mode == "EDIT" else len(obj.data.vertices)


def sync_others(session: ObjectSession) -> None:
    """Brings the meshes of the other parts of the session's vehicle to its current state: a mesh whose part looks
    the same is only marked with the state, the others are built again."""
    rev = session.link.rev
    for obj, view in views_of(session)[1:]:
        if mesh_io.mesh_rev(obj) == rev and not view.stale:
            continue
        data = view.link.build(view.scope, obj.jbs.all_nodes)
        if (obj.mode != "EDIT" and not view.stale and view.shown == _shape(data)
                and view.built == mesh_io.fingerprint(obj)):
            mesh_io.set_rev(obj, rev)
            view.built = mesh_io.fingerprint(obj)
            continue
        rebuild(obj, view, others=False, data=data)
    share_changes(session)


_sharing = False
_refresh: dict[str, Group] = {}
"""Sessions with changes of other sessions to take, whose objects show what changed, by key."""
_last_share = 0.0
REFRESH_DELAY = 0.6
"""Pause after the last change before other sessions that show what changed take it."""
REFRESH_BUDGET = 0.03
"""Time spent taking changes in one tick of the timer, so the viewport stays smooth meanwhile."""


def share_changes(session: ObjectSession) -> None:
    """Passes the session's changes of files to the other sessions that read the same files, such as other parts
    of one .jbeam file imported on their own. A session that has the file as it was before the change keeps the
    change to take later (`ensure_current`): before it edits or saves anything, or, if its objects show what the
    file defines, once editing pauses. A session that changed the file itself keeps its own text."""
    global _last_share
    group = session.group
    if _sharing:
        return
    changed: dict[Path, tuple[str, str]] = {}
    for path in set(group.edit.texts) | set(group.shared):
        text = group.edit.text_of(path)
        before = group.shared.get(path, group.edit.base_text(path))
        if before is not None and before != text:
            changed[path] = (before, text)
            group.shared[path] = text
    if not changed:
        return
    spans = {path: _changed_span(before, text) for path, (before, text) in changed.items()}
    for other in SESSIONS.values():
        if other is group or not other.views:
            continue
        for path, (before, text) in changed.items():
            if not other.edit.knows(path):
                continue
            own = other.edit.text_of(path)
            seen = other.pending.get(path, (own, own))[1]
            if seen not in (before, text):
                continue
            if own == text:
                other.pending.pop(path, None)
            else:
                other.pending[path] = (own, text)
                if _shows_change(other, path, spans[path] if own == before else None):
                    _refresh[other.key] = other
            other.shared[path] = text
    if _refresh:
        _last_share = time.perf_counter()
        if not bpy.app.timers.is_registered(_take_shared):
            bpy.app.timers.register(_take_shared, first_interval=REFRESH_DELAY)


def _changed_span(before: str, after: str) -> tuple[int, int]:
    """The span of `before` from its first difference to `after` to its last one."""
    shorter = min(len(before), len(after))
    low, high = 0, shorter
    while low < high:
        middle = (low + high + 1) // 2
        if before[:middle] == after[:middle]:
            low = middle
        else:
            high = middle - 1
    start = low
    low, high = 0, shorter - start
    while low < high:
        middle = (low + high + 1) // 2
        if before[len(before) - middle:] == after[len(after) - middle:]:
            low = middle
        else:
            high = middle - 1
    return start, len(before) - low


def _shows_change(group: Group, path: Path, span: tuple[int, int] | None) -> bool:
    """Whether the objects of a session show something a file defines in a changed span of the session's text of
    the file: a part, or nodes of other parts. Without a span, whether they show anything the file defines."""
    vehicle = group.edit.vehicle

    def touched(src) -> bool:
        if src is None or Path(src.file) != path:
            return False
        return span is None or (src.node.start <= span[1] and span[0] <= src.node.end)

    return (any(touched(part.data.src) for part in vehicle.parts.values())
            or any(touched(node.src) for node in vehicle.external_nodes.values()))


def _take_shared() -> float | None:
    if time.perf_counter() - _last_share < REFRESH_DELAY:
        return REFRESH_DELAY
    started = time.perf_counter()
    for key, group in list(_refresh.items()):
        if time.perf_counter() - started > REFRESH_BUDGET:
            return 0.05
        if SESSIONS.get(key) is not group:
            del _refresh[key]
        elif not any(o.mode == "EDIT" for o, _ in _objects(group)):
            del _refresh[key]
            ensure_current(group)
    return 1.0 if _refresh else None


def _objects(group: Group) -> list:
    return [(o, v) for v in group.views.values() if (o := object_of(v)) is not None]


def ensure_current(group: Group) -> bool:
    """Takes the changes other sessions made to the session's files, as one step of its history, and builds its
    objects again. Unapplied mesh edits of the objects are applied first; where the session itself changed a file
    since, the changes of both are joined line by line, and only its own are kept where both touched the same lines.
    Returns whether the session changed."""
    global _sharing
    if isinstance(group, ObjectSession):
        group = group.group
    if not group.pending or _sharing:
        return False
    _refresh.pop(group.key, None)
    views = _objects(group)
    _sharing = True
    try:
        editing = [(o, v) for o, v in views if o.mode == "EDIT"]
        if editing:
            commit_edit_mesh(*editing[0])
        for index, (obj, view) in enumerate((o, v) for o, v in views if o.mode != "EDIT"):
            if not in_sync(obj, view):
                mirror(obj, view, follow=index == 0 and not editing)
        pending, group.pending = group.pending, {}
        taken = {}
        for path, (before, theirs) in pending.items():
            own = group.edit.text_of(path)
            text = merge_texts(before, own, theirs)
            if text is not None and text != own:
                taken[path] = text
        if not taken:
            return False
        with group.edit.transaction(f"Take the edits of {', '.join(p.name for p in taken)}"):
            for path, text in taken.items():
                group.edit.replace_text(path, text)
    except EditError:
        return False
    finally:
        _sharing = False
    for path in taken:
        group.edit.accept_disk(path)
    group.link.changed()
    for obj, view in views:
        rebuild(obj, view, others=False)
    if views:
        share_changes(views[0][1])
    return True


def _shape(data) -> int:
    return hash((tuple(data.positions), tuple(data.node_uids), tuple(data.edges), tuple(data.edge_uids),
                 tuple(data.faces), tuple(data.face_uids), tuple(data.ghosts)))


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
    sync_others(session)
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
    """Records a save; other sessions that have the saved files with the same text take them as saved."""
    if saved:
        session.saved_at = time.time()
        session.saved_files = [p.name for p in saved]
        for other in SESSIONS.values():
            if other is not session.group:
                for path in saved:
                    other.edit.accept_disk(path)


def in_sync(obj, session: ObjectSession) -> bool:
    """Whether the mesh shows the session as it is (checked roughly, in Object Mode)."""
    return obj.mode != "EDIT" and session.built == mesh_io.fingerprint(obj) and mesh_io.mesh_rev(obj) == session.link.rev


def get_cursor_target(session: ObjectSession) -> tuple[str | None, str | None, int | None]:
    """Finds the (part_name, section, anchor_idx) at the text cursor position for this session."""
    text = None
    space = getattr(bpy.context, "space_data", None) if bpy.context else None
    if space and getattr(space, "type", "") == "TEXT_EDITOR" and space.text:
        if space.text.get(TEXT_SESSION) == session.key:
            text = space.text
    if text is None:
        wm = getattr(bpy.context, "window_manager", None) if bpy.context else None
        if wm:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type == "TEXT_EDITOR" and area.spaces.active and area.spaces.active.text:
                        t = area.spaces.active.text
                        if t.get(TEXT_SESSION) == session.key:
                            text = t
                            break
                if text is not None:
                    break
    if text is None:
        for t in bpy.data.texts:
            if t.get(TEXT_SESSION) == session.key:
                text = t
                break
    if text is None or not text.get(TEXT_PATH):
        return None, None, None
    path = Path(text[TEXT_PATH])
    line = text.current_line_index
    col = text.current_character
    return mesh_sync.find_cursor_target(session.edit, path, line, col)


def mirror(obj, session: ObjectSession, follow: bool = True) -> bool:
    """Brings the session to what the mesh shows: the state the mesh was built from, plus the mesh's edits.

    Leaves the mesh as it is and works in both modes, so it can run after every operation and after Blender's
    undo and redo. Returns whether the session changed. Raises EditError when the edits cannot be applied; the
    session then shows the state the mesh was built from. Without `follow` the session stays in its state, for
    a mesh of another part applied right after one that moved it there.
    """
    ensure_current(session.group)
    before = session.link.rev
    rev = mesh_io.mesh_rev(obj)
    if follow and rev is not None and rev != before and not session.link.goto(rev):
        session.stale = True
        raise EditError(STALE)
    session.stale = False
    data = mesh_io.read_mesh(obj)
    plan = session.link.plan(data, session.scope)
    session.last_plan = plan
    session.new_ids = {}
    try:
        if not plan.empty:
            settings = obj.jbs
            session.edit.move_mode = MoveMode(settings.move_mode)
            node_mode = True
            if obj.mode == "EDIT":
                tool_settings = getattr(bpy.context, "tool_settings", None) if bpy.context else None
                if tool_settings and hasattr(tool_settings, "mesh_select_mode"):
                    node_mode = bool(tool_settings.mesh_select_mode[0])
            placement = "cursor" if settings.place_at_cursor else settings.placement
            cursor_target = None
            if placement == "cursor":
                cursor_target = get_cursor_target(session)
            session.new_ids = session.link.apply(
                plan, settings.active_part or None, settings.node_prefix or "n", settings.allow_shared,
                settings.auto_names, placement, settings.new_group.strip() or None, active_vertex(obj),
                keep_dependents=node_mode, cursor_target=cursor_target)
            session.cursor_warning = session.link.last_cursor_warning
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
        sync_others(session)
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
        sync_others(session)
    autosave(obj, session)
    if changed:
        refresh_texts(session)
    return changed


def commit_edit_mesh(obj, session: ObjectSession) -> bool:
    """In Edit Mode: applies the mesh edits of every part of the vehicle in Edit Mode and writes the resulting
    uids and positions into their edit meshes, so they match the session exactly; the meshes of the other parts
    are built again. Returns whether the session changed.

    The edit mesh then differs from Blender's last undo step, which holds the mesh as the user left it; undoing
    to that step or redoing it applies the same edits again and reaches the same state, so this is safe.
    """
    editing = [(o, v) for o, v in views_of(session) if o.mode == "EDIT"] or [(obj, session)]
    changed = False
    for index, (edited, view) in enumerate(editing):
        changed |= mirror(edited, view, follow=index == 0)
    rev = session.link.rev
    for edited, view in editing:
        if view.last_plan.empty and mesh_io.mesh_rev(edited) == rev:
            continue
        mesh_io.stamp(edited, session.link, view.last_plan, view.new_ids)
        view.mirrored = mesh_io.fingerprint(edited)
    sync_others(session)
    if changed:
        refresh_texts(session)
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
        sync_others(session)
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
    """Updates `changed_on_disk`; True if it changed. A file on disk that holds the session's text, or a change of
    another session it has still to take, is not reported."""
    group = session.group
    changed = []
    for path in session.edit.changed_on_disk(watched_files(session)):
        if session.edit.accept_disk(path):
            continue
        if path in group.pending:
            try:
                stat = path.stat()
                state = (stat.st_mtime_ns, stat.st_size)
                if group.quiet.get(path) == state or read_text(path) == group.pending[path][1]:
                    group.quiet[path] = state
                    continue
            except OSError:
                pass
        changed.append(path)
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
    ensure_current(session.group)
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


TEXT_APPLY_DELAY = 0.35
_text_mod_times: dict[str, float] = {}
_text_last_contents: dict[str, str] = {}


def check_auto_apply_texts() -> bool:
    """Automatically applies valid text edits to the 3D meshes and session when auto-save is enabled."""
    if not auto_save_enabled():
        _text_mod_times.clear()
        _text_last_contents.clear()
        return False

    now = time.monotonic()
    changed_any = False

    for text in list(bpy.data.texts):
        key = text.get(TEXT_SESSION)
        if not key or key not in SESSIONS:
            continue
        group = SESSIONS[key]
        if not text_edited(text):
            _text_mod_times.pop(text.name, None)
            _text_last_contents.pop(text.name, None)
            continue

        raw = text.as_string()
        if _text_last_contents.get(text.name) != raw:
            _text_last_contents[text.name] = raw
            _text_mod_times[text.name] = now
            continue

        last_time = _text_mod_times.get(text.name, 0.0)
        if now - last_time < TEXT_APPLY_DELAY:
            continue

        path_str = text.get(TEXT_PATH)
        if not path_str:
            continue
        path = Path(path_str)
        content = raw
        if "\r\n" in group.edit.text_of(path):
            content = content.replace("\n", "\r\n")

        from ..core.sjson import parse
        doc = parse(content, str(path))
        if doc.diagnostics.has_errors():
            continue

        active = bpy.context.view_layer.objects.active if bpy.context.view_layer else None
        active_sess = session_of(active) if active else None
        target_session = active_sess if (active_sess and active_sess.group is group) else next(iter(group.views.values()), None)
        if target_session is None:
            continue
        obj = object_of(target_session)
        if obj is None:
            continue

        try:
            apply_text(obj, target_session, text)
            _text_mod_times.pop(text.name, None)
            _text_last_contents.pop(text.name, None)
            changed_any = True
        except EditError:
            pass
        except Exception:
            import traceback
            traceback.print_exc()

    return changed_any
