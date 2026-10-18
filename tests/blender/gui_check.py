"""Checks the add-on in a Blender window, where undo, timers and drawing work as they do for users.

    blender --factory-startup --python tests/blender/gui_check.py -- <results.json> [<screenshot.png>]

Uses the installed extension if it is enabled, otherwise the add-on from this repository. Writes the results
to <results.json> and quits.
"""

import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RESULTS = Path(arguments[0]) if arguments else Path(tempfile.gettempdir()) / "jbs_gui_check.json"
SCREENSHOT = Path(arguments[1]) if len(arguments) > 1 else None
results: dict = {"steps": [], "errors": []}


def package():
    for name, module in sys.modules.items():
        if name.endswith("jbeam_studio") and hasattr(module, "register") and name + ".blender.sessions" in sys.modules:
            return name
    sys.path.insert(0, str(ROOT))
    import jbeam_studio
    jbeam_studio.register()
    return "jbeam_studio"


def window_override():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return {"window": window, "area": area, "region": region}


def make_car() -> Path:
    sys.path.insert(0, str(ROOT / ".blender-pytest"))
    spec = ROOT / "tests" / "core" / "conftest.py"
    namespace: dict = {}
    exec(compile(spec.read_text(encoding="utf-8"), str(spec), "exec"), namespace)
    folder = Path(tempfile.mkdtemp()) / "vehicles" / "car"
    folder.mkdir(parents=True)
    for name, text in (("body", namespace["BODY"]), ("doors", namespace["DOORS"]), ("engine", namespace["ENGINE"])):
        (folder / f"{name}.jbeam").write_text(text, encoding="utf-8")
    (folder / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return folder


def show_panel(area, name: str) -> None:
    """Opens the sidebar with the JBeam panels in its first tab; scripts cannot switch sidebar tabs."""
    area.spaces.active.show_region_ui = True
    panels = sys.modules[name + ".ui.panels"]
    for cls in reversed(panels.CLASSES):
        bpy.utils.unregister_class(cls)
    for cls in panels.CLASSES:
        cls.bl_category = "Item"
        if cls.bl_idname == "JBS_PT_diagnostics":
            cls.bl_options = set()
        bpy.utils.register_class(cls)


def steps():
    bpy.context.preferences.view.use_save_prompt = False
    bpy.ops.wm.read_homefile()
    yield 1.0
    name = package()
    sessions = sys.modules[name + ".blender.sessions"]
    override = window_override()
    area = override["area"]
    show_panel(area, name)
    car = make_car()
    with bpy.context.temp_override(**override):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)
        bpy.ops.jbs.import_pc("EXEC_DEFAULT", True, filepath=str(car / "base.pc"))
    obj = bpy.data.objects["car_body"]
    session = sessions.session_of(obj)
    root = bpy.data.collections["JBeam"]
    results["steps"].append(("collections", {c.name: sorted(o.name for o in c.objects) for c in root.children}))
    results["steps"].append(("imported", len(obj.data.vertices)))
    yield 0.5

    with bpy.context.temp_override(**override, active_object=obj, object=obj):
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.verts.layers.int["jbs_node_uid"]
    uid = session.link.map.nodes["b2"]
    vertex = next(v for v in bm.verts if v[layer] == uid)
    vertex.co.x = 0.25
    for other in bm.verts:
        other.select = other is vertex
    bm.select_flush(False)
    bmesh.update_edit_mesh(obj.data)
    setattr(*sessions.auto_save_owner(), True)
    with bpy.context.temp_override(**override):
        bpy.ops.ed.undo_push(message="move b2")
    yield 1.0

    def b2_on_disk():
        return "0.250" in (car / "body.jbeam").read_text(encoding="utf-8")

    def state(label):
        current = sessions.object_of(session)
        results["steps"].append((label, round(session.edit.vehicle.nodes["b2"].pos[0], 3), b2_on_disk(),
                                 current.mode if current else None, [o.name for o in bpy.data.objects]))

    state("applied in edit mode")
    with bpy.context.temp_override(**override):
        bpy.ops.ed.undo()
    yield 1.0
    state("after undo in edit mode")
    with bpy.context.temp_override(**override):
        bpy.ops.ed.redo()
    yield 1.0
    state("after redo in edit mode")
    obj = sessions.object_of(session)
    with bpy.context.temp_override(**override, active_object=obj, object=obj):
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="OBJECT")
    yield 1.0
    state("after leaving edit mode")
    obj = sessions.object_of(session)
    results["steps"].append(("in sync", sessions.in_sync(obj, session)))
    for _ in range(3):
        with bpy.context.temp_override(**override):
            bpy.ops.ed.undo()
        yield 1.0
        state("undo")
    for _ in range(3):
        with bpy.context.temp_override(**override):
            bpy.ops.ed.redo()
        yield 1.0
        state("redo")
    obj = sessions.object_of(session)
    setattr(*sessions.auto_save_owner(), False)

    window = override["window"]
    text_area = max((a for a in window.screen.areas if a.type == "PROPERTIES"), key=lambda a: a.height)
    text_area.type = "TEXT_EDITOR"
    text_space = text_area.spaces.active
    text_space.show_line_numbers = True
    text_space.text = sessions.show_text(session, car / "body.jbeam")
    obj = bpy.data.objects["car_body"]
    for part, _view in sessions.views_of(session):
        part.select_set(True)
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(**override, active_object=obj, object=obj):
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="EDIT")
    results["steps"].append(("parts in edit mode", sorted(o.name for o, _ in sessions.views_of(session) if o.mode == "EDIT")))
    bpy.context.scene.tool_settings.mesh_select_mode = (False, True, False)
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.verts.layers.int["jbs_node_uid"]
    ends = {session.link.map.nodes["b1l"], session.link.map.nodes["b2"]}
    for collection in (bm.verts, bm.edges, bm.faces):
        for element in collection:
            element.select = False
    for edge in bm.edges:
        if {v[layer] for v in edge.verts} == ends:
            edge.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    yield 1.0
    highlight = sys.modules[name + ".ui.text_highlight"]
    results["steps"].append(("beam highlighted", text_space.text.name, dict((k[1][-12:], v) for k, v in highlight._highlights.items())))
    if SCREENSHOT is not None:
        shot = SCREENSHOT.with_name(SCREENSHOT.stem + "_beam.png")
        with bpy.context.temp_override(**override):
            bpy.ops.screen.screenshot(filepath=str(shot))
    bpy.context.scene.tool_settings.mesh_select_mode = (True, False, False)
    door_obj = bpy.data.objects["car_door_L_stock"]
    door_bm = bmesh.from_edit_mesh(door_obj.data)
    door_layer = door_bm.verts.layers.int["jbs_node_uid"]
    door = session.link.map.nodes["d1l"]
    for collection in (door_bm.verts, door_bm.edges, door_bm.faces):
        for element in collection:
            element.select = False
    for vertex in door_bm.verts:
        vertex.select = vertex[door_layer] == door
    door_bm.select_flush_mode()
    bmesh.update_edit_mesh(door_obj.data)
    bpy.context.view_layer.objects.active = door_obj
    yield 1.0
    results["steps"].append(("followed to", text_space.text.name, text_space.top))
    bpy.context.view_layer.objects.active = obj
    body = sessions.show_text(session, car / "body.jbeam")
    text_space.text = body
    yield 0.5
    line = next(i for i, row in enumerate(body.lines) if '["b1l", "b2"]' in row.body)
    column = body.lines[line].body.index('["b1l", "b2"]') + 2
    body.cursor_set(line, character=column)
    yield 0.8
    picked = [(b.id1, b.id2) for b in sessions.selected_entries(obj, session, (False, True, False))]
    results["steps"].append(("clicked in text", picked, tuple(bpy.context.scene.tool_settings.mesh_select_mode),
                             (body.current_line_index, body.current_character) == (line, column)))
    if SCREENSHOT is not None:
        shot = SCREENSHOT.with_name(SCREENSHOT.stem + "_node.png")
        with bpy.context.temp_override(**override):
            bpy.ops.screen.screenshot(filepath=str(shot))

    def ghost_state(label):
        current = sessions.object_of(session)
        text = session.edit.text_of(car / "body.jbeam")
        results["steps"].append((label, "ghost" in text, '["b1r", "ghost", {"optional":true}]' in text,
                                 current.mode if current else None,
                                 [d.message for d in session.edit.vehicle.diagnostics if d.fix]))

    ghost_state("before fix")
    if SCREENSHOT is not None:
        panels = sys.modules[name + ".ui.panels"]
        others = [c for c in panels.CLASSES if c.bl_idname not in ("JBS_PT_main", "JBS_PT_diagnostics")
                  and getattr(c, "bl_parent_id", "") == "JBS_PT_main"]
        for cls in others:
            bpy.utils.unregister_class(cls)
        for region in area.regions:
            region.tag_redraw()
        yield 0.8
        with bpy.context.temp_override(**override):
            bpy.ops.screen.screenshot(filepath=str(SCREENSHOT.with_name(SCREENSHOT.stem + "_fix.png")))
        for cls in others:
            bpy.utils.register_class(cls)
    with bpy.context.temp_override(**override, active_object=obj, object=obj):
        outcome = bpy.ops.jbs.fix("EXEC_DEFAULT", True, group="missing")
    yield 1.0
    results["steps"].append(("fix", sorted(outcome)))
    ghost_state("fixed")
    with bpy.context.temp_override(**override):
        bpy.ops.ed.undo()
    yield 1.0
    ghost_state("fix undone")
    with bpy.context.temp_override(**override):
        bpy.ops.ed.redo()
    yield 1.0
    ghost_state("fix redone")
    obj = sessions.object_of(session)
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.verts.layers.int["jbs_node_uid"]
    for collection in (bm.verts, bm.edges, bm.faces):
        for element in collection:
            element.select = False
    bm.select_history.clear()
    for node_id in ("b2", "b1l"):
        vertex = next(v for v in bm.verts if v[layer] == session.link.map.nodes[node_id])
        vertex.select = True
        bm.select_history.add(vertex)
    bpy.context.scene.tool_settings.mesh_select_mode = (True, False, False)
    bmesh.update_edit_mesh(obj.data)
    with bpy.context.temp_override(**override):
        bpy.ops.ed.undo_push(message="select b2 b1l")
    with bpy.context.temp_override(**override, active_object=obj, object=obj):
        outcome = bpy.ops.jbs.add_extra("EXEC_DEFAULT", True, section="hydros")
    yield 1.0

    def hydros(label):
        results["steps"].append((label, [e.ids for e in session.edit.vehicle.extras if e.section == "hydros"],
                                 sessions.object_of(session).mode))

    results["steps"].append(("add hydro", sorted(outcome)))
    hydros("hydro added")
    if SCREENSHOT is not None:
        panels = sys.modules[name + ".ui.panels"]
        others = [c for c in panels.CLASSES if c.bl_idname != "JBS_PT_main"
                  and getattr(c, "bl_parent_id", "") == "JBS_PT_main"]
        for cls in others:
            bpy.utils.unregister_class(cls)
        operators = sys.modules[name + ".ui.operators"]
        hydro = next(e for e in session.edit.vehicle.extras if e.section == "hydros")
        bpy.context.window_manager.jbs_view.expanded_extra = operators.extra_key(hydro)
        opened = type("JBS_PT_extras_open", (panels.JBS_PT_extras,),
                      {"bl_idname": "JBS_PT_extras_open", "bl_options": set()})
        bpy.utils.register_class(opened)
        for region in area.regions:
            region.tag_redraw()
        yield 0.8
        with bpy.context.temp_override(**override):
            bpy.ops.screen.screenshot(filepath=str(SCREENSHOT.with_name(SCREENSHOT.stem + "_extras.png")))
        bpy.utils.unregister_class(opened)
        for cls in others:
            bpy.utils.register_class(cls)
    with bpy.context.temp_override(**override):
        bpy.ops.ed.undo()
    yield 1.0
    hydros("hydro undone")
    with bpy.context.temp_override(**override):
        bpy.ops.ed.redo()
    yield 1.0
    hydros("hydro redone")
    obj = sessions.object_of(session)
    with bpy.context.temp_override(**override, active_object=obj, object=obj):
        bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="OBJECT")
    yield 0.5

    view_settings = bpy.context.window_manager.jbs_view
    view_settings.labels = "ALL"
    window_region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(**{**override, "region": window_region}):
        bpy.ops.view3d.view_axis(type="TOP")
        bpy.ops.view3d.view_all()
    yield 1.0
    region_3d = area.spaces.active.region_3d
    engine = bpy.data.objects["car_engine_small"]
    point = region_3d.perspective_matrix @ (engine.matrix_world @ Vector(session.edit.vehicle.nodes["e1"].pos)).to_4d()
    x = (point.x / point.w + 1) * 0.5 * window_region.width + window_region.x
    y = (point.y / point.w + 1) * 0.5 * window_region.height + window_region.y
    results["steps"].append(("e1 label", x, y, window.width, window.height))
    for label, value in (("top_hidden", False), ("top_through", True)):
        view_settings.through_faces = value
        for region in area.regions:
            region.tag_redraw()
        yield 1.0
        if SCREENSHOT is not None:
            with bpy.context.temp_override(**override):
                bpy.ops.screen.screenshot(filepath=str(SCREENSHOT.with_name(SCREENSHOT.stem + f"_{label}.png")))
    view_settings.through_faces = False

    vehicles = Path(tempfile.gettempdir()) / "bng-vehicles" / "vehicles" / "pickup"
    configs = sorted(vehicles.glob("*.pc"))
    if configs:
        with bpy.context.temp_override(**override):
            bpy.ops.jbs.import_pc("EXEC_DEFAULT", True, filepath=str(configs[0]))
        pickup = bpy.context.view_layer.objects.active
        for part, _view in sessions.views_of(session):
            part.hide_set(True)
        started = time.perf_counter()
        with bpy.context.temp_override(**override, active_object=pickup, object=pickup):
            bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="EDIT")
            bpy.ops.mesh.select_all(action="DESELECT")
        pickup_views = sessions.views_of(sessions.session_of(pickup))
        results["steps"].append(("pickup parts", len(pickup_views), sum(o.mode == "EDIT" for o, _ in pickup_views),
                                 len(bpy.data.collections["JBeam"].children), round(time.perf_counter() - started, 2)))
        bm = bmesh.from_edit_mesh(pickup.data)
        bm.verts.ensure_lookup_table()
        bm.verts[0].select = True
        bm.select_history.add(bm.verts[0])
        bmesh.update_edit_mesh(pickup.data)
        bpy.context.window_manager.jbs_view.labels = "ALL"
        with bpy.context.temp_override(**override, active_object=pickup, object=pickup):
            bpy.ops.view3d.view_all()
        results["steps"].append(("pickup", len(pickup.data.vertices), len(pickup.data.edges),
                                 sum(v.select for v in bm.verts),
                                 len(sessions.selected_node_ids(pickup, sessions.session_of(pickup))),
                                 bpy.context.window_manager.jbs_view.labels))
    else:
        with bpy.context.temp_override(**override, active_object=obj, object=obj):
            bpy.ops.object.mode_set("EXEC_DEFAULT", True, mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.view3d.view_selected()
    for region in area.regions:
        region.tag_redraw()
    yield 2.0
    if SCREENSHOT is not None:
        with bpy.context.temp_override(**override):
            bpy.ops.screen.screenshot(filepath=str(SCREENSHOT))
        results["steps"].append(("screenshot", str(SCREENSHOT)))
    yield 0.2
    view_settings = bpy.context.window_manager.jbs_view
    shading = area.spaces.active.shading
    for label, change in (("through", lambda: setattr(view_settings, "through_faces", True)),
                          ("xray", lambda: (setattr(view_settings, "through_faces", False),
                                            setattr(shading, "show_xray", True))),
                          ("gradient", lambda: (setattr(shading, "show_xray", False),
                                                setattr(view_settings, "beam_color_by", "beamSpring"),
                                                setattr(view_settings, "group_colors", True),
                                                setattr(view_settings, "node_color_by", "nodeWeight")))):
        change()
        for region in area.regions:
            region.tag_redraw()
        yield 1.0
        if SCREENSHOT is not None:
            with bpy.context.temp_override(**override):
                bpy.ops.screen.screenshot(filepath=str(SCREENSHOT.with_name(SCREENSHOT.stem + f"_{label}.png")))
    view_settings.beam_color_by, view_settings.group_colors = "TYPE", False
    yield 0.2

    big = override["area"]
    big.type = "TEXT_EDITOR"
    big.spaces.active.show_line_numbers = True
    big.spaces.active.text = sessions.show_text(session, car / "body.jbeam")
    doors = sessions.show_text(session, car / "doors.jbeam")
    broken = doors.as_string().replace('"slotType": "car_door_L",', '"slotType": "car_door_L" "oops",', 1)
    doors.clear()
    doors.write(broken)
    doors.cursor_set(3, character=4)
    text_space.text = doors
    big.spaces.active.top = 0
    for area in window.screen.areas:
        area.tag_redraw()
    yield 1.5
    syntax = sys.modules[name + ".ui.text_syntax"]
    results["steps"].append(("problems", {t.name: {k: [p.message for p in v] for k, v in
                                                  (syntax.analysis_of(t, t.as_string()).problems | syntax.session_problems(t)).items()}
                                          for t in (big.spaces.active.text, doors)}))
    if SCREENSHOT is not None:
        with bpy.context.temp_override(window=window, area=big):
            bpy.ops.screen.screenshot(filepath=str(SCREENSHOT.with_name(SCREENSHOT.stem + "_syntax.png")))
    yield 0.2

    big.type = "VIEW_3D"
    with bpy.context.temp_override(window=window, area=big, region=big.regions[-1]):
        outcome = bpy.ops.jbs.import_jbeam_part("INVOKE_DEFAULT", paths="\n".join(
            str(car / name) for name in ("doors.jbeam", "engine.jbeam")))
    results["steps"].append(("chooser", sorted(outcome)))
    yield 1.0
    if SCREENSHOT is not None:
        with bpy.context.temp_override(window=window, area=big):
            bpy.ops.screen.screenshot(filepath=str(SCREENSHOT.with_name(SCREENSHOT.stem + "_dialog.png")))
    yield 0.2


_generator = None


def tick():
    global _generator
    try:
        if _generator is None:
            _generator = steps()
        return next(_generator)
    except StopIteration:
        pass
    except Exception:
        results["errors"].append(traceback.format_exc())
    RESULTS.write_text(json.dumps(results, indent=1), encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2.0, persistent=True)
