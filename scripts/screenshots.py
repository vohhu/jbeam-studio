"""Takes the screenshots of the README with the ETK 800 of the game.

    blender --factory-startup --enable-event-simulate --python scripts/screenshots.py --
        <unpacked vehicles> <output folder> <set> [ru]

The vehicles folder holds `etk800` and `common` (the add-on's preferences can unpack them). Each set is taken in a
Blender of its own, as popups stay open and panels keep whether they are open: `viewport`, `editing`, `parts`,
`popover`, `popover-more`, `panels-editing`, `panels-lists`, `dialog`. With `ru` the interface is in Russian and the names
end in `-ru`. Blender quits when the images are done.
"""

import json
import math
import sys
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler

ROOT = Path(__file__).resolve().parents[1]
arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
VEHICLES = Path(arguments[0]) if arguments else Path(tempfile.gettempdir()) / "bng-vehicles" / "vehicles"
OUT = Path(arguments[1]).resolve() if len(arguments) > 1 else ROOT / "docs" / "images"
SET = arguments[2] if len(arguments) > 2 else "viewport"
RUSSIAN = len(arguments) > 3 and arguments[3] == "ru"
CONFIG = "856_ttsport_DCT.pc"
WIDTH = 1600
log: dict = {"shots": [], "errors": [], "notes": []}


def window():
    return bpy.context.window_manager.windows[0]


def view_area():
    return max((a for a in window().screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)


def override(area=None):
    area = area or view_area()
    region = next(r for r in area.regions if r.type == "WINDOW")
    return {"window": window(), "area": area, "region": region}


def redraw():
    for area in window().screen.areas:
        area.tag_redraw()


def shot(name: str, part: str = "view") -> None:
    """Saves the 3D viewport (`view`), its sidebar (`sidebar`) or the whole window (`window`), at most WIDTH
    pixels wide."""
    raw = Path(tempfile.gettempdir()) / f"jbs_shot_{name}.png"
    with bpy.context.temp_override(**override()):
        bpy.ops.screen.screenshot(filepath=str(raw))
    image = bpy.data.images.load(str(raw))
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)
    bpy.data.images.remove(image)
    if part != "window":
        area = view_area()
        box = area if part == "view" else next(r for r in area.regions if r.type == "UI")
        pixels = pixels[box.y:box.y + box.height, box.x:box.x + box.width]
    height, width = pixels.shape[:2]
    name += "-ru" if RUSSIAN else ""
    result = bpy.data.images.new(name, width, height, alpha=False)
    pixels[..., 3] = 1.0
    result.pixels.foreach_set(np.ascontiguousarray(pixels).ravel())
    if width > WIDTH:
        result.scale(WIDTH, round(height * WIDTH / width))
    OUT.mkdir(parents=True, exist_ok=True)
    result.filepath_raw = str(OUT / f"{name}.png")
    result.file_format = "PNG"
    result.save()
    bpy.data.images.remove(result)
    log["shots"].append(name)


def frame(objects, rotation=(68, 0, 40), zoom: float = 0.0, active=None, keep_selected: bool = False) -> None:
    """Looks at the objects from a direction; afterwards they are not selected, as Blender outlines the edges of
    selected objects, and `active` (the first object by default) is the active object."""
    space = view_area().spaces.active
    region_3d = space.region_3d
    region_3d.view_perspective = "PERSP"
    region_3d.view_rotation = Euler([math.radians(a) for a in rotation]).to_quaternion()
    space.lens = 50
    for obj in bpy.data.objects:
        obj.select_set(obj in objects)
    bpy.context.view_layer.objects.active = objects[0]
    with bpy.context.temp_override(**override()):
        bpy.ops.view3d.view_selected()
    region_3d.view_distance *= 1.0 - zoom
    if not keep_selected:
        for obj in objects:
            obj.select_set(False)
    bpy.context.view_layer.objects.active = active or objects[0]


def panels_open(names: set[str]) -> None:
    """Shows only these panels of the sidebar, besides the main one, and opens them; before the sidebar is
    first drawn, as Blender keeps whether a panel is open once it is drawn."""
    panels = sys.modules["jbeam_studio.ui.panels"]
    sidebar = [c for c in panels.CLASSES if c.bl_region_type == "UI" and c.bl_idname != "JBS_PT_main"]
    for cls in reversed(sidebar):
        bpy.utils.unregister_class(cls)
    for cls in sidebar:
        if cls.bl_idname in names:
            cls.bl_options = set()
            bpy.utils.register_class(cls)


def popover_open(names: set[str]) -> None:
    """Opens these sections of the JBeam popover and closes the others."""
    panels = sys.modules["jbeam_studio.ui.panels"]
    sections = [c for c in panels.CLASSES if c.bl_region_type == "HEADER" and c.bl_idname != "JBS_PT_overlay"]
    for cls in reversed(sections):
        bpy.utils.unregister_class(cls)
    for cls in sections:
        cls.bl_options = set() if cls.bl_idname in names else {"DEFAULT_CLOSED"}
        bpy.utils.register_class(cls)


def sidebar(show: bool) -> None:
    view_area().spaces.active.show_region_ui = show


def mouse_at(x: float, y: float):
    """Moves the mouse to a place in the 3D viewport, given as parts of its width and height, where popups open."""
    area = view_area()
    if bpy.app.use_event_simulate:
        window().event_simulate(type="MOUSEMOVE", value="NOTHING", x=area.x + int(area.width * x),
                                y=area.y + int(area.height * y))
        yield 0.3


def jbeam_tab():
    """Clicks the JBeam tab of the sidebar, the last one, as scripts cannot choose the tab: finds the tabs in a
    screenshot with nothing else drawn. Needs Blender started with --enable-event-simulate."""
    area = view_area()
    region = next(r for r in area.regions if r.type == "UI")
    if region.active_panel_category == "JBeam":
        return
    if not bpy.app.use_event_simulate:
        log["notes"].append("start Blender with --enable-event-simulate to show the JBeam tab")
        return
    space = area.spaces.active
    shown = [o for o in bpy.context.view_layer.objects if o.visible_get()]
    for obj in shown:
        obj.hide_set(True)
    space.overlay.show_overlays = False
    redraw()
    yield 0.5
    raw = Path(tempfile.gettempdir()) / "jbs_shot_tabs.png"
    with bpy.context.temp_override(**override()):
        bpy.ops.screen.screenshot(filepath=str(raw))
    image = bpy.data.images.load(str(raw))
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    for obj in shown:
        obj.hide_set(False)
    space.overlay.show_overlays = True
    scale = bpy.context.preferences.system.ui_scale
    x = region.x + region.width - int(9 * scale)
    column = pixels.reshape(height, width, 4)[region.y:region.y + region.height, x, :3].mean(axis=1)
    marked = np.abs(column - np.median(column)) > 0.03
    runs, start = [], None
    for index, value in enumerate(marked.tolist() + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start > 8 * scale:
                runs.append((start, index))
            start = None
    if not runs:
        log["notes"].append("sidebar tab: no tabs found")
        return
    low, high = runs[0]
    y = region.y + (low + high) // 2
    window().event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    window().event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
    window().event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
    redraw()
    yield 0.5
    if region.active_panel_category != "JBeam":
        log["notes"].append(f"sidebar tab: {region.active_panel_category}, tabs at {runs}")


def select_nodes(obj, mesh_io, share: float = 3) -> None:
    """Edit Mode with the lower part of the object's own nodes selected."""
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(**override(), active_object=obj, object=obj):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    ghost = bm.verts.layers.bool.get(mesh_io.GHOST)
    own = [v for v in bm.verts if ghost is None or not v[ghost]]
    own.sort(key=lambda v: (round(v.co.z, 1), v.co.y))
    for vertex in own[: max(6, int(len(own) // share))]:
        vertex.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def steps():
    bpy.context.preferences.view.use_save_prompt = False
    bpy.ops.wm.read_homefile()
    yield 1.0
    if RUSSIAN:
        bpy.context.preferences.view.language = "ru_RU"
        bpy.context.preferences.view.use_translate_interface = True
        bpy.context.preferences.view.use_translate_tooltips = True
        redraw()
        yield 2.0
    sys.path.insert(0, str(ROOT))
    import jbeam_studio
    jbeam_studio.register()
    from jbeam_studio.blender import mesh_io, sessions
    from jbeam_studio.ui import view
    display = view.settings()
    view.reset(display)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    space = view_area().spaces.active
    space.show_gizmo_navigate = False
    space.overlay.show_cursor = False
    space.show_region_toolbar = False
    sidebar(False)

    if SET == "parts":
        doors = VEHICLES / "etk800"
        front = next(doors.rglob("etk800_doors_F.jbeam"))
        rear = next(doors.rglob("etk800_doors_R.jbeam"))
        with bpy.context.temp_override(**override()):
            bpy.ops.jbs.import_jbeam("EXEC_DEFAULT", filepath=str(front), part_name="etk800_door_FL")
            bpy.ops.jbs.import_jbeam("EXEC_DEFAULT", filepath=str(rear), part_name="etk800_door_RL")
        fl = next(o for o in bpy.data.objects if o.jbs.part_name == "etk800_door_FL")
        rl = next(o for o in bpy.data.objects if o.jbs.part_name == "etk800_door_RL")
        display.node_colors = True
        frame([fl], rotation=(80, 0, 90), zoom=-0.2)
        with bpy.context.temp_override(**override(), active_object=fl, object=fl):
            bpy.ops.object.mode_set(mode="EDIT")
        sidebar(True)
        redraw()
        yield 0.5
        yield from jbeam_tab()
        redraw()
        yield 1.0
        with bpy.context.temp_override(**override(), active_object=fl, object=fl):
            bpy.ops.object.mode_set(mode="OBJECT")
        redraw()
        yield 1.5
        shot("part-ghosts")
        fl_nodes = sorted(sessions.session_of(fl).edit.vehicle.nodes)
        rl_session = sessions.session_of(rl)
        rl_node = sorted(rl_session.edit.vehicle.nodes)[0]
        bpy.context.view_layer.objects.active = rl
        with bpy.context.temp_override(**override(), active_object=rl, object=rl):
            bpy.ops.jbs.rename_node("EXEC_DEFAULT", old_id=rl_node, new_id=fl_nodes[0])
        log["notes"].append(f"renamed {rl_node} of the rear door to {fl_nodes[0]}")
        frame([fl, rl], rotation=(80, 0, 90), zoom=0.05)
        bpy.context.view_layer.objects.active = fl
        display.labels = "ALL"
        redraw()
        yield 1.5
        shot("conflict")
        return

    with bpy.context.temp_override(**override()):
        bpy.ops.jbs.import_pc("EXEC_DEFAULT", filepath=str(VEHICLES / "etk800" / CONFIG))
    objects = [o for o in bpy.data.objects if sessions.session_of(o) is not None]
    door = next((o for o in objects if o.jbs.part_name.endswith("door_FL")), objects[0])
    session = sessions.session_of(door)
    yield 1.0

    if SET == "viewport":
        def take(name, **settings):
            view.reset(display)
            display.ghosts = False
            for key, value in settings.items():
                setattr(display, key, value)
            redraw()
            yield 1.0
            shot(name)

        body = next((o for o in objects if "_body" in o.jbs.part_name), objects[0])
        hood = next((o for o in objects if "hood" in o.jbs.part_name), door)
        frame(objects, zoom=0.3, active=body)
        yield from take("overview", normal_beams=True, node_colors=True, through_faces=True)
        yield from take("beam-types")
        yield from take("beam-types-through", through_faces=True)
        yield from take("beam-spring", beam_color_by="beamSpring")
        yield from take("beam-deform-rainbow", beam_color_by="beamDeform", palette="RAINBOW")
        yield from take("beam-strength-viridis", beam_color_by="beamStrength", palette="VIRIDIS", through_faces=True)
        yield from take("break-groups", beam_color_by="BREAK_GROUP", through_faces=True)
        yield from take("deform-groups", beam_color_by="DEFORM_GROUP", through_faces=True)
        yield from take("beams-by-part", beam_color_by="PART", through_faces=True)
        yield from take("nodes-flags", beam_colors=False, node_colors=True, through_faces=True, node_size=9.0)
        yield from take("nodes-groups", beam_colors=False, node_colors=True, node_color_by="GROUP",
                        through_faces=True, node_size=9.0)
        yield from take("nodes-weight", beam_colors=False, node_colors=True, node_color_by="nodeWeight",
                        through_faces=True, node_size=9.0)
        bpy.context.view_layer.objects.active = hood
        yield from take("dimmed", scope="ACTIVE", normal_beams=True, node_colors=True)
        yield from take("active-only", scope="ACTIVE", dim_others=False, normal_beams=True, node_colors=True,
                        through_faces=True)
        bpy.context.view_layer.objects.active = body

        bumper = [o for o in objects if "bumper_F" in o.jbs.part_name] or objects
        frame(bumper, rotation=(78, 0, 20), zoom=0.45)
        yield from take("names", labels="ALL", label_size=14, node_colors=True, through_faces=True,
                        scope="ACTIVE", normal_beams=True)
        bpy.context.view_layer.objects.active = body

        holders = [o for o in objects if any(e.section in ("torsionbars", "hydros", "rails")
                                             and e.part == o.jbs.part_name
                                             for e in sessions.session_of(o).edit.vehicle.extras)] or objects
        frame(holders, rotation=(60, 0, 35), zoom=0.2)
        yield from take("hydros-rails", beam_colors=False, through_faces=True, line_opacity=1.0, extra_width=4.0)

    elif SET == "editing":
        view.reset(display)
        redraw()
        yield 1.0
        frame([door], rotation=(80, 0, 90), zoom=0.15)
        sidebar(True)
        redraw()
        yield 0.5
        yield from jbeam_tab()
        select_nodes(door, mesh_io)
        display.node_colors = True
        redraw()
        yield 1.5
        shot("edit-mode")

        text_area = max((a for a in window().screen.areas if a.type == "PROPERTIES"), key=lambda a: a.height)
        text_area.type = "TEXT_EDITOR"
        text_space = text_area.spaces.active
        text_space.show_line_numbers = True
        path = Path(session.edit.vehicle.parts[door.jbs.part_name].file.path)
        text_space.text = sessions.show_text(session, path)
        bpy.context.scene.tool_settings.mesh_select_mode = (False, True, False)
        bm = bmesh.from_edit_mesh(door.data)
        ghost = bm.verts.layers.bool.get(mesh_io.GHOST)
        for element in (*bm.verts, *bm.edges):
            element.select = False
        edges = [e for e in bm.edges if all(ghost is None or not v[ghost] for v in e.verts)]
        for edge in edges[len(edges) // 2: len(edges) // 2 + 6]:
            edge.select = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(door.data)
        redraw()
        yield 2.0
        shot("text-editor", "window")

    elif SET in ("popover", "popover-more"):
        if SET == "popover-more":
            popover_open({f"JBS_PT_overlay_{n}" for n in ("extras", "highlights", "names", "center")})
        frame([door], rotation=(80, 0, 90), zoom=0.1)
        select_nodes(door, mesh_io)
        display.node_colors = True
        redraw()
        yield 1.0
        yield from mouse_at(0.2, 0.92)
        with bpy.context.temp_override(**override()):
            bpy.ops.wm.call_panel(name="JBS_PT_overlay", keep_open=True)
        yield 1.0
        shot("display-settings" if SET == "popover" else "display-settings-more")

    elif SET == "panels-editing":
        panels_open({"JBS_PT_settings", "JBS_PT_tools", "JBS_PT_text"})
        frame([door], rotation=(80, 0, 90), zoom=0.15)
        select_nodes(door, mesh_io, share=8)
        sidebar(True)
        redraw()
        yield 0.5
        yield from jbeam_tab()
        redraw()
        yield 1.5
        shot("panels-editing", "sidebar")

    elif SET == "panels-lists":
        panels_open({"JBS_PT_groups", "JBS_PT_extras", "JBS_PT_diagnostics"})
        holder = next((o for o in objects if any(e.section in ("hydros", "torsionbars")
                                                 and e.part == o.jbs.part_name
                                                 for e in sessions.session_of(o).edit.vehicle.extras)), door)
        frame([holder], zoom=0.1)
        sidebar(True)
        redraw()
        yield 0.5
        yield from jbeam_tab()
        redraw()
        yield 1.5
        shot("panels-lists", "sidebar")

    elif SET == "dialog":
        frame(objects, zoom=0.3)
        files = sorted({str(Path(p.file.path)) for p in session.edit.vehicle.parts.values()
                        if "door" in Path(p.file.path).name})[:3]
        yield from mouse_at(0.5, 0.75)
        with bpy.context.temp_override(**override()):
            bpy.ops.jbs.import_jbeam_part("INVOKE_DEFAULT", paths="\n".join(files))
        yield 1.0
        shot("choose-parts", "window")


def run():
    generator = steps()

    def tick():
        try:
            return next(generator)
        except StopIteration:
            pass
        except Exception:
            log["errors"].append(traceback.format_exc())
        name = f"jbs_screenshots_{SET}{'_ru' if RUSSIAN else ''}.json"
        (Path(tempfile.gettempdir()) / name).write_text(json.dumps(log, indent=1), encoding="utf-8")
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(tick, first_interval=1.0, persistent=True)


run()
