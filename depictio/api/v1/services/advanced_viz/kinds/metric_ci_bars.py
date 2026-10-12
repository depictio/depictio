"""Metric with confidence intervals — a forest plot over callsets.

Port of ``advanced_viz/MetricCiBarsRenderer.tsx`` (the ``figure`` useMemo, lines
71-145).

Named "CI bars" but drawn as a **forest plot**: a point estimate per callset with
a horizontal whisker for the interval. Bars were the obvious choice and the wrong
one — somatic recall runs around 0.02, and a bar chart anchored at zero renders
every caller as an identical sliver. A point on an auto-scaled axis zooms into
the range that actually varies.

Two details carry that decision:

* **the x-axis is scaled to the data**, padded by 15% of the observed spread and
  clamped to [0, 1], rather than pinned to [0, 1];
* **value labels sit above the point**, not beside it, so they never collide with
  the CI whisker.

The sort is reversed after ordering, because Plotly draws horizontal categories
bottom-to-top and the best callset belongs at the top.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.color_scale import plotly_colorscale
from depictio.api.v1.services.advanced_viz.figure_registry import register


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("label_col"),
        config.get("value_col"),
        config.get("lower_col"),
        config.get("upper_col"),
    ]


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result if math.isfinite(result) else fallback


@register("metric_ci_bars", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    label_col = config.get("label_col") or "label"
    value_col = config.get("value_col") or "value"
    lower_col = config.get("lower_col") or "lower"
    upper_col = config.get("upper_col") or "upper"
    metric_name = config.get("metric_name") or "F1"

    labels = [str(v if v is not None else "") for v in (rows.get(label_col) or [])]
    if not labels:
        return {
            "data": [],
            "layout": {
                "annotations": [
                    {
                        "text": "No callsets in data",
                        "showarrow": False,
                        "x": 0.5,
                        "y": 0.5,
                        "xref": "paper",
                        "yref": "paper",
                    }
                ],
                "xaxis": {"visible": False},
                "yaxis": {"visible": False},
            },
        }

    values = [_as_float(v) for v in (rows.get(value_col) or [])]
    # A missing bound collapses to the point estimate — a zero-width interval,
    # which reads as "no CI reported" rather than fabricating one at zero.
    lowers = [
        _as_float(v, values[i] if i < len(values) else 0.0)
        for i, v in enumerate(rows.get(lower_col) or [])
    ]
    uppers = [
        _as_float(v, values[i] if i < len(values) else 0.0)
        for i, v in enumerate(rows.get(upper_col) or [])
    ]

    def at(series: list[float], index: int) -> float:
        return series[index] if index < len(series) else 0.0

    sort_desc = bool(controls.get("sort_desc", config.get("sort_desc", True)))
    point_size = float(controls.get("point_size", 11))
    show_labels = bool(controls.get("show_labels", True))

    order = sorted(range(len(labels)), key=lambda i: at(values, i), reverse=sort_desc)
    order.reverse()  # Plotly draws horizontal categories bottom-to-top.

    xs = [at(values, i) for i in order]
    minus = [at(values, i) - at(lowers, i) for i in order]
    plus = [at(uppers, i) - at(values, i) for i in order]

    low = min((at(lowers, i) for i in order), default=0.0)
    high = max((at(uppers, i) for i in order), default=1.0)
    pad = max((high - low) * 0.15, 0.01)

    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers+text" if show_labels else "markers",
                "x": xs,
                "y": [labels[i] for i in order],
                "marker": {
                    "size": point_size,
                    "color": xs,
                    "colorscale": plotly_colorscale(str(config.get("colorscale") or "Tealgrn")),
                    "cmin": low,
                    "cmax": high,
                    "line": {"width": 1, "color": "#fff"},
                },
                "error_x": {
                    "type": "data",
                    "symmetric": False,
                    "array": plus,
                    "arrayminus": minus,
                    "color": "rgba(70,70,70,0.85)",
                    "thickness": 1.6,
                    "width": 6,
                },
                "text": [f"{x:.3f}" for x in xs],
                "textposition": "top center",
                "textfont": {"size": 11, "color": "#222"},
                # Labels at the axis edge would otherwise be clipped away.
                "cliponaxis": False,
                "customdata": [[at(lowers, i), at(uppers, i)] for i in order],
                "hovertemplate": (
                    f"<b>%{{y}}</b><br>{metric_name}: %{{x:.3f}}"
                    "<br>95% CI: [%{customdata[0]:.3f}, %{customdata[1]:.3f}]<extra></extra>"
                ),
            }
        ],
        "layout": {
            "margin": {"l": 90, "r": 30, "t": 24, "b": 40},
            "xaxis": {
                "title": {"text": f"{metric_name} (95% CI)"},
                "range": [max(0.0, low - pad), min(1.0, high + pad)],
            },
            "yaxis": {"automargin": True},
            "showlegend": False,
        },
    }
