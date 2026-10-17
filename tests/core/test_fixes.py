import pytest

from jbeam_studio.core.edit import EditError, EditSession
from jbeam_studio.core.edit.fixes import fix, group_of


def session_for(car):
    (car / "base.pc").write_text('{"format": 2, "parts": {}}', encoding="utf-8")
    return EditSession.for_pc(car / "base.pc")


def fixable(session, group=None):
    return [d for d in session.vehicle.diagnostics if group_of(d) and group in (None, group_of(d))]


def with_beams(session, car, rows, ghost='["b1r", "ghost"]'):
    path = car / "body.jbeam"
    text = session.text_of(path).replace('["b1r", "ghost"]]', ghost + (", " + rows if rows else "") + "]", 1)
    session.replace_text(path, text)
    return path


def test_a_row_with_a_missing_node_is_kept_and_marked_optional(car):
    session = session_for(car)
    [problem] = fixable(session)
    assert "ghost" in problem.message and group_of(problem) == "missing"
    result = fix(session, [problem])
    assert (result.optional, result.deleted) == (1, 0)
    assert '["b1r", "ghost", {"optional":true}]' in session.text_of(car / "body.jbeam")
    assert fixable(session) == []
    assert len(session.vehicle.beams) == 3 and len(session.history) == 1


@pytest.mark.parametrize("row, marked", [
    ('["b1r", "ghost", {"beamSpring": 5}]', '["b1r", "ghost", {"beamSpring": 5, "optional": true}]'),
    ('["b1r", "ghost", {"optional": false}]', '["b1r", "ghost", {"optional": true}]'),
    ('["b1r", {"beamSpring": 5}]', '["b1r", {"beamSpring": 5}, {"optional":true}]'),
])
def test_the_flag_goes_where_the_game_reads_the_options_of_a_row(car, row, marked):
    session = session_for(car)
    path = with_beams(session, car, "", ghost=row)
    fix(session, fixable(session, "missing"))
    assert marked in session.text_of(path)
    assert fixable(session) == []


def test_rows_shorter_than_their_header_get_a_modifier_around_them(car):
    session = session_for(car)
    session.add_rail("car_body", "track", ["b1l", "b2"])
    session.add_extras("car_body", "slidenodes", [("b2", "track")])
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path).replace(
        '["b2", "track"]', '["far1", "track"],\n        ["far2", "track"],\n        ["b2", "track"]', 1))
    result = fix(session, fixable(session, "missing"))
    assert result.optional == 3
    text = session.text_of(path)
    assert text.index('{"optional":true}') < text.index('"far1"') < text.index('"far2"') < \
        text.index('{"optional":false}') < text.index('["b2", "track"]')
    assert '["b1r", "ghost", {"optional":true}]' in text
    [slide] = [e for e in session.vehicle.extras if e.section == "slidenodes"]
    assert slide.ids == ("b2",) and not slide.props.get("optional")
    assert fixable(session) == []


def test_only_the_repeats_of_a_beam_can_be_deleted(car):
    session = session_for(car)
    path = with_beams(session, car, '["b2", "b1l"],\n        ["b1l", "b2"]')
    duplicates = [d for d in session.vehicle.diagnostics if d.message.startswith("duplicate beam")]
    assert len(duplicates) == 3
    assert [group_of(d) for d in duplicates] == [None, "duplicates", "duplicates"]
    assert "repeats body.jbeam:" in duplicates[1].message
    beams = len(session.vehicle.beams)
    result = fix(session, fixable(session, "duplicates"))
    assert result.deleted == 2 and len(session.vehicle.beams) == beams - 2
    assert '["b2", "b1l"]' not in session.text_of(path)
    assert session.text_of(path).count('["b1l", "b2"]') == 1
    assert not [d for d in session.vehicle.diagnostics if d.message.startswith("duplicate beam")]


def test_fixing_everything_in_one_file_is_one_change_that_undoes_at_once(car):
    session = session_for(car)
    path = with_beams(session, car, '["b1l", "nowhere"], ["b2", "b1l"]')
    path.write_text(session.text_of(path), encoding="utf-8")
    session = session_for(car)
    original = session.text_of(path)
    result = fix(session, fixable(session))
    assert (result.optional, result.deleted) == (2, 1)
    text = session.text_of(path)
    assert '["b1r", "ghost", {"optional":true}]' in text and '["b1l", "nowhere", {"optional":true}]' in text
    assert '["b2", "b1l"]' not in text
    assert fixable(session) == []
    assert len(session.history) == 1
    session.undo()
    assert session.text_of(path) == original


def test_a_changed_file_is_not_touched_by_old_diagnostics(car):
    session = session_for(car)
    [problem] = fixable(session)
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path).replace('"beams": [', '"beams":  [', 1))
    with pytest.raises(EditError):
        fix(session, [problem])


def test_a_single_part_offers_no_fix_for_a_node_it_cannot_find(car):
    session = EditSession.for_part(car / "body.jbeam", "car_body")
    [problem] = [d for d in session.vehicle.diagnostics if '"ghost"' in d.message]
    assert group_of(problem) is None and "preferences" in problem.message
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path).replace('["b1r", "ghost"]', '["b1r", "ghost", {"optional": true}]'))
    assert not [d for d in session.vehicle.diagnostics if '"ghost"' in d.message]


def test_resets_are_added_for_every_leaking_part(car):
    session = session_for(car)
    path = car / "body.jbeam"
    session.replace_text(path, session.text_of(path).replace(
        '"beams": [["id1:", "id2:"],', '"beams": [["id1:", "id2:"], {"beamPrecompression": 1.1},', 1))
    leaks = fixable(session, "resets")
    assert [d.fix for d in leaks] == [("add_resets", "car_body")]
    result = fix(session, leaks)
    assert result.resets == {"car_body": {"beams": ["beamPrecompression"]}}
    assert fixable(session, "resets") == []


def test_problems_without_a_fix_are_refused(car):
    session = session_for(car)
    others = [d for d in session.vehicle.diagnostics if not group_of(d)]
    with pytest.raises(EditError):
        fix(session, others)
