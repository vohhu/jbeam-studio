"""Extracts .jbeam, .pc and info.json files from BeamNG vehicle archives, keeping their paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jbeam_studio.core.extract import extract_vehicles  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, type=Path, help="folder with vehicle archives, e.g. <game>/content/vehicles")
    parser.add_argument("--dst", required=True, type=Path, help="folder to extract into")
    parser.add_argument("--archives", help="comma-separated archive names without .zip")
    args = parser.parse_args(argv)
    archives = set(args.archives.split(",")) if args.archives else None
    count = extract_vehicles(args.src, args.dst, archives)
    print(f"extracted {count} files to {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
