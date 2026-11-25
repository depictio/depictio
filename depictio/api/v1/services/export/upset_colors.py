"""The UpSet figure drawn in its sets' colours, as the dashboard draws it.

The server builds an UpSet plot in the library's own palette. The live
dashboard then recolours it in the browser (``upsetFigure.ts``:
``resolveUpsetSetColors``, ``colourUpsetSets``, ``withUpsetSetLabelDots``) so
a group is the colour every other tile of the dashboard draws it in. A figure
that never reaches that renderer (the PDF of a notebook export, the fallback a
report shows beside its live tile) needs the same pass, so this is its port,
kept to the same rules and held to them by a shared fixture
(``packages/depictio-react-core/src/components/advanced_viz/fixtures/upset-colouring.json``,
read by ``upsetFigure.fixture.test.ts`` and ``test_upset_colors.py``).

Everything is read off the figure's structure, never trace names: every trace
places intersections at ``x = 0..n-1`` except the horizontal set-size bars,
whose ``y`` is the set index, and the dot matrix is whatever sits on a y axis
labelled with the set names.

The colours are the dashboard's ``category_colors`` for the column the sets are
values of (``{column: {value: colour}}``, the family's merged map), never
chosen here.
"""

from __future__ import annotations

import re
from typing import Any

Trace = dict[str, Any]
Layout = dict[str, Any]

_YAXIS_KEY = re.compile(r"^yaxis(\d*)$")


def _values(v: Any) -> list[Any]:
    if hasattr(v, "tolist"):
        v = v.tolist()
    return list(v) if isinstance(v, (list, tuple)) else []


def _integer(v: Any) -> int | None:
    """``Number.isInteger``: an int or a float with no fraction, never a bool."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _is_set_size_bars(t: Trace) -> bool:
    return t.get("type") == "bar" and t.get("orientation") == "h"


def _has_markers(t: Trace) -> bool:
    return t.get("type") == "scatter" and "markers" in str(t.get("mode") or "")


def _set_name_axes(layout: Layout) -> set[str]:
    """Trace references (``y``, ``y2``, ...) of the y axes labelled with set names."""
    refs: set[str] = set()
    for key, axis in layout.items():
        match = _YAXIS_KEY.match(key)
        if match and isinstance(axis, dict) and isinstance(axis.get("ticktext"), list):
            refs.add(f"y{match.group(1)}")
    return refs


def _is_matrix_dots(t: Trace, axes: set[str]) -> bool:
    return _has_markers(t) and str(t.get("yaxis") or "y") in axes


def _is_filled_matrix_dots(t: Trace, axes: set[str]) -> bool:
    """The matrix dots of a set that belongs to the intersection: the only ones
    carrying a label. The empty dots of the other sets have none."""
    return _is_matrix_dots(t, axes) and t.get("hovertext") is not None


def upset_set_names(layout: Layout) -> dict[int, str]:
    """The set names by row index: ``names[y]`` is the set drawn at height ``y``."""
    for key, axis in layout.items():
        if not _YAXIS_KEY.match(key) or not isinstance(axis, dict):
            continue
        text = _values(axis.get("ticktext"))
        if not text:
            continue
        at = _values(axis.get("tickvals"))
        names: dict[int, str] = {}
        for i, name in enumerate(text):
            y = _integer(at[i]) if len(at) == len(text) else i
            if y is not None and y >= 0:
                names[y] = str(name)
        return names
    return {}


def _upset_column_sets(data: list[Trace], layout: Layout) -> dict[int, list[str]]:
    """The sets each intersection joins, by intersection (x) index."""
    axes = _set_name_axes(layout)
    names = upset_set_names(layout)
    rows: dict[int, set[int]] = {}
    for t in data:
        if not _is_filled_matrix_dots(t, axes):
            continue
        ys = _values(t.get("y"))
        for i, x in enumerate(_values(t.get("x"))):
            column = _integer(x)
            y = _integer(ys[i]) if i < len(ys) else None
            if column is None or y is None:
                continue
            rows.setdefault(column, set()).add(y)
    return {column: [names.get(y, str(y)) for y in sorted(ys)] for column, ys in rows.items()}


def resolve_upset_set_colors(
    category_colors: dict[str, dict[str, str]] | None,
    set_names: list[str],
    *,
    column: str | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """The colour each set is drawn in, or ``None`` to keep the figure as built.

    The sets of an UpSet are the values of some categorical column of the
    underlying data (a locality, a habitat): the recipe pivoted on it and they
    came out as column names. So their colours are that column's
    ``category_colors``. ``column`` names it; without one, the column is found
    by value: the one ``category_colors`` column that pins every set drawn.
    Several that pin them all but disagree are left alone rather than guessed
    between. ``overrides`` is the component's own ``set_colors``, which wins
    per set.
    """
    sets = [name for name in set_names if name]
    if not sets:
        return None
    source = category_colors or {}

    def pinned_for(col: str) -> dict[str, str]:
        mapping = source.get(col) or {}
        return {name: mapping[name] for name in sets if mapping.get(name)}

    pinned: dict[str, str] = {}
    if column:
        pinned = pinned_for(column)
    else:
        complete: list[dict[str, str]] = []
        for col in source:
            found = pinned_for(col)
            if len(found) == len(sets) and found not in complete:
                complete.append(found)
        if len(complete) == 1:
            pinned = complete[0]

    merged = dict(pinned)
    for name in sets:
        own = (overrides or {}).get(name)
        if own:
            merged[name] = own
    return merged or None


def _colour_at(original: Any, i: int) -> Any:
    if isinstance(original, (list, tuple)):
        return original[i] if i < len(original) else None
    return original


def _recoloured(t: Trace, set_at) -> Trace:
    """``marker.color`` with one entry per point: the set's colour where it has
    one, the colour the point already had otherwise."""
    marker = dict(t.get("marker") or {})
    n = max(len(_values(t.get("x"))), len(_values(t.get("y"))))
    original = marker.get("color")
    if hasattr(original, "tolist"):
        original = original.tolist()
    color = []
    for i in range(n):
        own = set_at(i)
        color.append(own if own is not None else _colour_at(original, i))
    return {**t, "marker": {**marker, "color": color}}


def colour_upset_sets(
    data: list[Trace], layout: Layout, colors: dict[str, str] | None
) -> list[Trace]:
    """The figure with each set drawn in its colour: its size bar, its filled
    dots in the matrix, and the bar of the intersection that is that set alone.

    Only the per-set intersection colouring has single-set bars to give a set's
    colour to. It is the one mode in which the server colours the intersection
    bars one by one (an array ``marker.color``), which is how it is recognised
    here; a bar several sets share keeps the neutral grey the server gave it.
    The single colour and the degree colouring are the author's choice and stay
    as they are.
    """
    if not colors:
        return data
    axes = _set_name_axes(layout)
    names = upset_set_names(layout)
    column_sets = _upset_column_sets(data, layout)

    def set_of_row(y: Any) -> str | None:
        row = _integer(y)
        name = names.get(row) if row is not None else None
        return colors.get(name) if name is not None else None

    out: list[Trace] = []
    for t in data:
        if _is_set_size_bars(t) or _is_filled_matrix_dots(t, axes):
            ys = _values(t.get("y"))
            out.append(_recoloured(t, lambda i, ys=ys: set_of_row(ys[i]) if i < len(ys) else None))
            continue
        per_bar = isinstance((t.get("marker") or {}).get("color"), (list, tuple))
        if t.get("type") == "bar" and per_bar:
            xs = _values(t.get("x"))

            def single_set_colour(i: int, xs=xs) -> str | None:
                column = _integer(xs[i]) if i < len(xs) else None
                sets = column_sets.get(column) if column is not None else None
                return colors.get(sets[0]) if sets and len(sets) == 1 else None

            out.append(_recoloured(t, single_set_colour))
            continue
        out.append(t)
    return out


def with_upset_set_label_dots(layout: Layout, colors: dict[str, str] | None) -> Layout:
    """The layout with a dot in its set's colour before each set name, the same
    cue the filter chips use. A dot rather than coloured text: a dark category
    colour on a dark theme leaves a name unreadable, a dot of it does not."""
    if not colors:
        return layout
    out = dict(layout)
    for key, axis in layout.items():
        if not _YAXIS_KEY.match(key) or not isinstance(axis, dict):
            continue
        ticktext = axis.get("ticktext")
        if not isinstance(ticktext, list):
            continue
        out[key] = {
            **axis,
            "ticktext": [
                f'<span style="color:{colors[str(name)]}">●</span> {name}'
                if str(name) in colors and colors[str(name)]
                else name
                for name in ticktext
            ],
        }
    return out


def colour_upset_figure(
    figure: dict[str, Any],
    category_colors: dict[str, dict[str, str]] | None,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """An UpSet ``{data, layout}`` in the dashboard's set colours, as
    ``UpsetRenderer`` draws it. Unchanged when nothing pins the sets."""
    config = config or {}
    data = list(figure.get("data") or [])
    layout = dict(figure.get("layout") or {})
    names = [name for _, name in sorted(upset_set_names(layout).items())]
    colors = resolve_upset_set_colors(
        category_colors,
        names,
        column=config.get("set_category_column"),
        overrides=config.get("set_colors"),
    )
    if not colors:
        return figure
    return {
        **figure,
        "data": colour_upset_sets(data, layout, colors),
        "layout": with_upset_set_label_dots(layout, colors),
    }
