"""Confusion matrix — TP / FP / FN counts per callset, as a heatmap.

Port of ``advanced_viz/ConfusionMatrixRenderer.tsx`` (the ``figure`` useMemo,
lines 77-151).

Not a classical confusion matrix: the rows are outcome classes and the columns
are callers, so several tools can be compared side by side. That is what makes
normalisation the central decision here — TP is routinely three orders of
magnitude larger than FP, so a raw colour scale paints one bright row and three
black ones and communicates nothing.

Three normalisation modes, matching the TSX:

* ``per_caller`` (default) — each column sums to 1. "What fraction of this
  caller's calls were false positives?"
* ``per_truth`` — each row sums to 1. "Which caller contributed most of the
  false positives?"
* ``none`` — divide by the global maximum. Honest, and usually unreadable.

Cell text is the raw count regardless of mode, because a fraction alone loses
the scale that tells you whether a 3% FP rate is thirty calls or thirty thousand.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.color_scale import contrasting_text_for_value
from depictio.api.v1.services.advanced_viz.figure_registry import register


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("label_col"),
        config.get("tp_col"),
        config.get("fp_col"),
        config.get("fn_col"),
        config.get("tn_col"),
    ]


def _as_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _format_count(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.0f}"


@register("confusion_matrix", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    label_col = config.get("label_col") or "label"
    tn_col = config.get("tn_col")

    callers = [str(v if v is not None else "") for v in (rows.get(label_col) or [])]
    if not callers:
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

    class_names = ["TP", "FP", "FN"] + (["TN"] if tn_col else [])
    class_columns = [
        config.get("tp_col") or "tp",
        config.get("fp_col") or "fp",
        config.get("fn_col") or "fn",
    ] + ([tn_col] if tn_col else [])
    counts = [[_as_float(v) for v in (rows.get(column) or [])] for column in class_columns]

    colorscale = str(config.get("colorscale") or "Blues")
    mode = str(controls.get("normalize_mode", config.get("normalize_mode", "per_caller")))
    show_fractions = bool(controls.get("normalize", config.get("normalize", False)))
    show_colorbar = bool(controls.get("show_colorbar", True))
    font_size = float(controls.get("font_size", 11))

    fractions = [[0.0] * len(callers) for _ in class_names]
    if mode == "per_caller":
        for column in range(len(callers)):
            total = sum(row[column] if column < len(row) else 0.0 for row in counts) or 1.0
            for index, row in enumerate(counts):
                fractions[index][column] = (row[column] if column < len(row) else 0.0) / total
    elif mode == "per_truth":
        for index, row in enumerate(counts):
            total = sum(row) or 1.0
            for column in range(len(callers)):
                fractions[index][column] = (row[column] if column < len(row) else 0.0) / total
    else:
        peak = max((max(row, default=0.0) for row in counts), default=0.0) or 1.0
        for index, row in enumerate(counts):
            for column in range(len(callers)):
                fractions[index][column] = (row[column] if column < len(row) else 0.0) / peak

    # Plotly draws heatmap y bottom-to-top, so reverse to keep TP on top where
    # a reader expects it.
    y_order = list(reversed(class_names))
    z = [fractions[class_names.index(name)] for name in y_order]
    z_counts = [counts[class_names.index(name)] for name in y_order]

    annotations = [
        {
            "x": caller,
            "y": name,
            "text": (
                f"{z[row_index][column]:.2f}"
                if show_fractions
                else _format_count(
                    z_counts[row_index][column] if column < len(z_counts[row_index]) else 0.0
                )
            ),
            "showarrow": False,
            # Sampled off the real colorscale rather than approximated: a
            # linear guess puts white text on a pale cell and loses the label.
            "font": {
                "size": font_size,
                "color": contrasting_text_for_value(colorscale, z[row_index][column]),
            },
        }
        for row_index, name in enumerate(y_order)
        for column, caller in enumerate(callers)
    ]

    return {
        "data": [
            {
                "type": "heatmap",
                "x": callers,
                "y": y_order,
                "z": z,
                "customdata": z_counts,
                "colorscale": colorscale,
                # Pinned domain: with per-column normalisation every value is
                # already a fraction, and letting Plotly autoscale would make
                # two matrices with different maxima look identical.
                "zmin": 0,
                "zmax": 1,
                "showscale": show_colorbar,
                "colorbar": {"thickness": 10, "len": 0.7, "title": {"text": "fraction"}},
                "hovertemplate": "%{y} · %{x}: %{customdata} (%{z:.2f})<extra></extra>",
                "xgap": 3,
                "ygap": 3,
            }
        ],
        "layout": {
            "margin": {"l": 48, "r": 20 if show_colorbar else 8, "t": 18, "b": 64},
            "xaxis": {"tickangle": -30, "automargin": True},
            "yaxis": {"automargin": True},
            "annotations": annotations,
        },
    }
