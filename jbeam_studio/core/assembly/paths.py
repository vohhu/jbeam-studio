from __future__ import annotations

from pathlib import Path


def vehicles_root_of(path: Path) -> Path | None:
    """The `vehicles` folder that contains `path`."""
    path = Path(path)
    for candidate in (path, *path.parents):
        if candidate.name.lower() == "vehicles":
            return candidate
    return None


def model_dir_of(path: Path) -> Path | None:
    """`vehicles/<model>` folder that contains `path`."""
    path = Path(path)
    root = vehicles_root_of(path)
    if root is None or path == root:
        return None
    return root / path.relative_to(root).parts[0]


def resolve_game_path(from_file: Path, game_path: str) -> Path | None:
    """Maps a game path such as `/vehicles/pickup/x.pc` onto the extracted folder that `from_file` lives in."""
    root = vehicles_root_of(from_file)
    if root is None:
        return None
    return root.parent / game_path.replace("\\", "/").lstrip("/")
