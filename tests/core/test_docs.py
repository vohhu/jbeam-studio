import importlib.util
from pathlib import Path

from jbeam_studio.core import docs

TOOL = Path(__file__).resolve().parents[2] / "tools" / "port_vscode_docs.py"


def test_lookup():
    entry = docs.lookup("nodes", "id")
    assert entry is not None
    assert "unique" in entry.description.lower()
    assert entry.url.startswith("https://documentation.beamng.com/")


def test_link_keys_match_with_or_without_colon():
    assert docs.lookup("beams", "id1:") is not None
    assert docs.lookup("beams", "id1:") == docs.lookup("beams", "id1")


def test_every_entry_has_a_link():
    entries = docs.all_entries()
    assert len(entries) == 76
    assert all(entry.url for entry in entries)


def test_converter():
    spec = importlib.util.spec_from_file_location("port_vscode_docs", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    js = ('const jbeamDocumentation = {\n  // nodes\n  "nodes > id": {\n    "description": "Node `name`",\n'
          '    "type": "string",\n    "default": "",\n    "documentation": "[here](https://documentation.beamng.com/x/#id)"\n'
          '  },\n}\n\nmodule.exports = {\n  jbeamDocumentation\n}\n')
    assert tool.convert(js)["entries"] == [{
        "section": "nodes", "key": "id", "description": "Node `name`", "type": "string", "default": "",
        "url": "https://documentation.beamng.com/x/#id",
    }]
