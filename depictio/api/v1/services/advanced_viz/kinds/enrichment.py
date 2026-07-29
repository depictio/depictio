"""Pathway enrichment (GSEA) — NES dot plot.

Port of ``advanced_viz/EnrichmentRenderer.tsx`` (the ``figure`` useMemo, lines
90-225).

Three encodings carry the data and all three have to survive the port:

* **x** is the normalised enrichment score,
* **marker size** is the gene count, sqrt-scaled so area reads proportionally,
* **marker colour** is significance, defaulting to ``-log10(padj)`` exactly as
  the TSX's ``colourBy`` state does.

The double sort matters: select top-N by *significance* (smallest padj), then
re-sort by *NES ascending* so positive scores land at the top of the y-axis —
Plotly draws the first category at the bottom.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register

#: Floor for -log10 so a reported padj of 0 does not become infinity.
_PADJ_FLOOR = 1e-300

_COLOR_MODES = {
    "neg_log10_padj": ("Viridis", "-log10(padj)"),
    "abs_nes": ("YlOrRd", "|NES|"),
    "gene_count": ("Viridis", "gene count"),
    "nes_sign": (
        [[0.0, "#1f77b4"], [0.49, "#1f77b4"], [0.51, "#d62728"], [1.0, "#d62728"]],
        "NES sign",
    ),
}


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("term_col"),
        config.get("nes_col"),
        config.get("padj_col"),
        config.get("gene_count_col"),
        config.get("source_col"),
    ]


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@register("enrichment", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    term_col = config.get("term_col") or "term"
    nes_col = config.get("nes_col") or "nes"
    padj_col = config.get("padj_col") or "padj"
    count_col = config.get("gene_count_col") or "gene_count"
    source_col = config.get("source_col")

    top_n = int(controls.get("top_n", config.get("top_n", 20)))
    padj_threshold = float(controls.get("padj_threshold", config.get("padj_threshold", 0.05)))
    color_by = str(controls.get("color_by", "neg_log10_padj"))
    if color_by not in _COLOR_MODES:
        color_by = "neg_log10_padj"
    selected_sources = [str(s) for s in (controls.get("sources") or [])]

    terms = rows.get(term_col) or []
    nes_values = rows.get(nes_col) or []
    padj_values = rows.get(padj_col) or []
    counts = rows.get(count_col) or []
    sources = rows.get(source_col) if source_col else None

    collected: list[dict[str, Any]] = []
    for i in range(len(terms)):
        padj = _as_float(padj_values[i]) if i < len(padj_values) else None
        nes = _as_float(nes_values[i]) if i < len(nes_values) else None
        if padj is None or nes is None or padj > padj_threshold:
            continue
        source = str(sources[i]) if sources and i < len(sources) and sources[i] is not None else ""
        if selected_sources and sources and source not in selected_sources:
            continue
        collected.append(
            {
                "term": str(terms[i] if terms[i] is not None else ""),
                "nes": nes,
                "padj": padj,
                "count": _as_float(counts[i]) if i < len(counts) else 0.0,
                "source": source,
            }
        )

    collected.sort(key=lambda r: r["padj"])
    top = collected[:top_n]
    top.sort(key=lambda r: r["nes"])

    if not top:
        return {
            "data": [],
            "layout": {
                "annotations": [
                    {
                        "text": f"No terms at padj ≤ {padj_threshold}",
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

    count_values = [r["count"] or 0.0 for r in top]
    count_max = max([*count_values, 1.0])
    sizes = [6 + math.sqrt(c / count_max) * 24 for c in count_values]

    if color_by == "neg_log10_padj":
        color_values = [-math.log10(max(r["padj"], _PADJ_FLOOR)) for r in top]
    elif color_by == "abs_nes":
        color_values = [abs(r["nes"]) for r in top]
    elif color_by == "gene_count":
        color_values = count_values
    else:
        color_values = [float((r["nes"] > 0) - (r["nes"] < 0)) for r in top]

    colorscale, colorbar_title = _COLOR_MODES[color_by]

    marker: dict[str, Any] = {
        "size": sizes,
        "color": color_values,
        "colorscale": colorscale,
        "showscale": True,
        "colorbar": {
            "title": {"text": colorbar_title, "side": "right"},
            "thickness": 10,
            "len": 0.85,
        },
        "line": {"width": 0},
    }
    if color_by == "nes_sign":
        # A two-bucket palette needs an explicit domain, or the boundary
        # auto-fits to the data instead of landing on zero.
        marker["cmin"] = -1
        marker["cmax"] = 1
        marker["colorbar"].update({"tickvals": [-1, 1], "ticktext": ["down", "up"]})

    hovertemplate = (
        "<b>%{y}</b><br>NES: %{x:.2f}<br>padj: %{customdata[0]:.2e}<br>genes: %{customdata[1]}"
    )
    if source_col:
        hovertemplate += "<br>source: %{customdata[2]}"
    hovertemplate += "<extra></extra>"

    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "x": [r["nes"] for r in top],
                "y": [r["term"] for r in top],
                "customdata": [[r["padj"], r["count"], r["source"]] for r in top],
                "hovertemplate": hovertemplate,
                "marker": marker,
            }
        ],
        "layout": {
            # Wide left margin: pathway names are long and automargin alone
            # leaves them clipped on first paint.
            "margin": {"l": 220, "r": 60, "t": 16, "b": 48},
            "xaxis": {"title": {"text": "NES (normalized enrichment score)"}, "zeroline": True},
            "yaxis": {"automargin": True, "ticks": "", "showgrid": True},
            "showlegend": False,
        },
    }
