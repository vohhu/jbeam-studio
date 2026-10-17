import copy
import random

import pytest
from _corpus import configs, path_id

from jbeam_studio.core.edit import EditSession, SharedRowError, TemplateIdError, UnreachablePositionError
from jbeam_studio.core.mesh_sync import MeshLink

seen_models = set()
MODELS = [c for c in configs() if c[1] is not None and not (c[0] in seen_models or seen_models.add(c[0]))]


def _without_vertex(data, index):
    data = copy.deepcopy(data)
    shift = lambda v: v - (v > index)  # noqa: E731
    for name in ("positions", "node_uids", "node_checks", "ghosts", "parts"):
        del getattr(data, name)[index]
    kept = [i for i, edge in enumerate(data.edges) if index not in edge]
    data.edges, data.edge_uids = [tuple(map(shift, data.edges[i])) for i in kept], [data.edge_uids[i] for i in kept]
    kept = [i for i, face in enumerate(data.faces) if index not in face]
    data.faces, data.face_uids = [tuple(map(shift, data.faces[i])) for i in kept], [data.face_uids[i] for i in kept]
    return data


@pytest.mark.parametrize("model_dir, pc", MODELS, ids=path_id)
def test_mesh_matches_the_session_and_mesh_edits_apply(model_dir, pc):
    link = MeshLink(EditSession.for_pc(pc))
    vehicle = link.session.vehicle
    base_rev, base = link.rev, link.build()
    assert link.plan(base).empty
    shown = sum(len(g.indices) for g in link.map.beams.values())
    drawable = sum(1 for b in vehicle.beams if b.id1 != b.id2 and b.id1 in vehicle.nodes and b.id2 in vehicle.nodes)
    assert shown == drawable

    rng = random.Random(model_dir.name)
    edited = copy.deepcopy(base)
    moved = rng.randrange(len(edited.positions))
    x, y, z = edited.positions[moved]
    edited.positions[moved] = (x, y, z + 0.05)
    anchor = rng.randrange(len(edited.positions))
    edited.positions.append((x + 0.1, y, z))
    edited.node_uids.append(0)
    edited.node_checks.append(0)
    edited.ghosts.append(False)
    edited.parts.append(0)
    edited.edges.append((anchor, len(edited.positions) - 1))
    edited.edge_uids.append(0)
    victim = rng.choice([i for i in range(len(base.positions)) if i not in (moved, anchor)])
    edited = _without_vertex(edited, victim)

    plan = link.plan(edited)
    assert len(plan.moves) == 1 and len(plan.new_nodes) == 1 and len(plan.deleted_nodes) == 1
    try:
        link.apply(plan, vehicle.main_part)
    except (SharedRowError, TemplateIdError, UnreachablePositionError):
        return
    assert link.plan(link.build()).empty
    assert link.goto(base_rev) and link.plan(base).empty
