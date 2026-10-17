"""Variables, slot variables and components, resolved the way the game's loader does it."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..diagnostics import VARIABLES, DiagnosticList
from ..lua import deep_copy, ipairs_keyed, is_number, length, tostring
from ..model.tables import process_table
from ..sjson import JDict, JList
from .expressions import Evaluator
from .slots import FoundParts, JournalEntry

COMPONENTS = "$components"
_MAX_SLOT_VARIABLE_PASSES = 400


@dataclass(eq=False)
class Resolver:
    diags: DiagnosticList
    evaluator: Evaluator = field(default_factory=Evaluator)

    def warn(self, where, message: str) -> None:
        self.diags.at(where, "warning", VARIABLES, message)


def resolve_string(text, variables: dict, ctx: Resolver, where, root, *, equals_only=False, allow_redirect=False):
    """Resolves one `$...` string; returns the new value and whether it was replaced."""
    if not isinstance(text, str) or not text.startswith("$"):
        return text, False
    second = text[1:2]
    if second == "=":
        return ctx.evaluator.evaluate_safe(text, variables, lambda message: ctx.warn(where, message)), True
    if equals_only:
        return text, False
    if allow_redirect and text.startswith("$>>"):
        value = _value_from_path(root, text[3:])
        if value is None:
            ctx.warn(where, f'component path not found: "{text[3:]}"')
            return None, True
        return deep_copy(value), True
    if second == ".":
        return _as_text(variables.get("$prefix")) + text[2:] + _as_text(variables.get("$suffix")), True
    if second not in ("+", "<", ">") and (allow_redirect or second != "*"):
        value = variables.get(text)
        if value is None:
            ctx.warn(where, f"missing variable {text}")
            return None, True
        if isinstance(value, dict):
            return value.get("val"), True
        return value, True
    return text, False


def _as_text(value) -> str:
    if isinstance(value, dict):
        value = value.get("val")
    if value is None:
        return ""
    return value if isinstance(value, str) else tostring(value)


def _value_from_path(root, path: str):
    keys = [key for key in path.split(".") if key]
    if not keys or keys[0] != "components":
        return None
    current = root
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def apply_variables(data, variables: dict, ctx: Resolver, *, equals_only=False, keys_only_in_variables=False) -> None:
    """Replaces `$name`, `$=expression`, `$.name` and `$>>components.path` in keys and values of `data`."""
    stack = [(data, True)]
    while stack:
        table, process_values = stack.pop()
        where = getattr(table, "src", None)
        renames = []
        items = list(enumerate(table)) if isinstance(table, list) else list(table.items())
        for key, value in items:
            if isinstance(key, str) and key.startswith("$"):
                new_key, changed = resolve_string(key, variables, ctx, where, data, equals_only=equals_only)
                if changed and new_key is not None and new_key != key and isinstance(new_key, (str, int, float)):
                    renames.append((key, new_key))
            if process_values and isinstance(value, str):
                new_value, changed = resolve_string(value, variables, ctx, where, data, equals_only=equals_only,
                                                    allow_redirect=True)
                if changed:
                    if isinstance(table, dict) and new_value is None:
                        del table[key]
                    else:
                        table[key] = new_value
            elif isinstance(value, (dict, list)):
                if key != "variables":
                    stack.append((value, process_values))
                elif keys_only_in_variables:
                    stack.append((value, False))
        for old, new in renames:
            if old in table:
                if new in table:
                    ctx.warn(where, f"key {old} resolves to the existing key {new}, which is overwritten")
                table[new] = table.pop(old)


def resolve_slot_variables(slot_variables: dict, parent: dict, ctx: Resolver, where=None) -> dict:
    """Resolves the `variables` of a slot definition against the parent part's scope, in dependency order."""
    if not parent:
        return deep_copy(slot_variables)
    scope = deep_copy(parent)
    pending = dict(slot_variables)
    resolved: dict = {}
    for _ in range(_MAX_SLOT_VARIABLE_PASSES):
        progressed = False
        for key, value in list(pending.items()):
            if isinstance(value, str) and value.startswith("$"):
                second = value[1:2]
                if second == "=":
                    try:
                        result = ctx.evaluator.evaluate(value, scope)
                    except Exception:
                        continue
                    progressed = True
                    resolved[key] = scope[key] = result
                    del pending[key]
                elif second not in ("+", "<", ">"):
                    progressed = True
                    del pending[key]
                    found = scope.get(value)
                    if found is None:
                        ctx.warn(where, f"slot variable {key}: missing variable {value}")
                        continue
                    resolved[key] = scope[key] = found.get("val") if isinstance(found, dict) else found
            else:
                progressed = True
                resolved[key] = scope[key] = value
                del pending[key]
        if not progressed:
            break
    if pending:
        ctx.warn(where, f"slot variables could not be resolved: {', '.join(map(str, pending))}")
    return resolved


def variable_rows(part: dict, ctx: Resolver) -> dict:
    rows = part.get("variables")
    if not isinstance(rows, list) or not rows:
        return {}
    return process_table(rows, None, ctx.diags, "variables") or {}


def evaluate_variable_rows(rows: dict, scope: dict, ctx: Resolver) -> dict:
    wrapper = JDict({"_v": deep_copy(rows)})
    apply_variables(wrapper, scope, ctx, equals_only=True)
    return wrapper["_v"]


def sanitize_variables(rows, user_vars: dict, ctx: Resolver, report: bool = True) -> dict:
    """Keeps valid `range` variables and sets `val` from the part config or the default, clamped to min and max."""

    def warn(where, message):
        if report:
            ctx.warn(where, message)

    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name, where = row.get("name"), getattr(row, "src", None)
        if row.get("type") != "range":
            warn(where, f"variable {name} ignored, unknown type {row.get('type')!r}")
            continue
        if row.get("unit") == "":
            del row["unit"]
        bad = next((key for key in ("min", "max", "default") if not is_number(row.get(key))), None)
        if bad is not None:
            warn(where, f"variable {name} ignored, {bad} is not a number")
            continue
        value = user_vars.get(name)
        if value is None:
            value = row["default"]
        elif not is_number(value):
            warn(where, f"variable {name}: config value {value!r} is not a number, the default is used")
            value = row["default"]
        low, high = min(row["min"], row["max"]), max(row["min"], row["max"])
        clamped = min(max(value, low), high)
        if clamped != value:
            warn(where, f"variable {name}: value {tostring(value)} clamped to [{tostring(low)}, {tostring(high)}]")
        row["val"] = clamped
        if name is not None:
            result[name] = row
    return result


def _slot_scope(entry: JournalEntry, parent_scope: dict, ctx: Resolver) -> dict:
    slot_variables = entry.slot_def.get("variables")
    resolved = resolve_slot_variables(deep_copy(slot_variables) if isinstance(slot_variables, dict) else {},
                                      parent_scope, ctx, entry.slot_def.src)
    scope = deep_copy(parent_scope)
    scope.update(resolved)
    return scope


def collect_variables(found: FoundParts, user_vars: dict, ctx: Resolver) -> dict:
    """All variables of the chosen parts, each part evaluated in its own slot scope."""
    root = found.root
    root_rows = evaluate_variable_rows(variable_rows(root, ctx), {}, ctx)
    root_scope = sanitize_variables(deep_copy(list(root_rows.values())), user_vars, ctx, report=False)
    root_scope[COMPONENTS] = {"val": root.get("components")}
    scopes = {id(root): root_scope}
    all_rows = list(root_rows.values())
    positions: dict = {}
    for entry in reversed(found.journal):
        scope = _slot_scope(entry, scopes.get(id(entry.parent), root_scope), ctx)
        rows = variable_rows(entry.part, ctx)
        if length(rows) > 0:
            evaluated = evaluate_variable_rows(rows, scope, ctx)
            for row in ipairs_keyed(evaluated):
                name = row.get("name") if isinstance(row, dict) else None
                if name in positions:
                    all_rows[positions[name]] = row
                elif name is not None:
                    positions[name] = len(all_rows)
                    all_rows.append(row)
            scope.update(sanitize_variables(deep_copy(list(evaluated.values())), user_vars, ctx, report=False))
        scopes[id(entry.part)] = scope
    return sanitize_variables(all_rows, user_vars, ctx)


def _pairs(table):
    return enumerate(table, start=1) if isinstance(table, list) else list(table.items())


def _get(table, key):
    if isinstance(table, list):
        return table[key - 1] if isinstance(key, int) and 1 <= key <= len(table) else None
    return table.get(key)


def _set(table, key, value) -> None:
    if isinstance(table, dict):
        table[key] = value
    elif isinstance(key, int) and key >= 1:
        while len(table) < key:
            table.append(None)
        table[key - 1] = value


def _is_array(table) -> bool:
    return isinstance(table, list) or (isinstance(table, dict) and not table)


def merge_recursive_array(target, source):
    """Lua `tableMergeRecursiveArray`: nested lists are concatenated, nested objects merged, values overwritten."""
    for key, value in _pairs(source):
        current = _get(target, key)
        if isinstance(value, (dict, list)) and isinstance(current, (dict, list)):
            if _is_array(current) and _is_array(value):
                if isinstance(current, list):
                    current.extend(value if isinstance(value, list) else [])
                else:
                    _set(target, key, JList(value if isinstance(value, list) else []))
            else:
                merge_recursive_array(current, value)
        elif isinstance(value, (dict, list)):
            _set(target, key, JList(value) if _is_array(value) else merge_recursive_array(JDict(), value))
        else:
            _set(target, key, value)
    return target


def process_components(found: FoundParts, variables: dict, ctx: Resolver) -> None:
    """Collects the `components` sections of all parts into the root part, parents first."""
    root = found.root
    components = root.get("components")
    if not isinstance(components, dict):
        components = JDict()
        root["components"] = components
    variables[COMPONENTS] = {"val": components}
    scopes = {id(root): deep_copy(variables)}
    for entry in found.journal_c:
        scope = _slot_scope(entry, scopes[id(entry.parent)], ctx)
        scope[COMPONENTS] = {"val": components}
        scopes[id(entry.part)] = scope
        if "components" not in entry.part:
            continue
        part_components = entry.part.pop("components")
        if not isinstance(part_components, dict):
            continue
        for key, value in part_components.items():
            if isinstance(value, (dict, list)):
                if not isinstance(components.get(key), (dict, list)):
                    components[key] = JDict()
                apply_variables(value, scope, ctx, keys_only_in_variables=True)
                merge_recursive_array(components[key], value)
            else:
                components[key] = value


def process_parts(found: FoundParts, variables: dict, ctx: Resolver) -> None:
    """Applies variables to every chosen part and its slot options, parents first."""
    root = found.root
    components = root.get("components")
    variables[COMPONENTS] = {"val": components}
    scopes = {id(root): variables}
    if isinstance(components, (dict, list)):
        apply_variables(components, variables, ctx)
    saved = root.pop("components", None)
    apply_variables(root, variables, ctx)
    if saved is not None:
        root["components"] = saved
    for entry in reversed(found.journal):
        scope = _slot_scope(entry, scopes[id(entry.parent)], ctx)
        scopes[id(entry.part)] = scope
        apply_variables(entry.slot_options, scope, ctx)
        apply_variables(entry.part, scope, ctx)


def apply_standalone(part: JDict, ctx: Resolver) -> dict:
    """Variables of a single part with their defaults applied to it, for importing one part without a config."""
    rows = evaluate_variable_rows(variable_rows(part, ctx), {}, ctx)
    variables = sanitize_variables(deep_copy(list(rows.values())), {}, ctx)
    components = part.get("components")
    variables[COMPONENTS] = {"val": components}
    if isinstance(components, (dict, list)):
        apply_variables(components, variables, ctx)
    saved = part.pop("components", None)
    apply_variables(part, variables, ctx)
    if saved is not None:
        part["components"] = saved
    return variables
