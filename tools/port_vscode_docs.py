"""Regenerates jbeam_studio/core/docs_data.json from src/docHelper.js of BeamNG/vscode-jbeam-editor (MIT)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jbeam_studio.core.sjson import parse, to_python  # noqa: E402

SOURCE = "BeamNG/vscode-jbeam-editor src/docHelper.js, MIT License, Copyright 2023 BeamNG GmbH - Thomas Fischer"
_START = "const jbeamDocumentation = "
_END = re.compile(r"^\}[ \t]*\r?$", re.M)
_LINK = re.compile(r"\((https?://[^)\s]+)\)")


def object_literal(js: str) -> str:
    start = js.index(_START) + len(_START)
    end = _END.search(js, start)
    if end is None:
        raise ValueError("end of jbeamDocumentation not found")
    return js[start:end.end()]


def convert(js: str) -> dict:
    doc = parse(object_literal(js), "docHelper.js")
    if doc.root is None:
        raise ValueError("; ".join(str(d) for d in doc.diagnostics))
    entries = []
    for name, entry in to_python(doc).items():
        section, _, key = name.partition(" > ")
        link = _LINK.search(str(entry.get("documentation", "")))
        entries.append({
            "section": section.strip(),
            "key": key.strip(),
            "description": str(entry.get("description", "")),
            "type": str(entry.get("type", "")),
            "default": str(entry.get("default", "")),
            "url": link.group(1) if link else "",
        })
    return {"source": SOURCE, "entries": entries}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("doc_helper", type=Path, help="path to src/docHelper.js")
    parser.add_argument("--out", type=Path, default=ROOT / "jbeam_studio" / "core" / "docs_data.json")
    args = parser.parse_args(argv)
    data = convert(args.doc_helper.read_text(encoding="utf-8"))
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(data['entries'])} entries to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
