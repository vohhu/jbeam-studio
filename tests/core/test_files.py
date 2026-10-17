from jbeam_studio.core.model.files import load_source_file


def test_cache_and_reload(tmp_path):
    path = tmp_path / "a.jbeam"
    path.write_text('{"a": 1}', encoding="utf-8")
    first = load_source_file(path)
    assert first.data == {"a": 1}
    assert load_source_file(path) is first
    path.write_text('{"a": 22}', encoding="utf-8")
    second = load_source_file(path)
    assert second is not first
    assert second.data == {"a": 22}


def test_text_is_kept_byte_for_byte(tmp_path):
    raw = '{\r\n "a": "\u00e9"\r\n}'.encode("utf-8") + b"\xff"
    path = tmp_path / "b.jbeam"
    path.write_bytes(raw)
    assert load_source_file(path).doc.serialize().encode("utf-8", errors="surrogateescape") == raw
