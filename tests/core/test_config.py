from jbeam_studio.core.assembly.config import read_pc
from jbeam_studio.core.assembly.paths import model_dir_of, resolve_game_path, vehicles_root_of
from jbeam_studio.core.diagnostics import DiagnosticList


def pc(tmp_path, name, text):
    folder = tmp_path / "vehicles" / "car"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder / name


def test_format_2(tmp_path):
    config = read_pc(pc(tmp_path, "a.pc", '{"format": 2, "model": "car", "mainPartName": "body", '
                                          '"parts": {"s": "p"}, "vars": {"$v": 1}}'), DiagnosticList())
    assert (config.model, config.main_part_name, config.parts, config.vars) == ("car", "body", {"s": "p"}, {"$v": 1})


def test_format_4_linked(tmp_path):
    pc(tmp_path, "base.pc", '{"format": 2, "parts": {"s": "p"}}')
    diags = DiagnosticList()
    config = read_pc(pc(tmp_path, "c.pc", '{"format": 4, "vehicles": [{"linkedPCFile": "/vehicles/car/base.pc"}, '
                                          '{"model": "trailer"}]}'), diags)
    assert config.parts == {"s": "p"}
    assert any("not imported" in d.message for d in diags)


def test_format_4_inline(tmp_path):
    config = read_pc(pc(tmp_path, "d.pc", '{"format": 4, "vehicles": [{"model": "car", "parts": {"s": "q"}}]}'),
                     DiagnosticList())
    assert (config.model, config.parts) == ("car", {"s": "q"})


def test_without_format_the_object_is_the_slot_map(tmp_path):
    assert read_pc(pc(tmp_path, "e.pc", '{"s": "p", "t": ""}'), DiagnosticList()).parts == {"s": "p", "t": ""}


def test_unknown_format_is_an_error(tmp_path):
    diags = DiagnosticList()
    assert read_pc(pc(tmp_path, "f.pc", '{"format": 3}'), diags) is None
    assert diags.has_errors()


def test_paths(tmp_path):
    file = tmp_path / "vehicles" / "car" / "sub" / "x.pc"
    assert vehicles_root_of(file) == tmp_path / "vehicles"
    assert model_dir_of(file) == tmp_path / "vehicles" / "car"
    assert resolve_game_path(file, "/vehicles/car/y.pc") == tmp_path / "vehicles" / "car" / "y.pc"
    assert resolve_game_path(tmp_path / "x.pc", "vehicles/a.pc") is None
