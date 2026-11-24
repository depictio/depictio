"""Categorical colours for annotation tracks that sit next to a colour scale.

A heatmap track (a strip of group colours beside the matrix) must not wear the
hues at the two ends of the matrix' own scale, or a "low" cell and a group read
as the same thing. The default ramps are built from fixed categorical slots:

- diverging: slot 2 (teal) at the low end, slot 1 (orange) at the high end;
- sequential: slot 0 (violet) at the emphasis end.

UpSet tracks sit beside the set bars, which take slots 0..n-1 in order, so the
first three slots are left to the sets.

This module is on purpose outside ``depictio.models.palettes`` (the shared
source) and free of FastAPI, so a catalog recipe on the CLI-only install can
import it next to ``palettes``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from depictio.models import palettes

# Slots of the default palette that a given scale (or companion mark) already uses.
RESERVED_SLOTS: dict[str, frozenset[int]] = {
    "diverging": frozenset({1, 2}),
    "sequential": frozenset({0}),
    "sets": frozenset({0, 1, 2}),
}


def track_palette(scale_kind: str | None, mode: str | None = "light") -> list[str]:
    """Categorical colours for a track beside a ``scale_kind`` scale.

    ``scale_kind`` is ``diverging``, ``sequential`` or ``sets`` (UpSet); any other
    value keeps the whole palette.
    """
    skip = RESERVED_SLOTS.get(scale_kind or "", frozenset())
    return [c for i, c in enumerate(palettes.categorical(None, mode)) if i not in skip]


def track_colors(
    values: Iterable[Any],
    scale_kind: str | None,
    *,
    mode: str | None = "light",
    pinned: Mapping[str, str] | None = None,
    ranked: bool = False,
) -> dict[str, str]:
    """``{value: colour}`` for one track: pin > reserved grey > track slot.

    ``ranked=True`` keeps the order of ``values`` (most frequent first) so the top
    ranks take the first slots; see ``palettes.assign_colors``.
    """
    return palettes.assign_colors(
        values,
        pinned=pinned,
        palette=track_palette(scale_kind, mode),
        mode=mode,
        ranked=ranked,
    )


def rank_by_frequency(counts: Mapping[Any, int]) -> list[str]:
    """Values by descending count, ties by name (case-insensitive): the ``ranked`` order."""
    return [
        str(v)
        for v, _ in sorted(
            counts.items(), key=lambda kv: (-kv[1], str(kv[0]).casefold(), str(kv[0]))
        )
    ]


def pins_for_column(category_colors: Mapping[str, Any] | None, column: str) -> dict[str, str]:
    """The dashboard's ``{value: colour}`` pins of ``column`` (exact name, else case-insensitive)."""
    if not isinstance(category_colors, Mapping):
        return {}
    pins = category_colors.get(column)
    if pins is None:
        wanted = column.casefold()
        pins = next((v for k, v in category_colors.items() if str(k).casefold() == wanted), None)
    if not isinstance(pins, Mapping):
        return {}
    return {str(v): str(c) for v, c in pins.items() if c and isinstance(c, str)}


# --- pins that would collide with the ends of a heatmap's colour scale -----------

_HEX = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)
_RGB = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", re.IGNORECASE)

# RGB distance (0-255 per channel) under which two colours read as the same one.
CLOSE_COLOUR_DISTANCE = 40.0


def _rgb(colour: str) -> tuple[int, int, int] | None:
    text = colour.strip()
    if m := _HEX.match(text):
        h = m.group(1)
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if m := _RGB.match(text):
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def reserved_colors(scale_kind: str | None, mode: str | None = "light") -> list[str]:
    """Colours a track must not wear next to a ``scale_kind`` scale.

    The reserved categorical slots plus the ends of the scale's own ramp.
    """
    categorical = palettes.categorical(None, mode)
    out = [categorical[i] for i in sorted(RESERVED_SLOTS.get(scale_kind or "", frozenset()))]
    if scale_kind == "diverging":
        ramp = palettes.diverging(None, mode)
        out += [ramp[0], ramp[-1]]
    elif scale_kind == "sequential":
        out.append(palettes.sequential(None, mode)[-1])
    return out


def is_reserved_colour(colour: str, scale_kind: str | None, mode: str | None = "light") -> bool:
    """True when ``colour`` equals, or is very close to, a colour the scale ends use."""
    probe = _rgb(colour)
    for reserved in reserved_colors(scale_kind, mode):
        if colour.strip().lower() == reserved.lower():
            return True
        target = _rgb(reserved)
        if probe is not None and target is not None:
            dist = sum((a - b) ** 2 for a, b in zip(probe, target, strict=True)) ** 0.5
            if dist <= CLOSE_COLOUR_DISTANCE:
                return True
    return False


def track_pins(
    category_colors: Mapping[str, Any] | None,
    columns: Iterable[str],
    scale_kind: str | None,
    mode: str | None = "light",
) -> dict[str, dict[str, str]]:
    """``{column: {value: colour}}`` dashboard pins a heatmap track may wear.

    A pin equal or close to a colour reserved for the scale's ends is dropped, so
    its value falls back to a free track slot instead of sharing a colour with the
    scale. Columns are matched case-insensitively; columns with no pin are absent.
    """
    out: dict[str, dict[str, str]] = {}
    for column in columns:
        pins = {
            v: c
            for v, c in pins_for_column(category_colors, column).items()
            if not is_reserved_colour(c, scale_kind, mode)
        }
        if pins:
            out[column] = pins
    return out
