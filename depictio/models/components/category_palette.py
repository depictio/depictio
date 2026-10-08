"""Colours for a categorical column whose values are only known from the data.

A template can say ``category_colors: {condition: auto}``: give every value of
``condition`` its own colour, without knowing the values in advance. The import
reads the column's distinct values and calls :func:`assign_category_colors`,
which hands out the slots of :data:`CATEGORY_PALETTE` in a fixed order, so one
run's ``control`` is the same colour on every tab and, on a re-import, the same
colour it had before.

Pure: no I/O, no randomness. The same values, pins and previous colours always
give the same map.
"""

import re
from collections.abc import Iterable, Mapping

# Colour-vision-deficiency safe, in the order slots are handed out: the first
# two alone already separate under every common deficiency.
CATEGORY_PALETTE: tuple[str, ...] = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#4a3aa7",
    "#e34948",
)

_DIGITS = re.compile(r"(\d+)")


def natural_sort_key(value: str) -> tuple[tuple[tuple[int, int | str], ...], str]:
    """Sort key that orders ``S2`` before ``S10``, case-insensitively.

    Digit runs compare as numbers, other runs as lower-cased text. The raw
    value breaks the remaining ties (``a`` vs ``A``), so the order is total and
    never depends on the order the values were read in.
    """
    parts: list[tuple[int, int | str]] = []
    for part in _DIGITS.split(value):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part.lower()))
    return tuple(parts), value


def assign_category_colors(
    values: Iterable[str],
    pinned: Mapping[str, str] | None = None,
    previous: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """A colour for every value of a column, from its data.

    Args:
        values: The column's distinct values, as read from the data. Order and
            duplicates do not matter.
        pinned: Colours the template sets for some values (``control: "#868e96"``).
        previous: The column's colours on the dashboard this import replaces,
            so a re-import keeps every surviving value's colour.

    Returns:
        ``{value: colour}``. Each value takes, in order of precedence, its
        previous colour, its pinned colour, or the next palette slot no pinned
        or previous colour already uses (values in natural order). When more
        values need a slot than the palette has free, none is generated: the
        column keeps its pinned and previous colours only, and the dashboard's
        brand colorway colours the rest. Pinned values absent from the data
        are kept, after the others.
    """
    pinned = dict(pinned or {})
    previous = dict(previous or {})
    ordered = sorted({str(v) for v in values}, key=natural_sort_key)

    fixed: dict[str, str] = {}
    for value in ordered:
        colour = previous.get(value) or pinned.get(value)
        if colour:
            fixed[value] = colour

    used = {c.lower() for c in fixed.values()} | {c.lower() for c in pinned.values()}
    free = [c for c in CATEGORY_PALETTE if c.lower() not in used]
    unassigned = [v for v in ordered if v not in fixed]
    generated = dict(zip(unassigned, free)) if len(unassigned) <= len(free) else {}

    result = {v: fixed.get(v) or generated[v] for v in ordered if v in fixed or v in generated}
    for value, colour in pinned.items():
        result.setdefault(value, colour)
    return result
