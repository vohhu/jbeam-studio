import pytest
from _corpus import path_id, source_files

from jbeam_studio.core.model.files import read_text
from jbeam_studio.core.sjson import parse


@pytest.mark.parametrize("path", source_files(), ids=path_id)
def test_parses_and_serializes_losslessly(path):
    text = read_text(path)
    doc = parse(text, str(path))
    assert doc.root is not None, [str(d) for d in doc.diagnostics]
    assert doc.serialize() == text
