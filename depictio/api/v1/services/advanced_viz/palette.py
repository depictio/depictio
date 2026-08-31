"""Python mirror of ``packages/depictio-react-core/src/colors.ts``.

Categorical colours must be assigned off the *universe* of distinct values, not
the filtered subset — otherwise filtering to one category re-maps its colour. A
server-built figure has to use the same rule as the TypeScript renderer or an
exported figure will not match the dashboard.
"""

from __future__ import annotations

from typing import Any, Iterable

#: matplotlib tab10, also scanpy's default categorical palette. Mirrors
#: ``TAB10_PALETTE`` in colors.ts.
TAB10_PALETTE: tuple[str, ...] = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)


def stable_color_map(
    all_values: Iterable[Any],
    palette: tuple[str, ...] = TAB10_PALETTE,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map each distinct value to a palette colour, deterministically.

    Sorting is case-insensitive so capitalisation differences do not flip the
    ordering — matching ``localeCompare(..., {sensitivity: 'base'})`` in colors.ts.
    Empty and null entries are skipped. Overrides are applied last so a pinned
    domain colour wins over the palette index.
    """
    cleaned = {str(v) for v in all_values if v is not None and v != ""}
    ordered = sorted(cleaned, key=lambda s: (s.casefold(), s))
    lookup = {v: palette[i % len(palette)] for i, v in enumerate(ordered)}
    if overrides:
        lookup.update(overrides)
    return lookup
