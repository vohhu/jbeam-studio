import bmesh
import bpy
import pytest

from jbeam_studio.blender import mesh_io, sessions
from jbeam_studio.ui import operators, text_highlight
from jbeam_studio.ui.operators import EXTRA_ICONS


def import_pc(car):
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    obj = bpy.context.active_object
    return obj, sessions.session_of(obj)


def select_in_order(obj, session, node_ids):
    if obj.mode != "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.verts.layers.int[mesh_io.NODE_UID]
    for collection in (bm.verts, bm.edges, bm.faces):
        for element in collection:
            element.select = False
    bm.select_history.clear()
    by_uid = {v[layer]: v for v in bm.verts}
    for node_id in node_ids:
        vertex = by_uid[session.link.map.nodes[node_id]]
        vertex.select = True
        bm.select_history.add(vertex)
    bmesh.update_edit_mesh(obj.data)


def extras(session, section):
    return [(e.ids, e.name) for e in session.edit.vehicle.extras if e.section == section]


def test_the_icons_of_the_list_exist():
    icons = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items.keys()
    assert set(EXTRA_ICONS.values()) <= set(icons)


def test_hydros_rails_and_slide_nodes_are_added_from_the_selection_in_edit_mode(car):
    obj, session = import_pc(car)
    select_in_order(obj, session, ["b2", "b1l"])
    assert bpy.ops.jbs.add_extra(section="hydros") == {"FINISHED"}
    assert extras(session, "hydros") == [(("b2", "b1l"), None)]
    assert obj.mode == "EDIT" and mesh_io.mesh_rev(obj) == session.link.rev
    select_in_order(obj, session, ["b1l", "b2", "b1r"])
    with pytest.raises(RuntimeError, match="Select 2 nodes"):
        bpy.ops.jbs.add_extra(section="hydros")
    assert bpy.ops.jbs.add_rail(name="track", looped=True) == {"FINISHED"}
    assert extras(session, "rails") == [(("b1l", "b2", "b1r"), "track")]
    select_in_order(obj, session, ["b2"])
    assert bpy.ops.jbs.add_slidenodes(rail="track") == {"FINISHED"}
    assert extras(session, "slidenodes") == [(("b2",), "track")]
    text = session.edit.text_of(car / "body.jbeam")
    assert '"track": {"links:":["b1l", "b2", "b1r"], "broken:":[], "looped":true, "capped":true}' in text
    assert len(session.edit.history) == 3


def test_the_row_of_a_hydro_in_the_text_selects_its_nodes_in_order(car):
    obj, session = import_pc(car)
    session.edit.add_extras("car_body", "hydros", [("b2", "b1r")])
    sessions.after_change(obj, session)
    select_in_order(obj, session, [])
    text = sessions.show_text(session, car / "body.jbeam")
    line = next(i for i, row in enumerate(text.lines) if '["b2", "b1r"]' in row.body)
    column = text.lines[line].body.index('["b2", "b1r"]') + 3
    kind, extra = text_highlight.entry_at(session, text[sessions.TEXT_PATH], line, column)
    assert kind == "extras" and extra.ids == ("b2", "b1r")
    assert text_highlight.select_entry(obj, session, kind, extra, bpy.context.scene.tool_settings)
    assert sessions.selected_node_ids(obj, session) == ["b2", "b1r"]
    assert not text_highlight.select_entry(obj, session, kind, extra, bpy.context.scene.tool_settings)


def test_a_property_of_a_hydro_is_set_from_its_entry(car):
    obj, session = import_pc(car)
    session.edit.add_extras("car_body", "hydros", [("b2", "b1r")])
    sessions.after_change(obj, session)
    select_in_order(obj, session, ["b2"])
    [hydro] = session.edit.vehicle.extras
    key = operators.extra_key(hydro)
    assert bpy.ops.jbs.set_extra_property(extra=key, key="factor", value="0.25") == {"FINISHED"}
    assert '["b2", "b1r", {"factor": 0.25}]' in session.edit.text_of(car / "body.jbeam")
    assert operators.find_extra(session, key).props["factor"] == 0.25
    assert [k for k, _ in operators.extra_properties(operators.find_extra(session, key))] == ["factor"]
    assert mesh_io.mesh_rev(obj) == session.link.rev
    assert operators.value_text(float("inf")) == '"FLT_MAX"'


def test_mirroring_the_nodes_of_a_hydro_mirrors_the_hydro(car):
    obj, session = import_pc(car)
    session.edit.add_extras("car_body", "hydros", [("b1l", "b2")])
    sessions.after_change(obj, session)
    select_in_order(obj, session, ["b1l"])
    assert bpy.ops.jbs.mirror() == {"FINISHED"}
    assert sorted(extras(session, "hydros")) == [(("b1l", "b2"), None), (("b1r", "b2"), None)]


def test_an_entry_of_the_list_selects_its_nodes_and_deletes_itself(car):
    obj, session = import_pc(car)
    session.edit.add_rail("car_body", "track", ["b1l", "b2"])
    session.edit.add_extras("car_body", "slidenodes", [("d1l", "track")])
    sessions.after_change(obj, session)
    select_in_order(obj, session, [])
    index = next(i for i, e in enumerate(session.edit.vehicle.extras) if e.section == "rails")
    assert bpy.ops.jbs.select_extra(index=index) == {"FINISHED"}
    assert sorted(sessions.selected_node_ids(obj, session)) == ["b1l", "b2"]
    assert bpy.ops.jbs.delete_extra(index=index) == {"FINISHED"}
    assert session.edit.vehicle.extras == []
    assert "track" not in session.edit.text_of(car / "body.jbeam")
    assert mesh_io.mesh_rev(obj) == session.link.rev
