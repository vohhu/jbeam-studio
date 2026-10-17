import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "jbeam_studio" / "core"
BLENDER_MODULES = {
    "bpy", "bmesh", "gpu", "gpu_extras", "mathutils", "blf", "bpy_extras", "bl_math", "idprop", "aud", "freestyle", "bgl",
}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_does_not_import_blender():
    offenders = {}
    for path in CORE.rglob("*.py"):
        found = _imported_roots(path) & BLENDER_MODULES
        if found:
            offenders[str(path.relative_to(CORE))] = sorted(found)
    assert offenders == {}


def test_core_imports_without_blender():
    import jbeam_studio.core  # noqa: F401
