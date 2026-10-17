"""Vehicle assembly from part configs, mirroring the game's JBeam loader."""

from .config import VehicleConfig, read_pc
from .index import PartDef, PartIndex
from .result import AssembledVehicle, BeamEntry, ExtraEntry, FaceEntry, NodeEntry
from .slots import SlotNode
from .vehicle import EXTRA_SECTIONS, assemble_part, assemble_pc, assemble_vehicle

__all__ = [
    "AssembledVehicle", "BeamEntry", "EXTRA_SECTIONS", "ExtraEntry", "FaceEntry", "NodeEntry", "PartDef", "PartIndex",
    "SlotNode", "VehicleConfig", "assemble_part", "assemble_pc", "assemble_vehicle", "read_pc",
]
