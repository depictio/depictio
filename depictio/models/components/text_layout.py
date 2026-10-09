"""How many grid rows a text tile's body needs, estimated from its markdown.

The viewer autofits text tiles at render (TextRenderer measures its content and
DashboardGrid turns that into rows), so this only sizes the stored layout: what
the first paint shows before the measurement lands, and what the shipped
dashboard lint checks against. It is deliberately rough.

A row is ~100px; at the full 8-column width it holds about three lines of
~100 characters. Block markdown is counted per block, not per character: a
heading, a list item or a table row takes a line of its own however short it
is, and a `::: steps` flow is drawn across the tile as a single band.
"""

from __future__ import annotations

import math
import re

GRID_COLUMNS = 8
CHARS_PER_LINE_FULL_WIDTH = 100
LINES_PER_ROW = 3
# Width a placeholder such as `{{share}}` takes once filled ("12.3%", "Bacteroidota").
PLACEHOLDER_CHARS = 8
# Lines a `::: steps` flow takes across a wide tile: marks, labels, values.
STEP_FLOW_LINES = 4
# Below this width the flow runs down the tile, two lines a step.
STEP_FLOW_MIN_WIDTH = 6

_LINK = re.compile(r"(?<!!)\[([^\]\n]*)\]\([^)\n]*\)")
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_PLACEHOLDER = re.compile(r"\{\{[^{}\n]+\}\}")
_EMPHASIS = re.compile(r"(\*\*|\*|`)")
_FENCE = re.compile(r"^\s*:::")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")


def rendered_text(line: str) -> str:
    """The characters a reader sees: link labels, not hrefs; icons as one glyph."""
    line = _IMAGE.sub(lambda m: (m.group(1) + " ") if m.group(1) else "x", line)
    line = _LINK.sub(r"\1", line)
    line = _PLACEHOLDER.sub("x" * PLACEHOLDER_CHARS, line)
    return _EMPHASIS.sub("", line)


def _lines_for(text: str, chars_per_line: int) -> int:
    return max(1, math.ceil(len(text.strip()) / chars_per_line))


def _step_flow_lines(steps: int, width: int) -> int:
    return STEP_FLOW_LINES if width >= STEP_FLOW_MIN_WIDTH else 2 * max(steps, 1)


def estimate_text_lines(body: str, width: int = GRID_COLUMNS) -> int:
    """Rendered lines of ``body`` in a tile ``width`` columns wide."""
    width = min(max(int(width or GRID_COLUMNS), 1), GRID_COLUMNS)
    chars_per_line = max(20, CHARS_PER_LINE_FULL_WIDTH * width // GRID_COLUMNS)
    lines = 0
    steps: int | None = None
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if _FENCE.match(line):
            if steps is None and "steps" in line:
                steps = 0
            elif steps is not None:
                lines += _step_flow_lines(steps, width)
                steps = None
            continue
        if steps is not None:
            if _LIST_ITEM.match(line):
                steps += 1
            continue
        # The renderer keeps the body's line breaks (white-space: pre-wrap), so
        # every authored line starts a new rendered one; a folded `>` body
        # arrives with each paragraph already on a single line.
        if line and not _TABLE_RULE.match(line):
            lines += _lines_for(rendered_text(line), chars_per_line)
    if steps is not None:  # an unclosed fence still draws its flow
        lines += _step_flow_lines(steps, width)
    return lines


def estimate_text_rows(body: str, width: int = GRID_COLUMNS) -> int:
    """Grid rows ``body`` needs in a tile ``width`` columns wide (at least 1)."""
    return max(1, math.ceil(estimate_text_lines(body, width) / LINES_PER_ROW))
