"""Volcano plot — effect size vs significance.

Port of ``advanced_viz/VolcanoRenderer.tsx`` (the ``figure`` useMemo, lines
103-270). Constants are copied deliberately — the tier colours, the binary 5/7
marker sizing, the ``|x| * y`` top-N ranking and the hovertemplate all have to
match or an exported figure looks different from the dashboard it came from.

Intra-viz controls (``significance_threshold``, ``effect_threshold``,
``top_n_labels``, ``search``, ``show_labels``) default from the persisted config,
exactly as the renderer seeds its ``useState``. A live tweak the user made in the
browser is not visible server-side, so an export reflects the persisted state
unless the caller pins ``controls``.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register

#: Tier colours, matching VolcanoRenderer.tsx:129-131.
_COLOR_UP = "#e64980"
_COLOR_DN = "#1c7ed6"
_COLOR_NS = "rgba(160,160,160,0.55)"

#: Binary marker sizing so hits pop out of the grey NS cloud without
#: distracting magnitude variation (VolcanoRenderer.tsx:135).
_SIZE_NS = 5
_SIZE_HIT = 7

_THRESHOLD_LINE = {"dash": "dot", "color": "rgba(128,128,128,0.6)", "width": 1}


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("feature_id_col") or "feature_id",
        config.get("effect_size_col") or "effect_size",
        config.get("significance_col") or "significance",
        config.get("label_col"),
        config.get("category_col"),
    ]


def _neg_log10(value: Any) -> float | None:
    """-log10 of a p-value, or ``None`` for null/non-positive input."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0 or not math.isfinite(v):
        return None
    return -math.log10(v)


@register("volcano", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    effect_col = config.get("effect_size_col") or "effect_size"
    sig_col = config.get("significance_col") or "significance"
    id_col = config.get("feature_id_col") or "feature_id"
    label_col = config.get("label_col")
    is_neg_log10 = bool(config.get("significance_is_neg_log10", False))

    sig_threshold = float(
        controls.get("significance_threshold", config.get("significance_threshold", 0.05))
    )
    effect_threshold = float(controls.get("effect_threshold", config.get("effect_threshold", 1.0)))
    top_n = int(controls.get("top_n_labels", config.get("top_n_labels", 20)))
    search = str(controls.get("search", "") or "").strip().lower()
    show_labels = bool(controls.get("show_labels", True))

    xs_raw = rows.get(effect_col) or []
    sig_raw = rows.get(sig_col) or []
    ids = rows.get(id_col) or []
    labels = (rows.get(label_col) or ids) if label_col else ids

    xs: list[float | None] = []
    for v in xs_raw:
        try:
            xs.append(float(v) if v is not None else None)
        except (TypeError, ValueError):
            xs.append(None)

    ys: list[float | None] = (
        [None if v is None else float(v) for v in sig_raw]
        if is_neg_log10
        else [_neg_log10(v) for v in sig_raw]
    )

    # When the column holds raw p-values the threshold must be transformed too,
    # so both live on the same axis.
    sig_threshold_y = sig_threshold if is_neg_log10 else (_neg_log10(sig_threshold) or 0.0)

    tiers: list[str] = []
    for i, x in enumerate(xs):
        y = ys[i] if i < len(ys) else None
        if y is None or x is None:
            tiers.append("NS")
            continue
        if y >= sig_threshold_y and abs(x) >= effect_threshold:
            tiers.append("UP" if x > 0 else "DN")
        else:
            tiers.append("NS")

    colors = [_COLOR_UP if t == "UP" else _COLOR_DN if t == "DN" else _COLOR_NS for t in tiers]
    sizes = [_SIZE_NS if t == "NS" else _SIZE_HIT for t in tiers]

    # Top-N by combined |effect| * significance so both axes matter.
    ranked = [
        (i, abs(x) * (ys[i] or 0.0))
        for i, x in enumerate(xs)
        if x is not None and math.isfinite(abs(x) * (ys[i] or 0.0))
    ]
    ranked.sort(key=lambda d: d[1], reverse=True)
    top_idx = {i for i, _ in ranked[:top_n]}

    matched_idx: set[int] | None = None
    if search:
        matched_idx = {
            i
            for i in range(len(ids))
            if search in str(ids[i] or "").lower()
            or search in str(labels[i] if i < len(labels) else "" or "").lower()
        }

    annotations: list[dict[str, Any]] = []
    if show_labels:
        selected = matched_idx if matched_idx is not None else top_idx
        for i in sorted(selected):
            if i >= len(xs) or xs[i] is None or ys[i] is None:
                continue
            annotations.append(
                {
                    "x": xs[i],
                    "y": ys[i],
                    "text": str((labels[i] if i < len(labels) else None) or ids[i] or ""),
                    # Anchor stays on the point; the text box lifts 16px with a
                    # thin connector so clustered top-N labels stay readable.
                    "showarrow": True,
                    "arrowhead": 0,
                    "arrowwidth": 0.6,
                    "arrowcolor": "rgba(120,120,120,0.6)",
                    "ax": 0,
                    "ay": -16,
                    "font": {"size": 10},
                }
            )

    customdata = [
        [
            str((labels[i] if i < len(labels) else None) or (ids[i] if i < len(ids) else "") or ""),
            sig_raw[i] if i < len(sig_raw) else None,
            tiers[i],
        ]
        for i in range(len(xs))
    ]

    y_title = sig_col if is_neg_log10 else f"-log10({sig_col})"

    return {
        "data": [
            {
                "type": "scattergl",
                "mode": "markers",
                "x": xs,
                "y": ys,
                "text": [str(v if v is not None else "") for v in ids],
                "customdata": customdata,
                "hovertemplate": (
                    '<b>%{customdata[0]}</b>  <span style="opacity:0.7">'
                    "[%{customdata[2]}]</span>"
                    f"<br>{effect_col}: %{{x:.3f}}"
                    f"<br>{sig_col}: %{{customdata[1]:.2e}}"
                    "<br>-log10(sig): %{y:.2f}"
                    "<extra></extra>"
                ),
                "marker": {"color": colors, "size": sizes, "opacity": 0.85},
            }
        ],
        "layout": {
            "margin": {"l": 50, "r": 20, "t": 30, "b": 40},
            "xaxis": {"title": {"text": effect_col}, "zeroline": True},
            "yaxis": {"title": {"text": y_title}},
            "shapes": [
                {
                    "type": "line",
                    "x0": -effect_threshold,
                    "x1": -effect_threshold,
                    "yref": "paper",
                    "y0": 0,
                    "y1": 1,
                    "line": dict(_THRESHOLD_LINE),
                },
                {
                    "type": "line",
                    "x0": effect_threshold,
                    "x1": effect_threshold,
                    "yref": "paper",
                    "y0": 0,
                    "y1": 1,
                    "line": dict(_THRESHOLD_LINE),
                },
                {
                    "type": "line",
                    "xref": "paper",
                    "x0": 0,
                    "x1": 1,
                    "y0": sig_threshold_y,
                    "y1": sig_threshold_y,
                    "line": dict(_THRESHOLD_LINE),
                },
            ],
            "annotations": annotations,
            "showlegend": False,
            "autosize": True,
        },
    }
