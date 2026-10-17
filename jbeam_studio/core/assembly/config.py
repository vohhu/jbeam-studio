from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ..diagnostics import PARSE, DiagnosticList
from ..model.files import load_source_file
from .paths import resolve_game_path


@dataclass
class VehicleConfig:
    model: str | None = None
    main_part_name: str | None = None
    parts: dict = field(default_factory=dict)
    vars: dict = field(default_factory=dict)
    path: Path | None = None


def read_pc(path: Path, diags: DiagnosticList, overrides: Mapping[Path, str] | None = None,
            files: dict | None = None, _depth: int = 0) -> VehicleConfig | None:
    """Reads a part config in format 2, format 4 (a vehicle collection saved by the game) or without a format.

    Every file read is added to `files`.
    """
    overrides = overrides or {}
    source = load_source_file(path, overrides.get(Path(path).absolute()))
    if files is not None:
        files[source.path] = source
    diags.extend(source.doc.diagnostics)
    data = source.data
    if not isinstance(data, dict):
        if source.doc.root is not None:
            diags.add("error", PARSE, "a part config must be an object", str(source.path), 1, 1)
        return None
    fmt = data.get("format")
    if fmt == 4:
        vehicles = data.get("vehicles")
        if not isinstance(vehicles, list) or not vehicles or not isinstance(vehicles[0], dict):
            diags.at(data.src, "error", PARSE, 'format 4 part config has no "vehicles" entries')
            return None
        if len(vehicles) > 1:
            diags.at(data.src, "info", PARSE, f"{len(vehicles) - 1} attached vehicle(s) in this config are not imported")
        first = vehicles[0]
        linked = first.get("linkedPCFile")
        if isinstance(linked, str):
            target = resolve_game_path(source.path, linked)
            if target is None or not target.is_file() or _depth > 8:
                diags.at(first.src, "error", PARSE, f'linked part config "{linked}" not found')
                return None
            return read_pc(target, diags, overrides, files, _depth + 1)
        return _from_dict(first, source.path)
    if fmt == 2:
        return _from_dict(data, source.path)
    if fmt is None:
        return VehicleConfig(parts=dict(data), path=source.path)
    diags.at(data.src, "error", PARSE, f"part config format {fmt!r} is not supported")
    return None


def _from_dict(data: dict, path: Path) -> VehicleConfig:
    parts, variables = data.get("parts"), data.get("vars")
    model, main = data.get("model"), data.get("mainPartName")
    return VehicleConfig(
        model=model if isinstance(model, str) else None,
        main_part_name=main if isinstance(main, str) else None,
        parts=dict(parts) if isinstance(parts, dict) else {},
        vars=dict(variables) if isinstance(variables, dict) else {},
        path=path,
    )
