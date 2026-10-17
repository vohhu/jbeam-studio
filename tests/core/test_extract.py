import zipfile

from jbeam_studio.core.extract import extract_vehicles


def test_extracts_only_vehicle_definitions(tmp_path):
    source = tmp_path / "zips"
    source.mkdir()
    with zipfile.ZipFile(source / "car.zip", "w") as zf:
        zf.writestr("vehicles/car/car.jbeam", "{}")
        zf.writestr("vehicles/car/a.pc", "{}")
        zf.writestr("vehicles/car/info.json", "{}")
        zf.writestr("vehicles/car/car.dae", "x")
        zf.writestr("../evil.jbeam", "{}")
    with zipfile.ZipFile(source / "other.zip", "w") as zf:
        zf.writestr("vehicles/other/o.jbeam", "{}")
    destination = tmp_path / "out"
    assert extract_vehicles(source, destination, {"car"}) == 3
    files = sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file())
    assert files == ["vehicles/car/a.pc", "vehicles/car/car.jbeam", "vehicles/car/info.json"]
    assert not (tmp_path / "evil.jbeam").exists()
