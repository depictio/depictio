"""Colours for a categorical column whose values are only known from the data.

A template can say ``category_colors: {condition: auto}``: give every value of
``condition`` its own colour, without knowing the values in advance. The import
reads the column's distinct values and calls :func:`assign_category_colors`,
which hands out the slots of :data:`CATEGORY_PALETTE` (the shared depictio
palette) in a fixed order, so one run's ``control`` is the same colour on every
tab and, on a re-import, the same colour it had before.

Pure: no I/O, no randomness. The same values, pins and previous colours always
give the same map.
"""

import re
from collections.abc import Iterable, Mapping

from depictio.models import palettes
from depictio.models.palettes import ui_hues

# The default depictio palette (light variant), CVD-checked as a whole: slots are
# handed out in its order. A dashboard stores these hexes, so the same value keeps
# its colour on every tab.
CATEGORY_PALETTE: tuple[str, ...] = tuple(palettes.categorical(None, "light"))

# The palette's darker twins (`style.overflow: shade`), same hue and chroma. A
# column whose palette slots another column already holds takes these before it
# falls back on a colour that column shows.
CATEGORY_SHADES: tuple[str, ...] = tuple(
    ui_hues.overflow_shades(
        list(CATEGORY_PALETTE), float(palettes.style()["overflow_shade_dl"]["light"])
    )
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
    ranked: bool = False,
    avoid: Iterable[str] | None = None,
) -> dict[str, str]:
    """A colour for every value of a column, from its data.

    Args:
        values: The column's distinct values, as read from the data. Order and
            duplicates do not matter.
        pinned: Colours the template sets for some values (``control: "#868e96"``).
        previous: The column's colours on the dashboard this import replaces,
            so a re-import keeps every surviving value's colour.
        ranked: `values` come largest first (`auto:<column>`). Only the
            largest, as many as the palette has slots, get a generated colour,
            in that order; the figures fold the rest into Other.
        avoid: Colours other columns of the dashboard hold: their pins, and
            what the auto columns resolved before this one took. A previous
            colour among them is given up. Slots come from the palette first,
            then from its darker twins (`CATEGORY_SHADES`), and only then from
            the avoided colours, so a column's values are not drawn in the hue
            another column gave one of its own (Bacteria's violet on a phylum,
            Groundwater's orange on Pseudomonadota).

    Returns:
        ``{value: colour}``. Each value takes, in order of precedence, its
        pinned colour (the template's explicit choice: a re-import that replaces
        the dashboard applies a changed pin), its previous colour (an ``auto``
        value keeps what it had), or the next palette slot no pinned
        or previous colour already uses (values in natural order). A reserved
        value (Other, Unclassified, NA) never gets a slot: it stays out of the
        map unless pinned or previous, so it keeps its semantic grey at render.
        Unranked, when more values need a slot than the palette has slots this
        column's own pins and previous colours leave free, none is generated:
        the column keeps its pinned and previous colours only, and the
        dashboard's brand colorway colours the rest. Pinned values absent
        from the data are kept, after the others.
    """
    pinned = dict(pinned or {})
    previous = dict(previous or {})
    if ranked:
        ordered = list(dict.fromkeys(str(v) for v in values))
    else:
        ordered = sorted({str(v) for v in values}, key=natural_sort_key)

    avoided = {c.lower() for c in avoid or ()}
    fixed: dict[str, str] = {}
    for value in ordered:
        before = previous.get(value)
        colour = pinned.get(value) or (before if (before or "").lower() not in avoided else None)
        if colour:
            fixed[value] = colour

    used = {c.lower() for c in fixed.values()} | {c.lower() for c in pinned.values()}
    capacity = sum(c.lower() not in used for c in CATEGORY_PALETTE)
    free = [
        c
        for group in (
            [c for c in CATEGORY_PALETTE if c.lower() not in avoided],
            # Twins of the hues other columns hold first: a twin of one of this
            # column's own colours would sit next to it in the same legend.
            [
                shade
                for _, shade in sorted(
                    zip(CATEGORY_PALETTE, CATEGORY_SHADES, strict=True),
                    key=lambda pair: pair[0].lower() not in avoided,
                )
                if shade.lower() not in avoided
            ],
            [c for c in CATEGORY_PALETTE if c.lower() in avoided],
        )
        for c in group
        if c.lower() not in used
    ]
    free_values = [v for v in ordered if palettes.reserved_kind(v) is None]
    if ranked:
        # The largest values, as many as the palette has slots, and only them:
        # the figures fold the rest into Other, whatever colours are left over.
        unassigned = [v for v in free_values[: len(CATEGORY_PALETTE)] if v not in fixed]
        generated = dict(zip(unassigned, free))
    else:
        unassigned = [v for v in free_values if v not in fixed]
        generated = dict(zip(unassigned, free)) if len(unassigned) <= capacity else {}

    colours = {**fixed, **generated}
    result = {v: colours[v] for v in ordered if v in colours}
    for value, colour in pinned.items():
        result.setdefault(value, colour)
    return result
