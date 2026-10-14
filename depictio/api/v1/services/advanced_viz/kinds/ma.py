"""MA plot — mean log intensity vs log2 fold change.

Port of ``advanced_viz/MARenderer.tsx`` (the ``figure`` useMemo, lines 89-224).
Shares volcano's tier scheme and colours; the differences that matter are:

* the significance column is optional — without it, tiering is by |fold change|
  alone and the hovertemplate drops the significance line
* top-N ranks by ``|FC| * -log10(sig)``, falling back to ``|FC|`` when there is no
  significance column
* labels are plain (no connector arrow) and the threshold lines are horizontal
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register

_COLOR_UP = "#e64980"
_COLOR_DN = "#1c7ed6"
_COLOR_NS = "rgba(160,160,160,0.55)"
_SIZE_NS = 5
_SIZE_HIT = 7
_THRESHOLD_LINE = {"dash": "dot", "color": "rgba(128,128,128,0.6)", "width": 1}


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("feature_id_col") or "feature_id",
        config.get("avg_log_intensity_col") or "avg_log_intensity",
        config.get("log2_fold_change_col") or "log2_fold_change",
        config.get("significance_col"),
        config.get("label_col"),
    ]


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@register("ma", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    x_col = config.get("avg_log_intensity_col") or "avg_log_intensity"
    y_col = config.get("log2_fold_change_col") or "log2_fold_change"
    id_col = config.get("feature_id_col") or "feature_id"
    label_col = config.get("label_col")
    sig_col = config.get("significance_col")

    sig_threshold = float(
        controls.get("significance_threshold", config.get("significance_threshold", 0.05))
    )
    fc_threshold = float(
        controls.get("fold_change_threshold", config.get("fold_change_threshold", 1.0))
    )
    top_n = int(controls.get("top_n_labels", config.get("top_n_labels", 15)))
    search = str(controls.get("search", "") or "").strip().lower()
    show_labels = bool(controls.get("show_labels", True))

    xs = [_as_float(v) for v in (rows.get(x_col) or [])]
    ys = [_as_float(v) for v in (rows.get(y_col) or [])]
    ids = rows.get(id_col) or []
    labels = (rows.get(label_col) or ids) if label_col else ids
    sig_raw = [_as_float(v) for v in (rows.get(sig_col) or [])] if sig_col else None

    tiers: list[str] = []
    for i in range(len(xs)):
        fc = ys[i] if i < len(ys) else None
        if fc is None:
            tiers.append("NS")
            continue
        if sig_raw is None:
            pass_sig = True
        else:
            sig = sig_raw[i] if i < len(sig_raw) else None
            pass_sig = sig is not None and sig < sig_threshold
        if pass_sig and abs(fc) >= fc_threshold:
            tiers.append("UP" if fc > 0 else "DN")
        else:
            tiers.append("NS")

    colors = [_COLOR_UP if t == "UP" else _COLOR_DN if t == "DN" else _COLOR_NS for t in tiers]
    sizes = [_SIZE_NS if t == "NS" else _SIZE_HIT for t in tiers]

    ranked: list[tuple[int, float]] = []
    for i, fc in enumerate(ys):
        sig_weight = 1.0
        if sig_raw is not None:
            sig = sig_raw[i] if i < len(sig_raw) else None
            if sig is not None and sig > 0:
                sig_weight = -math.log10(sig)
        score = abs(fc or 0.0) * sig_weight
        if math.isfinite(score):
            ranked.append((i, score))
    ranked.sort(key=lambda d: d[1], reverse=True)
    top_idx = {i for i, _ in ranked[:top_n]}

    matched_idx: set[int] | None = None
    if search:
        matched_idx = {
            i
            for i in range(len(ids))
            if search in str(ids[i] or "").lower()
            or search in str((labels[i] if i < len(labels) else None) or "").lower()
        }

    annotations: list[dict[str, Any]] = []
    if show_labels:
        selected = matched_idx if matched_idx is not None else top_idx
        for i in sorted(selected):
            if i >= len(xs):
                continue
            annotations.append(
                {
                    "x": xs[i],
                    "y": ys[i] if i < len(ys) else None,
                    "text": str((labels[i] if i < len(labels) else None) or ids[i] or ""),
                    "showarrow": False,
                    "font": {"size": 10},
                }
            )

    customdata = [
        [
            str((labels[i] if i < len(labels) else None) or (ids[i] if i < len(ids) else "") or ""),
            (sig_raw[i] if sig_raw is not None and i < len(sig_raw) else None),
            tiers[i],
        ]
        for i in range(len(xs))
    ]

    hovertemplate = (
        '<b>%{customdata[0]}</b>  <span style="opacity:0.7">[%{customdata[2]}]</span>'
        f"<br>{x_col}: %{{x:.3f}}"
        f"<br>{y_col}: %{{y:.3f}}"
    )
    if sig_raw is not None:
        hovertemplate += f"<br>{sig_col}: %{{customdata[1]:.2e}}"
    hovertemplate += "<extra></extra>"

    return {
        "data": [
            {
                "type": "scattergl",
                "mode": "markers",
                "x": xs,
                "y": ys,
                "text": [str(v if v is not None else "") for v in ids],
                "customdata": customdata,
                "hovertemplate": hovertemplate,
                "marker": {"color": colors, "size": sizes, "opacity": 0.85},
            }
        ],
        "layout": {
            "margin": {"l": 50, "r": 20, "t": 30, "b": 40},
            "xaxis": {"title": {"text": x_col}, "zeroline": False},
            "yaxis": {"title": {"text": y_col}, "zeroline": True},
            "shapes": [
                {
                    "type": "line",
                    "xref": "paper",
                    "x0": 0,
                    "x1": 1,
                    "y0": bound,
                    "y1": bound,
                    "line": dict(_THRESHOLD_LINE),
                }
                for bound in (fc_threshold, -fc_threshold)
            ],
            "annotations": annotations,
            "showlegend": False,
            "autosize": True,
        },
    }
