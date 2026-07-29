"""PR benchmark — one point per callset in precision-recall space.

Port of ``advanced_viz/PrBenchmarkRenderer.tsx`` (the ``figure`` useMemo, lines
109-250).

Distinct from ``roc_pr_curve``: that one draws a *sweep* for a single caller,
this one places *one point per caller* so several tools can be compared at their
operating point. The iso-F1 contours are what make that comparison legible —
without them, "is 0.9 precision at 0.7 recall better than 0.8 at 0.85?" has no
visual answer.

An iso-F1 contour is the curve where F1 is constant. From
``F1 = 2pr / (p + r)`` you get ``p = cr / (2r - c)``, which is only defined for
``r > c/2`` — hence the sweep starting just above that asymptote.

Point encoding follows the config:

* **colour** — a discrete palette per ``category_col`` when bound, otherwise a
  continuous F1 scale.
* **size** — sqrt of ``support_col`` so *area* tracks the count, which is how a
  reader actually judges a bubble.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.color_scale import plotly_colorscale
from depictio.api.v1.services.advanced_viz.figure_registry import register

_PALETTE: tuple[str, ...] = (
    "#4C72B0",
    "#DD8452",
    "#55A467",
    "#C44E52",
    "#8172B3",
    "#937860",
    "#DA8BC3",
)

#: Contours drawn behind the points. Four is enough to read the gradient without
#: turning the panel into graph paper.
_ISO_LEVELS = (0.2, 0.4, 0.6, 0.8)


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("label_col"),
        config.get("recall_col"),
        config.get("precision_col"),
        config.get("f1_col"),
        config.get("support_col"),
        config.get("category_col"),
    ]


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _iso_f1(level: float) -> tuple[list[float], list[float]]:
    """Points along the curve where F1 == level.

    ``p = cr / (2r - c)`` diverges as ``r`` approaches ``c/2``, so the sweep
    starts just past the asymptote rather than at it.
    """
    xs: list[float] = []
    ys: list[float] = []
    recall = level / 2 + 0.001
    while recall <= 1.0001:
        precision = (level * recall) / (2 * recall - level)
        if 0 <= precision <= 1:
            xs.append(min(recall, 1.0))
            ys.append(precision)
        recall += 0.01
    return xs, ys


@register("pr_benchmark", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    label_col = config.get("label_col") or "label"
    recall_col = config.get("recall_col") or "recall"
    precision_col = config.get("precision_col") or "precision"
    f1_col = config.get("f1_col")
    support_col = config.get("support_col")
    category_col = config.get("category_col")

    labels = [str(v if v is not None else "") for v in (rows.get(label_col) or [])]
    recall = [_as_float(v) for v in (rows.get(recall_col) or [])]
    precision = [_as_float(v) for v in (rows.get(precision_col) or [])]
    f1 = [_as_float(v) for v in (rows.get(f1_col) or [])] if f1_col else None
    support = [_as_float(v) for v in (rows.get(support_col) or [])] if support_col else None
    categories = rows.get(category_col) if category_col else None

    show_iso = bool(controls.get("show_iso_f1", True))
    show_labels = bool(controls.get("show_labels", True))
    show_diagonal = bool(controls.get("show_diagonal", False))
    show_colorbar = bool(controls.get("show_colorbar", True))
    base_size = float(controls.get("point_size", 12))
    label_font = float(controls.get("label_font", 10))

    data: list[dict[str, Any]] = []

    if show_iso:
        for level in _ISO_LEVELS:
            xs, ys = _iso_f1(level)
            if not xs:
                continue
            data.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "x": xs,
                    "y": ys,
                    "line": {"dash": "dot", "width": 1, "color": "rgba(140,140,140,0.5)"},
                    "hoverinfo": "skip",
                    "showlegend": False,
                    "name": f"F1={level}",
                }
            )
            data.append(
                {
                    "type": "scatter",
                    "mode": "text",
                    "x": [xs[-1]],
                    "y": [ys[-1]],
                    "text": [f"F1 {level}"],
                    "textposition": "top left",
                    "textfont": {"size": 9, "color": "rgba(140,140,140,0.8)"},
                    "hoverinfo": "skip",
                    "showlegend": False,
                }
            )

    # sqrt so *area* scales with support, which is how a bubble is read.
    if support and str(controls.get("size_mode", "support")) == "support":
        peak = max((v or 0.0 for v in support), default=0.0) or 1.0
        sizes: Any = [
            base_size * 0.6 + base_size * 1.4 * math.sqrt((v or 0.0) / peak) for v in support
        ]
    else:
        sizes = base_size

    marker: dict[str, Any] = {
        "size": sizes,
        "opacity": 0.9,
        "line": {"width": 1, "color": "#fff"},
    }
    if categories:
        unique = list(dict.fromkeys(str(v if v is not None else "") for v in categories))
        marker["color"] = [
            _PALETTE[unique.index(str(v if v is not None else "")) % len(_PALETTE)]
            for v in categories
        ]
    elif f1:
        marker.update(
            {
                "color": f1,
                "colorscale": plotly_colorscale(str(config.get("colorscale") or "Viridis")),
                # Pinned to the metric's own domain: F1 is defined on [0, 1] and
                # autoscaling would make two panels incomparable.
                "cmin": 0,
                "cmax": 1,
                "showscale": show_colorbar,
                "colorbar": {"title": {"text": "F1"}, "thickness": 12, "len": 0.8},
            }
        )
    else:
        marker["color"] = "#3b82c4"

    hovertemplate = (
        f"<b>%{{customdata[0]}}</b><br>{recall_col}: %{{x:.3f}}<br>{precision_col}: %{{y:.3f}}"
    )
    if f1:
        hovertemplate += "<br>F1: %{customdata[1]:.3f}"
    if support:
        hovertemplate += f"<br>{support_col}: %{{customdata[2]}}"
    hovertemplate += "<extra></extra>"

    data.append(
        {
            "type": "scatter",
            "mode": "markers+text" if show_labels else "markers",
            "x": recall,
            "y": precision,
            "text": labels,
            "textposition": "top center",
            "textfont": {"size": label_font, "color": "#222"},
            "cliponaxis": False,
            "customdata": [
                [
                    labels[i] if i < len(labels) else "",
                    f1[i] if f1 and i < len(f1) else None,
                    support[i] if support and i < len(support) else None,
                ]
                for i in range(len(recall))
            ],
            "hovertemplate": hovertemplate,
            "marker": marker,
            "showlegend": False,
        }
    )

    shapes = (
        [
            {
                "type": "line",
                "x0": 0,
                "y0": 0,
                "x1": 1,
                "y1": 1,
                "line": {"dash": "dash", "width": 1, "color": "rgba(128,128,128,0.5)"},
            }
        ]
        if show_diagonal
        else []
    )

    return {
        "data": data,
        "layout": {
            "margin": {"l": 55, "r": 20, "t": 20, "b": 45},
            # Slightly past 1 so a perfect caller's marker and label are not
            # clipped by the axis.
            "xaxis": {"title": {"text": "Recall"}, "range": [-0.02, 1.06], "zeroline": False},
            "yaxis": {"title": {"text": "Precision"}, "range": [-0.02, 1.06], "zeroline": False},
            "shapes": shapes,
            "showlegend": False,
        },
    }
