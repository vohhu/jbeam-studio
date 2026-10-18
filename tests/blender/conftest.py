import importlib.util
from pathlib import Path

import bpy
import pytest

import jbeam_studio
from jbeam_studio.blender import sessions

_core = importlib.util.spec_from_file_location("core_conftest", Path(__file__).parents[1] / "core" / "conftest.py")
core_conftest = importlib.util.module_from_spec(_core)
_core.loader.exec_module(core_conftest)


@pytest.fixture(scope="session", autouse=True)
def addon():
    jbeam_studio.register()
    yield
    jbeam_studio.unregister()


@pytest.fixture(autouse=True)
def clean_scene():
    yield
    bpy.context.window_manager.jbs_auto_save = False
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    sessions.SESSIONS.clear()


@pytest.fixture
def car(tmp_path):
    folder = tmp_path / "vehicles" / "car"
    folder.mkdir(parents=True)
    (folder / "body.jbeam").write_text(core_conftest.BODY, encoding="utf-8")
    (folder / "doors.jbeam").write_text(core_conftest.DOORS, encoding="utf-8")
    (folder / "engine.jbeam").write_text(core_conftest.ENGINE, encoding="utf-8")
    (folder / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return folder
