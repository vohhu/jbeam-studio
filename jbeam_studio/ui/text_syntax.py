"""JBeam syntax colours and problems in Blender's text editor.

Blender has no syntax colouring for JBeam and no way to add one, so the editor shows JBeam as plain text and
this module paints every coloured token again: it clears each character cell with the colour Blender gave it
(background, selection or current line) and draws the character with the editor's monospace font. Problems
from the parser and, for files of an edit session, from the vehicle assembly are underlined, marked next to
the line number and described after the end of the line.
"""

from __future__ import annotations

import os
import traceback
import unicodedata
from dataclasses import dataclass, field

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ..blender import sessions
from ..core.diagnostics import PARSE, Severity
from ..core.sjson import parse
from ..core.sjson.tokens import (
    COMMENT, EXPRESSION, KEY, LITERAL, NUMBER, PART, SECTION, STRING, VARIABLE, tokens_by_line,
)
from . import view
from .text_highlight import path_key

COLORS = {
    PART: (0.31, 0.79, 0.69),
    SECTION: (0.86, 0.86, 0.67),
    KEY: (0.61, 0.86, 1.0),
    STRING: (0.81, 0.57, 0.47),
    VARIABLE: (0.31, 0.76, 1.0),
    EXPRESSION: (0.77, 0.53, 0.75),
    NUMBER: (0.71, 0.81, 0.66),
    LITERAL: (0.34, 0.61, 0.84),
    COMMENT: (0.42, 0.60, 0.33),
}
SEVERITY_COLORS = {
    Severity.ERROR: (0.96, 0.32, 0.32),
    Severity.WARNING: (0.95, 0.76, 0.22),
    Severity.INFO: (0.45, 0.70, 1.0),
}
SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
SYNC_LIMIT = 200_000
"""Texts up to this many characters are analysed as they change; longer ones after a pause in typing."""
PAUSE = 0.4
_handle = None
_footer = None
_font: int | None = None


@dataclass
class Analysis:
    tokens: list = field(default_factory=list)
    problems: dict = field(default_factory=dict)
    """Parse problems by 0-based line."""


_analyses: dict[str, tuple[int, Analysis]] = {}
"""Last analysis of each text by name, with the hash of the content it was made from."""
_pending: dict[str, int] = {}


def is_jbeam(text) -> bool:
    return bool(text.get(sessions.TEXT_SESSION)) or text.name.lower().endswith((".jbeam", ".pc"))


def _analyse(content: str, name: str) -> Analysis:
    analysis = Analysis(tokens_by_line(content))
    for problem in parse(content, name).diagnostics:
        if problem.line:
            analysis.problems.setdefault(problem.line - 1, []).append(problem)
    return analysis


def analysis_of(text, content: str) -> Analysis | None:
    """The analysis of the text's content: made now for short texts, after a pause for long ones."""
    key = hash(content)
    cached = _analyses.get(text.name)
    if cached is not None and cached[0] == key:
        return cached[1]
    if cached is None or len(content) <= SYNC_LIMIT:
        analysis = _analyse(content, text.name)
        _analyses[text.name] = (key, analysis)
        return analysis
    if _pending.get(text.name) != key:
        _pending[text.name] = key
        name = text.name

        def later():
            if _pending.get(name) != key:
                return None
            _pending.pop(name, None)
            current = bpy.data.texts.get(name)
            if current is not None and hash(current.as_string()) == key:
                _analyses[name] = (key, _analyse(current.as_string(), name))
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "TEXT_EDITOR":
                            area.tag_redraw()
            return None

        bpy.app.timers.register(later, first_interval=PAUSE)
    return cached[1]


def session_problems(text) -> dict[int, list]:
    """Problems the vehicle assembly found in the file of a session text, while the text shows the session."""
    session = sessions.SESSIONS.get(text.get(sessions.TEXT_SESSION, ""))
    if session is None or sessions.text_edited(text):
        return {}
    path = path_key(text[sessions.TEXT_PATH])
    found: dict[int, list] = {}
    for problem in session.edit.vehicle.diagnostics:
        if problem.category != PARSE and problem.file and problem.line and path_key(problem.file) == path:
            found.setdefault(problem.line - 1, []).append(problem)
    return found


def problems_of(text, analysis: Analysis) -> dict[int, list]:
    """Problems by 0-based line, the most severe first."""
    problems = {line: list(found) for line, found in analysis.problems.items()}
    for line, found in session_problems(text).items():
        problems.setdefault(line, []).extend(found)
    for found in problems.values():
        found.sort(key=lambda p: SEVERITY_ORDER[p.severity])
    return problems


def draw_footer() -> None:
    """The problem of the cursor's line, or the first problem of the file, at the right of the footer."""
    try:
        context = bpy.context
        space = context.space_data
        text = space.text if space is not None else None
        if text is None or not is_jbeam(text) or not view.settings(context).text_problems:
            return
        cached = _analyses.get(text.name)
        if cached is None:
            return
        problems = problems_of(text, cached[1])
        if not problems:
            return
        line = text.select_end_line_index
        shown_line = line if line in problems else min(problems)
        problem = problems[shown_line][0]
        count = sum(len(found) for found in problems.values())
        note = f"{count} \u26a0  " + bpy.app.translations.pgettext_iface("Line {line}: {message}").format(
            line=shown_line + 1, message=problem.message)
        region = context.region
        scale = context.preferences.view.ui_scale
        blf.size(0, 11 * scale)
        width = blf.dimensions(0, note)[0]
        room = region.width * 0.6
        if width > room:
            while note and blf.dimensions(0, note + "\u2026")[0] > room:
                note = note[:-1]
            note += "\u2026"
            width = blf.dimensions(0, note)[0]
        blf.color(0, *SEVERITY_COLORS[problem.severity], 1.0)
        blf.position(0, region.width - width - 10 * scale, (region.height - 11 * scale) / 2 + 2 * scale, 0)
        blf.draw(0, note)
    except Exception:
        traceback.print_exc()


def font() -> int:
    global _font
    if _font is None:
        path = bpy.context.preferences.view.font_path_ui_mono
        if not path or not os.path.exists(bpy.path.abspath(path)):
            path = os.path.join(bpy.utils.system_resource("DATAFILES"), "fonts", "DejaVuSansMono.woff2")
        loaded = blf.load(bpy.path.abspath(path)) if os.path.exists(bpy.path.abspath(path)) else -1
        _font = loaded if loaded >= 0 else 0
    return _font


@dataclass
class Metrics:
    height: int
    """Line height in pixels, as the editor's TXT_LINE_HEIGHT."""
    size: int
    """Font size in pixels, as the editor's lheight_px."""
    cell: int
    left: int
    """Left edge of the text body."""


def _line_size(height: int, cell: int) -> int:
    candidates = [s for s in range(max(1, int(height / 1.3) - 2), int(height / 1.3) + 3)
                  if int(np.float32(1.3) * np.float32(s)) == height]
    if not candidates:
        return max(1, round(height / 1.3))
    for size in reversed(candidates):
        blf.size(font(), size)
        if int(blf.dimensions(font(), "0")[0]) == cell:
            return size
    return candidates[-1]


def metrics(space, text, first: int) -> Metrics | None:
    lines = text.lines
    location = space.region_location_from_cursor
    heights = []
    for line in range(first, min(first + 8, len(lines) - 1)):
        step = location(line, 0)[1] - location(line + 1, 0)[1]
        if step > 0:
            heights.append(step)
    cell = 0
    for line in range(first, min(first + 40, len(lines))):
        body = lines[line].body
        if len(body) >= 2 and "\t" not in body[:2]:
            a, b = location(line, 0), location(line, 1)
            if a[1] == b[1] and b[0] > a[0]:
                cell = b[0] - a[0]
                break
    if not cell:
        return None
    height = min(heights) if heights else round(space.font_size * 1.3 * bpy.context.preferences.system.ui_scale)
    numbers = cell * (len(str(len(lines))) + 2) if space.show_line_numbers else 0
    return Metrics(height, _line_size(height, cell), cell, numbers + cell)


def _visible_lines(space, text, region, height: int) -> range:
    lines = len(text.lines)
    if not space.show_word_wrap:
        return range(min(space.top, lines), min(space.top + space.visible_lines + 2, lines))
    location = space.region_location_from_cursor
    low, high = 0, lines - 1
    while low < high:
        middle = (low + high + 1) // 2
        if location(middle, 0)[1] >= region.height:
            low = middle
        else:
            high = middle - 1
    last = low
    while last < lines and location(last, 0)[1] > -height:
        last += 1
    return range(low, last)


def _blend(color, other, amount: float):
    return tuple(c * (1 - amount) + o * amount for c, o in zip(color, other))


def _rectangles(rects_by_color: dict) -> None:
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    for color, rects in rects_by_color.items():
        vertices, indices = [], []
        for x0, y0, x1, y1 in rects:
            base = len(vertices)
            vertices += [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            indices += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
        batch = batch_for_shader(shader, "TRIS", {"pos": vertices}, indices=indices)
        shader.uniform_float("color", (*color[:3], color[3] if len(color) > 3 else 1.0))
        batch.draw(shader)


def _lines(segments_by_color: dict) -> None:
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    for color, points in segments_by_color.items():
        batch = batch_for_shader(shader, "LINES", {"pos": points})
        shader.uniform_float("color", (*color, 1.0))
        batch.draw(shader)


def _width(character: str) -> int:
    return 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1


def draw() -> None:
    try:
        _draw()
    except Exception:
        traceback.print_exc()


def _draw() -> None:
    context = bpy.context
    space = context.space_data
    text = space.text if space is not None else None
    if text is None or not is_jbeam(text):
        return
    display = view.settings(context)
    colours = display.text_syntax and space.show_syntax_highlight
    if not colours and not display.text_problems:
        return
    region = context.region
    content = text.as_string()
    analysis = analysis_of(text, content)
    if analysis is None:
        return
    lines = text.lines
    first_guess = min(space.top, max(len(lines) - 1, 0))
    measures = metrics(space, text, first_guess)
    if measures is None:
        return
    height, cell, left = measures.height, measures.cell, measures.left
    baseline = height - measures.size
    location = space.region_location_from_cursor
    theme = context.preferences.themes[0].text_editor
    back = tuple(theme.space.back)[:3]
    selected = tuple(theme.selected_text)[:3]
    foreground = tuple(theme.space.text)[:3]
    start = (text.current_line_index, text.current_character)
    end = (text.select_end_line_index, text.select_end_character)
    low, high = min(start, end), max(start, end)
    cursor_line = text.select_end_line_index
    clear: dict[tuple, list] = {}
    glyphs: dict[tuple, list] = {}
    problems = problems_of(text, analysis) if display.text_problems else {}
    underline: dict[tuple, list] = {}
    gutter: dict[tuple, list] = {}
    messages = []
    right = region.width - bpy.context.preferences.view.ui_scale * 20

    for line in _visible_lines(space, text, region, height):
        body = lines[line].body
        tokens = analysis.tokens[line] if line < len(analysis.tokens) else []
        if colours:
            for token_start, token_end, kind in tokens:
                color = COLORS.get(kind)
                if color is None or token_end > len(body):
                    continue
                x, y = location(line, token_start)
                plain = "\t" not in body[token_start:token_end]
                column = token_start
                for character in body[token_start:token_end]:
                    if not plain or space.show_word_wrap:
                        x, y = location(line, column)
                    if left - 1 <= x < right and -height < y < region.height and not character.isspace():
                        cell_color = selected if low <= (line, column) < high else back
                        if line == cursor_line and space.show_line_highlight:
                            cell_color = _blend(cell_color, foreground, 0.1)
                        clear.setdefault(cell_color, []).append((x, y, x + cell * _width(character), y + height))
                        glyphs.setdefault(color, []).append((x, y + baseline, character))
                    if plain and not space.show_word_wrap:
                        x += cell * _width(character)
                    column += 1
        found = problems.get(line)
        if found:
            worst = found[0]
            color = SEVERITY_COLORS[worst.severity]
            column = min(max((worst.column or 1) - 1, 0), max(len(body) - 1, 0))
            span = next(((s, e) for s, e, _ in tokens if s <= column < e), (column, max(len(body), column + 1)))
            x0, y0 = location(line, min(span[0], len(body)))
            x1, _ = location(line, min(span[1], len(body)))
            if x1 <= x0:
                x1 = x0 + cell
            if -height < y0 < region.height:
                points = underline.setdefault(color, [])
                step = max(2, cell // 3)
                x, up = max(x0, left), False
                while x < min(x1, right):
                    points += [(x, y0 + (3 if up else 1)), (min(x + step, x1), y0 + (1 if up else 3))]
                    x += step
                    up = not up
                if space.show_line_numbers:
                    gutter.setdefault((*color, 1.0), []).append((0, y0, max(2, cell // 4), y0 + height))
                end_x = location(line, len(body))[0] + 3 * cell
                note = worst.message + (f"  (+{len(found) - 1})" if len(found) > 1 else "")
                room = int((right - end_x) // cell)
                if room > 4:
                    messages.append((end_x, y0 + baseline, color, note if len(note) <= room else note[:room - 1] + "\u2026"))

    gpu.state.blend_set("ALPHA")
    if clear:
        _rectangles({(*c, 1.0): r for c, r in clear.items()})
    if gutter:
        _rectangles(gutter)
    if underline:
        _lines(underline)
    gpu.state.blend_set("NONE")
    if glyphs or messages:
        font_id = font()
        blf.size(font_id, measures.size)
        for color, items in glyphs.items():
            blf.color(font_id, *color, 1.0)
            for x, y, character in items:
                blf.position(font_id, x, y, 0)
                blf.draw(font_id, character)
        for x, y, color, note in messages:
            blf.color(font_id, *color, 0.9)
            blf.position(font_id, x, y, 0)
            blf.draw(font_id, note)
    if clear and not space.use_overwrite:
        x, y = location(text.select_end_line_index, text.select_end_character)
        if left - 1 <= x < right and -height < y < region.height:
            pixel = bpy.context.preferences.system.pixel_size
            gpu.state.blend_set("ALPHA")
            _rectangles({(*tuple(theme.cursor)[:3], 1.0): [(x - pixel, y, x + pixel, y + height)]})
            gpu.state.blend_set("NONE")


def register() -> None:
    global _handle, _footer
    _handle = bpy.types.SpaceTextEditor.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")
    _footer = bpy.types.SpaceTextEditor.draw_handler_add(draw_footer, (), "FOOTER", "POST_PIXEL")


def unregister() -> None:
    global _handle, _footer, _font
    if _handle is not None:
        bpy.types.SpaceTextEditor.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    if _footer is not None:
        bpy.types.SpaceTextEditor.draw_handler_remove(_footer, "FOOTER")
        _footer = None
    _analyses.clear()
    _font = None
