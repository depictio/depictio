"""Python mirror of ``packages/depictio-react-core/src/colors.ts``.

Categorical colours must be assigned off the *universe* of distinct values, not
the filtered subset — otherwise filtering to one category re-maps its colour. A
server-built figure has to use the same rule as the TypeScript renderer or an
exported figure will not match the dashboard.

The colours and the assignment rule come from the shared palette module
(:mod:`depictio.models.palettes`): pinned colour, then the reserved grey of an
"Other" / "Unclassified" / "NA" value, then the palette slots in case-insensitive
order, skipping the slots a pin already uses.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from depictio.models import palettes

#: The default categorical palette (light variant). Kept importable for callers
#: that want the bare colours; pass ``mode="dark"`` to ``stable_color_map`` for
#: the dark variant instead of reading this.
TAB10_PALETTE: tuple[str, ...] = tuple(palettes.categorical(None, "light"))


def stable_color_map(
    all_values: Iterable[Any],
    palette: Sequence[str] | None = None,
    overrides: dict[str, str] | None = None,
    mode: str | None = "light",
) -> dict[str, str]:
    """Map each distinct value to a palette colour, deterministically.

    Sorting is case-insensitive so capitalisation differences do not flip the
    ordering — matching ``localeCompare(..., {sensitivity: 'base'})`` in colors.ts.
    Empty and null entries are skipped. ``overrides`` (pinned domain colours) win
    over the palette and free their slot for the other values; reserved remainder
    values (Other, Unclassified, NA...) take their semantic grey. ``palette``
    defaults to the shared depictio palette in ``mode``.
    """
    cleaned = {str(v) for v in all_values if v is not None and v != ""}
    return palettes.assign_colors(
        cleaned,
        pinned=overrides,
        palette=list(palette) if palette else None,
        mode=mode,
    )


def significance_colors(mode: str | None = "light") -> tuple[str, str, str]:
    """``(up, down, ns)`` colours shared by the volcano, MA and Manhattan kinds.

    Up and down are the palette's ``direction`` colours, the viewer's too
    (``DIRECTION_COLORS``), ns the semantic NA grey, so a hit reads the same in
    every differential-expression plot, served or exported.
    """
    return (
        palettes.direction("up", mode),
        palettes.direction("down", mode),
        palettes.semantic("na", mode),
    )
