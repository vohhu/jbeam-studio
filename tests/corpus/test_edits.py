import os
import random

import pytest
from _corpus import configs, path_id

from jbeam_studio.core.diagnostics import Severity
from jbeam_studio.core.edit import EditError, EditSession, SharedRowError, TemplateIdError, UnreachablePositionError

ROUNDS = int(os.environ.get("JBS_CORPUS_EDITS", "1"))
FIRST_CONFIGS = [(model_dir, pc) for model_dir, pc in configs() if pc is not None]
seen_models = set()
EDIT_CONFIGS = [c for c in FIRST_CONFIGS if not (c[0] in seen_models or seen_models.add(c[0]))]


def _errors(vehicle):
    return sum(1 for d in vehicle.diagnostics if d.severity is Severity.ERROR)


def _operations(session, rng):
    vehicle = session.vehicle
    nodes = sorted(vehicle.nodes)
    parts = sorted(vehicle.parts)
    node = vehicle.nodes[rng.choice(nodes)]
    yield "move", lambda: session.move_nodes({node.id: tuple(c + rng.uniform(-0.05, 0.05) for c in node.pos)})
    renamed = rng.choice(nodes)
    yield "rename", lambda: session.rename_node(renamed, f"jbs_{renamed}")
    yield "add node", lambda: session.add_node(rng.choice(parts), (rng.uniform(-1, 1), rng.uniform(-2, 2), rng.uniform(0, 1.5)))
    a, b = rng.sample(sorted(session.vehicle.nodes), 2)
    owner = session.vehicle.nodes[a].part if session.vehicle.nodes[a].part in vehicle.parts else rng.choice(parts)
    yield "add beam", lambda: session.add_beam(owner, a, b)
    if session.vehicle.beams:
        beam = rng.choice(session.vehicle.beams)
        yield "delete beam", lambda: session.delete_entries([beam])
    if session.vehicle.triangles:
        face = rng.choice(session.vehicle.triangles)
        yield "flip", lambda: session.flip_faces([face])
    victim = rng.choice(sorted(session.vehicle.nodes))
    yield "delete node", lambda: session.delete_nodes([victim], cascade=True)


@pytest.mark.parametrize("model_dir, pc", EDIT_CONFIGS, ids=path_id)
def test_random_edits_verify_and_undo(model_dir, pc):
    rng = random.Random(model_dir.name)
    session = EditSession.for_pc(pc)
    errors_before = _errors(session.vehicle)
    failures = []
    for _ in range(ROUNDS):
        for name, operation in _operations(session, rng):
            texts = dict(session.texts)
            try:
                operation()
            except (SharedRowError, TemplateIdError, UnreachablePositionError):
                assert session.texts == texts, f"{name} was refused but changed the text"
            except EditError as error:
                failures.append(f"{name}: {error}")
                assert session.texts == texts, f"{name} failed but changed the text"
            assert _errors(session.vehicle) <= errors_before, f"{name} introduced errors"
    while session.can_undo:
        session.undo()
    assert all(session.text_of(path) == session._saved[path] for path in session.texts)
    assert failures == []
