"""DA barplot — per-contrast horizontal bars of log fold change.

Port of ``advanced_viz/DaBarplotRenderer.tsx`` (``buildPanel``, lines 136-180).

The renderer is tabbed: one panel per contrast plus an "All" faceted view. A
static export has no tabs, so it renders **one contrast** — the one
``config.contrast_view`` names, else the first alphabetically. Pass
``controls['contrast']`` to pick another. The panel title carries the contrast
name so an exported figure is never ambiguous about which one it shows.

The two-step sort is the part worth preserving: rank by ``|lfc|`` to take the
top-N, then re-sort by signed ``lfc`` so the bars read as a diverging ladder
rather than a magnitude ranking.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register

_POSITIVE = "#1f77b4"
_NEGATIVE = "#d62728"
_FADED = "rgba(127,127,127,0.45)"


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("feature_id_col"),
        config.get("contrast_col"),
        config.get("lfc_col"),
        config.get("significance_col"),
        config.get("label_col"),
    ]


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@register("da_barplot", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    feature_col = config.get("feature_id_col") or "feature_id"
    contrast_col = config.get("contrast_col") or "contrast"
    lfc_col = config.get("lfc_col") or "lfc"
    sig_col = config.get("significance_col")
    label_col = config.get("label_col")

    top_n = int(controls.get("top_n", config.get("top_n", 15)))
    sig_threshold = float(
        controls.get("significance_threshold", config.get("significance_threshold", 0.05))
    )

    features = rows.get(feature_col) or []
    contrasts = rows.get(contrast_col) or []
    lfcs = rows.get(lfc_col) or []
    sigs = rows.get(sig_col) if sig_col else None
    labels = rows.get(label_col) if label_col else None

    grouped: dict[str, list[dict[str, Any]]] = {}
    for i in range(len(features)):
        lfc = _as_float(lfcs[i]) if i < len(lfcs) else None
        if lfc is None:
            continue
        # Missing significance means "not significant", never "significant".
        sig = (_as_float(sigs[i]) if sigs and i < len(sigs) else None) or 1.0
        feature = str(features[i] if features[i] is not None else "")
        label = str(labels[i]) if labels and i < len(labels) and labels[i] is not None else feature
        key = str(contrasts[i] if i < len(contrasts) and contrasts[i] is not None else "")
        grouped.setdefault(key, []).append(
            {"feature": feature, "label": label, "lfc": lfc, "sig": sig}
        )

    names = sorted(grouped)
    requested = controls.get("contrast") or config.get("contrast_view")
    contrast = requested if requested in grouped else (names[0] if names else None)

    if contrast is None:
        return {"data": [], "layout": {"annotations": [{"text": "No contrasts in data"}]}}

    entries = grouped[contrast]
    # Rank by magnitude to select, then re-sort signed so the bars diverge.
    entries = sorted(entries, key=lambda r: -abs(r["lfc"]))[:top_n]
    entries.sort(key=lambda r: r["lfc"])

    colors = [
        (_POSITIVE if r["lfc"] >= 0 else _NEGATIVE) if r["sig"] <= sig_threshold else _FADED
        for r in entries
    ]

    hovertemplate = f"<b>%{{text}}</b><br>{lfc_col}: %{{x:.3f}}"
    if sig_col:
        hovertemplate += f"<br>{sig_col}: %{{customdata:.2e}}"
    hovertemplate += "<extra></extra>"

    return {
        "data": [
            {
                "type": "bar",
                "orientation": "h",
                "x": [r["lfc"] for r in entries],
                "y": [r["label"] for r in entries],
                "text": [r["label"] for r in entries],
                "customdata": [r["sig"] for r in entries],
                "textposition": "outside",
                "marker": {"color": colors, "line": {"width": 0}},
                "hovertemplate": hovertemplate,
                "showlegend": False,
            }
        ],
        "layout": {
            # The export cannot show tabs, so the contrast has to be on the figure.
            "title": {"text": str(contrast), "font": {"size": 12}},
            "margin": {"l": 8, "r": 80, "t": 32, "b": 36},
            "xaxis": {"title": {"text": lfc_col}, "zeroline": True},
            "yaxis": {"automargin": True, "showticklabels": False, "ticks": ""},
            "showlegend": False,
        },
    }
