from __future__ import annotations

import random
from pathlib import Path
from typing import Mapping, Sequence

from ..checks import run_checks
from ..diagnostics import REFERENCES, SLOTS, TABLE, DiagnosticList
from ..lua import deep_copy, is_number, truthy
from ..model.files import load_source_file
from ..model.tables import process_vehicle_tables
from .config import VehicleConfig, read_pc
from .expressions import Evaluator
from .index import PartDef, PartIndex, parts_in_file
from .links import drop_broken_links
from .merge import merge_named_sections, unify
from .paths import model_dir_of, vehicles_root_of
from .positions import node_position
from .result import AssembledVehicle, BeamEntry, ExtraEntry, FaceEntry, NodeEntry
from .slots import find_parts
from .variables import COMPONENTS, Resolver, apply_standalone, collect_variables, process_components, process_parts

EXTRA_SECTIONS = {
    "hydros": ("id1:", "id2:"),
    "torsionbars": ("id1:", "id2:", "id3:", "id4:"),
    "torsionHydros": ("id1:", "id2:", "id3:", "id4:"),
    "slidenodes": ("id:",),
}
"""Table sections of rows that join nodes without being mesh edges, with the columns of their nodes."""


def _directories(model_dir: Path, common_dir: Path | None = None,
                 vehicle_roots: Sequence[Path] = ()) -> tuple[list[Path], list[Path]]:
    """The model folder and the same model in the other `vehicles` folders, then every common folder.

    Like the game's virtual file system, the common folders of all roots form one namespace; earlier ones win.
    """
    model_dir = Path(model_dir)
    seen = {model_dir.resolve()}
    directories = [model_dir]
    candidates = [Path(root) / model_dir.name for root in vehicle_roots]
    commons_wanted = [Path(common_dir)] if common_dir else [model_dir.parent / "common"]
    commons_wanted += [Path(root) / "common" for root in vehicle_roots]
    commons = []
    for candidate, is_common in [(c, False) for c in candidates] + [(c, True) for c in commons_wanted]:
        if candidate.is_dir() and candidate.resolve() not in seen:
            seen.add(candidate.resolve())
            directories.append(candidate)
            if is_common:
                commons.append(candidate)
    return directories, commons


def _index(model_dir, common_dir, vehicle_roots, diags, overrides, closed) -> PartIndex:
    directories, commons = _directories(model_dir, common_dir, vehicle_roots)
    return PartIndex(directories, diags, overrides, commons, closed)


def assemble_vehicle(model_dir: Path, config: VehicleConfig | None = None, *, common_dir: Path | None = None,
                     vehicle_roots: Sequence[Path] = (), overrides: Mapping[Path, str] | None = None,
                     closed: bool = False, seed: int = 0, diagnostics: DiagnosticList | None = None) -> AssembledVehicle:
    """Assembles a vehicle from `vehicles/<model>` and `vehicles/common` the way the game's loader does.

    `vehicle_roots` are other `vehicles` folders, such as the extracted game content when editing a mod; the same
    model and the common folder are also looked up there, after the vehicle's own folder. `overrides` maps file
    paths to texts that replace the files on disk; with `closed` they are the complete set of JBeam files.
    """
    diags = diagnostics if diagnostics is not None else DiagnosticList()
    model_dir = Path(model_dir)
    config = config or VehicleConfig()
    index = _index(model_dir, common_dir, vehicle_roots, diags, overrides, closed)
    vehicle = AssembledVehicle(model=config.model or model_dir.name, config=config, index=index,
                               files=dict(index.files), diagnostics=diags)
    found = find_parts(index, config, diags)
    if found is not None:
        vehicle.main_part = found.root_def.name
        vehicle.slot_tree = found.tree
        vehicle.parts = {found.root_def.name: found.root_def}
        vehicle.parts.update((entry.part_def.name, entry.part_def) for entry in found.journal_c)
        ctx = Resolver(diags, Evaluator(random.Random(seed)))
        root = found.root
        root["partOrigin"] = root.get("partName")
        root["partPath"] = "/" + str(root.get("partName"))
        variables = collect_variables(found, config.vars, ctx)
        process_components(found, variables, ctx)
        process_parts(found, variables, ctx)
        for entry in found.journal:
            unify(entry.parent, entry.part, entry.slot_options, entry.part_path, diags)
        vehicle.variables = {name: row for name, row in variables.items() if name != COMPONENTS and isinstance(row, dict)}
        process_vehicle_tables(root, diags)
        merge_named_sections(root, "triggers", "triggers2", diags)
        merge_named_sections(root, "rails", "rails2", diags)
        drop_broken_links(root, diags)
        vehicle.data = root
        collect_entries(vehicle, root)
    if not vehicle.nodes:
        diags.add("error", SLOTS, f'the assembled vehicle "{vehicle.model}" has no nodes')
    run_checks(vehicle)
    return vehicle


def assemble_pc(pc_path: Path, *, common_dir: Path | None = None, vehicle_roots: Sequence[Path] = (),
                overrides: Mapping[Path, str] | None = None, closed: bool = False, seed: int = 0) -> AssembledVehicle:
    """Assembles the vehicle described by a part config file; see `assemble_vehicle` for the folders searched."""
    diags = DiagnosticList()
    pc_path = Path(pc_path)
    files: dict = {}
    config = read_pc(pc_path, diags, overrides, files)
    model_dir = model_dir_of(pc_path) or pc_path.parent
    if config is not None and config.model:
        root = vehicles_root_of(pc_path)
        if root is not None and (root / config.model).is_dir():
            model_dir = root / config.model
    vehicle = assemble_vehicle(model_dir, config or VehicleConfig(path=pc_path), common_dir=common_dir,
                               vehicle_roots=vehicle_roots, overrides=overrides, closed=closed, seed=seed,
                               diagnostics=diags)
    vehicle.files.update(files)
    return vehicle


def assemble_part(jbeam_path: Path, part_name: str, *, common_dir: Path | None = None,
                  vehicle_roots: Sequence[Path] = (), overrides: Mapping[Path, str] | None = None,
                  closed: bool = False, seed: int = 0) -> AssembledVehicle:
    """Processes one part on its own, with variable defaults and without slots, for editing a single file.

    Nodes of other parts that its beams, triangles and quads reference are looked up in the same vehicle folder
    and in common and returned as `external_nodes`.
    """
    diags = DiagnosticList()
    jbeam_path = Path(jbeam_path).absolute()
    model_dir = model_dir_of(jbeam_path) or jbeam_path.parent
    index = _index(model_dir, common_dir, vehicle_roots, diags, overrides, closed)
    source = load_source_file(jbeam_path, (overrides or {}).get(jbeam_path))
    parts, file_diags = parts_in_file(source)
    if not any(_is_inside(jbeam_path, d) for d in index.directories):
        diags.extend(file_diags)
    vehicle = AssembledVehicle(model=model_dir.name, main_part=part_name, index=index,
                               files={**index.files, source.path: source}, diagnostics=diags)
    part = parts.get(part_name)
    if part is None:
        diags.add("error", SLOTS, f'part "{part_name}" not found in {jbeam_path.name}', str(jbeam_path))
        return vehicle
    vehicle.parts = {part_name: part}
    vehicle.data, variables = _standalone(part, Resolver(diags, Evaluator(random.Random(seed))))
    vehicle.variables = {name: row for name, row in variables.items() if name != COMPONENTS}
    collect_entries(vehicle, vehicle.data)
    referenced = {i for beam in vehicle.beams for i in (beam.id1, beam.id2)}
    referenced.update(i for face in vehicle.triangles + vehicle.quads for i in face.ids)
    missing = referenced - vehicle.nodes.keys()
    if missing:
        vehicle.external_nodes = _external_nodes(index, missing, part_name, seed)
        required = {i for beam in vehicle.beams if not truthy(beam.props.get("optional")) for i in (beam.id1, beam.id2)}
        required.update(i for face in vehicle.triangles + vehicle.quads if not truthy(face.props.get("optional"))
                        for i in face.ids)
        for node_id in sorted((missing & required) - vehicle.external_nodes.keys()):
            diags.add("warning", REFERENCES,
                      f'node "{node_id}" is not defined in {model_dir.name} or in common; parts of other vehicles '
                      f'and mods are only searched in the "Unpacked game vehicles" folder of the preferences',
                      str(jbeam_path))
    if not vehicle.nodes:
        diags.add("info", SLOTS, f'part "{part_name}" has no nodes of its own')
    run_checks(vehicle)
    return vehicle


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _standalone(part: PartDef, ctx: Resolver) -> tuple[dict, dict]:
    data = deep_copy(part.data)
    data["partOrigin"] = part.name
    data["partPath"] = "/" + part.name
    variables = apply_standalone(data, ctx)
    process_vehicle_tables(data, ctx.diags)
    return data, variables


def _external_nodes(index: PartIndex, wanted: set[str], exclude: str, seed: int) -> dict[str, NodeEntry]:
    found: dict[str, NodeEntry] = {}
    quiet = Resolver(DiagnosticList(), Evaluator(random.Random(seed)))
    for part in index:
        remaining = wanted - found.keys()
        if not remaining:
            break
        rows = part.data.get("nodes")
        if part.name == exclude or not isinstance(rows, list):
            continue
        ids = {row[0] for row in rows[1:] if isinstance(row, list) and row and isinstance(row[0], str)}
        hits = remaining & ids
        if not hits:
            continue
        other = AssembledVehicle(diagnostics=quiet.diags)
        collect_entries(other, _standalone(part, quiet)[0])
        for node_id in hits:
            if node_id in other.nodes:
                found[node_id] = other.nodes[node_id]
    return found


def _rows(section):
    if isinstance(section, dict):
        return [row for row in section.values() if isinstance(row, dict)]
    return []


def collect_entries(vehicle: AssembledVehicle, data: dict) -> None:
    """Builds the node, beam, triangle and quad lists from processed vehicle data."""
    nodes = data.get("nodes")
    if isinstance(nodes, dict):
        for key, row in nodes.items():
            if not isinstance(row, dict):
                continue
            node_id = str(row.get("name", key))
            if not all(is_number(row.get(axis)) for axis in ("posX", "posY", "posZ")):
                vehicle.diagnostics.at(getattr(row, "src", None), "warning", TABLE,
                                       f'node "{node_id}" has no numeric position, skipped')
                continue
            vehicle.nodes[node_id] = NodeEntry(node_id, node_position(row), row.get("partOrigin"), row.get("partPath"),
                                               row, getattr(row, "src", None))
    for row in _rows(data.get("beams")):
        id1, id2 = row.get("id1:"), row.get("id2:")
        if id1 is not None and id2 is not None:
            vehicle.beams.append(BeamEntry(str(id1), str(id2), row.get("partOrigin"), row, getattr(row, "src", None)))
    for section, keys, target in (("triangles", ("id1:", "id2:", "id3:"), vehicle.triangles),
                                  ("quads", ("id1:", "id2:", "id3:", "id4:"), vehicle.quads)):
        for row in _rows(data.get(section)):
            ids = tuple(row.get(key) for key in keys)
            if None not in ids:
                target.append(FaceEntry(tuple(map(str, ids)), row.get("partOrigin"), row, getattr(row, "src", None)))
    for section, keys in EXTRA_SECTIONS.items():
        for row in _rows(data.get(section)):
            ids = tuple(row.get(key) for key in keys)
            if None not in ids:
                rail = row.get("railName") if section == "slidenodes" else None
                vehicle.extras.append(ExtraEntry(section, tuple(map(str, ids)), row.get("partOrigin"), row,
                                                 getattr(row, "src", None), None if rail is None else str(rail)))
    rails = data.get("rails")
    for name, rail in (rails.items() if isinstance(rails, dict) else ()):
        links = rail.get("links:") if isinstance(rail, dict) else None
        if isinstance(links, list) and links:
            vehicle.extras.append(ExtraEntry("rails", tuple(map(str, links)), rail.get("partOrigin"), rail,
                                             getattr(rail, "src", None), str(name)))
