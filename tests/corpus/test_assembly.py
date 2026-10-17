import pytest
from _corpus import configs, path_id

from jbeam_studio.core.assembly import assemble_pc, assemble_vehicle
from jbeam_studio.core.diagnostics import Severity


@pytest.mark.parametrize("model_dir, pc", configs(), ids=path_id)
def test_assembles_without_errors(model_dir, pc):
    vehicle = assemble_pc(pc) if pc else assemble_vehicle(model_dir)
    errors = [str(d) for d in vehicle.diagnostics if d.severity is Severity.ERROR]
    assert errors == []
    assert vehicle.nodes
