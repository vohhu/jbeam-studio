"""Filtering selection of JBeam mesh nodes so only visible nodes are selected.

When occlude_selection is enabled and X-Ray is off, nodes hidden behind other objects
or behind faces from the current viewpoint are automatically deselected.
"""

from __future__ import annotations

import traceback
from typing import Mapping

import bmesh
import bpy
from mathutils import Vector

from . import sessions

SELECTION_INTERVAL = 0.08
_filtering = False
_last_selection: dict[str, frozenset[int]] = {}
_scheduled = False


def find_viewport(context=None):
    """Finds the active 3D viewport region_3d and space."""
    if context is not None:
        area = getattr(context, "area", None)
        if area is not None and area.type == "VIEW_3D":
            space = getattr(context, "space_data", None)
            if space is not None and getattr(space, "region_3d", None) is not None:
                return space.region_3d, space, getattr(context, "window", None)
        region_3d = getattr(context, "region_data", None)
        if region_3d is not None:
            space = getattr(context, "space_data", None)
            return region_3d, space, getattr(context, "window", None)

    wm = bpy.context.window_manager
    if wm is not None:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    space = area.spaces.active
                    if space and space.type == "VIEW_3D" and space.region_3d:
                        return space.region_3d, space, window
    return None, None, None


def is_xray_enabled(space=None, context=None) -> bool:
    """Whether X-Ray or wireframe shading is enabled in the viewport."""
    shading = getattr(space, "shading", None) if space is not None else None
    if shading is None and context is not None:
        space_data = getattr(context, "space_data", None)
        shading = getattr(space_data, "shading", None) if space_data is not None else None
    if shading is None:
        return False
    return shading.type == "WIREFRAME" or (shading.type == "SOLID" and shading.show_xray)


def filter_visible_selection(obj, region_3d, depsgraph=None) -> bool:
    """Deselects any selected vertices of `obj` that are occluded from `region_3d`.

    Returns True if any vertices were deselected.
    """
    if obj.mode != "EDIT" or obj.type != "MESH":
        return False

    bm = bmesh.from_edit_mesh(obj.data)
    selected_verts = [v for v in bm.verts if v.select]
    if not selected_verts:
        return False

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene

    is_persp = region_3d.is_perspective
    view_inv = region_3d.view_matrix.inverted()
    toward = view_inv.col[2].xyz.normalized()
    cam_pos = view_inv.translation

    changed = False
    for v in selected_verts:
        w_pos = obj.matrix_world @ v.co
        if is_persp:
            ray = w_pos - cam_pos
            dist = ray.length
            if dist < 1e-6:
                continue
            direction = ray / dist
            origin = cam_pos
        else:
            direction = -toward
            origin = w_pos + toward * (region_3d.view_distance * 4.0 + 100.0)
            dist = (w_pos - origin).length

        margin = max(0.001, dist * 0.0005)
        hit, loc, norm, idx, hit_obj, matrix = scene.ray_cast(depsgraph, origin, direction, distance=dist - margin)
        if hit:
            v.select_set(False)
            changed = True

    if changed:
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return changed


def _operator_running() -> bool:
    wm = bpy.context.window_manager
    return any(len(window.modal_operators) for window in wm.windows) if wm is not None else False


def check_selection_occlusion(context=None) -> bool:
    """Checks selected vertices in all editing JBeam objects and removes occluded ones."""
    global _filtering
    if _filtering:
        return False

    from . import handlers
    if getattr(handlers, "_restoring", False):
        return False

    if _operator_running():
        return False

    from ..ui import view
    display = view.settings(context)
    if display is None or not getattr(display, "occlude_selection", True):
        return False

    region_3d, space, _window = find_viewport(context)
    if region_3d is None or is_xray_enabled(space, context):
        return False

    editing = [(o, s) for o, s in sessions.jbeam_objects() if o.mode == "EDIT"]
    if not editing:
        _last_selection.clear()
        return False

    _filtering = True
    changed_any = False
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for obj, _session in editing:
            bm = bmesh.from_edit_mesh(obj.data)
            current_selected = frozenset(v.index for v in bm.verts if v.select)
            last = _last_selection.get(obj.name)
            if current_selected != last:
                newly = current_selected - (last or frozenset())
                if newly:
                    changed = filter_visible_selection(obj, region_3d, depsgraph)
                    if changed:
                        changed_any = True
                bm = bmesh.from_edit_mesh(obj.data)
                _last_selection[obj.name] = frozenset(v.index for v in bm.verts if v.select)
        if changed_any:
            handlers.redraw()
    except Exception:
        traceback.print_exc()
    finally:
        _filtering = False
    return changed_any


def _step_timer() -> None:
    global _scheduled
    _scheduled = False
    check_selection_occlusion()
    return None


def schedule_check() -> None:
    """Schedules a selection check on the next event loop tick."""
    global _scheduled
    if not _scheduled and not _filtering:
        _scheduled = True
        bpy.app.timers.register(_step_timer, first_interval=0.0)


def watch_selection() -> float:
    """Periodic watcher for selection changes in Edit Mode."""
    try:
        check_selection_occlusion()
    except Exception:
        traceback.print_exc()
    return SELECTION_INTERVAL


def clear_cache() -> None:
    _last_selection.clear()


def register() -> None:
    if not bpy.app.timers.is_registered(watch_selection):
        bpy.app.timers.register(watch_selection, first_interval=SELECTION_INTERVAL, persistent=True)


def unregister() -> None:
    if bpy.app.timers.is_registered(watch_selection):
        bpy.app.timers.unregister(watch_selection)
    if bpy.app.timers.is_registered(_step_timer):
        bpy.app.timers.unregister(_step_timer)
    clear_cache()
