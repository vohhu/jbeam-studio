"""Takes the screenshots of the README with the ETK 800 of the game.

    blender --factory-startup --python scripts/screenshots.py -- <unpacked vehicles folder> <output folder> <set>

The vehicles folder holds `etk800` and `common` (the add-on's preferences can unpack them). <set> is `viewport`
(the default), `popover` or `dialog`: popups stay open until Blender quits, so each is taken in a run of its own.
Blender quits when the images are done.
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


def shot(name: str, full: bool = False) -> None:
    """Saves the 3D viewport, or the whole window, at most WIDTH pixels wide."""
    raw = Path(tempfile.gettempdir()) / f"jbs_shot_{name}.png"
    with bpy.context.temp_override(**override()):
        bpy.ops.screen.screenshot(filepath=str(raw))
    image = bpy.data.images.load(str(raw))
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)
    bpy.data.images.remove(image)
    if not full:
        area = view_area()
        pixels = pixels[area.y:area.y + area.height, area.x:area.x + area.width]
    height, width = pixels.shape[:2]
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


def frame(objects, rotation=(68, 0, 225), zoom: float = 0.0) -> None:
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


def sidebar(show: bool) -> None:
    area = view_area()
    area.spaces.active.show_region_ui = show
    if show:
        region = next(r for r in area.regions if r.type == "UI")
        try:
            region.active_panel_category = "JBeam"
        except (AttributeError, TypeError, ValueError) as error:
            log["notes"].append(f"sidebar tab: {error}")


def edit_door(door, mesh_io) -> None:
    with bpy.context.temp_override(**override(), active_object=door, object=door):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(door.data)
    ghost = bm.verts.layers.bool.get(mesh_io.GHOST)
    own = [v for v in bm.verts if ghost is None or not v[ghost]]
    own.sort(key=lambda v: (round(v.co.z, 1), v.co.y))
    for vertex in own[: max(6, len(own) // 3)]:
        vertex.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(door.data)


def steps():
    bpy.context.preferences.view.use_save_prompt = False
    bpy.ops.wm.read_homefile()
    yield 1.0
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
    with bpy.context.temp_override(**override()):
        bpy.ops.jbs.import_pc("EXEC_DEFAULT", filepath=str(VEHICLES / "etk800" / CONFIG))
    objects = [o for o in bpy.data.objects if sessions.session_of(o) is not None]
    door = next((o for o in objects if o.jbs.part_name.endswith("door_FL")), objects[0])
    session = sessions.session_of(door)
    yield 1.0

    if SET == "viewport":
        display.ghosts = False
        display.normal_beams, display.node_colors, display.through_faces = True, True, True
        frame(objects, zoom=0.3)
        redraw()
        yield 1.0
        shot("overview")

        display.normal_beams, display.node_colors = False, False
        display.beam_color_by = "beamSpring"
        redraw()
        yield 1.0
        shot("beam-spring")

        display.beam_color_by = "BREAK_GROUP"
        redraw()
        yield 1.0
        shot("break-groups")
        view.reset(display)

        frame([door], rotation=(80, 0, 90), zoom=0.15)
        sidebar(True)
        edit_door(door, mesh_io)
        display.node_colors = True
        redraw()
        yield 1.0
        sidebar(True)
        redraw()
        yield 1.0
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
        shot("text-editor", full=True)

    elif SET == "popover":
        frame([door], rotation=(80, 0, 90), zoom=0.15)
        edit_door(door, mesh_io)
        display.node_colors = True
        redraw()
        yield 1.0
        with bpy.context.temp_override(**override()):
            bpy.ops.wm.call_panel(name="JBS_PT_overlay", keep_open=True)
        yield 1.0
        shot("display-settings")

    elif SET == "dialog":
        frame(objects, zoom=0.3)
        files = sorted({str(Path(p.file.path)) for p in session.edit.vehicle.parts.values()
                        if "door" in Path(p.file.path).name})[:3]
        with bpy.context.temp_override(**override()):
            bpy.ops.jbs.import_jbeam_part("INVOKE_DEFAULT", paths="\n".join(files))
        yield 1.0
        shot("choose-parts", full=True)


def run():
    generator = steps()

    def tick():
        try:
            return next(generator)
        except StopIteration:
            pass
        except Exception:
            log["errors"].append(traceback.format_exc())
        (Path(tempfile.gettempdir()) / f"jbs_screenshots_{SET}.json").write_text(json.dumps(log, indent=1),
                                                                                 encoding="utf-8")
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(tick, first_interval=1.0, persistent=True)


run()
