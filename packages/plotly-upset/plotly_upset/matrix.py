"""Dot matrix rendering for the UpSet indicator panel."""

from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go


@dataclass
class MatrixResult:
    """Traces and layout shapes for the dot matrix."""

    traces: list[go.BaseTraceType]
    shapes: list[dict]


def dot_matrix_traces(
    patterns: list[tuple[int, ...]],
    set_names: list[str],
    *,
    active_color: str = "#333333",
    inactive_color: str = "#C2C2C2",
    set_colors: dict[str, str] | None = None,
    dot_size: int = 12,
    edge_color: str = "#333333",
    edge_width: float = 2.0,
) -> MatrixResult:
    """Generate Plotly traces for the UpSet dot matrix.

    Parameters
    ----------
    set_colors:
        When provided, each set's active dots and edges are colored
        per-set. Overrides *active_color* and *edge_color*.

    Coordinate system:
    - x = intersection index (0, 1, 2, ...)
    - y = set index (0, 1, 2, ..., n_sets-1), bottom to top
    """
    n_sets = len(set_names)
    use_set_colors = set_colors is not None

    # Build hover text map
    hover_map: dict[tuple[int, int], str] = {}
    for xi, pattern in enumerate(patterns):
        active_names = [set_names[yi] for yi, bit in enumerate(pattern) if bit == 1]
        label = " & ".join(active_names)
        for yi, bit in enumerate(pattern):
            if bit == 1:
                hover_map[(xi, yi)] = label

    # Collect inactive dots
    inactive_x: list[int] = []
    inactive_y: list[int] = []

    for xi, pattern in enumerate(patterns):
        for yi, bit in enumerate(pattern):
            if bit == 0:
                inactive_x.append(xi)
                inactive_y.append(yi)

    traces: list[go.BaseTraceType] = []

    # Inactive dots (empty circles)
    if inactive_x:
        traces.append(
            go.Scatter(
                x=inactive_x,
                y=inactive_y,
                mode="markers",
                marker={
                    "size": dot_size,
                    "color": inactive_color,
                    "symbol": "circle",
                },
                showlegend=False,
                hoverinfo="skip",
            )
        )

    if use_set_colors:
        # Per-set colored rendering: one scatter per set + colored edges
        _add_colored_edges(traces, patterns, set_names, set_colors, edge_width)
        _add_colored_dots(traces, patterns, set_names, set_colors, dot_size, hover_map)
    else:
        # Monochrome rendering: single scatter for all active dots + single-color edges
        _add_mono_edges(traces, patterns, edge_color, edge_width)
        _add_mono_dots(traces, patterns, set_names, active_color, dot_size, hover_map)

    # Alternating row stripes for visual clarity
    shapes: list[dict] = []
    for yi in range(n_sets):
        if yi % 2 == 0:
            shapes.append(
                {
                    "type": "rect",
                    "x0": -0.5,
                    "x1": len(patterns) - 0.5,
                    "y0": yi - 0.5,
                    "y1": yi + 0.5,
                    "fillcolor": "rgba(0,0,0,0.03)",
                    "line": {"width": 0},
                    "layer": "below",
                }
            )

    return MatrixResult(traces=traces, shapes=shapes)


# ---------------------------------------------------------------------------
# Monochrome helpers (backwards-compatible)
# ---------------------------------------------------------------------------


def _add_mono_edges(
    traces: list[go.BaseTraceType],
    patterns: list[tuple[int, ...]],
    edge_color: str,
    edge_width: float,
) -> None:
    for xi, pattern in enumerate(patterns):
        active_in_column = [yi for yi, bit in enumerate(pattern) if bit == 1]
        if len(active_in_column) >= 2:
            traces.append(
                go.Scatter(
                    x=[xi, xi],
                    y=[min(active_in_column), max(active_in_column)],
                    mode="lines",
                    line={"color": edge_color, "width": edge_width},
                    showlegend=False,
                    hoverinfo="skip",
                )
            )


def _add_mono_dots(
    traces: list[go.BaseTraceType],
    patterns: list[tuple[int, ...]],
    set_names: list[str],
    active_color: str,
    dot_size: int,
    hover_map: dict[tuple[int, int], str],
) -> None:
    active_x: list[int] = []
    active_y: list[int] = []
    for xi, pattern in enumerate(patterns):
        for yi, bit in enumerate(pattern):
            if bit == 1:
                active_x.append(xi)
                active_y.append(yi)

    if active_x:
        hover_text = [hover_map[(x, y)] for x, y in zip(active_x, active_y)]
        traces.append(
            go.Scatter(
                x=active_x,
                y=active_y,
                mode="markers",
                marker={
                    "size": dot_size,
                    "color": active_color,
                    "symbol": "circle",
                },
                showlegend=False,
                hovertext=hover_text,
                hoverinfo="text",
            )
        )


# ---------------------------------------------------------------------------
# Per-set colored helpers
# ---------------------------------------------------------------------------


def _add_colored_edges(
    traces: list[go.BaseTraceType],
    patterns: list[tuple[int, ...]],
    set_names: list[str],
    set_colors: dict[str, str],
    edge_width: float,
) -> None:
    for xi, pattern in enumerate(patterns):
        active_in_column = [yi for yi, bit in enumerate(pattern) if bit == 1]
        if len(active_in_column) >= 2:
            # Use a dark neutral color for multi-set edges
            traces.append(
                go.Scatter(
                    x=[xi, xi],
                    y=[min(active_in_column), max(active_in_column)],
                    mode="lines",
                    line={"color": "#333333", "width": edge_width},
                    showlegend=False,
                    hoverinfo="skip",
                )
            )


def _add_colored_dots(
    traces: list[go.BaseTraceType],
    patterns: list[tuple[int, ...]],
    set_names: list[str],
    set_colors: dict[str, str],
    dot_size: int,
    hover_map: dict[tuple[int, int], str],
) -> None:
    # Group active dots by set (yi) so each set gets its own color
    per_set: dict[int, tuple[list[int], list[int], list[str]]] = {}
    for xi, pattern in enumerate(patterns):
        for yi, bit in enumerate(pattern):
            if bit == 1:
                if yi not in per_set:
                    per_set[yi] = ([], [], [])
                xs, ys, ht = per_set[yi]
                xs.append(xi)
                ys.append(yi)
                ht.append(hover_map.get((xi, yi), ""))

    for yi in sorted(per_set.keys()):
        xs, ys, ht = per_set[yi]
        color = set_colors.get(set_names[yi], "#333333")
        traces.append(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers",
                marker={
                    "size": dot_size,
                    "color": color,
                    "symbol": "circle",
                },
                showlegend=False,
                hovertext=ht,
                hoverinfo="text",
            )
        )
