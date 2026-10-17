from __future__ import annotations

import zipfile
from pathlib import Path

SUFFIXES = (".jbeam", ".pc")
NAMES = ("info.json",)


def is_vehicle_definition(member: str) -> bool:
    lower = member.lower()
    return lower.endswith(SUFFIXES) or lower.rsplit("/", 1)[-1] in NAMES


def extract_vehicles(source: Path, destination: Path, archives: set[str] | None = None) -> int:
    """Copies the JBeam, part config and info files out of every vehicle archive in `source`, keeping their paths."""
    destination = Path(destination).resolve()
    count = 0
    for archive in sorted(Path(source).glob("*.zip")):
        if archives and archive.stem not in archives:
            continue
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir() or not is_vehicle_definition(info.filename):
                    continue
                target = (destination / info.filename).resolve()
                if destination not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
                count += 1
    return count
