from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..diagnostics import DiagnosticList

if TYPE_CHECKING:
    from ..model.files import SourceFile
    from ..sjson import SourceRef
    from .config import VehicleConfig
    from .index import PartDef, PartIndex
    from .slots import SlotNode


@dataclass(eq=False)
class NodeEntry:
    id: str
    pos: tuple[float, float, float]
    part: str | None
    part_path: str | None
    props: dict
    src: SourceRef | None


@dataclass(eq=False)
class BeamEntry:
    id1: str
    id2: str
    part: str | None
    props: dict
    src: SourceRef | None


@dataclass(eq=False)
class FaceEntry:
    ids: tuple[str, ...]
    part: str | None
    props: dict
    src: SourceRef | None


@dataclass(eq=False)
class ExtraEntry:
    """A hydro, torsion bar, torsion hydro, slide node or rail: rows that join nodes but are not mesh edges."""
    section: str
    ids: tuple[str, ...]
    """The nodes it joins, in order: the links of a rail, the one node of a slide node."""
    part: str | None
    props: dict
    src: SourceRef | None
    name: str | None = None
    """The name of a rail, or the rail a slide node slides on."""


@dataclass(eq=False)
class AssembledVehicle:
    model: str | None = None
    main_part: str | None = None
    config: VehicleConfig | None = None
    slot_tree: SlotNode | None = None
    variables: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    """The assembled vehicle: every section processed into entries, like the game's vehicle data."""
    nodes: dict[str, NodeEntry] = field(default_factory=dict)
    beams: list[BeamEntry] = field(default_factory=list)
    triangles: list[FaceEntry] = field(default_factory=list)
    quads: list[FaceEntry] = field(default_factory=list)
    extras: list[ExtraEntry] = field(default_factory=list)
    external_nodes: dict[str, NodeEntry] = field(default_factory=dict)
    """Nodes of other parts that a single imported part references; shown read-only."""
    dropped: list[tuple[str, dict]] = field(default_factory=list)
    """Rows the game discards because they reference entries that do not exist, with their sections."""
    parts: dict[str, PartDef] = field(default_factory=dict)
    """The parts that make up the vehicle, parents before children."""
    index: PartIndex | None = None
    files: dict[Path, SourceFile] = field(default_factory=dict)
    """Every file read while assembling, by path."""
    diagnostics: DiagnosticList = field(default_factory=DiagnosticList)
