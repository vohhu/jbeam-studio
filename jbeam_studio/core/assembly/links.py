from __future__ import annotations

import re

from ..diagnostics import REFERENCES, DiagnosticList
from ..lua import ipairs, truthy

OPTIONAL_LINKS = frozenset({
    "torqueArm:", "torqueArm2:", "torqueCoupling:", "torqueCouple:", "nodeArm:", "nodeCoupling:", "nodeCouple:",
    "torqueJointNode1:", "torqueJointNode2:",
})
SECTION_RENAMES = {"triggers2": "triggers", "rails2": "rails"}
_GROUP_LINK = re.compile(r"\[.*\]")


def link_target(key) -> str | None:
    """Section a `name:section` key points to, `nodes` for a bare `name:`; None for keys that are not links."""
    if not isinstance(key, str) or key.count(":") != 1:
        return None
    name, _, section = key.partition(":")
    if _GROUP_LINK.search(name):
        return None
    section = section or "nodes"
    return SECTION_RENAMES.get(section, section)


def _exists(section: dict, key) -> bool:
    try:
        return key in section
    except TypeError:
        return False


def drop_broken_links(vehicle: dict, diags: DiagnosticList) -> None:
    """Removes rows that reference missing entries, like the game does before it builds the physics."""
    for section_name, section in list(vehicle.items()):
        if not isinstance(section, dict):
            continue
        for row_key, row in list(section.items()):
            if not isinstance(row, (dict, list)):
                continue
            if isinstance(row_key, str) and ":" in row_key:
                if not isinstance(row, list):
                    continue
                target_section = row_key.split(":", 1)[1] or "nodes"
                target_name = SECTION_RENAMES.get(target_section, target_section)
                target = vehicle.get(target_name)
                if not isinstance(target, dict):
                    diags.at(getattr(row, "src", None), "warning", REFERENCES,
                             f'{section_name}/{row_key}: section "{target_name}" does not exist')
                    continue
                missing = next((value for value in ipairs(row) if not _exists(target, value)), None)
                if missing is not None:
                    diags.at(getattr(row, "src", None), "warning", REFERENCES,
                             f'{section_name}/{row_key}: "{missing}" not found in "{target_name}"')
                section[f"{row_key.split(':', 1)[0]}_{target_name}"] = section.pop(row_key)
                continue
            if not isinstance(row, dict):
                continue
            for cell_key, cell_value in list(row.items()):
                target_name = link_target(cell_key)
                if target_name is None:
                    continue
                target = vehicle.get(target_name)
                if not isinstance(target, dict):
                    diags.at(getattr(row, "src", None), "warning", REFERENCES,
                             f'{section_name}: link "{cell_key}" points to the missing section "{target_name}"')
                    continue
                if isinstance(cell_value, list):
                    missing = next((value for value in ipairs(cell_value) if not _exists(target, value)), None)
                    if missing is None:
                        continue
                elif _exists(target, cell_value) or cell_key in OPTIONAL_LINKS:
                    continue
                else:
                    missing = cell_value
                if not truthy(row.get("optional")):
                    src = getattr(row, "src", None)
                    diags.at(src, "warning", REFERENCES,
                             f'{section_name}: "{missing}" not found in "{target_name}" ({cell_key}), row discarded',
                             fix=("mark_optional", src.node.start) if src is not None else ())
                del section[row_key]
                break
