import bpy

from jbeam_studio.blender import sessions
from jbeam_studio.core.sjson.tokens import PART, SECTION
from jbeam_studio.ui import text_syntax


def import_pc(car):
    assert bpy.ops.jbs.import_pc(filepath=str(car / "base.pc")) == {"FINISHED"}
    obj = bpy.context.active_object
    return obj, sessions.session_of(obj)


def test_session_text_gets_tokens_and_assembly_problems(car):
    _obj, session = import_pc(car)
    text = sessions.show_text(session, car / "body.jbeam")
    assert text_syntax.is_jbeam(text)
    analysis = text_syntax.analysis_of(text, text.as_string())
    kinds = {kind for line in analysis.tokens for _, _, kind in line}
    assert {PART, SECTION} <= kinds
    problems = text_syntax.problems_of(text, analysis)
    [(line, found)] = problems.items()
    assert '"ghost"' in text.lines[line].body and "ghost" in found[0].message


def test_typing_errors_show_up_and_assembly_problems_wait_for_apply(car):
    _obj, session = import_pc(car)
    text = sessions.show_text(session, car / "body.jbeam")
    broken = text.as_string().replace('"slotType": "main",', '"slotType": "main" "oops",', 1)
    text.clear()
    text.write(broken)
    problems = text_syntax.problems_of(text, text_syntax.analysis_of(text, text.as_string()))
    [(line, found)] = problems.items()
    assert '"oops"' in text.lines[line].body and "oops" in found[0].message
    assert found[0].column - 1 == text.lines[line].body.index('"oops"')


def test_plain_jbeam_texts_are_coloured_too():
    text = bpy.data.texts.new("custom.jbeam")
    text.write('{"p": {"nodes": [["id"]]}}')
    assert text_syntax.is_jbeam(text) and not text_syntax.is_jbeam(bpy.data.texts.new("script.py"))
    assert text_syntax.problems_of(text, text_syntax.analysis_of(text, text.as_string())) == {}


def test_long_texts_keep_the_last_analysis_while_typing(monkeypatch):
    monkeypatch.setattr(text_syntax, "SYNC_LIMIT", 10)
    text = bpy.data.texts.new("long.jbeam")
    text.write('{"p": {}}')
    first = text_syntax.analysis_of(text, text.as_string())
    text.write("\n// more")
    assert text_syntax.analysis_of(text, text.as_string()) is first
