from jbeam_studio.core.assembly.variables import (
    Resolver, apply_variables, merge_recursive_array, resolve_slot_variables, sanitize_variables,
)
from jbeam_studio.core.diagnostics import DiagnosticList
from jbeam_studio.core.sjson import JDict, JList


def ctx():
    return Resolver(DiagnosticList())


def test_apply_replaces_values_and_keys():
    data = JDict({"a": "$x", "$side": 1, "list": JList(["$=$x * 2", "$missing", 3]), "variables": JDict({"v": "$x"})})
    resolver = ctx()
    apply_variables(data, {"$x": {"val": 5}, "$side": "left"}, resolver)
    assert data == {"a": 5, "left": 1, "list": [10, None, 3], "variables": {"v": "$x"}}
    assert any("missing variable $missing" in d.message for d in resolver.diags)


def test_missing_variable_removes_dict_value():
    data = JDict({"a": "$nope"})
    apply_variables(data, {}, ctx())
    assert data == {}


def test_equals_only_keeps_plain_references():
    data = JDict({"a": "$x", "b": "$=1+1"})
    apply_variables(data, {"$x": 3}, ctx(), equals_only=True)
    assert data == {"a": "$x", "b": 2}


def test_prefix_and_suffix():
    data = JDict({"n": "$.node"})
    apply_variables(data, {"$prefix": "l_", "$suffix": "_1"}, ctx())
    assert data == {"n": "l_node_1"}


def test_merge_keys_are_not_variables():
    data = JDict({"$+beamSpring": 10, "$<x": 1})
    apply_variables(data, {}, ctx())
    assert data == {"$+beamSpring": 10, "$<x": 1}


def test_component_redirect():
    data = JDict({"components": JDict({"engine": JDict({"bore": 0.1})}), "value": "$>>components.engine.bore"})
    apply_variables(data, {}, ctx())
    assert data["value"] == 0.1


def test_slot_variables_resolve_in_any_order():
    resolved = resolve_slot_variables({"$a": "$=$b * 2", "$b": 3, "$c": "$parent"}, {"$parent": {"val": 7}}, ctx())
    assert resolved == {"$b": 3, "$a": 6, "$c": 7}


def test_sanitize_clamps_and_ignores_bad_rows():
    resolver = ctx()
    rows = [
        JDict({"name": "$h", "type": "range", "default": 0, "min": -1, "max": 1}),
        JDict({"name": "$bad", "type": "range", "default": "x", "min": 0, "max": 1}),
        JDict({"name": "$s", "type": "string"}),
    ]
    result = sanitize_variables(rows, {"$h": 5}, resolver)
    assert list(result) == ["$h"]
    assert result["$h"]["val"] == 1
    assert len(resolver.diags.warnings()) == 3


def test_merge_recursive_array():
    target = JDict({"a": JDict({"list": JList([1]), "x": 1})})
    merge_recursive_array(target, JDict({"a": JDict({"list": JList([2]), "y": 2}), "b": 3}))
    assert target == {"a": {"list": [1, 2], "x": 1, "y": 2}, "b": 3}
