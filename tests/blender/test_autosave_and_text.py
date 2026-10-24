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


def leave(obj):
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")


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



def test_auto_save_syncs_3d_move_to_text_editor(car):
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    text = sessions.show_text(session, car / "body.jbeam")
    assert ORIGINAL_ROW in text.as_string()
    move_b2(obj, session)
    sessions.apply_live(obj, session)
    assert MOVED_ROW in text.as_string()
    assert not sessions.text_edited(text)


def test_auto_save_syncs_text_edit_to_3d_mesh(car):
    import time
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    text = sessions.show_text(session, car / "body.jbeam")
    new_content = text.as_string().replace(ORIGINAL_ROW, '["b2", 0.777, 1.0, 0.3]')
    text.clear()
    text.write(new_content)
    assert sessions.text_edited(text)

    # First call records the modification time
    sessions.check_auto_apply_texts()
    assert sessions.text_edited(text)

    # Backdate modification time to simulate passage of delay
    sessions._text_mod_times[text.name] = time.monotonic() - 1.0
    applied = sessions.check_auto_apply_texts()
    assert applied is True
    assert not sessions.text_edited(text)

    # Verify 3D mesh got updated to 0.777
    bm = edit(obj)
    v_b2 = vertex(session, bm, "b2")
    assert abs(v_b2.co.x - 0.777) < 1e-4
    leave(obj)

    # Verify saved on disk
    assert '["b2", 0.777, 1.0, 0.3]' in read_text(car / "body.jbeam")


def test_text_edit_in_edit_mode_recalculates_normals(car):
    import time
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    edit(obj)
    text = sessions.show_text(session, car / "body.jbeam")
    new_content = text.as_string().replace(ORIGINAL_ROW, '["b2", 0.777, 1.0, 0.3]')
    text.clear()
    text.write(new_content)
    sessions.check_auto_apply_texts()
    sessions._text_mod_times[text.name] = time.monotonic() - 1.0
    assert sessions.check_auto_apply_texts() is True
    bm = bmesh.from_edit_mesh(obj.data)
    assert len(bm.faces) > 0
    assert all(f.normal.length > 0.5 for f in bm.faces)
    assert all(v.normal.length > 0.5 for v in bm.verts if v.link_faces)
    leave(obj)


def test_text_editor_multi_selection_selects_nodes_in_3d(car):
    obj, session = import_pc(car)
    edit(obj)
    text = sessions.show_text(session, car / "body.jbeam")
    lines = [l.body for l in text.lines]

    # Select entire file (Ctrl+A simulation)
    matched_all = text_highlight.entries_in_range(session, str(car / "body.jbeam"), 0, 0, len(lines) - 1, len(lines[-1]))
    assert len([e for k, e in matched_all if k == "nodes"]) == 3
    assert text_highlight.select_entries_multi(obj, session, matched_all, bpy.context.tool_settings) is True
    bm = bmesh.from_edit_mesh(obj.data)
    selected_verts = [v for v in bm.verts if v.select]
    assert len(selected_verts) == 3

    # Select sub-range (lines containing b1l and b1r)
    b1l_line = next(i for i, l in enumerate(lines) if '["b1l"' in l)
    b1r_line = next(i for i, l in enumerate(lines) if '["b1r"' in l)
    matched_sub = text_highlight.entries_in_range(session, str(car / "body.jbeam"), b1l_line, 0, b1r_line, len(lines[b1r_line]))
    assert [e.id for k, e in matched_sub] == ["b1l", "b1r"]
    assert text_highlight.select_entries_multi(obj, session, matched_sub, bpy.context.tool_settings) is True
    selected_verts_sub = [v for v in bm.verts if v.select]
    assert len(selected_verts_sub) == 2
    leave(obj)


def test_hotkeys_copy_cut_delete_nodes(car):
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    bm = edit(obj)
    b2_uid = session.link.map.nodes["b2"]
    layer = bm.verts.layers.int.get(mesh_io.NODE_UID)
    for v in bm.verts:
        v.select = (v[layer] == b2_uid)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)

    from jbeam_studio.ui import operators

    # Test copy
    assert bpy.ops.jbs.copy_nodes() == {"FINISHED"}
    assert ORIGINAL_ROW in operators._last_copied

    # Test delete
    assert bpy.ops.jbs.delete_nodes() == {"FINISHED"}
    bm = bmesh.from_edit_mesh(obj.data)
    vert_uids = [v[layer] for v in bm.verts]
    assert b2_uid not in vert_uids
    # Beams referencing b2 must NOT be deleted from JBeam text!
    body_text = session.edit.text_of(car / "body.jbeam")
    assert '["b1l", "b2"]' in body_text

    # Test cut on b1l
    b1l_uid = session.link.map.nodes["b1l"]
    for v in bm.verts:
        v.select = (v[layer] == b1l_uid)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    assert bpy.ops.jbs.cut_nodes() == {"FINISHED"}
    assert '["b1l"' in operators._last_copied
    bm = bmesh.from_edit_mesh(obj.data)
    vert_uids = [v[layer] for v in bm.verts]
    assert b1l_uid not in vert_uids
    leave(obj)


def test_hotkeys_work_from_text_selection(car):
    from jbeam_studio.ui import operators
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True
    text = sessions.show_text(session, car / "body.jbeam")
    lines = [l.body for l in text.lines]
    b2_line = next(i for i, l in enumerate(lines) if '["b2"' in l)

    # Select b2 in text editor
    text.select_set(b2_line, 0, b2_line, len(lines[b2_line]))

    # Test copy from text
    assert bpy.ops.jbs.copy_nodes() == {"FINISHED"}
    assert ORIGINAL_ROW in operators._last_copied

    # Test cut from text
    assert bpy.ops.jbs.cut_nodes() == {"FINISHED"}
    assert ORIGINAL_ROW in operators._last_copied
    assert "b2" not in session.edit.vehicle.nodes
    assert ORIGINAL_ROW not in text.as_string()


def test_text_editor_horizontal_scroll(car):
    obj, session = import_pc(car)
    text = sessions.show_text(session, car / "body.jbeam")
    area = bpy.context.screen.areas[0]
    old_type = area.type
    area.type = "TEXT_EDITOR"
    try:
        st = area.spaces.active
        st.text = text
        st.show_word_wrap = False
        from jbeam_studio.ui.operators import _get_left_index
        import ctypes
        buf = (ctypes.c_int32 * 64).from_address(st.as_pointer())
        idx = _get_left_index(st)
        buf[idx] = 0

        with bpy.context.temp_override(area=area, space_data=st):
            assert bpy.ops.jbs.text_scroll_horizontal(direction="RIGHT", step=60) == {"FINISHED"}
            assert buf[idx] == 60
            assert bpy.ops.jbs.text_scroll_horizontal(direction="LEFT", step=20) == {"FINISHED"}
            assert buf[idx] == 40
    finally:
        area.type = old_type


def test_hotkeys_cut_beams_and_triangles(car):
    from jbeam_studio.ui import operators
    obj, session = import_pc(car)
    bpy.context.window_manager.jbs_auto_save = True

    # 1. Edge mode: cut a beam
    bpy.context.tool_settings.mesh_select_mode = (False, True, False)
    bm = edit(obj)
    edge_layer = bm.edges.layers.int.get(mesh_io.BEAM_UID)
    beam_uids = list(session.link.map.beams.keys())
    assert beam_uids
    target_beam_uid = beam_uids[0]
    for e in bm.edges:
        e.select = (e[edge_layer] == target_beam_uid)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)

    initial_beam_count = len(session.edit.vehicle.beams)
    assert bpy.ops.jbs.cut_nodes() == {"FINISHED"}
    assert operators._last_copied != ""
    assert len(session.edit.vehicle.beams) == initial_beam_count - 1

    # 2. Face mode: cut a triangle
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bm = bmesh.from_edit_mesh(obj.data)
    face_layer = bm.faces.layers.int.get(mesh_io.FACE_UID)
    face_uids = list(session.link.map.faces.keys())
    assert face_uids
    target_face_uid = face_uids[0]
    for f in bm.faces:
        f.select = (f[face_layer] == target_face_uid)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)

    initial_tri_count = len(session.edit.vehicle.triangles)
    assert bpy.ops.jbs.cut_nodes() == {"FINISHED"}
    assert operators._last_copied != ""
    assert len(session.edit.vehicle.triangles) == initial_tri_count - 1
    leave(obj)

    # 3. Text editor: cut a beam from text
    text = sessions.show_text(session, car / "body.jbeam")
    lines = [l.body for l in text.lines]
    beam_line = next(i for i, l in enumerate(lines) if '["b1l", "b2"]' in l)
    text.select_set(beam_line, 0, beam_line, len(lines[beam_line]))
    assert bpy.ops.jbs.cut_nodes() == {"FINISHED"}
    assert '["b1l", "b2"]' in operators._last_copied
    assert '["b1l", "b2"]' not in text.as_string()


def test_place_at_cursor_toggle_and_sync(car):
    obj, session = import_pc(car)
    settings = obj.jbs
    assert settings.placement == "end"
    assert settings.place_at_cursor is False

    settings.place_at_cursor = True
    assert settings.placement == "cursor"
    assert settings.place_at_cursor is True

    settings.placement = "source"
    assert settings.place_at_cursor is False
    assert settings.placement == "source"

    settings.placement = "cursor"
    assert settings.place_at_cursor is True


def test_place_at_cursor_node_insertion(car):
    obj, session = import_pc(car)
    obj.jbs.place_at_cursor = True
    text = sessions.show_text(session, car / "body.jbeam")
    lines = [l.body for l in text.lines]
    # Find b1l in nodes
    b1l_line = next(i for i, l in enumerate(lines) if '["b1l"' in l)
    text.cursor_set(b1l_line, character=len(lines[b1l_line]))

    # In Edit Mode, add a vertex
    bm = edit(obj)
    v = bm.verts.new((0.5, 0.5, 0.5))
    v.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    leave(obj)
    assert sessions.apply_mesh(obj, session) is True

    # Verify node was placed directly after b1l
    updated_lines = [l.body for l in text.lines]
    new_b1l = next(i for i, l in enumerate(updated_lines) if '["b1l"' in l)
    new_node = next(i for i, l in enumerate(updated_lines) if '0.500' in l)
    assert new_node == new_b1l + 1
    assert session.cursor_warning is None


def test_place_at_cursor_beam_insertion(car):
    obj, session = import_pc(car)
    # Add two vertices first
    bm = edit(obj)
    v1 = bm.verts.new((1.0, 1.0, 0.0))
    v2 = bm.verts.new((2.0, 1.0, 0.0))
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    leave(obj)
    sessions.apply_mesh(obj, session)

    obj.jbs.place_at_cursor = True
    text = sessions.show_text(session, car / "body.jbeam")
    lines = [l.body for l in text.lines]
    # Place cursor in beams
    beam_line = next(i for i, l in enumerate(lines) if '["id1:", "id2:"]' in l)
    text.cursor_set(beam_line, character=5)

    # In Edit Mode, connect the two vertices with an edge (beam)
    bm = edit(obj)
    v1_uid = session.link.map.nodes[session.link.map.ids[session.link.map.nodes["n1"]]]
    v2_uid = session.link.map.nodes[session.link.map.ids[session.link.map.nodes["n2"]]]
    layer = bm.verts.layers.int.get(mesh_io.NODE_UID)
    bv1 = next(v for v in bm.verts if v[layer] == v1_uid)
    bv2 = next(v for v in bm.verts if v[layer] == v2_uid)
    e = bm.edges.new((bv1, bv2))
    e.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    leave(obj)
    sessions.apply_mesh(obj, session)

    # Verify beam was placed and no warning
    assert session.cursor_warning is None
    import re
    assert re.search(r'\["n1",\s+"n2"\]', text.as_string()) is not None


def test_place_at_cursor_mismatch_warning(car):
    obj, session = import_pc(car)
    obj.jbs.place_at_cursor = True
    text = sessions.show_text(session, car / "body.jbeam")
    lines = [l.body for l in text.lines]

    # 1. Cursor in beams, but adding a node
    beam_line = next(i for i, l in enumerate(lines) if '["id1:", "id2:"]' in l)
    text.cursor_set(beam_line, character=5)

    bm = edit(obj)
    v = bm.verts.new((0.9, 0.9, 0.9))
    v.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    leave(obj)
    sessions.apply_mesh(obj, session)

    assert session.cursor_warning is not None
    assert "Cursor is in 'beams', but adding nodes" in session.cursor_warning
    # Node should still have been added at the end of nodes (not restricted!)
    assert any("0.900" in l.body for l in text.lines)

    # Test dismissing warning
    assert bpy.ops.jbs.dismiss_cursor_warning() == {"FINISHED"}
    assert session.cursor_warning is None

    # 2. Add two nodes first so we can add a beam between them
    bm = edit(obj)
    v1 = bm.verts.new((1.5, 0.0, 0.0))
    v2 = bm.verts.new((2.5, 0.0, 0.0))
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    leave(obj)
    sessions.apply_mesh(obj, session)

    # Cursor in nodes, but adding a beam
    lines = [l.body for l in text.lines]
    node_line = next(i for i, l in enumerate(lines) if '["b1l"' in l)
    text.cursor_set(node_line, character=5)

    bm = edit(obj)
    layer = bm.verts.layers.int.get(mesh_io.NODE_UID)
    n_nodes = [v for v in bm.verts if v[layer] in (session.link.map.nodes["n2"], session.link.map.nodes["n3"])]
    e = bm.edges.new((n_nodes[0], n_nodes[1]))
    e.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    leave(obj)
    sessions.apply_mesh(obj, session)

    assert session.cursor_warning is not None
    assert "Cursor is in 'nodes', but adding beams" in session.cursor_warning
