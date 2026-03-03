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
    dot_size: int = 12,
    edge_color: str = "#333333",
    edge_width: float = 2.0,
) -> MatrixResult:
    """Generate Plotly traces for the UpSet dot matrix.

    Coordinate system:
    - x = intersection index (0, 1, 2, ...)
    - y = set index (0, 1, 2, ..., n_sets-1), bottom to top
    """
    n_sets = len(set_names)

    active_x: list[int] = []
    active_y: list[int] = []
    inactive_x: list[int] = []
    inactive_y: list[int] = []
    edge_traces: list[go.Scatter] = []

    for xi, pattern in enumerate(patterns):
        active_in_column: list[int] = []
        for yi, bit in enumerate(pattern):
            if bit == 1:
                active_x.append(xi)
                active_y.append(yi)
                active_in_column.append(yi)
            else:
                inactive_x.append(xi)
                inactive_y.append(yi)

        # Connect all active dots in this column with a vertical line
        if len(active_in_column) >= 2:
            y_min = min(active_in_column)
            y_max = max(active_in_column)
            edge_traces.append(
                go.Scatter(
                    x=[xi, xi],
                    y=[y_min, y_max],
                    mode="lines",
                    line={"color": edge_color, "width": edge_width},
                    showlegend=False,
                    hoverinfo="skip",
                )
            )

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

    # Edges (connecting lines) — add before active dots so dots are on top
    traces.extend(edge_traces)

    # Active dots (filled circles)
    if active_x:
        # Build hover text showing which sets are active
        hover_map: dict[tuple[int, int], str] = {}
        for xi, pattern in enumerate(patterns):
            active_names = [set_names[yi] for yi, bit in enumerate(pattern) if bit == 1]
            label = " & ".join(active_names)
            for yi, bit in enumerate(pattern):
                if bit == 1:
                    hover_map[(xi, yi)] = label

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
