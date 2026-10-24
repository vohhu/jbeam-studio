import math
import bmesh
import bpy
from mathutils import Euler, Matrix, Vector
import pytest

from jbeam_studio.blender import selection, sessions
from jbeam_studio.ui import view


class FakeRegion3D:
    def __init__(self, is_perspective=True, view_matrix=None, view_distance=5.0):
        self.is_perspective = is_perspective
        self.view_matrix = view_matrix or Matrix.Identity(4)
        self.view_distance = view_distance


def setup_scene():
    bpy.ops.wm.read_homefile(use_empty=True)

    # 1. Car body box at (0, 0, 0), size 2x2x2 (from -1 to 1 on X, Y, Z)
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
    cube = bpy.context.active_object
    cube.name = "Body"

    # 2. JBeam mesh object with front (visible) and back (occluded) nodes
    mesh = bpy.data.meshes.new("part_mesh")
    obj = bpy.data.objects.new("part_obj", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()
    bm.verts.new((0.0, -2.0, 0.0))  # v0 in front of cube (Y=-2)
    bm.verts.new((0.0, 2.0, 0.0))   # v1 behind cube (Y=+2)
    bm.to_mesh(mesh)
    bm.free()

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    return cube, obj


def test_perspective_occlusion_filter():
    cube, obj = setup_scene()

    # Select both vertices
    bm = bmesh.from_edit_mesh(obj.data)
    for v in bm.verts:
        v.select_set(True)

    # Camera looking along +Y from (0, -5, 0)
    cam_world = Matrix.Translation(Vector((0, -5, 0))) @ Euler((math.pi / 2, 0, 0)).to_matrix().to_4x4()
    r3d = FakeRegion3D(is_perspective=True, view_matrix=cam_world.inverted(), view_distance=5.0)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    changed = selection.filter_visible_selection(obj, r3d, depsgraph)

    assert changed is True
    bm = bmesh.from_edit_mesh(obj.data)
    selected = [v.index for v in bm.verts if v.select]
    assert selected == [0]  # Only the front vertex stays selected


def test_orthographic_occlusion_filter():
    cube, obj = setup_scene()

    bm = bmesh.from_edit_mesh(obj.data)
    for v in bm.verts:
        v.select_set(True)

    cam_world = Matrix.Translation(Vector((0, -5, 0))) @ Euler((math.pi / 2, 0, 0)).to_matrix().to_4x4()
    r3d = FakeRegion3D(is_perspective=False, view_matrix=cam_world.inverted(), view_distance=5.0)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    changed = selection.filter_visible_selection(obj, r3d, depsgraph)

    assert changed is True
    bm = bmesh.from_edit_mesh(obj.data)
    selected = [v.index for v in bm.verts if v.select]
    assert selected == [0]


def test_filter_no_occlusion_keeps_all():
    cube, obj = setup_scene()

    # Move cube away so nothing is occluded
    cube.location.x = 10.0
    bpy.context.view_layer.update()

    bm = bmesh.from_edit_mesh(obj.data)
    for v in bm.verts:
        v.select_set(True)

    cam_world = Matrix.Translation(Vector((0, -5, 0))) @ Euler((math.pi / 2, 0, 0)).to_matrix().to_4x4()
    r3d = FakeRegion3D(is_perspective=True, view_matrix=cam_world.inverted())

    depsgraph = bpy.context.evaluated_depsgraph_get()
    changed = selection.filter_visible_selection(obj, r3d, depsgraph)

    assert changed is False
    bm = bmesh.from_edit_mesh(obj.data)
    selected = [v.index for v in bm.verts if v.select]
    assert selected == [0, 1]


def test_occlude_selection_setting():
    prefs = view.settings()
    assert hasattr(prefs, "occlude_selection")
    # By default it is True
    assert prefs.occlude_selection is True
