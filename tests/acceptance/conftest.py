"""Runs the edit scenarios of the original Blender JBeam Editor against JBeam Studio's edit sessions.

The scenario files are the original tests, unchanged; they import Blender modules and the original helper, so
permissive stand-ins for Blender and an adapter named like the original helper are installed here.
"""

import sys
import types
from pathlib import Path

import pytest

REF_NODES_DEVIATION = (
    "the original editor also deleted refNodes rows that use a deleted node; JBeam Studio keeps the row and "
    "reports the broken reference"
)
DEVIATIONS = {
    "delete_nodes/test_delete_nodes.py::test_4": REF_NODES_DEVIATION,
    "delete_nodes/test_delete_nodes.py::test_7": REF_NODES_DEVIATION,
    "delete_nodes/test_delete_nodes.py::test_8": REF_NODES_DEVIATION,
    "multiple_actions/test_multiple_actions.py::test_delete_rename_1": REF_NODES_DEVIATION,
}
BLENDER_SCENE_TESTS = "no_edits/test_import_export_no_edits.py"


def pytest_collection_modifyitems(config, items):
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        for key, reason in DEVIATIONS.items():
            if nodeid.endswith(key):
                item.add_marker(pytest.mark.xfail(reason=reason, strict=True))
        if BLENDER_SCENE_TESTS in nodeid:
            item.add_marker(pytest.mark.skip(reason="checks objects in the Blender scene; covered by the Blender bridge tests"))


class _Anything:
    def __getattr__(self, name):
        return self

    def __setattr__(self, name, value):
        pass

    def __call__(self, *args, **kwargs):
        return self


for _name in ("bpy", "bmesh", "jbeam_editor", "jbeam_editor.constants"):
    _module = types.ModuleType(_name)
    _module.__getattr__ = lambda attribute: _Anything()
    sys.modules[_name] = _module
sys.modules["jbeam_editor"].constants = sys.modules["jbeam_editor.constants"]
_helper = types.ModuleType("addon_helper")
_helper.get_version = lambda *args, **kwargs: None
sys.modules["addon_helper"] = _helper
sys.path.insert(0, str(Path(__file__).resolve().parent))
