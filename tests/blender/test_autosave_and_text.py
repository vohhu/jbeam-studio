import bmesh
import bpy
import pytest

from jbeam_studio.blender import handlers, mesh_io, sessions
from jbeam_studio.core.model.files import read_text
from jbeam_studio.ui import text_highlight

ORIGINAL_ROW = '["b2", 0.0, 1.0, 0.3]'
MOVED_ROW = '["b2", 0.100, 1.0, 0.3]'


def import_pc(car):
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    obj = bpy.context.active_object
    return obj, sessions.session_of(obj)


def edit(obj):
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    return bm


def vertex(session, bm, node_id):
    layer = bm.verts.layers.int[mesh_io.NODE_UID]
    return next(v for v in bm.verts if v[layer] == session.link.map.nodes[node_id])


def move_b2(obj, session):
    bm = edit(obj)
    vertex(session, bm, "b2").co = (0.1, 1.0, 0.3)
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")


def select_only(obj, bm, elements, mode):
    bpy.context.tool_settings.mesh_select_mode = mode
    for collection in (bm.verts, bm.edges, bm.faces):
        for element in collection:
            element.select = False
    for element in elements:
        element.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def test_auto_save_writes_after_apply_and_after_undo(car):
    obj, session = import_pc(car)
    obj.jbs.live_apply = False
    bpy.context.window_manager.jbs_auto_save = True
    first = session.link.rev
    move_b2(obj, session)
    sessions.apply_mesh(obj, session)
    assert MOVED_ROW in read_text(car / "body.jbeam") and session.edit.dirty_files() == []
    mesh_io.set_rev(obj, first)
    handlers.on_undo_post()
    assert ORIGINAL_ROW in read_text(car / "body.jbeam") and session.save_error is None


def test_turning_auto_save_on_saves_pending_edits(car):
    obj, session = import_pc(car)
    move_b2(obj, session)
    sessions.apply_mesh(obj, session)
    assert ORIGINAL_ROW in read_text(car / "body.jbeam")
    bpy.context.window_manager.jbs_auto_save = True
    assert MOVED_ROW in read_text(car / "body.jbeam")


def test_auto_save_does_not_overwrite_files_changed_on_disk(car):
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    path = car / "body.jbeam"
    outside = read_text(path).replace('"Body"', '"Body changed outside"')
    path.write_bytes(outside.encode("utf-8"))
    move_b2(obj, session)
    sessions.apply_mesh(obj, session)
    assert read_text(path) == outside
    assert session.save_error and session.changed_on_disk == [path.absolute()]


def test_save_after_an_automatic_save_says_when_it_was_saved(car):
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    move_b2(obj, session)
    sessions.apply_mesh(obj, session)
    assert session.saved_at is not None and session.saved_files == ["body.jbeam"]
    assert bpy.ops.jbs.save() == {"FINISHED"}
    assert session.edit.dirty_files() == [] and MOVED_ROW in read_text(car / "body.jbeam")


def test_text_edits_that_are_not_applied_are_listed_and_can_be_discarded(car):
    obj, session = import_pc(car)
    text = sessions.show_text(session, car / "body.jbeam")
    text.write("g")
    assert sessions.edited_texts(session) == [text]
    assert bpy.ops.jbs.discard_text(text_name=text.name) == {"FINISHED"}
    assert sessions.edited_texts(session) == [] and text.as_string() == read_text(car / "body.jbeam").replace("\r\n", "\n")


def test_selection_follows_the_select_mode(car):
    obj, session = import_pc(car)
    bm = edit(obj)
    b1l, b2 = vertex(session, bm, "b1l"), vertex(session, bm, "b2")
    edge = next(e for e in bm.edges if set(e.verts) == {b1l, b2})
    select_only(obj, bm, [edge], (False, True, False))
    beams = sessions.selected_entries(obj, session, (False, True, False))
    assert [(b.id1, b.id2) for b in beams] == [("b1l", "b2")]
    nodes = sessions.selected_entries(obj, session, (True, False, False))
    assert sorted(n.id for n in nodes) == ["b1l", "b2"]
    select_only(obj, bm, [next(iter(bm.faces))], (False, False, True))
    faces = sessions.selected_entries(obj, session, (False, False, True))
    assert [f.ids for f in faces] == [("b1l", "b1r", "b2")]


def test_a_text_position_finds_its_row_and_selects_it(car):
    obj, session = import_pc(car)
    text = sessions.show_text(session, car / "body.jbeam")
    lines = [line.body for line in text.lines]
    beam_line = next(i for i, body in enumerate(lines) if '["b1l", "b2"]' in body)
    kind, beam = text_highlight.entry_at(session, text[sessions.TEXT_PATH], beam_line,
                                         lines[beam_line].index('["b1l", "b2"]') + 3)
    assert kind == "beams" and (beam.id1, beam.id2) == ("b1l", "b2")
    node_line = next(i for i, body in enumerate(lines) if '["b2", 0.0' in body)
    assert text_highlight.entry_at(session, text[sessions.TEXT_PATH], node_line, 9)[1].id == "b2"
    assert text_highlight.entry_at(session, text[sessions.TEXT_PATH], 0, 0) is None
    edit(obj)
    assert text_highlight.select_entry(obj, session, kind, beam, bpy.context.tool_settings)
    assert tuple(bpy.context.tool_settings.mesh_select_mode) == (False, True, False)
    assert [(b.id1, b.id2) for b in sessions.selected_entries(obj, session, (False, True, False))] == [("b1l", "b2")]


def test_highlight_bands_cover_the_rows_in_the_shown_text(car):
    obj, session = import_pc(car)
    text = sessions.show_text(session, car / "body.jbeam")
    bm = edit(obj)
    b1l, b2 = vertex(session, bm, "b1l"), vertex(session, bm, "b2")
    edge = next(e for e in bm.edges if set(e.verts) == {b1l, b2})
    select_only(obj, bm, [edge], (False, True, False))
    found, first = text_highlight.bands(session, sessions.selected_entries(obj, session, (False, True, False)))
    key = (session.key, text_highlight.path_key(text[sessions.TEXT_PATH]))
    [(line, start, end_line, end)] = found[key]
    assert first[2] == (line, start, end_line, end)
    assert line == end_line
    assert text.lines[line].body[start:end] == '["b1l", "b2"]'
