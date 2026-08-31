"""ROC / precision-recall curve — a threshold sweep, drawn as a curve.

Port of ``advanced_viz/RocPrCurveRenderer.tsx`` (the ``figure`` useMemo, lines
99-203).

Three cases share one renderer, and the export picks between them the same way
the TSX defaults do:

* **pr** (default) — precision against recall, sorted by recall.
* **roc** — TPR against FPR, only when ``fpr_col`` is bound. Adds the diagonal
  chance line, which is the entire point of a ROC: a curve below it is worse
  than guessing.
* **threshold** — precision *and* recall against the quality threshold, so you
  can read off where a caller's cutoff should sit.

AUC is computed by the trapezoid rule over points sorted by x, which is what the
TSX does. Sorting matters: a threshold sweep arrives in threshold order, not
recall order, and integrating unsorted points produces a meaningless number that
still looks plausible.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register

#: seaborn deep — mirrors PALETTE in the TSX.
_PALETTE: tuple[str, ...] = (
    "#4C72B0",
    "#DD8452",
    "#55A467",
    "#C44E52",
    "#8172B3",
    "#937860",
    "#DA8BC3",
)


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("recall_col"),
        config.get("precision_col"),
        config.get("fpr_col"),
        config.get("threshold_col"),
        config.get("group_col"),
    ]


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _auc(xs: list[float | None], ys: list[float | None]) -> float:
    """Trapezoidal area under y(x), over finite points sorted by x."""
    points = sorted(
        ((x, y) for x, y in zip(xs, ys) if x is not None and y is not None),
        key=lambda p: p[0],
    )
    area = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        area += (x1 - x0) * (y1 + y0) / 2
    return area


@register("roc_pr_curve", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    recall_col = config.get("recall_col") or "recall"
    precision_col = config.get("precision_col") or "precision"
    fpr_col = config.get("fpr_col")
    threshold_col = config.get("threshold_col")
    group_col = config.get("group_col")

    recall = [_as_float(v) for v in (rows.get(recall_col) or [])]
    precision = [_as_float(v) for v in (rows.get(precision_col) or [])]
    fpr = [_as_float(v) for v in (rows.get(fpr_col) or [])] if fpr_col else None
    thresholds = [_as_float(v) for v in (rows.get(threshold_col) or [])] if threshold_col else None
    groups_raw = rows.get(group_col) if group_col else None

    # Mode resolution mirrors the TSX: the requested case only applies when the
    # column it needs is actually bound, otherwise fall back to PR.
    requested = str(controls.get("mode", config.get("default_mode", "pr")))
    roc_mode = requested == "roc" and bool(fpr)
    threshold_mode = requested == "threshold" and bool(thresholds)
    show_auc = bool(controls.get("show_auc", True))
    line_mode = "lines+markers" if controls.get("show_markers", False) else "lines"
    marker_size = float(controls.get("marker_size", 5))

    grouped: dict[str, list[int]] = {}
    for i in range(len(recall)):
        key = str(groups_raw[i]) if groups_raw and i < len(groups_raw) else ""
        grouped.setdefault(key, []).append(i)

    data: list[dict[str, Any]] = []
    for position, (key, indices) in enumerate(grouped.items()):
        color = _PALETTE[position % len(_PALETTE)]
        prefix = f"{key} · " if key else ""

        if roc_mode and fpr:
            ordered = sorted(indices, key=lambda i: fpr[i] if fpr[i] is not None else 0.0)
            xs = [fpr[i] for i in ordered]
            ys = [recall[i] for i in ordered]
            area = _auc(xs, ys) if show_auc else None
            name = key or "ROC"
            data.append(
                {
                    "type": "scatter",
                    "mode": line_mode,
                    "x": xs,
                    "y": ys,
                    "name": f"{name}  (AUC {area:.3f})" if area is not None else name,
                    "line": {"width": 2, "color": color},
                    "marker": {"size": marker_size, "color": color},
                    "hovertemplate": (
                        f"<b>{name}</b><br>FPR: %{{x:.3f}}<br>TPR: %{{y:.3f}}<extra></extra>"
                    ),
                }
            )
            continue

        # Both remaining cases sort by threshold when one exists, otherwise by
        # recall. Integrating an unsorted sweep yields a plausible-looking but
        # meaningless AUC, so the order is load-bearing.
        def sort_key(i: int) -> float:
            if thresholds:
                return thresholds[i] if thresholds[i] is not None else 0.0
            return recall[i] if recall[i] is not None else 0.0

        ordered = sorted(indices, key=sort_key)

        if threshold_mode and thresholds:
            xs = [thresholds[i] for i in ordered]
            for label, values, dash in (
                ("precision", [precision[i] for i in ordered], None),
                ("recall", [recall[i] for i in ordered], "dot"),
            ):
                line: dict[str, Any] = {"width": 2, "color": color}
                if dash:
                    line["dash"] = dash
                data.append(
                    {
                        "type": "scatter",
                        "mode": line_mode,
                        "x": xs,
                        "y": values,
                        "name": f"{prefix}{label}",
                        "line": line,
                        "marker": {"size": marker_size, "color": color},
                        "hovertemplate": (
                            f"<b>{key}</b><br>{threshold_col}: %{{x}}"
                            f"<br>{label.title()}: %{{y:.3f}}<extra></extra>"
                        ),
                    }
                )
            continue

        xs = [recall[i] for i in ordered]
        ys = [precision[i] for i in ordered]
        area = _auc(xs, ys) if show_auc else None
        name = key or "curve"
        trace: dict[str, Any] = {
            "type": "scatter",
            "mode": line_mode,
            "x": xs,
            "y": ys,
            "name": f"{name}  (AUC {area:.3f})" if area is not None else name,
            "line": {"width": 2, "color": color},
            "marker": {"size": marker_size, "color": color},
            "hovertemplate": (
                f"<b>{name}</b><br>Recall: %{{x:.3f}}<br>Precision: %{{y:.3f}}<extra></extra>"
            ),
        }
        if thresholds:
            trace["customdata"] = [thresholds[i] for i in ordered]
            trace["hovertemplate"] = (
                f"<b>{name}</b><br>Recall: %{{x:.3f}}<br>Precision: %{{y:.3f}}"
                f"<br>{threshold_col}: %{{customdata}}<extra></extra>"
            )
        data.append(trace)

    if threshold_mode:
        x_title, y_title = (threshold_col or "threshold"), "Score"
        x_range = None
    elif roc_mode:
        x_title, y_title = "False positive rate", "True positive rate"
        x_range = [0, 1.03]
    else:
        x_title, y_title = "Recall", "Precision"
        x_range = [0, 1.03]

    # The chance diagonal is what makes a ROC readable; without it "above the
    # line" has nothing to be above.
    shapes = (
        [
            {
                "type": "line",
                "x0": 0,
                "y0": 0,
                "x1": 1,
                "y1": 1,
                "line": {"dash": "dot", "width": 1, "color": "rgba(128,128,128,0.5)"},
            }
        ]
        if roc_mode
        else []
    )

    x_axis: dict[str, Any] = {"title": {"text": x_title}}
    if x_range:
        x_axis["range"] = x_range

    return {
        "data": data,
        "layout": {
            "margin": {"l": 55, "r": 20, "t": 20, "b": 45},
            "xaxis": x_axis,
            "yaxis": {"title": {"text": y_title}, "range": [0, 1.03]},
            "shapes": shapes,
            "showlegend": bool(controls.get("show_legend", True)),
            "legend": {
                "x": 0.98,
                "y": 0.02,
                "xanchor": "right",
                "yanchor": "bottom",
                "bgcolor": "rgba(255,255,255,0.65)",
                "bordercolor": "rgba(128,128,128,0.3)",
                "borderwidth": 1,
            },
        },
    }
