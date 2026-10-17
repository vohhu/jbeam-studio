"""Checks of an assembled vehicle that point at likely mistakes in the JBeam."""

from __future__ import annotations

from pathlib import Path

from ..assembly.result import AssembledVehicle
from ..diagnostics import CHECKS

def run_checks(vehicle: AssembledVehicle) -> None:
    check_duplicate_beams(vehicle)
    check_degenerate_faces(vehicle)


def check_duplicate_beams(vehicle: AssembledVehicle) -> None:
    seen: dict = {}
    for beam in vehicle.beams:
        props = beam.props
        if (props.get("beamSpring") == 0 or props.get("deformGroup") not in (None, "")
                or props.get("beamType") == "|BOUNDED" or props.get("optional") is True):
            continue
        beam_type = props.get("beamType") or "|NORMAL"
        a, b = sorted((beam.id1, beam.id2))
        key = (a, b, beam_type)
        first = seen.get(key)
        if first is None:
            seen[key] = [beam, False]
            continue
        if not first[1]:
            vehicle.diagnostics.at(first[0].src, "warning", CHECKS, f"duplicate beam {a} - {b}")
            first[1] = True
        original, src = first[0].src, beam.src
        if original is None or src is None or src.node is original.node:
            vehicle.diagnostics.at(src, "warning", CHECKS, f"duplicate beam {a} - {b}")
            continue
        vehicle.diagnostics.at(src, "warning", CHECKS,
                               f"duplicate beam {a} - {b}, repeats {Path(original.file).name}:{original.line}",
                               fix=("delete_duplicate", src.node.start))


def check_degenerate_faces(vehicle: AssembledVehicle) -> None:
    for kind, faces in (("triangle", vehicle.triangles), ("quad", vehicle.quads)):
        for face in faces:
            if len(set(face.ids)) < len(face.ids):
                vehicle.diagnostics.at(face.src, "error", CHECKS,
                                       f"degenerate {kind} {', '.join(face.ids)}: the same node is used twice")
