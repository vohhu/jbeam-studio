"""Adapter with the interface of the original test helper, implemented with JBeam Studio edit sessions.

Results are compared with the expected files by their parsed content, because JBeam Studio formats inserted
rows differently from the original editor.
"""

import json
import shutil
import tempfile
from pathlib import Path

from jbeam_studio.core.edit import EditSession
from jbeam_studio.core.model.files import read_text
from jbeam_studio.core.sjson import parse, to_python

SCENARIOS = Path(__file__).resolve().parent / "jbeam_import_modify_export"
FINISHED = {"FINISHED"}


def _rotations(ids):
    return {tuple(ids[i:] + ids[:i]) for i in range(len(ids))}


class JBeamEditorTest:
    def __init__(self, test_suite_name):
        self.suite = SCENARIOS / test_suite_name
        self.session = None

    def set_test_to_run(self, test_name):
        self.work = Path(tempfile.mkdtemp(prefix="jbs-legacy-"))
        shutil.copytree(self.suite / test_name / "original", self.work / "original")
        self.expected = self.suite / test_name / "expected"
        data = json.loads((self.suite / test_name / "import.json").read_text(encoding="utf-8"))
        self.import_file = self.work / data["import_file"].replace("\\", "/")
        self.import_part = data["import_part"]

    def import_jbeam(self):
        self.session = EditSession.for_part(self.import_file, self.import_part)
        return FINISHED

    def select_imported_jbeam_mesh(self):
        pass

    def add_nodes_from_imported_jbeam_mesh(self, node_ids, node_id_to_new_position):
        for node_id in node_ids:
            self.session.add_node(self.import_part, node_id_to_new_position[node_id], node_id)

    add_nodes = add_nodes_from_imported_jbeam_mesh

    def delete_nodes_from_imported_jbeam_mesh(self, node_ids):
        self.session.delete_nodes(sorted(node_ids), cascade=True)

    def move_nodes_from_imported_jbeam_mesh(self, node_ids_to_new_pos):
        self.session.move_nodes(node_ids_to_new_pos)

    def rename_nodes_from_imported_jbeam_mesh(self, old_to_new_node_ids):
        for old, new in old_to_new_node_ids:
            self.session.rename_node(old, new)

    def add_beams_from_imported_jbeam_mesh(self, beams):
        for id1, id2 in beams:
            self.session.add_beam(self.import_part, id1, id2)

    def delete_beams_from_imported_jbeam_mesh(self, beams):
        wanted = {tuple(sorted(pair)) for pair in beams}
        self.session.delete_entries([b for b in self.session.vehicle.beams if tuple(sorted((b.id1, b.id2))) in wanted])

    def add_faces_from_imported_jbeam_mesh(self, faces):
        for face in faces:
            if len(face) == 3:
                self.session.add_triangle(self.import_part, list(face))
            else:
                self.session.add_quad(self.import_part, list(face))

    def delete_faces_from_imported_jbeam_mesh(self, faces):
        wanted = set()
        for face in faces:
            wanted |= _rotations(list(face))
        vehicle = self.session.vehicle
        self.session.delete_entries([f for f in vehicle.triangles + vehicle.quads if f.ids in wanted])

    def export_jbeam(self):
        return FINISHED

    def export_jbeam_to_file(self):
        self.session.save()
        return FINISHED

    def test_result(self):
        ours, expected = self.work / "original", self.expected
        expected_files = sorted(p.relative_to(expected) for p in expected.rglob("*") if p.is_file())
        our_files = sorted(p.relative_to(ours) for p in ours.rglob("*") if p.is_file() and not p.name.endswith(".bak"))
        assert our_files == expected_files
        for relative in expected_files:
            a, b = ours / relative, expected / relative
            if relative.suffix in (".jbeam", ".pc"):
                assert to_python(parse(read_text(a))) == to_python(parse(read_text(b))), f"{relative} differs"
            else:
                assert a.read_bytes() == b.read_bytes(), f"{relative} differs"
        return True

    def cleanup(self):
        shutil.rmtree(self.work, ignore_errors=True)
