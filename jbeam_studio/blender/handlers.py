"""Blender handlers and timers: applying mesh edits on leaving Edit Mode, undo, file loading, external changes."""

from __future__ import annotations

import traceback

import bpy
from bpy.app.handlers import persistent

from ..core.edit import EditError
from . import mesh_io, sessions

WATCH_INTERVAL = 2.0
LIVE_DELAY = 0.3
"""Pause after the last change of an edit mesh before its edits are applied."""
MODAL_WAIT = 5.0
"""How long applying waits for running tools such as a move to finish; some add-ons keep a tool running."""
_restoring = False
_live_tokens: dict[str, int] = {}
_listeners: list = []
"""Callables run after a session changed outside an operator, such as on leaving Edit Mode."""


def window_context() -> dict:
    wm = bpy.context.window_manager
    window = bpy.context.window or (wm.windows[0] if wm is not None and wm.windows else None)
    return {"window": window} if window is not None else {}


def undo_push(message: str) -> None:
    override = window_context()
    if not override:
        return
    with bpy.context.temp_override(**override):
        bpy.ops.ed.undo_push(message=message)


def redraw() -> None:
    wm = bpy.context.window_manager
    for window in wm.windows if wm is not None else ():
        for area in window.screen.areas:
            if area.type in {"VIEW_3D", "TEXT_EDITOR", "PROPERTIES"}:
                area.tag_redraw()


def notify(title: str, message: str, icon: str = "ERROR") -> None:
    override = window_context()
    if not override:
        print(f"JBeam Studio: {title}: {message}")
        return

    def draw(menu, _context):
        for line in message.splitlines():
            menu.layout.label(text=line)

    with bpy.context.temp_override(**override):
        bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def find_view(key: str, part: str):
    group = sessions.SESSIONS.get(key)
    session = group.views.get(part) if group is not None else None
    return (sessions.object_of(session), session) if session is not None else (None, None)


def apply_later(key: str, part: str) -> None:
    def run():
        obj, session = find_view(key, part)
        if obj is None or obj.mode == "EDIT":
            return None
        try:
            changed = sessions.apply_mesh(obj, session)
        except EditError as error:
            notify(bpy.app.translations.pgettext_iface("Mesh edits were not applied"), str(error))
            redraw()
            return None
        except Exception:
            session.error = traceback.format_exc(limit=3)
            traceback.print_exc()
            redraw()
            return None
        if changed:
            undo_push("JBeam: apply mesh edits")
            if session.save_error:
                notify(bpy.app.translations.pgettext_iface("Files were not saved"), session.save_error)
        for listener in _listeners:
            listener(obj, session)
        redraw()
        return None

    bpy.app.timers.register(run, first_interval=0.0)


def _operator_running() -> bool:
    wm = bpy.context.window_manager
    return any(len(window.modal_operators) for window in wm.windows) if wm is not None else False


def apply_live_later(key: str) -> None:
    """Applies the edits of the edit meshes of a vehicle's parts once they stopped changing and no tool is still
    running."""
    token = _live_tokens[key] = _live_tokens.get(key, 0) + 1
    waited = 0.0

    def run():
        nonlocal waited
        if _live_tokens.get(key) != token or _restoring:
            return None
        group = sessions.SESSIONS.get(key)
        editing = [(o, s) for o, s in sessions.jbeam_objects() if s.group is group and o.mode == "EDIT"]
        active = bpy.context.view_layer.objects.active if bpy.context.view_layer else None
        editing.sort(key=lambda item: item[0] != active)
        if not editing:
            return None
        obj, session = editing[0]
        if not obj.jbs.live_apply or session.stale:
            return None
        if _operator_running() and waited < MODAL_WAIT:
            waited += LIVE_DELAY
            return LIVE_DELAY
        if all(mesh_io.fingerprint(o) == s.mirrored for o, s in editing):
            return None
        try:
            sessions.apply_live(obj, session)
        except EditError:
            pass
        except Exception:
            session.error = traceback.format_exc(limit=3)
            traceback.print_exc()
        for listener in _listeners:
            listener(obj, session)
        redraw()
        return None

    bpy.app.timers.register(run, first_interval=LIVE_DELAY)


def _geometry_changed(depsgraph, obj) -> bool:
    for update in depsgraph.updates:
        original = getattr(update.id, "original", update.id)
        if update.is_updated_geometry and (original == obj or original == obj.data):
            return True
    return False


@persistent
def on_depsgraph_update(_scene, depsgraph) -> None:
    if _restoring:
        return
    for obj, session in sessions.jbeam_objects():
        mode = obj.mode
        if session.mode == "EDIT" and mode != "EDIT" and obj.jbs.apply_on_exit:
            apply_later(session.key, session.part_name)
        elif mode == "EDIT" and obj.jbs.live_apply and _geometry_changed(depsgraph, obj):
            apply_live_later(session.key)
        session.mode = mode


@persistent
def on_undo_pre(*_args) -> None:
    global _restoring
    _restoring = True


@persistent
def on_undo_post(*_args) -> None:
    """Brings each session to the mesh Blender restored: with live applying, to the mesh with its edits. Of the
    parts of a vehicle, a part in Edit Mode, or else the active object, leads, and the others follow it."""
    global _restoring
    try:
        active = bpy.context.view_layer.objects.active if bpy.context.view_layer else None
        objects = sessions.jbeam_objects()
        for group in list(sessions.SESSIONS.values()):
            views = [(o, s) for o, s in objects if s.group is group]
            views.sort(key=lambda item: (item[0].mode != "EDIT", item[0] != active))
            if not views:
                continue
            obj, session = views[0]
            try:
                if obj.jbs.live_apply:
                    sessions.apply_live(obj, session)
                else:
                    sessions.catch_up(obj, session)
            except EditError:
                pass
            except Exception:
                traceback.print_exc()
            for view_obj, view in views:
                view.mode = view_obj.mode
    finally:
        _restoring = False


@persistent
def on_load_pre(*_args) -> None:
    sessions.SESSIONS.clear()


@persistent
def on_load_post(*_args) -> None:
    for obj in list(bpy.data.objects):
        if obj.type != "MESH" or obj.jbs.kind == "NONE" or not obj.jbs.path:
            continue
        try:
            sessions.load_object(obj)
        except Exception as error:
            print(f"JBeam Studio: {obj.name} could not be loaded from {obj.jbs.path}: {error}")


def watch() -> float:
    try:
        changed = False
        checked = set()
        for _obj, session in sessions.jbeam_objects():
            if session.key not in checked:
                checked.add(session.key)
                changed |= sessions.check_disk(session)
        if changed:
            redraw()
    except Exception:
        traceback.print_exc()
    return WATCH_INTERVAL


HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, on_depsgraph_update),
    (bpy.app.handlers.undo_pre, on_undo_pre),
    (bpy.app.handlers.redo_pre, on_undo_pre),
    (bpy.app.handlers.undo_post, on_undo_post),
    (bpy.app.handlers.redo_post, on_undo_post),
    (bpy.app.handlers.load_pre, on_load_pre),
    (bpy.app.handlers.load_post, on_load_post),
)


def register() -> None:
    for handlers, function in HANDLERS:
        if function not in handlers:
            handlers.append(function)
    if not bpy.app.timers.is_registered(watch):
        bpy.app.timers.register(watch, first_interval=WATCH_INTERVAL, persistent=True)


def unregister() -> None:
    if bpy.app.timers.is_registered(watch):
        bpy.app.timers.unregister(watch)
    for handlers, function in HANDLERS:
        if function in handlers:
            handlers.remove(function)
    sessions.SESSIONS.clear()
