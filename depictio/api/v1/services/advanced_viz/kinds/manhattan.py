"""Manhattan plot — genome-wide scores laid out along a concatenated axis.

Port of ``advanced_viz/ManhattanRenderer.tsx`` (the ``figure`` useMemo, lines
147-585). The layout work is what makes this non-trivial: chromosomes have no
shared coordinate system, so each one is given a cumulative x-offset and the
axis is re-labelled with a tick at every chromosome's midpoint.

Scope note. The TS renderer supports a *Colour by* select over arbitrary
columns, with a categorical palette or a continuous colorbar depending on the
column's type. That is live control state with no persisted counterpart, so a
server-side export renders the default: chromosome colouring, or the two-tier
palette when a score threshold is set. Pass ``controls['color_by']`` to pin a
column explicitly.
"""

from __future__ import annotations

import math
import re
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register
from depictio.api.v1.services.trace_rendering import EXPORT_SCATTER_TYPE

#: GWAS-style alternating chromosome palette, mirroring ``_palette`` in the TSX.
_CHR_PALETTE: tuple[str, ...] = (
    "#1c7ed6",
    "#495057",
    "#0ca678",
    "#e8590c",
    "#7048e8",
    "#c2255c",
    "#1098ad",
    "#5c940d",
)

#: Tier colours when a threshold splits the points. Match the Volcano/MA scheme.
_COLOR_ABOVE = "#0ca678"
_COLOR_BELOW = "#e8590c"
_COLOR_DIM = "rgba(160,160,160,0.45)"
_COLOR_INACTIVE = "rgba(200,200,200,0.3)"

#: Score kinds bounded to [0, 1]. Plotly's autorange over-pads when top-N labels
#: sit at the ceiling, so these get an explicit range — same test as the TSX.
_BOUNDED_SCORE = re.compile(r"(af|allele frequency|frequency|proportion|fraction)", re.I)


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("chr_col"),
        config.get("pos_col"),
        config.get("score_col"),
        config.get("feature_col"),
    ]


def _chromosome_sort_key(label: str) -> int:
    """chr1..chr22, then X, Y, MT; unrecognised labels sort last."""
    stripped = re.sub(r"^chr", "", label, flags=re.I).upper()
    if stripped == "X":
        return 23
    if stripped == "Y":
        return 24
    if stripped in ("MT", "M"):
        return 25
    try:
        return int(stripped)
    except ValueError:
        return 100


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@register("manhattan", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    chr_col = config.get("chr_col") or "chr"
    pos_col = config.get("pos_col") or "pos"
    score_col = config.get("score_col") or "score"
    feature_col = config.get("feature_col")

    threshold = controls.get("score_threshold", config.get("score_threshold"))
    threshold = _as_float(threshold) if threshold is not None else None
    top_n = int(controls.get("top_n_labels", config.get("top_n_labels", 8)))
    highlight = str(controls.get("highlight", config.get("highlight", "above")))
    size_above = float(controls.get("marker_size_above", config.get("marker_size_above", 6)))
    size_below = float(controls.get("marker_size_below", config.get("marker_size_below", 4)))
    size_uniform = float(controls.get("marker_size_uniform", config.get("marker_size_uniform", 5)))
    selected = [str(c) for c in (controls.get("selected_chromosomes") or [])]

    chrs = [str(v if v is not None else "") for v in (rows.get(chr_col) or [])]
    positions = [_as_float(v) or 0.0 for v in (rows.get(pos_col) or [])]
    scores = [_as_float(v) for v in (rows.get(score_col) or [])]
    features = (
        [str(v if v is not None else "") for v in (rows.get(feature_col) or [])]
        if feature_col
        else []
    )

    all_chrs = sorted(set(chrs), key=_chromosome_sort_key)
    active = set(selected) if selected else set(all_chrs)

    # Concatenated axis: each chromosome occupies [offset, offset + its max pos],
    # separated by 2% of the largest chromosome so blocks do not butt together.
    max_pos: dict[str, float] = {}
    for i, name in enumerate(chrs):
        pos = positions[i] if i < len(positions) else 0.0
        if pos > max_pos.get(name, 0.0):
            max_pos[name] = pos
    global_max = max(max_pos.values(), default=0.0)
    padding = max(1.0, round(global_max * 0.02))

    offsets: dict[str, float] = {}
    spans: dict[str, tuple[float, float, float]] = {}
    cursor = 0.0
    for name in all_chrs:
        offsets[name] = cursor
        span = max_pos.get(name, 0.0)
        spans[name] = (cursor, cursor + span, cursor + span / 2)
        cursor = cursor + span + padding
    total_span = cursor

    xs = [
        offsets.get(name, 0.0) + (positions[i] if i < len(positions) else 0.0)
        for i, name in enumerate(chrs)
    ]

    tiers: list[str] | None = None
    if threshold is not None:
        tiers = ["ABOVE" if (s is not None and s >= threshold) else "BELOW" for s in scores]

    chr_colors = {name: _CHR_PALETTE[i % len(_CHR_PALETTE)] for i, name in enumerate(all_chrs)}

    def point_color(index: int, name: str) -> str:
        if name not in active:
            return _COLOR_INACTIVE
        if tiers and highlight != "none":
            is_above = tiers[index] == "ABOVE"
            highlighted = is_above if highlight == "above" else not is_above
            if not highlighted:
                return _COLOR_DIM
        if tiers:
            return _COLOR_ABOVE if tiers[index] == "ABOVE" else _COLOR_BELOW
        return chr_colors.get(name, "#777")

    colors = [point_color(i, name) for i, name in enumerate(chrs)]

    if tiers:
        sizes: Any = [
            (
                (size_above if tier == "ABOVE" else size_below)
                if highlight == "none"
                else (
                    size_above
                    if (tier == "ABOVE" if highlight == "above" else tier != "ABOVE")
                    else size_below
                )
            )
            for tier in tiers
        ]
    else:
        sizes = size_uniform

    # Alternating background bands, one per even-indexed chromosome.
    band = "rgba(0,0,0,0.04)" if theme != "dark" else "rgba(255,255,255,0.04)"
    shapes: list[dict[str, Any]] = [
        {
            "type": "rect",
            "xref": "x",
            "yref": "paper",
            "x0": spans[name][0],
            "x1": spans[name][1],
            "y0": 0,
            "y1": 1,
            "fillcolor": band,
            "line": {"width": 0},
            "layer": "below",
        }
        for index, name in enumerate(all_chrs)
        if index % 2 == 0
    ]

    if threshold is not None:
        shapes.append(
            {
                "type": "line",
                "xref": "paper",
                "x0": 0,
                "x1": 1,
                "y0": threshold,
                "y1": threshold,
                "line": {"dash": "solid", "color": "rgba(214,51,108,0.85)", "width": 1.5},
            }
        )

    annotations: list[dict[str, Any]] = []
    if top_n > 0:
        candidates = []
        for i, name in enumerate(chrs):
            if name not in active:
                continue
            if threshold is not None and highlight != "none":
                score = scores[i]
                is_above = score is not None and score >= threshold
                highlighted = is_above if highlight == "above" else not is_above
                if not highlighted:
                    continue
            candidates.append(i)
        # Highlighting the sub-threshold side means the *lowest* scores matter.
        reverse = not (threshold is not None and highlight == "below")
        candidates.sort(
            key=lambda i: scores[i] if scores[i] is not None else math.inf, reverse=reverse
        )
        for i in candidates[:top_n]:
            label = (
                features[i]
                if i < len(features) and features[i]
                else f"{chrs[i]}:{positions[i]:.0f}"
            )
            annotations.append(
                {
                    "x": xs[i],
                    "y": scores[i],
                    "text": label,
                    "showarrow": True,
                    "arrowhead": 0,
                    "arrowsize": 0.7,
                    "arrowwidth": 1,
                    "ax": 0,
                    "ay": -20,
                    "font": {"size": 10},
                    "bgcolor": "rgba(255,255,255,0.85)",
                    "bordercolor": "rgba(0,0,0,0.2)",
                    "borderwidth": 1,
                    "borderpad": 2,
                }
            )

    score_title = config.get("score_kind") or score_col
    y_axis: dict[str, Any] = {"title": {"text": score_title}, "zeroline": False}
    if _BOUNDED_SCORE.search(str(config.get("score_kind") or "")):
        y_axis.update({"range": [0, 1.05], "autorange": False})

    trace = {
        # This file's own reasoning, now the shared rule: an exported spec may be
        # rendered where there is no WebGL context to spare, so SVG unless the
        # point count genuinely needs the GPU. See services/trace_rendering.py.
        "type": EXPORT_SCATTER_TYPE,
        "mode": "markers",
        "x": xs,
        "y": scores,
        "text": features if features else chrs,
        "customdata": chrs,
        "hovertemplate": "chr %{customdata}, pos %{x}<br>score: %{y}<br>%{text}<extra></extra>",
        "marker": {"color": colors, "size": sizes, "opacity": 0.85},
        "showlegend": False,
    }

    return {
        "data": [trace],
        "layout": {
            "margin": {"l": 55, "r": 20, "t": 10, "b": 8 if len(all_chrs) <= 1 else 22},
            "xaxis": {
                "zeroline": False,
                "showgrid": False,
                "tickmode": "array",
                "tickvals": [spans[name][2] for name in all_chrs],
                "ticktext": [re.sub(r"^chr", "", name, flags=re.I) for name in all_chrs],
                "showticklabels": len(all_chrs) > 1,
                "range": [0, total_span],
            },
            "yaxis": y_axis,
            "shapes": shapes,
            "annotations": annotations,
            "showlegend": False,
        },
    }
