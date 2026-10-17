from __future__ import annotations

from dataclasses import dataclass, field

from ..diagnostics import SLOTS, DiagnosticList
from ..lua import deep_copy
from ..sjson import JDict
from .config import VehicleConfig
from .index import PartDef, PartIndex

MAX_DEPTH = 50
_SLOT_DEFINITION_KEYS = ("name", "type", "allowTypes", "denyTypes", "default", "description")


@dataclass(eq=False)
class SlotNode:
    id: str
    path: str
    description: str = ""
    chosen_part: str = ""
    decision: str = ""
    part_path: str | None = None
    children: dict[str, SlotNode] = field(default_factory=dict)
    slot_def: JDict | None = None


@dataclass(eq=False)
class JournalEntry:
    parent: JDict
    part: JDict
    level: int
    slot_options: JDict
    part_path: str
    slot_def: JDict
    part_def: PartDef


@dataclass(eq=False)
class FoundParts:
    root: JDict
    root_def: PartDef
    tree: SlotNode
    journal: list[JournalEntry] = field(default_factory=list)
    """Children before their parents: the order in which parts are merged."""
    journal_c: list[JournalEntry] = field(default_factory=list)
    """Parents before their children: the order in which components are collected."""
    active_parts: dict[str, str] = field(default_factory=dict)


def part_fits_slot(part: PartDef, slot_def) -> tuple[bool, str | None]:
    allow = slot_def.get("allowTypes")
    if allow is None:
        return False, "invalid slot configuration"
    allow = allow if isinstance(allow, list) else []
    deny = slot_def.get("denyTypes")
    deny = deny if isinstance(deny, list) else []
    slot_type = part.data.get("slotType")
    if isinstance(slot_type, str):
        fits = slot_type in allow
        return fits, None if fits else "part type not in allowed types"
    if isinstance(slot_type, list):
        if not any(t in allow for t in slot_type):
            return False, "no matching allowed types"
        if any(t in deny for t in slot_type):
            return False, "part type is in the deny list"
        return True, None
    return False, "invalid slot configuration"


def find_parts(index: PartIndex, config: VehicleConfig, diags: DiagnosticList) -> FoundParts | None:
    """Fills the slot tree from the part config like the game's slot system."""
    main_name = config.main_part_name or index.main_part_name()
    root_def = index.get(main_name)
    if root_def is None:
        diags.add("error", SLOTS, f'main part "{main_name}" not found' if main_name else "no part with slotType \"main\" found")
        return None
    root = deep_copy(root_def.data)
    slot_type = root.get("slotType")
    tree = SlotNode(id=slot_type if isinstance(slot_type, str) else "main", path="/", chosen_part=root_def.name,
                    decision="main", part_path="/" + root_def.name)
    found = FoundParts(root, root_def, tree, active_parts={"/" + root_def.name: root_def.name})
    if root.get("slots2"):
        _fill(index, config, found, root, 1, None, tree.children, "/", diags)
    return found


def _fill(index, config, found, current_part, level, parent_options, out, path, diags):
    if level > MAX_DEPTH:
        diags.add("error", SLOTS, f"more than {MAX_DEPTH} slot levels below {path}; check for cycles")
        return
    for slot_def in current_part.get("slots2") or []:
        if not isinstance(slot_def, dict):
            continue
        slot_id = slot_def.get("name") or slot_def.get("type")
        if not isinstance(slot_id, str):
            continue
        options = deep_copy(parent_options) if parent_options is not None else JDict(src=slot_def.src)
        options.update(deep_copy(slot_def))
        for key in _SLOT_DEFINITION_KEYS:
            options.pop(key, None)
        new_path = path + slot_id + "/"
        description = slot_def.get("description")
        node = SlotNode(id=slot_id, path=new_path, description=description if isinstance(description, str) else slot_id,
                        slot_def=slot_def)
        out[slot_id] = node

        desired = config.parts.get(slot_id)
        user = "" if desired == "none" else desired
        if user is None:
            user = config.parts.get(new_path)
        if user == "":
            node.decision = "user-empty"
            continue

        chosen = None
        default = slot_def.get("default")
        if user is not None:
            chosen = index.get(user)
            if chosen is not None:
                fits, reason = part_fits_slot(chosen, slot_def)
                if not fits:
                    diags.at(slot_def.src, "warning", SLOTS,
                             f'slot "{slot_id}": part "{user}" does not fit ({reason}); using the default part')
                    chosen = None
                node.decision = "user"
            else:
                diags.at(slot_def.src, "warning", SLOTS,
                         f'slot "{slot_id}": part "{user}" not found; using the default part "{default or ""}"')
        if default is not None and chosen is None:
            if default == "":
                node.decision = "default-empty"
                continue
            node.decision = "default"
            chosen = index.get(default)

        if chosen is None:
            if user:
                diags.at(slot_def.src, "warning", SLOTS, f'slot "{slot_id}" left empty: part "{user}" not found')
            elif default:
                diags.at(slot_def.src, "warning", SLOTS, f'slot "{slot_id}": default part "{default}" not found')
            continue

        part_path = new_path + chosen.name
        if options.get("coreSlot") is True:
            del options["coreSlot"]
        options.pop("variables", None)
        node.chosen_part = chosen.name
        node.part_path = part_path
        found.active_parts[part_path] = chosen.name
        part = deep_copy(chosen.data)
        entry = JournalEntry(current_part, part, level, options, part_path, slot_def, chosen)
        found.journal_c.append(entry)
        if part.get("slots2"):
            _fill(index, config, found, part, level + 1, options, node.children, new_path, diags)
        found.journal.append(entry)
