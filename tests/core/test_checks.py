from jbeam_studio.core.assembly.result import AssembledVehicle, BeamEntry, FaceEntry, NodeEntry
from jbeam_studio.core.checks import run_checks


def node(node_id, x, y=0.0, z=0.0):
    return NodeEntry(node_id, (x, y, z), "p", "/p", {}, None)


def beam(a, b, **props):
    return BeamEntry(a, b, "p", props, None)


def vehicle(nodes=(), beams=(), triangles=(), quads=()):
    return AssembledVehicle(nodes={n.id: n for n in nodes}, beams=list(beams),
                            triangles=[FaceEntry(ids, "p", {}, None) for ids in triangles],
                            quads=[FaceEntry(ids, "p", {}, None) for ids in quads])


def messages(v):
    return [d.message for d in v.diagnostics]


def test_duplicate_beams():
    v = vehicle(beams=[beam("a", "b"), beam("b", "a"), beam("a", "b", beamType="|SUPPORT"), beam("a", "b", beamSpring=0),
                       beam("a", "b", deformGroup="x"), beam("a", "b", beamType="|BOUNDED"), beam("a", "b", optional=True)])
    run_checks(v)
    assert messages(v) == ["duplicate beam a - b", "duplicate beam a - b"]


def test_degenerate_faces():
    v = vehicle(triangles=[("a", "b", "a"), ("a", "b", "c")], quads=[("a", "b", "c", "c")])
    run_checks(v)
    assert len(v.diagnostics.errors()) == 2


def test_asymmetric_left_and_right_nodes_are_not_reported():
    v = vehicle(nodes=[node("bl1", 0.5), node("br1", -0.6, 0.3)])
    run_checks(v)
    assert messages(v) == []
