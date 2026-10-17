"""Highlighting the rows of the selection in Blender's text editor.

Vertices select node rows, edges beam rows and faces triangle and quad rows, following the mesh select mode.
A timer notices selection changes; the text editor then draws a band over each row and, if following is on,
scrolls to the row of the active element and switches to its file.
"""

from __future__ import annotations

import bisect
import os
import re
import traceback
from pathlib import Path

import bmesh
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from ..blender import mesh_io, sessions
from ..core.sjson import Kind

INTERVAL = 0.15
COLOR = (1.0, 0.55, 0.1, 0.28)
_highlights: dict[tuple[str, str], list[tuple[int, int, int, int]]] = {}
"""Bands by (session key, file): 0-based start line and column, end line and column."""
_first: tuple | None = None
"""Session key and file key of the active element's row, its band and the file's path."""
_handle = None


def path_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def bands(session, entries) -> tuple[dict, tuple | None]:
    found: dict[tuple[str, str], list] = {}
    first = None
    for entry in entries:
        src = entry.src
        if src is None or src.node.kind is not Kind.ARRAY:
            continue
        key = (session.key, path_key(src.file))
        start_line, start_column = src.doc.line_col(src.node.start)
        end_line, end_column = src.doc.line_col(src.node.end)
        band = (start_line - 1, start_column - 1, end_line - 1, end_column - 1)
        found.setdefault(key, [])
        if band not in found[key]:
            found[key].append(band)
        if first is None:
            first = (*key, band, str(src.file))
    return found, first


def _text_spaces(wm):
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "TEXT_EDITOR":
                space = area.spaces.active
                if space.text is not None and space.text.get(sessions.TEXT_SESSION):
                    yield window, area, space


def _set(highlights: dict, first, wm) -> None:
    global _highlights, _first
    if highlights == _highlights and first == _first:
        return
    _highlights, _first = highlights, first
    for _window, area, _space in _text_spaces(wm):
        area.tag_redraw()


_placed: dict[str, tuple] = {}
"""The cursor each text got from following the selection, so that cursor is not taken as a click."""
_cursors: dict[str, tuple] = {}
_rows: dict[tuple, list] = {}


def rows_of(session, path: str) -> tuple[list[int], list[tuple[int, int, str, object]]]:
    """Rows of nodes, beams, faces, hydros, torsion bars, slide nodes and rails in a file, as (start, end, kind,
    entry) sorted by start, with the starts."""
    key = (session.key, session.link.rev, path)
    if key not in _rows:
        _rows.clear()
        vehicle = session.edit.vehicle
        found = []
        for kind, entries in (("nodes", vehicle.nodes.values()), ("beams", vehicle.beams),
                              ("faces", vehicle.triangles + vehicle.quads), ("extras", vehicle.extras)):
            for entry in entries:
                src = entry.src
                if src is not None and src.node.kind in (Kind.ARRAY, Kind.OBJECT) and path_key(src.file) == path:
                    found.append((src.node.start, src.node.end, kind, entry))
        found.sort(key=lambda row: row[0])
        _rows[key] = ([row[0] for row in found], found)
    return _rows[key]


def entry_at(session, path: str, line: int, column: int):
    """The node, beam or face whose row holds a text position, with its kind; rows do not nest."""
    text = session.edit.text_of(Path(path))
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    if line >= len(starts):
        return None
    offset = starts[line] + column
    row_starts, rows = rows_of(session, path_key(path))
    index = bisect.bisect_right(row_starts, offset) - 1
    if index >= 0 and rows[index][0] <= offset < rows[index][1]:
        return rows[index][2], rows[index][3]
    return None


def _select_from_text(window, obj, session, wm) -> bool:
    """Selects in the viewport the node, beam or face whose row the user clicked in the text; True if it did."""
    for _window, _area, space in _text_spaces(wm):
        text = space.text
        if text.get(sessions.TEXT_SESSION) != session.key or sessions.text_edited(text):
            continue
        cursor = (text.select_end_line_index, text.select_end_character, text.current_line_index,
                  text.current_character)
        previous, _cursors[text.name] = _cursors.get(text.name), cursor
        if previous is None or previous == cursor or _placed.get(text.name) == cursor[:2] or cursor[:2] != cursor[2:]:
            continue
        found = entry_at(session, text[sessions.TEXT_PATH], cursor[0], cursor[1])
        if found is not None and select_entry(obj, session, *found, window.scene.tool_settings):
            return True
    return False


def select_entry(obj, session, kind: str, entry, tool_settings) -> bool:
    bm = bmesh.from_edit_mesh(obj.data)
    link = session.link
    if kind == "extras":
        layer = bm.verts.layers.int.get(mesh_io.NODE_UID)
        by_uid = {v[layer]: v for v in bm.verts} if layer is not None else {}
        targets = [by_uid[u] for u in dict.fromkeys(link.map.nodes.get(i) for i in entry.ids) if u in by_uid]
        if not targets or list(bm.select_history) == targets:
            return False
        tool_settings.mesh_select_mode = (True, False, False)
        for element in (*bm.verts, *bm.edges, *bm.faces):
            element.select = False
        bm.select_history.clear()
        for vertex in targets:
            vertex.select_set(True)
            bm.select_history.add(vertex)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return True
    if kind == "nodes":
        layer, uid, elements = bm.verts.layers.int.get(mesh_io.NODE_UID), link.map.nodes.get(entry.id), bm.verts
        mode = (True, False, False)
    else:
        groups = link.map.beams if kind == "beams" else link.map.faces
        listing = session.edit.vehicle.beams if kind == "beams" else session.edit.vehicle.triangles + \
            session.edit.vehicle.quads
        uid = next((u for u, g in groups.items() if any(listing[i] is entry for i in g.indices)), None)
        if kind == "beams":
            layer, elements, mode = bm.edges.layers.int.get(mesh_io.BEAM_UID), bm.edges, (False, True, False)
        else:
            layer, elements, mode = bm.faces.layers.int.get(mesh_io.FACE_UID), bm.faces, (False, False, True)
    target = next((e for e in elements if layer is not None and uid is not None and e[layer] == uid), None)
    if target is None or (target.select and bm.select_history.active == target):
        return False
    tool_settings.mesh_select_mode = mode
    for element in (*bm.verts, *bm.edges, *bm.faces):
        element.select = False
    target.select_set(True)
    bm.select_history.clear()
    bm.select_history.add(target)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return True


def _reveal(window, area, space, band) -> None:
    """Puts the text cursor at the start of the row; moving the cursor with an operator also scrolls sideways.

    The row is not selected as text, so typing after a click cannot replace it.
    """
    line, column, _end_line, _end_column = band
    text = space.text
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    text.cursor_set(line, character=column)
    if region is not None:
        try:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.text.move(type="NEXT_CHARACTER")
                bpy.ops.text.move(type="PREVIOUS_CHARACTER")
        except RuntimeError:
            pass
    text.cursor_set(line, character=column)
    _placed[text.name] = (line, column)
    _cursors[text.name] = (text.select_end_line_index, text.select_end_character, text.current_line_index,
                           text.current_character)
    if not space.top <= line < space.top + max(1, space.visible_lines - 1):
        space.top = max(0, line - max(1, space.visible_lines // 3))


def _follow(session, wm) -> None:
    if _first is None:
        return
    key, path, band, original = _first
    for window, area, space in _text_spaces(wm):
        text = space.text
        if text.get(sessions.TEXT_SESSION) != key:
            continue
        if path_key(text[sessions.TEXT_PATH]) != path:
            target = next((t for t in bpy.data.texts if t.get(sessions.TEXT_SESSION) == key
                           and path_key(t[sessions.TEXT_PATH]) == path), None)
            space.text = target or sessions.show_text(session, original)
        if not sessions.text_edited(space.text):
            _reveal(window, area, space, band)
        area.tag_redraw()


def update() -> float:
    try:
        _update()
    except Exception:
        traceback.print_exc()
    return INTERVAL


def _update() -> None:
    wm = bpy.context.window_manager
    if wm is None or not wm.windows:
        return
    view = wm.jbs_view
    if not view.text_highlight or not any(True for _ in _text_spaces(wm)):
        _set({}, None, wm)
        return
    window = wm.windows[0]
    obj = window.view_layer.objects.active
    session = sessions.session_of(obj)
    if session is None or obj.mode != "EDIT" or session.stale:
        _set({}, None, wm)
        return
    clicked = view.text_select and _select_from_text(window, obj, session, wm)
    select_mode = tuple(window.scene.tool_settings.mesh_select_mode)
    highlights, first = bands(session, sessions.selected_entries(obj, session, select_mode))
    moved = first != _first
    _set(highlights, first, wm)
    if moved and view.text_follow and not clicked:
        _follow(session, wm)


def draw() -> None:
    context = bpy.context
    space = context.space_data
    text = space.text if space is not None else None
    if text is None or not text.get(sessions.TEXT_SESSION) or not _highlights:
        return
    rows = _highlights.get((text[sessions.TEXT_SESSION], path_key(text[sessions.TEXT_PATH])))
    if not rows or sessions.text_edited(text):
        return
    region = context.region
    lines = text.lines
    top, visible = space.top, space.visible_lines + 1
    origin = space.region_location_from_cursor(top, 0)
    if len(lines) > top + 1:
        height = origin[1] - space.region_location_from_cursor(top + 1, 0)[1]
    else:
        height = round(space.font_size * 1.5 * context.preferences.system.ui_scale)
    if height <= 0:
        return
    left = origin[0]
    rectangles = []

    def band(x0, x1, y) -> None:
        if y + height >= 0 and y <= region.height and x1 > x0:
            rectangles.append((x0, y, x1, y + height))

    for start_line, start_column, end_line, end_column in rows:
        if end_line < top or start_line > top + visible or start_line >= len(lines):
            continue
        for line in range(max(start_line, top), min(end_line, top + visible, len(lines) - 1) + 1):
            first = start_column if line == start_line else 0
            last = end_column if line == end_line else len(lines[line].body)
            x0, y0 = space.region_location_from_cursor(line, first)
            x1, y1 = space.region_location_from_cursor(line, last)
            if y0 == y1:
                band(x0, x1, y0)
            else:
                band(x0, region.width, y0)
                y = y0 - height
                while y > y1:
                    band(left, region.width, y)
                    y -= height
                band(left, x1, y1)
    if not rectangles:
        return
    vertices, indices = [], []
    for x0, y0, x1, y1 in rectangles:
        base = len(vertices)
        vertices += [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        indices += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": vertices}, indices=indices)
    gpu.state.blend_set("ALPHA")
    shader.uniform_float("color", COLOR)
    batch.draw(shader)
    gpu.state.blend_set("NONE")


def register() -> None:
    global _handle
    _handle = bpy.types.SpaceTextEditor.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")
    if not bpy.app.timers.is_registered(update):
        bpy.app.timers.register(update, first_interval=INTERVAL, persistent=True)


def unregister() -> None:
    global _handle
    if bpy.app.timers.is_registered(update):
        bpy.app.timers.unregister(update)
    if _handle is not None:
        bpy.types.SpaceTextEditor.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    _highlights.clear()
