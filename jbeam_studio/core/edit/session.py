"""Editing an assembled vehicle: operations on nodes, beams and faces that change only the affected text."""

from __future__ import annotations

import contextlib
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from ..assembly import AssembledVehicle, BeamEntry, ExtraEntry, FaceEntry, NodeEntry, assemble_part, assemble_pc
from ..assembly.positions import raw_position_for
from ..diagnostics import DiagnosticList
from ..model.files import encode_text, load_source_file, read_text
from ..sjson import Document, Kind, Node, parse
from .references import (
    Location, header_of, link_variables, location, node_references, part_object, section_node, string_values,
)
from .text import (
    DEFAULT_DECIMALS, TextEdit, TextEditError, apply_edits, delete_member, delete_value, format_number, format_row,
    insert_into, insert_member, insert_object_section, insert_rows, insert_section, insert_values, json_literal,
    literal_decimals, modifier_text, outside_target, replace_value, shift_expression,
)
from ..model.modifiers import DEFAULT_RESETS, leaks
from ..model.tables import replace_special_values

POSITION_KEYS = ("posX", "posY", "posZ")
DEFAULT_HEADERS = {
    "nodes": ["id", "posX", "posY", "posZ"],
    "beams": ["id1:", "id2:"],
    "triangles": ["id1:", "id2:", "id3:"],
    "quads": ["id1:", "id2:", "id3:", "id4:"],
    "hydros": ["id1:", "id2:"],
    "torsionbars": ["id1:", "id2:", "id3:", "id4:"],
    "slidenodes": ["id:", "railName", "attached", "fixToRail", "tolerance", "spring", "strength", "capStrength"],
}
EXTRA_COLUMNS = {
    "hydros": ("id1:", "id2:"),
    "torsionbars": ("id1:", "id2:", "id3:", "id4:"),
    "slidenodes": ("id:", "railName"),
}
"""The columns new rows of these sections fill: the nodes, and the rail of a slide node."""
ROW_OPTIONS = "\0options"
"""Key of the cell texts of a new row that holds the text of its options object, written after the columns."""
ENTRY_SECTIONS = ("nodes", "beams", "triangles", "quads")
# Coordinates are rounded to DEFAULT_DECIMALS before modifiers apply; a rotation can combine the rounding of
# all three axes into one.
POSITION_TOLERANCE = math.sqrt(3) * 0.5 * 10 ** -DEFAULT_DECIMALS + 1e-9


class MoveMode(str, Enum):
    OVERWRITE = "overwrite"
    """Write plain numbers so that the node ends up where it was placed."""
    KEEP_EXPRESSIONS = "keep_expressions"
    """Add the shift to the existing number, variable or expression."""


class EditError(Exception):
    pass


class DependentsError(EditError):
    def __init__(self, message: str, dependents: list):
        super().__init__(message)
        self.dependents = dependents


class SharedRowError(EditError):
    """The row also defines other entries, because its part is used in several slots."""

    def __init__(self, message: str, users: list[str]):
        super().__init__(message)
        self.users = users


class TemplateIdError(EditError):
    """The node's id is built from slot variables such as `$.a`, so it cannot be renamed as a value."""


class UnreachablePositionError(EditError):
    """The node's modifiers cannot put it at the requested position."""


class ExternalChangeError(EditError):
    def __init__(self, paths: list[Path]):
        super().__init__("changed on disk since loading: " + ", ".join(p.name for p in paths))
        self.paths = paths


@dataclass(frozen=True)
class NewBlock:
    """Rows placed at the end of a table between {key: value} and {key: reset}, such as a new node group."""

    key: str
    value: object
    reset: object = ""


def _item_of(table: Node, anchor: Node) -> Node | None:
    for item in table.items:
        if item is anchor or (item.start == anchor.start and item.end == anchor.end):
            return item
    return None


@dataclass
class Change:
    description: str
    before: dict[Path, str]
    after: dict[Path, str]


@dataclass
class RenameResult:
    references: list[Location] = field(default_factory=list)
    """Node references renamed with the node, located in the text before the rename."""
    other_matches: list[Location] = field(default_factory=list)
    """Strings equal to the old id that are not node references, and references in parts not in the vehicle,
    located in the current text: before the rename for a preview, after it for a rename."""


def _label(entry) -> str:
    if isinstance(entry, NodeEntry):
        return entry.id
    if isinstance(entry, BeamEntry):
        return f"{entry.id1}-{entry.id2}"
    return "-".join(entry.ids)


def _row_key(entry):
    return (entry.src.file, entry.src.node.start) if entry.src is not None else None


def _columns(entry) -> tuple:
    columns = getattr(entry.props, "columns", None)
    if columns is None:
        raise EditError("this entry does not come from a table row")
    return columns


def _counts(vehicle: AssembledVehicle) -> dict[str, int]:
    counts = {name: len(section) for name, section in vehicle.data.items()
              if isinstance(section, dict) and name not in ENTRY_SECTIONS and name != "options"}
    counts.update(nodes=len(vehicle.nodes), beams=len(vehicle.beams), triangles=len(vehicle.triangles),
                  quads=len(vehicle.quads))
    return counts


class EditSession:
    """Edits of one vehicle or part, kept in memory until saved. Every operation is one undoable change.

    The session reads every file once and then works on that text, so edits never mix with changes made to
    the files outside; such changes are reported by `changed_on_disk` and taken in with `reload_file`.
    """

    def __init__(self, assemble: Callable[[Mapping[Path, str], bool], AssembledVehicle], *,
                 move_mode: MoveMode = MoveMode.OVERWRITE):
        self._assemble_with = assemble
        self.move_mode = move_mode
        self.texts: dict[Path, str] = {}
        """Edited text of files that differ from their base."""
        self._base: dict[Path, str] = {}
        self._base_stat: dict[Path, tuple[int, int] | None] = {}
        self._backed_up: set[Path] = set()
        self.history: list[Change] = []
        self.position = 0
        self._transaction: Change | None = None
        self.notes = DiagnosticList()
        """Information about the last operation, such as expressions replaced by numbers."""
        self._users: dict = {}
        self._users_for: AssembledVehicle | None = None
        self._link_variables: set[str] = set()
        self._link_variables_for: AssembledVehicle | None = None
        self.vehicle = self._assemble(discover=True)

    @classmethod
    def for_pc(cls, pc_path: Path, *, move_mode: MoveMode = MoveMode.OVERWRITE, **assembly) -> EditSession:
        return cls(lambda texts, closed: assemble_pc(pc_path, overrides=texts, closed=closed, **assembly),
                   move_mode=move_mode)

    @classmethod
    def for_part(cls, jbeam_path: Path, part_name: str, *, move_mode: MoveMode = MoveMode.OVERWRITE,
                 **assembly) -> EditSession:
        return cls(lambda texts, closed: assemble_part(jbeam_path, part_name, overrides=texts, closed=closed,
                                                       **assembly), move_mode=move_mode)

    # files

    def _assemble(self, texts: Mapping[Path, str] | None = None, *, discover: bool = False) -> AssembledVehicle:
        """Assembles from the session's texts; only `discover` lets the assembly find files not read yet."""
        vehicle = self._assemble_with({**self._base, **(self.texts if texts is None else texts)},
                                      not discover and bool(self._base))
        for path, source in vehicle.files.items():
            if path not in self._base:
                self._base[path] = source.doc.text
                self._base_stat[path] = (source.mtime_ns, source.size) if source.mtime_ns >= 0 else None
        return vehicle

    @staticmethod
    def _stat(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def text_of(self, path: Path) -> str:
        path = Path(path).absolute()
        if path in self.texts:
            return self.texts[path]
        if path in self._base:
            return self._base[path]
        return load_source_file(path).doc.text

    def dirty_files(self) -> list[Path]:
        return [p for p, text in self.texts.items() if text != self._base.get(p)]

    def knows(self, path: Path) -> bool:
        """Whether the session read the file."""
        return Path(path).absolute() in self._base

    def base_text(self, path: Path) -> str | None:
        """The text of the file as read or last saved."""
        return self._base.get(Path(path).absolute())

    def accept_disk(self, path: Path) -> bool:
        """Takes the file on disk as the saved state of a file whose text in the session is the same, as after
        another session saved the same edits. Returns whether it did."""
        path = Path(path).absolute()
        if path not in self._base:
            return False
        text = self.text_of(path)
        try:
            if read_text(path) != text:
                return False
        except OSError:
            return False
        self._base[path] = text
        self._base_stat[path] = self._stat(path)
        self.texts.pop(path, None)
        return True

    def changed_on_disk(self, paths: Iterable[Path] | None = None) -> list[Path]:
        """Files whose content on disk differs from the text the session read (or last saved)."""
        changed = []
        for path in (paths if paths is not None else list(self._base)):
            path = Path(path).absolute()
            if path not in self._base:
                continue
            stat = self._stat(path)
            if stat is not None and stat == self._base_stat.get(path):
                continue
            if stat is None or read_text(path) != self._base[path]:
                changed.append(path)
        return changed

    def files_added_on_disk(self) -> list[Path]:
        """JBeam files in the vehicle's folders that appeared after the session read them; `rescan` takes them in."""
        index = self.vehicle.index
        if index is None:
            return []
        return [p for d in index.directories if d.is_dir() for p in sorted(d.rglob("*.jbeam"))
                if p.absolute() not in self._base]

    def rescan(self) -> None:
        """Takes in JBeam files added on disk since the session started; the undo history is cleared."""
        self.history.clear()
        self.position = 0
        self.vehicle = self._assemble(discover=True)

    def reload_file(self, path: Path) -> None:
        """Takes in the file as it is on disk, dropping its edits; the undo history is cleared."""
        path = Path(path).absolute()
        try:
            text = read_text(path)
        except OSError as error:
            raise EditError(f"{path.name} cannot be read: {error.strerror or error}") from error
        stat = self._stat(path)
        self.texts.pop(path, None)
        self._base[path] = text
        self._base_stat[path] = stat
        self.history.clear()
        self.position = 0
        self.vehicle = self._assemble()

    def save(self, paths: Iterable[Path] | None = None, *, overwrite_external: bool = False) -> list[Path]:
        """Writes edited files; the first save of a file keeps the original next to it as `<name>.bak`.

        All files are written to temporary files first and only then moved into place.
        """
        targets = [Path(p).absolute() for p in paths] if paths is not None else self.dirty_files()
        targets = [p for p in targets if p in self.texts and self.texts[p] != self._base.get(p)]
        changed = self.changed_on_disk(targets)
        if changed and not overwrite_external:
            raise ExternalChangeError(changed)
        temporaries: dict[Path, Path] = {}
        try:
            for path in targets:
                temporary = path.with_name(path.name + ".jbs-tmp")
                with open(temporary, "wb") as handle:
                    handle.write(encode_text(self.texts[path]))
                    handle.flush()
                    os.fsync(handle.fileno())
                temporaries[path] = temporary
            for path in targets:
                backup = path.with_name(path.name + ".bak")
                if path not in self._backed_up and not backup.exists() and path.exists():
                    backup.write_bytes(path.read_bytes())
                self._backed_up.add(path)
                os.replace(temporaries[path], path)
                del temporaries[path]
                self._base[path] = self.texts.pop(path)
                self._base_stat[path] = self._stat(path)
        finally:
            for temporary in temporaries.values():
                with contextlib.suppress(OSError):
                    temporary.unlink()
        return targets

    # history

    @property
    def can_undo(self) -> bool:
        return self.position > 0

    @property
    def can_redo(self) -> bool:
        return self.position < len(self.history)

    def undo(self) -> None:
        if not self.can_undo:
            raise EditError("nothing to undo")
        self._restore(self.history[self.position - 1].before)
        self.position -= 1

    def redo(self) -> None:
        if not self.can_redo:
            raise EditError("nothing to redo")
        self._restore(self.history[self.position].after)
        self.position += 1

    def goto(self, position: int, vehicle: AssembledVehicle | None = None) -> None:
        """Undoes or redoes changes until the history is at `position`, assembling the vehicle once.

        `vehicle` is the vehicle assembled earlier from the texts at `position`; it is used instead of assembling.
        """
        if not 0 <= position <= len(self.history):
            raise EditError(f"history position {position} does not exist")
        texts: dict[Path, str] = {}
        target = self.position
        while target > position:
            texts.update(self.history[target - 1].before)
            target -= 1
        while target < position:
            texts.update(self.history[target].after)
            target += 1
        if texts:
            if vehicle is None:
                self._restore(texts)
            else:
                for path, text in texts.items():
                    self._set_text(path, text)
                self.vehicle = vehicle
        self.position = position

    @contextlib.contextmanager
    def transaction(self, description: str):
        """Groups several operations into one change; on an error all of them are rolled back."""
        if self._transaction is not None:
            yield
            return
        self._transaction = Change(description, {}, {})
        snapshot = dict(self.texts), self.vehicle
        try:
            yield
        except BaseException:
            self.texts, self.vehicle = snapshot
            self._transaction = None
            raise
        change, self._transaction = self._transaction, None
        if change.after:
            self._push(change)

    def _set_text(self, path: Path, text: str) -> None:
        if text == self._base.get(path):
            self.texts.pop(path, None)
        else:
            self.texts[path] = text

    def _restore(self, texts: Mapping[Path, str]) -> None:
        for path, text in texts.items():
            self._set_text(path, text)
        self.vehicle = self._assemble()

    def _push(self, change: Change) -> None:
        del self.history[self.position:]
        self.history.append(change)
        self.position += 1

    # applying edits

    def _row(self, entry) -> tuple[Path, Document, Node]:
        src = entry.src
        if src is None or src.node.kind is not Kind.ARRAY:
            raise EditError("this entry does not come from a table row")
        path = Path(src.file)
        if src.doc.text is not self.text_of(path) and src.doc.text != self.text_of(path):
            raise EditError(f"{path.name} changed since this entry was read; assemble the vehicle again")
        return path, src.doc, src.node

    def _candidate(self, edits: Mapping[Path, list[TextEdit]], texts: Mapping[Path, str] | None = None) -> dict[Path, str]:
        result = {}
        for path, path_edits in edits.items():
            if not path_edits:
                continue
            old = texts[path] if texts is not None and path in texts else self.text_of(path)
            try:
                new = apply_edits(old, path_edits)
            except TextEditError as error:
                raise EditError(str(error)) from error
            for edit in path_edits:
                problem = outside_target(old, edit)
                if problem:
                    raise EditError(f"{path.name}: {problem}")
            result[path] = new
        return result

    def _try(self, new_texts: Mapping[Path, str]) -> AssembledVehicle:
        for path, text in new_texts.items():
            doc = parse(text, str(path))
            if doc.root is None:
                raise EditError(f"the edit would break {path.name}: {doc.diagnostics.errors()[0].message}")
        return self._assemble({**self.texts, **new_texts})

    def _commit(self, description: str, new_texts: Mapping[Path, str], vehicle: AssembledVehicle,
                verify: Callable[[AssembledVehicle], str | None] | None = None,
                expected: Mapping[str, int] | None = None, shrinking: bool = False) -> None:
        """Takes the change after checking it. `expected` lists the changes of section sizes the operation causes;
        every other section must keep its size, or may only shrink if `shrinking` is set."""
        if expected is not None:
            before, after = _counts(self.vehicle), _counts(vehicle)
            for name in before.keys() | after.keys():
                delta = after.get(name, 0) - before.get(name, 0)
                wanted = expected.get(name, 0)
                if delta != wanted and not (shrinking and name not in expected and delta < 0):
                    raise EditError(f'{description}: section "{name}" changed by {delta:+d} instead of {wanted:+d}; '
                                    f"the change was not applied")
            lost = [name for name in before if name not in expected and after.get(name, 0) < before[name]]
            if lost:
                self.notes.add("info", "edit", f"rows of {', '.join(lost)} referenced the deleted nodes and are now "
                                               f"discarded by the game")
        problem = verify(vehicle) if verify else None
        if problem:
            raise EditError(f"{description}: {problem}; the change was not applied")
        before_texts = {p: self.text_of(p) for p in new_texts}
        for path, text in new_texts.items():
            self._set_text(path, text)
        self.vehicle = vehicle
        after_texts = dict(new_texts)
        if self._transaction is not None:
            for path, text in before_texts.items():
                self._transaction.before.setdefault(path, text)
            self._transaction.after.update(after_texts)
        else:
            self._push(Change(description, before_texts, after_texts))

    def _apply(self, description: str, edits: Mapping[Path, list[TextEdit]],
               verify: Callable[[AssembledVehicle], str | None] | None = None,
               expected: Mapping[str, int] | None = None, shrinking: bool = False) -> AssembledVehicle:
        self.notes = DiagnosticList()
        new_texts = self._candidate(edits)
        if not new_texts:
            return self.vehicle
        vehicle = self._try(new_texts)
        self._commit(description, new_texts, vehicle, verify, expected, shrinking)
        return vehicle

    def restore(self, texts: Mapping[Path, str], vehicle: AssembledVehicle | None = None,
                description: str = "Restore an earlier state") -> None:
        """Sets files to texts of an earlier state as one change; `vehicle`, if given, was assembled from them."""
        self.notes = DiagnosticList()
        new_texts = {Path(p): t for p, t in texts.items() if t != self.text_of(Path(p))}
        if new_texts:
            self._commit(description, new_texts, vehicle if vehicle is not None else self._try(new_texts))

    def replace_text(self, path: Path, text: str) -> None:
        """Replaces a whole file, for edits made in a text editor."""
        self.notes = DiagnosticList()
        path = Path(path).absolute()
        new_texts = {path: text}
        self._commit(f"Edit {path.name}", new_texts, self._try(new_texts))

    # shared rows

    def _row_entries(self, entry) -> list[tuple[str, str]]:
        if self._users_for is not self.vehicle:
            users: dict = defaultdict(list)
            vehicle = self.vehicle
            for section, items in (("nodes", vehicle.nodes.values()), ("beams", vehicle.beams),
                                   ("triangles", vehicle.triangles), ("quads", vehicle.quads)):
                for item in items:
                    users[_row_key(item)].append((section, _label(item)))
            for extra in vehicle.extras:
                users[_row_key(extra)].append((extra.section, _label(extra)))
            self._users, self._users_for = users, vehicle
        return self._users.get(_row_key(entry), [])

    def row_users(self, entry) -> list[str]:
        """Everything defined by the row of `entry`: more than one when its part is used in several slots."""
        return [label for _, label in self._row_entries(entry)]

    def _removed_by(self, entries: Iterable) -> dict[str, int]:
        """How many entries of each section disappear when the rows of `entries` are deleted."""
        counts: dict[str, int] = defaultdict(int)
        for entry in {_row_key(e): e for e in entries}.values():
            for section, _ in self._row_entries(entry):
                counts[section] -= 1
        return dict(counts)

    def _link_variables_in_vehicle(self) -> set[str]:
        if self._link_variables_for is not self.vehicle:
            objects = [part_object(part.file.doc, name) for name, part in self.vehicle.parts.items()]
            self._link_variables = link_variables(o for o in objects if o is not None)
            self._link_variables_for = self.vehicle
        return self._link_variables

    def part_slots(self, part_name: str) -> list[str]:
        """Slot paths that hold a part; more than one when the part is used in several slots."""
        tree = self.vehicle.slot_tree
        if tree is None:
            return ["/"] if part_name in self.vehicle.parts else []
        found = []
        stack = [tree]
        while stack:
            node = stack.pop()
            if node.chosen_part == part_name:
                found.append(node.path)
            stack.extend(node.children.values())
        return sorted(found)

    def _check_part_shared(self, part_name: str, allow_shared: bool) -> None:
        slots = self.part_slots(part_name)
        if len(slots) > 1 and not allow_shared:
            raise SharedRowError(f'part "{part_name}" is used in {len(slots)} slots, so a new row appears in every one '
                                 f"of them", slots)

    def _check_shared(self, entries: Iterable, allow_shared: bool) -> None:
        if allow_shared:
            return
        for entry in entries:
            users = self.row_users(entry)
            if len(users) > 1:
                others = ", ".join(u for u in users if u != _label(entry))
                raise SharedRowError(f"the row of {_label(entry)} also defines {others}: its part is used in several "
                                     f"slots, so editing the row changes all of them", users)

    # nodes

    def _own_node(self, node_id: str) -> NodeEntry:
        node = self.vehicle.nodes.get(node_id)
        if node is None:
            if node_id in self.vehicle.external_nodes:
                raise EditError(f'node "{node_id}" belongs to another part and cannot be edited here')
            raise EditError(f'node "{node_id}" not found')
        return node

    def _definition_rows(self, node: NodeEntry) -> list[tuple[Path, Document, Node, Node | None]]:
        """The node's own row and every other row of the vehicle's parts that defines the same id."""
        path, doc, row = self._row(node)
        columns = _columns(node)
        index = columns.index("id") if "id" in columns else -1
        rows = {(path, row.start): (path, doc, row, row.items[index] if 0 <= index < len(row.items) else None)}
        for part_name, part in self.vehicle.parts.items():
            part_doc = part.file.doc
            obj = part_object(part_doc, part_name)
            table = section_node(obj, "nodes") if obj is not None else None
            header = header_of(table) if table is not None else None
            if not header or "id" not in header:
                continue
            column = header.index("id")
            for item in table.items[1:]:
                if item.kind is Kind.ARRAY and column < len(item.items) and item.items[column].value == node.id:
                    key = (Path(part_doc.path), item.start)
                    rows.setdefault(key, (Path(part_doc.path), part_doc, item, item.items[column]))
        return list(rows.values())

    def new_node_id(self, prefix: str = "n") -> str:
        taken = self.vehicle.nodes.keys() | self.vehicle.external_nodes.keys()
        number = 1
        while f"{prefix}{number}" in taken:
            number += 1
        return f"{prefix}{number}"

    def _position_edits(self, node: NodeEntry, target, notes: list[str]) -> tuple[Path, list[TextEdit]]:
        path, doc, row = self._row(node)
        columns = _columns(node)
        raw = raw_position_for(node.props, target)
        if raw is None:
            raise UnreachablePositionError(
                f'node "{node.id}" cannot be placed at X = {target[0]:.3f}: its nodeOffset on X keeps it at least that '
                f"far from the center line")
        edits = []
        for axis, key in enumerate(POSITION_KEYS):
            current = node.props[key]
            if abs(raw[axis] - current) < 1e-9:
                continue
            index = columns.index(key) if key in columns else -1
            if index < 0 or index >= len(row.items):
                raise EditError(f'node "{node.id}": {key} is not written in its row')
            cell = row.items[index]
            original = doc.text[cell.start:cell.end]
            decimals = max(DEFAULT_DECIMALS, literal_decimals(original)) if cell.kind is Kind.NUMBER else DEFAULT_DECIMALS
            if cell.kind is Kind.NUMBER or self.move_mode is MoveMode.OVERWRITE:
                if cell.kind is not Kind.NUMBER:
                    notes.append(f'node "{node.id}": {key} was {original}, replaced by a number')
                new = format_number(raw[axis], decimals)
            elif cell.kind is Kind.STRING:
                try:
                    new = json_literal(shift_expression(cell.value, raw[axis] - current, decimals))
                except TextEditError as error:
                    raise EditError(f'node "{node.id}": {error}') from error
            else:
                raise EditError(f'node "{node.id}": {key} is {original}, which cannot be moved')
            edits.append(replace_value(cell, new))
        return path, edits

    def move_nodes(self, targets: Mapping[str, Sequence[float]], allow_shared: bool = False) -> None:
        """Moves nodes to final positions (after their offset, move and rotate modifiers)."""
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        notes: list[str] = []
        nodes = [self._own_node(node_id) for node_id in targets]
        self._check_shared(nodes, allow_shared)
        for node, target in zip(nodes, targets.values()):
            path, node_edits = self._position_edits(node, tuple(target), notes)
            edits[path].extend(node_edits)
        siblings = {u for node in nodes for u in self.row_users(node)} if allow_shared else set(targets)
        old_positions = {node_id: node.pos for node_id, node in self.vehicle.nodes.items() if node_id not in siblings}

        def verify(vehicle: AssembledVehicle) -> str | None:
            for node_id, target in targets.items():
                node = vehicle.nodes.get(node_id)
                if node is None or any(abs(a - b) > POSITION_TOLERANCE for a, b in zip(node.pos, target)):
                    return f'node "{node_id}" did not end up at {tuple(target)}'
            for node_id, position in old_positions.items():
                node = vehicle.nodes.get(node_id)
                if node is None or any(abs(a - b) > 1e-9 for a, b in zip(node.pos, position)):
                    return f'node "{node_id}" moved although it was not edited'
            return None

        self._apply(f"Move {len(targets)} node(s)", edits, verify, expected={})
        for note in notes:
            self.notes.add("info", "edit", note)

    def _rename_targets(self, old: str) -> tuple[list[tuple[Path, Document, Node, Node]], list[Location],
                                                 list[Location]]:
        """Id cells to rename, node references to rename, and other matches."""
        node = self._own_node(old)
        definitions = self._definition_rows(node)
        for _, doc, _, id_cell in definitions:
            if id_cell is None:
                raise EditError(f'node "{old}": the id is not written in its row')
            if id_cell.kind is not Kind.STRING or id_cell.value != old:
                raise TemplateIdError(f'node "{old}" gets its id from {doc.text[id_cell.start:id_cell.end]}; '
                                      f'rename it in the text')
        handled = {(path, cell.start) for path, _, _, cell in definitions}
        references: list[Location] = []
        variables = self._link_variables_in_vehicle()
        for part_name, part in self.vehicle.parts.items():
            obj = part_object(part.file.doc, part_name)
            if obj is None:
                continue
            for value in node_references(obj, old, variables):
                if (Path(part.file.doc.path), value.start) not in handled:
                    handled.add((Path(part.file.doc.path), value.start))
                    references.append(location(part.file.doc, value, part_name, "link"))
        return definitions, references, self._other_matches(old, handled)

    def _other_matches(self, value: str, handled: set) -> list[Location]:
        other: list[Location] = []
        for part_name, part in self.vehicle.parts.items():
            obj = part_object(part.file.doc, part_name)
            if obj is not None:
                other.extend(location(part.file.doc, v, part_name, "text") for v in string_values(obj, value)
                             if (Path(part.file.doc.path), v.start) not in handled)
        other.extend(self._inactive_references(value))
        return other

    def rename_preview(self, old: str) -> RenameResult:
        """What a rename of `old` would change, and other strings equal to it that it would not."""
        _, references, other = self._rename_targets(old)
        return RenameResult(references, other)

    def rename_node(self, old: str, new: str, also: Iterable[Location] = ()) -> RenameResult:
        """Renames a node and every reference to it in the vehicle's parts.

        `also` adds chosen locations from `rename_preview(old)`, such as references in parts not in the vehicle.
        """
        self._check_new_id(new)
        definitions, references, other = self._rename_targets(old)
        self._check_shared([self._own_node(old)], False)
        literal = json_literal(new)
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        for path, _, _, id_cell in definitions:
            edits[path].append(replace_value(id_cell, literal))
        for place in [*references, *also]:
            text = self.text_of(place.path)
            try:
                current = json.loads(text[place.start:place.end])
            except ValueError:
                current = None
            if current != old:
                raise EditError(f'{place.path.name}:{place.line} no longer holds "{old}"; preview the rename again')
            edits[Path(place.path)].append(TextEdit(place.start, place.end, literal, (place.start, place.end)))

        def verify(vehicle: AssembledVehicle) -> str | None:
            if new not in vehicle.nodes:
                return f'node "{new}" is missing after the rename'
            if old in vehicle.nodes:
                return f'node "{old}" is still defined by a row that was not renamed'
            return None

        self._apply(f'Rename node "{old}" to "{new}"', edits, verify, expected={})
        return RenameResult(references, self._other_matches(old, set()))

    def _check_new_id(self, new: str) -> None:
        if not isinstance(new, str) or not new.strip() or new != new.strip():
            raise EditError("a node id must be a non-empty string without surrounding spaces")
        if new in self.vehicle.nodes or new in self.vehicle.external_nodes:
            raise EditError(f'node "{new}" already exists')

    def rename_nodes(self, renames: Mapping[str, str]) -> None:
        """Renames several nodes in one change, each with every reference to it in the vehicle's parts."""
        renames = dict(renames)
        if len(set(renames.values())) != len(renames):
            raise EditError("two nodes would get the same id")
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        for old, new in renames.items():
            self._check_new_id(new)
            definitions, references, _ = self._rename_targets(old)
            self._check_shared([self._own_node(old)], False)
            literal = json_literal(new)
            for path, _, _, id_cell in definitions:
                edits[path].append(replace_value(id_cell, literal))
            for place in references:
                edits[Path(place.path)].append(TextEdit(place.start, place.end, literal, (place.start, place.end)))

        def verify(vehicle: AssembledVehicle) -> str | None:
            for old, new in renames.items():
                if new not in vehicle.nodes:
                    return f'node "{new}" is missing after the rename'
                if old in vehicle.nodes:
                    return f'node "{old}" is still defined by a row that was not renamed'
            return None

        self._apply(f"Rename {len(renames)} node(s)", edits, verify, expected={})

    def find_references(self, node_id: str) -> list[Location]:
        """Node references to `node_id` in the vehicle's parts."""
        found = []
        variables = self._link_variables_in_vehicle()
        for part_name, part in self.vehicle.parts.items():
            obj = part_object(part.file.doc, part_name)
            if obj is not None:
                found.extend(location(part.file.doc, v, part_name, "link")
                             for v in node_references(obj, node_id, variables))
        return found

    def _inactive_references(self, node_id: str) -> list[Location]:
        index = self.vehicle.index
        if index is None:
            return []
        found = []
        for part in index:
            if part.name in self.vehicle.parts or index.is_common(part):
                continue
            obj = part_object(part.file.doc, part.name)
            if obj is not None:
                found.extend(location(part.file.doc, v, part.name, "link")
                             for v in node_references(obj, node_id, self._link_variables_in_vehicle()))
        return found

    def _table(self, part_name: str, section: str) -> tuple[Path, Document, Node, Node | None]:
        part = self.vehicle.parts.get(part_name)
        if part is None:
            raise EditError(f'part "{part_name}" is not part of this vehicle')
        doc = part.file.doc
        obj = part_object(doc, part_name)
        if obj is None:
            raise EditError(f'part "{part_name}" not found in {Path(doc.path).name}')
        table = section_node(obj, section)
        if table is not None and header_of(table) is None:
            raise EditError(f'the "{section}" section of part "{part_name}" is not a table')
        return Path(doc.path), doc, obj, table

    def _row_edits(self, part_name: str, section: str, rows: list[dict[str, str]], allow_shared: bool = False,
                   anchors: Sequence | None = None) -> tuple[Path, list[TextEdit]]:
        """Edits that add rows with the given cell texts (by column name) to a table of a part.

        `anchors` gives for each row where it goes: after an existing row of the table (its syntax node), into
        a new block of a modifier (`NewBlock`) at the end, or at the end of the table (None).
        """
        path, doc, obj, table = self._table(part_name, section)
        self._check_part_shared(part_name, allow_shared)
        header = header_of(table) if table is not None else DEFAULT_HEADERS[section]
        names = [name for name in rows[0] if name != ROW_OPTIONS]
        indices = [header.index(name) if name in header else -1 for name in names]
        if -1 in indices or sorted(indices) != list(range(len(names))):
            raise EditError(f'the "{section}" table of part "{part_name}" does not start with the columns '
                            f'{", ".join(names)}')
        cells = [[row[header[i]] for i in range(len(names))] + ([row[ROW_OPTIONS]] if ROW_OPTIONS in row else [])
                 for row in rows]
        if table is None:
            return path, insert_section(doc, obj, section, [json_literal(h) for h in header], cells)
        placed: dict[int, tuple[Node, list]] = {}
        blocks: dict[NewBlock, list] = {}
        at_end: list = []
        for row, anchor in zip(cells, anchors or [None] * len(cells)):
            item = _item_of(table, anchor) if isinstance(anchor, Node) else None
            if item is not None and item is not table.items[-1]:
                placed.setdefault(id(item), (item, []))[1].append(row)
            elif isinstance(anchor, NewBlock):
                blocks.setdefault(anchor, []).append(row)
            else:
                at_end.append(row)
        edits = [insert_rows(doc, table, group, item) for item, group in placed.values()]
        template = next((i for i in reversed(table.items[1:]) if i.kind is Kind.ARRAY), table.items[0])
        tail = [format_row(row, template, doc.text) for row in at_end]
        for block, block_rows in blocks.items():
            tail.append(modifier_text({block.key: block.value}))
            tail += [format_row(row, template, doc.text) for row in block_rows]
            tail.append(modifier_text({block.key: block.reset}))
        if tail:
            edits.append(insert_values(doc, table, tail))
        return path, edits

    def _copies(self, part_name: str) -> int:
        """How many entries one new row of a part defines."""
        return max(1, len(self.part_slots(part_name)))

    def add_node(self, part_name: str, position: Sequence[float], node_id: str | None = None,
                 prefix: str = "n", allow_shared: bool = False) -> str:
        """Adds a node to a part at a final position and returns its id."""
        return self.add_nodes(part_name, [position], [node_id] if node_id else None, prefix, allow_shared)[0]

    def add_nodes(self, part_name: str, positions: Sequence[Sequence[float]], node_ids: Sequence[str] | None = None,
                  prefix: str = "n", allow_shared: bool = False, anchors: Sequence | None = None) -> list[str]:
        """Adds nodes to a part at final positions in one change and returns their ids.

        `anchors` places each row: after a row of the part's table, in a `NewBlock`, or at the end (None).
        """
        self.notes = DiagnosticList()
        targets = [tuple(p) for p in positions]
        if not targets:
            return []
        taken = set(self.vehicle.nodes) | set(self.vehicle.external_nodes)
        if node_ids is None:
            node_ids, number = [], 1
            while len(node_ids) < len(targets):
                if f"{prefix}{number}" not in taken:
                    node_ids.append(f"{prefix}{number}")
                number += 1
        node_ids = list(node_ids)
        if len(node_ids) != len(targets) or len(set(node_ids)) != len(node_ids):
            raise EditError("every new node needs its own id")
        for node_id in node_ids:
            if node_id in taken:
                raise EditError(f'node "{node_id}" already exists')
        rows = []
        for node_id, target in zip(node_ids, targets):
            row = {"id": json_literal(node_id)}
            row.update((key, format_number(target[i])) for i, key in enumerate(POSITION_KEYS))
            rows.append(row)
        path, edits = self._row_edits(part_name, "nodes", rows, allow_shared, anchors)
        new_texts = self._candidate({path: edits})
        vehicle = self._try(new_texts)
        fixes: dict[Path, list[TextEdit]] = defaultdict(list)
        for node_id, target in zip(node_ids, targets):
            node = vehicle.nodes.get(node_id)
            if node is not None and any(abs(a - b) > POSITION_TOLERANCE for a, b in zip(node.pos, target)):
                fix_path, fix_edits = self._position_edits_in(node, target, new_texts, vehicle)
                fixes[fix_path].extend(fix_edits)
        if fixes:
            new_texts.update(self._candidate(fixes, new_texts))
            vehicle = self._try(new_texts)

        def verify(vehicle: AssembledVehicle) -> str | None:
            for node_id, target in zip(node_ids, targets):
                added = vehicle.nodes.get(node_id)
                if added is None:
                    return f'node "{node_id}" is missing after adding it'
                if any(abs(a - b) > POSITION_TOLERANCE for a, b in zip(added.pos, target)):
                    return f'node "{node_id}" did not end up at {target}'
            return None

        description = f'Add node "{node_ids[0]}"' if len(node_ids) == 1 else f"Add {len(node_ids)} nodes"
        self._commit(description, new_texts, vehicle, verify,
                     expected={"nodes": len(node_ids) * self._copies(part_name)})
        return node_ids

    def _position_edits_in(self, node: NodeEntry, target, texts: Mapping[Path, str],
                           vehicle: AssembledVehicle) -> tuple[Path, list[TextEdit]]:
        """Position edits for a node of a candidate vehicle assembled from `texts`."""
        saved = self.texts, self.vehicle
        self.texts, self.vehicle = {**self.texts, **texts}, vehicle
        try:
            return self._position_edits(node, target, [])
        finally:
            self.texts, self.vehicle = saved

    def dependents(self, node_ids: Iterable[str]) -> list[BeamEntry | FaceEntry]:
        ids = set(node_ids)
        found: list[BeamEntry | FaceEntry] = [b for b in self.vehicle.beams if {b.id1, b.id2} & ids]
        found += [f for f in self.vehicle.triangles + self.vehicle.quads if set(f.ids) & ids]
        return found

    def delete_nodes(self, node_ids: Iterable[str], cascade: bool = False, allow_shared: bool = False) -> None:
        """Deletes nodes; beams, triangles and quads that use them are deleted too when `cascade` is set.

        Rows of other sections that reference the nodes stay in the text; the game discards them, and
        `notes` lists the sections affected.
        """
        ids = list(dict.fromkeys(node_ids))
        nodes = [self._own_node(node_id) for node_id in ids]
        dependents = self.dependents(ids)
        if dependents and not cascade:
            raise DependentsError(f"{len(dependents)} beams, triangles or quads use these nodes", dependents)
        self._check_shared(nodes + dependents, allow_shared)
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        for node in nodes:
            for path, doc, row, _ in self._definition_rows(node):
                edits[path].append(delete_value(doc, row))
        for entry in dependents:
            path, doc, row = self._row(entry)
            edits[path].append(delete_value(doc, row))
        expected = self._removed_by(nodes + dependents)
        expected.setdefault("nodes", -len(ids))
        self._apply(f"Delete {len(ids)} node(s)", edits, expected=expected, shrinking=True)

    # beams and faces

    def _check_nodes(self, node_ids: Sequence[str]) -> None:
        if len(set(node_ids)) != len(node_ids):
            raise EditError("the same node is used more than once")
        for node_id in node_ids:
            if node_id not in self.vehicle.nodes and node_id not in self.vehicle.external_nodes:
                raise EditError(f'node "{node_id}" not found')

    def add_beam(self, part_name: str, id1: str, id2: str, allow_shared: bool = False) -> None:
        self.add_beams(part_name, [(id1, id2)], allow_shared)

    def add_beams(self, part_name: str, pairs: Sequence[Sequence[str]], allow_shared: bool = False,
                  anchors: Sequence | None = None) -> None:
        """Adds beams between pairs of nodes to a part in one change; `anchors` as for `add_nodes`."""
        self._add_links(part_name, "beams", [tuple(p) for p in pairs], allow_shared, anchors)

    def _add_links(self, part_name: str, section: str, links: list[tuple[str, ...]], allow_shared: bool,
                   anchors: Sequence | None = None) -> None:
        if not links:
            return
        for ids in links:
            self._check_nodes(ids)
        rows = [{f"id{i + 1}:": json_literal(node_id) for i, node_id in enumerate(ids)} for ids in links]
        path, edits = self._row_edits(part_name, section, rows, allow_shared, anchors)
        kind = {"beams": "beam", "triangles": "triangle", "quads": "quad"}[section]
        description = f"Add {kind} {', '.join(links[0])}" if len(links) == 1 else f"Add {len(links)} {section}"
        self._apply(description, {path: edits}, expected={section: len(links) * self._copies(part_name)})

    def add_triangle(self, part_name: str, ids: Sequence[str], allow_shared: bool = False) -> None:
        if len(ids) != 3:
            raise EditError("a triangle needs three nodes")
        self._add_links(part_name, "triangles", [tuple(ids)], allow_shared)

    def add_quad(self, part_name: str, ids: Sequence[str], allow_shared: bool = False) -> None:
        if len(ids) != 4:
            raise EditError("a quad needs four nodes")
        self._add_links(part_name, "quads", [tuple(ids)], allow_shared)

    def add_faces(self, part_name: str, faces: Sequence[Sequence[str]], allow_shared: bool = False,
                  anchors: Sequence | None = None) -> None:
        """Adds triangles (three nodes) and quads (four nodes) to a part in one change; `anchors` as for
        `add_nodes`, each a row of the part's table of that kind of face."""
        faces = [tuple(f) for f in faces]
        if any(len(f) not in (3, 4) for f in faces):
            raise EditError("a face needs three or four nodes")
        anchors = list(anchors) if anchors is not None else [None] * len(faces)
        with self.transaction(f"Add {len(faces)} face(s)"):
            for size, section in ((3, "triangles"), (4, "quads")):
                chosen = [i for i, f in enumerate(faces) if len(f) == size]
                self._add_links(part_name, section, [faces[i] for i in chosen], allow_shared,
                                [anchors[i] for i in chosen])

    def node_groups(self, part_name: str | None = None) -> dict[str, list[str]]:
        """Node ids by group, for the nodes of one part or of the whole vehicle."""
        found: dict[str, list[str]] = {}
        for node in self.vehicle.nodes.values():
            if part_name is not None and node.part != part_name:
                continue
            value = node.props.get("group")
            for name in value if isinstance(value, list) else [value]:
                if isinstance(name, str) and name:
                    found.setdefault(name, []).append(node.id)
        return found

    def rename_group(self, old: str, new: str) -> int:
        """Renames a node group in every part of the vehicle: in `group` modifiers and row options, and in group
        columns such as the `[group]:` column of flexbodies. Returns the number of values changed."""
        if not isinstance(new, str) or not new.strip() or new != new.strip():
            raise EditError("a group name must be a non-empty string without surrounding spaces")
        if new == old:
            return 0
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        literal = json_literal(new)

        def rename(value: Node, path: Path) -> None:
            for cell in (value.items if value.kind is Kind.ARRAY else [value]):
                if cell.kind is Kind.STRING and cell.value == old:
                    edits[path].append(replace_value(cell, literal))

        def options(row: Node, path: Path) -> None:
            for member in row.members:
                if member.key == "group":
                    rename(member.value, path)

        for part_name, part in self.vehicle.parts.items():
            obj = part_object(part.file.doc, part_name)
            if obj is None:
                continue
            path = Path(part.file.doc.path)
            for member in obj.members:
                header = header_of(member.value)
                if header is None:
                    continue
                columns = [i for i, h in enumerate(header) if isinstance(h, str) and h.strip("[]:") == "group"]
                for row in member.value.items[1:]:
                    if row.kind is Kind.OBJECT:
                        options(row, path)
                    elif row.kind is Kind.ARRAY:
                        for index in columns:
                            if index < len(row.items):
                                rename(row.items[index], path)
                        if len(row.items) == len(header) + 1 and row.items[-1].kind is Kind.OBJECT:
                            options(row.items[-1], path)
        if not edits:
            raise EditError(f'no part of this vehicle uses group "{old}"')

        def verify(vehicle: AssembledVehicle) -> str | None:
            for node in vehicle.nodes.values():
                value = node.props.get("group")
                if value == old or (isinstance(value, list) and old in value):
                    return f'node "{node.id}" is still in group "{old}"'
            return None

        self._apply(f'Rename group "{old}" to "{new}"', edits, verify, expected={})
        return sum(len(e) for e in edits.values())

    def add_resets(self, part_name: str, defaults: Mapping[str, Mapping[str, object]] | None = None) -> dict:
        """Adds a modifier row at the end of each table of a part that leaves keys set for the parts after it,
        setting those keys back to their defaults. Returns the keys reset, by section."""
        defaults = defaults or DEFAULT_RESETS
        part = self.vehicle.parts.get(part_name)
        if part is None:
            raise EditError(f'part "{part_name}" is not part of this vehicle')
        doc = part.file.doc
        obj = part_object(doc, part_name)
        edits: list[TextEdit] = []
        done: dict[str, list[str]] = {}
        for section in defaults:
            table = section_node(obj, section) if obj is not None else None
            if table is None or header_of(table) is None:
                continue
            found = leaks(table, section, defaults)
            if found:
                keys = [k for k in defaults[section] if k in found]
                edits.append(insert_values(doc, table, [modifier_text({k: defaults[section][k] for k in keys})]))
                done[section] = keys
        if edits:
            self._apply(f'Add resets to part "{part_name}"', {Path(doc.path): edits}, expected={})
        return done

    def delete_entries(self, entries: Iterable[BeamEntry | FaceEntry], allow_shared: bool = False) -> None:
        """Deletes beams, triangles or quads."""
        entries = list(entries)
        self._check_shared(entries, allow_shared)
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        for entry in entries:
            path, doc, row = self._row(entry)
            edits[path].append(delete_value(doc, row))
        self._apply(f"Delete {len(entries)} entries", edits, expected=self._removed_by(entries))

    def _table_rows(self, rows: Iterable[tuple[Path | str, int]]) -> dict[tuple[Path, int], tuple[Document, Node, Node]]:
        """The document, table and row of each table row of the vehicle's parts that starts at the given offset
        of its file, such as the rows diagnostics point at."""
        found: dict[tuple[Path, int], tuple[Document, Node, Node]] = {}
        for part_name, part in self.vehicle.parts.items():
            obj = part_object(part.file.doc, part_name)
            if obj is None:
                continue
            path = Path(part.file.doc.path)
            for member in obj.members:
                if header_of(member.value) is not None:
                    for row in member.value.items[1:]:
                        if row.kind is Kind.ARRAY:
                            found[(path, row.start)] = (part.file.doc, member.value, row)
        wanted = {}
        for key in dict.fromkeys((Path(path), offset) for path, offset in rows):
            if key not in found:
                raise EditError(f"{key[0].name}: no table row starts at offset {key[1]}; assemble the vehicle again")
            wanted[key] = found[key]
        return wanted

    def delete_rows(self, rows: Iterable[tuple[Path | str, int]], allow_shared: bool = False) -> int:
        """Deletes table rows given by file and the offset where they start. Returns the number deleted."""
        return self.change_rows(delete=rows, allow_shared=allow_shared)[1]

    def mark_optional(self, rows: Iterable[tuple[Path | str, int]]) -> int:
        """Gives table rows, given by file and the offset where they start, "optional": true: the game skips such
        a row without a warning while a node it references is missing, and uses it once another part or mod
        provides the node. Returns the number of rows marked."""
        return self.change_rows(optional=rows)[0]

    def change_rows(self, optional: Iterable[tuple[Path | str, int]] = (), delete: Iterable[tuple[Path | str, int]] = (),
                    allow_shared: bool = False) -> tuple[int, int]:
        """Marks rows optional and deletes rows, all given by file and offset in the current texts, as one change.
        Returns the numbers of rows marked and deleted."""
        marked, deleted = self._table_rows(optional), self._table_rows(delete)
        if marked.keys() & deleted.keys():
            raise EditError("the same row cannot be marked optional and deleted")
        vehicle = self.vehicle
        entries = {(Path(e.src.file), e.src.node.start): e
                   for e in [*vehicle.nodes.values(), *vehicle.beams, *vehicle.triangles, *vehicle.quads]
                   if e.src is not None}
        removed = [entries[key] for key in deleted if key in entries]
        self._check_shared(removed, allow_shared)
        edits = self._optional_edits(marked)
        for (path, _), (doc, _, row) in deleted.items():
            edits[path].append(delete_value(doc, row))
        before = self._missing_rows(vehicle)

        def verify(after: AssembledVehicle) -> str | None:
            gone = before - self._missing_rows(after)
            return None if gone == len(marked) else f"{gone} of {len(marked)} rows stopped referencing missing nodes"

        description = (f"Mark {len(marked)} row(s) optional" if marked and not deleted else
                       f"Delete {len(deleted)} row(s)" if deleted and not marked else
                       f"Mark {len(marked)} row(s) optional and delete {len(deleted)}")
        self._apply(description, edits, verify if marked else None, expected=self._removed_by(removed))
        return len(marked), len(deleted)

    @staticmethod
    def _optional_edits(wanted: Mapping[tuple[Path, int], tuple[Document, Node, Node]]) -> dict[Path, list[TextEdit]]:
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        short: dict[int, tuple[Path, Document, Node, list[int]]] = {}
        for (path, _), (doc, table, row) in wanted.items():
            header = header_of(table)
            items = row.items
            if len(items) == len(header) + 1 and items[-1].kind is Kind.OBJECT:
                flag = next((m for m in items[-1].members if m.key == "optional"), None)
                edits[path] += ([replace_value(flag.value, "true")] if flag is not None
                                else insert_member(doc, items[-1], "optional", "true"))
            elif items and len(items) == len(header):
                edits[path].append(insert_into(row, items[-1].end, ", " + modifier_text({"optional": True})))
            else:
                short.setdefault(id(table), (path, doc, table, []))[3].append(table.items.index(row))
        for path, doc, table, indices in short.values():
            indices.sort()
            runs = [[indices[0]]]
            for index in indices[1:]:
                if index == runs[-1][-1] + 1:
                    runs[-1].append(index)
                else:
                    runs.append([index])
            for run in runs:
                edits[path].append(insert_values(doc, table, [modifier_text({"optional": True})],
                                                 after=table.items[run[0] - 1]))
                edits[path].append(insert_values(doc, table, [modifier_text({"optional": False})],
                                                 after=table.items[run[-1]]))
        return edits

    @staticmethod
    def _missing_rows(vehicle: AssembledVehicle) -> int:
        return sum(1 for d in vehicle.diagnostics if d.fix[:1] == ("mark_optional",))

    # hydros, torsion bars, slide nodes and rails

    def rail_names(self) -> list[str]:
        return [e.name for e in self.vehicle.extras if e.section == "rails"]

    def add_extras(self, part_name: str, section: str, rows: Sequence[Sequence[str]],
                   allow_shared: bool = False) -> None:
        """Adds hydros or torsion bars (rows of node ids in order) or slide nodes (rows of a node id and the
        name of a rail) to a table of a part."""
        columns = EXTRA_COLUMNS.get(section)
        if columns is None:
            raise EditError(f'rows of "{section}" cannot be added')
        rows = [tuple(row) for row in rows]
        rails = set(self.rail_names())
        for row in rows:
            if len(row) != len(columns):
                raise EditError(f'a row of "{section}" needs {len(columns)} values: {", ".join(columns)}')
            self._check_nodes(list(row[:1] if section == "slidenodes" else row))
            if section == "slidenodes" and row[1] not in rails:
                raise EditError(f'rail "{row[1]}" not found')
        cells = [dict(zip(columns, map(json_literal, row))) for row in rows]
        _, doc, _, table = self._table(part_name, section)
        header = header_of(table) if table is not None else None
        full = next((r for r in reversed(table.items[1:]) if r.kind is Kind.ARRAY and len(r.items) >= len(header)),
                    None) if header else None
        if full is not None and len(header) > len(columns):
            rest = {header[i]: doc.text[full.items[i].start:full.items[i].end] for i in range(len(columns), len(header))}
            cells = [{**row, **rest} for row in cells]
        path, edits = self._row_edits(part_name, section, cells, allow_shared)
        self._apply(f"Add {len(rows)} {section}", {path: edits}, expected={section: len(rows)})

    def copy_extras(self, copies: Sequence[tuple[ExtraEntry, Mapping[str, str]]], allow_shared: bool = False) -> int:
        """Adds a copy of the row of each hydro, torsion bar or slide node right after the row, so the modifiers
        above it apply to the copy too, with the cells of some columns replaced (cell texts by column name); the
        other cells and the row's options are copied as they are. Returns the number of rows added."""
        groups: dict[tuple[str, str, tuple], list[tuple[dict, Node]]] = defaultdict(list)
        for entry, replaced in copies:
            path, doc, row = self._row(entry)
            columns = _columns(entry)
            cells = {column: replaced.get(column, doc.text[item.start:item.end])
                     for column, item in zip(columns, row.items)}
            if len(row.items) == len(columns) + 1 and row.items[-1].kind is Kind.OBJECT:
                cells[ROW_OPTIONS] = doc.text[row.items[-1].start:row.items[-1].end]
            part = entry.part
            if part not in self.vehicle.parts:
                raise EditError(f"the row of {_label(entry)} does not belong to a part of this vehicle")
            groups[(part, entry.section, tuple(cells))].append((cells, row))
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        expected: dict[str, int] = defaultdict(int)
        for (part, section, _), rows in groups.items():
            path, part_edits = self._row_edits(part, section, [c for c, _ in rows], allow_shared, [r for _, r in rows])
            edits[path] += part_edits
            expected[section] += len(rows)
        self._apply(f"Copy {len(copies)} row(s)", edits, expected=dict(expected))
        return len(copies)

    def add_rail(self, part_name: str, name: str, links: Sequence[str], looped: bool = False, capped: bool = True,
                 allow_shared: bool = False, broken: Sequence[str] = ()) -> None:
        """Adds a rail through the nodes `links` to the rails of a part, or to its rails2 table if it has one."""
        links = list(links)
        if len(links) < 2:
            raise EditError("a rail needs at least two nodes")
        self._check_nodes(links)
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise EditError("a rail name must be a non-empty string without surrounding spaces")
        if name in self.rail_names():
            raise EditError(f'rail "{name}" already exists')
        part = self.vehicle.parts.get(part_name)
        if part is None:
            raise EditError(f'part "{part_name}" is not part of this vehicle')
        self._check_part_shared(part_name, allow_shared)
        doc = part.file.doc
        obj = part_object(doc, part_name)
        if obj is None:
            raise EditError(f'part "{part_name}" not found in {Path(doc.path).name}')
        values = {"id": name, "links:": links, "broken:": list(broken), "looped": looped, "capped": capped}
        rails, table = section_node(obj, "rails"), section_node(obj, "rails2")
        if rails is not None and rails.kind is Kind.OBJECT:
            edits = insert_member(doc, rails, name, modifier_text({k: v for k, v in values.items() if k != "id"}))
        elif table is not None and header_of(table) is not None:
            cells: dict[str, str] = {}
            for column in header_of(table):
                if column not in values:
                    break
                cells[column] = json_literal(values[column])
            if "links:" not in cells:
                raise EditError(f'the "rails2" table of part "{part_name}" does not start with id and links:')
            _, edits = self._row_edits(part_name, "rails2", [cells], allow_shared)
        else:
            edits = insert_object_section(doc, obj, "rails", [
                (name, modifier_text({k: v for k, v in values.items() if k != "id"}))])
        self._apply(f'Add rail "{name}"', {Path(doc.path): edits}, expected={"rails": 1})

    def _rail_member(self, entry: ExtraEntry):
        path = Path(entry.src.file)
        for part_name, part in self.vehicle.parts.items():
            if Path(part.file.doc.path) != path:
                continue
            obj = part_object(part.file.doc, part_name)
            rails = section_node(obj, "rails") if obj is not None else None
            for member in rails.members if rails is not None and rails.kind is Kind.OBJECT else ():
                if member.value.start == entry.src.node.start:
                    return part_name, part.file.doc, member
        return None

    def extra_part(self, entry: ExtraEntry) -> str | None:
        """The part whose text defines a hydro, torsion bar, slide node or rail."""
        if entry.src is not None and entry.src.node.kind is Kind.OBJECT:
            found = self._rail_member(entry)
            return found[0] if found is not None else None
        return entry.part

    def delete_extras(self, entries: Iterable[ExtraEntry]) -> None:
        """Deletes hydros, torsion bars, torsion hydros, slide nodes and rails; the slide nodes on a deleted rail
        go with it."""
        chosen = {id(e): e for e in entries}
        rails = {e.name for e in chosen.values() if e.section == "rails"}
        chosen.update((id(e), e) for e in self.vehicle.extras if e.section == "slidenodes" and e.name in rails)
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        expected: dict[str, int] = defaultdict(int)
        for entry in chosen.values():
            if entry.src is not None and entry.src.node.kind is Kind.OBJECT:
                path = Path(entry.src.file)
                if entry.src.doc.text != self.text_of(path):
                    raise EditError(f"{path.name} changed since this entry was read; assemble the vehicle again")
                found = self._rail_member(entry)
                if found is None:
                    raise EditError(f'rail "{entry.name}" is not in the "rails" section of a part')
                edits[path].append(delete_member(*found[1:]))
            else:
                path, doc, row = self._row(entry)
                edits[path].append(delete_value(doc, row))
            expected[entry.section] -= 1
        self._apply(f"Delete {len(chosen)} entries", edits, expected=dict(expected))

    def flip_faces(self, faces: Iterable[FaceEntry], allow_shared: bool = False) -> None:
        """Reverses the winding of triangles and quads, which flips the side they face."""
        faces = list(faces)
        self._check_shared(faces, allow_shared)
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        expected = []
        for face in faces:
            path, doc, row = self._row(face)
            columns = _columns(face)
            keys = [f"id{i + 1}:" for i in range(len(face.ids))]
            if any(key not in columns or columns.index(key) >= len(row.items) for key in keys):
                raise EditError(f"face {', '.join(face.ids)}: its ids are not written in its row")
            cells = [row.items[columns.index(key)] for key in keys]
            order = [0, 2, 1] if len(cells) == 3 else [0, 3, 2, 1]
            for cell, source in zip(cells, order):
                edits[path].append(replace_value(cell, doc.text[cells[source].start:cells[source].end]))
            expected.append(tuple(face.ids[i] for i in order))
        self._apply(f"Flip {len(expected)} face(s)", edits,
                    lambda v: None if all(any(f.ids == ids for f in v.triangles + v.quads) for ids in expected)
                    else "a flipped face is missing", expected={})

    def set_property(self, entries: Iterable[NodeEntry | BeamEntry | FaceEntry | ExtraEntry], key: str, value,
                     allow_shared: bool = False) -> None:
        """Sets a property on table rows: in its column if the table has one, otherwise in the row's options; on a
        rail of a "rails" object, in its members."""
        entries = list(entries)
        self._check_shared(entries, allow_shared)
        literal = json_literal(value)
        edits: dict[Path, list[TextEdit]] = defaultdict(list)
        for entry in entries:
            if isinstance(entry, ExtraEntry) and entry.src is not None and entry.src.node.kind is Kind.OBJECT:
                path = Path(entry.src.file)
                found = self._rail_member(entry) if entry.src.doc.text == self.text_of(path) else None
                if found is None:
                    raise EditError(f'rail "{entry.name}" changed since it was read; assemble the vehicle again')
                _, doc, rail = found
                member = next((m for m in reversed(rail.value.members) if m.key == key), None)
                edits[path] += ([replace_value(member.value, literal)] if member is not None
                                else insert_member(doc, rail.value, key, literal))
                continue
            path, doc, row = self._row(entry)
            columns = _columns(entry)
            if key in columns:
                index = columns.index(key)
                if index >= len(row.items):
                    raise EditError(f'the row has no "{key}" cell; fill in the cells before it first')
                edits[path].append(replace_value(row.items[index], literal))
                continue
            options = row.items[len(columns)] if len(row.items) == len(columns) + 1 else None
            if options is not None and options.kind is Kind.OBJECT:
                member = next((m for m in reversed(options.members) if m.key == key), None)
                if member is not None:
                    edits[path].append(replace_value(member.value, literal))
                else:
                    separator = ", " if options.members else ""
                    edits[path].append(insert_into(options, options.end - 1, f"{separator}{json_literal(key)}: {literal}"))
            elif len(row.items) == len(columns):
                edits[path].append(insert_into(row, row.end - 1, f", {{{json_literal(key)}: {literal}}}"))
            else:
                raise EditError("the row is shorter than its table header, so options cannot be added to it")
        node_ids = [e.id for e in entries if isinstance(e, NodeEntry)]
        literal_value = not (isinstance(value, str) and value.startswith("$"))
        identity = key.endswith(":") or key in ("id", "name", "railName")
        extras = [(e.section, e.ids, e.name) for e in entries if isinstance(e, ExtraEntry)] if not identity else []

        def verify(vehicle: AssembledVehicle) -> str | None:
            for node_id in node_ids:
                node = vehicle.nodes.get(node_id)
                if node is None or (literal_value and key not in POSITION_KEYS and node.props.get(key) != value):
                    return f'node "{node_id}" does not have {key} = {literal} afterwards'
            found = {(e.section, e.ids, e.name): e for e in vehicle.extras}
            for wanted in extras:
                extra = found.get(wanted)
                if extra is None or (literal_value and extra.props.get(key) != replace_special_values(value)):
                    return f'{wanted[0]} {"-".join(wanted[1])} does not have {key} = {literal} afterwards'
            return None

        self._apply(f'Set "{key}"', edits, verify, expected={})
