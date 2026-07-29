"""Sunburst — hierarchical composition across ranked columns.

Port of ``advanced_viz/SunburstRenderer.tsx`` (the ``figure`` useMemo, lines
134-240).

The whole job is turning wide tidy rows into Plotly's flat parent/child arrays.
Each row carries one value per rank column (kingdom, phylum, genus, …) plus a
leaf abundance; walking the ranks builds a path, and the leaf's abundance is
accumulated into *every prefix* of that path.

Two details are load-bearing:

* **ids encode the whole path**, not the local label. Two genera under different
  phyla can share a name, and using bare labels silently merges them.
* **``branchvalues='total'``** tells Plotly the parent value already includes its
  children. Omitting it makes every ring sum its children again and the chart
  reads as inflated toward the centre.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register
from depictio.api.v1.services.advanced_viz.palette import TAB10_PALETTE, stable_color_map

#: Three rings by default: enough to read the hierarchy without outer slivers
#: so thin the chart looks like a sankey. Mirrors DEFAULT_DEPTH in the TSX.
_DEFAULT_DEPTH = 3

#: Drop nodes below this share of the root total, as a percentage.
_DEFAULT_MIN_PERCENT = 0.5

_PATH_SEPARATOR = " | "


def _rank_columns(config: dict[str, Any]) -> list[str]:
    return [str(c) for c in (config.get("rank_cols") or []) if c]


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [config.get("abundance_col"), *_rank_columns(config)]


def _as_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


@register("sunburst", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    ranks = _rank_columns(config)
    abundance_col = config.get("abundance_col") or "abundance"

    if len(ranks) < 2:
        return {
            "data": [],
            "layout": {
                "annotations": [
                    {
                        "text": "Sunburst needs at least two rank columns",
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

    start = max(0, min(len(ranks) - 1, int(controls.get("start_rank", 0))))
    depth = max(1, min(len(ranks) - start, int(controls.get("max_depth", _DEFAULT_DEPTH))))
    visible_ranks = ranks[start : start + depth]
    color_by = max(0, min(len(visible_ranks) - 1, int(controls.get("color_by_rank", 0)) - start))
    min_percent = float(controls.get("min_percent", _DEFAULT_MIN_PERCENT))
    show_counts = bool(controls.get("show_counts", False))

    abundance = rows.get(abundance_col) or []
    rank_values = [rows.get(rank) or [] for rank in visible_ranks]

    nodes: dict[str, dict[str, Any]] = {}
    for i in range(len(abundance)):
        value = _as_float(abundance[i])
        path = ""
        parent = ""
        color_key = ""
        for level in range(depth):
            column = rank_values[level]
            raw = column[i] if i < len(column) else None
            if raw is None or raw == "":
                break
            label = str(raw)
            path = f"{path}{_PATH_SEPARATOR}{label}" if path else label
            if level == color_by:
                color_key = label
            existing = nodes.get(path)
            if existing:
                existing["value"] += value
            else:
                nodes[path] = {
                    "label": label,
                    "parent": parent,
                    "value": value,
                    "color_key": color_key or label,
                }
            parent = path

    total = sum(n["value"] for n in nodes.values() if n["parent"] == "")
    floor = total * (min_percent / 100) if total > 0 else 0.0

    ids: list[str] = []
    labels: list[str] = []
    parents: list[str] = []
    values: list[float] = []
    color_keys: list[str] = []
    for path, node in nodes.items():
        if node["value"] < floor:
            continue
        ids.append(path)
        labels.append(node["label"])
        parents.append(node["parent"])
        values.append(node["value"])
        color_keys.append(node["color_key"])

    colors_map = stable_color_map(color_keys, TAB10_PALETTE, config.get("category_palette"))
    colors = [colors_map.get(key, "#aaa") for key in color_keys]

    if show_counts and total > 0:
        # Only annotate slices big enough to hold the text.
        text = [
            f"{label}\n{values[i] / total * 100:.1f}%" if values[i] / total * 100 >= 1 else label
            for i, label in enumerate(labels)
        ]
    else:
        text = labels

    return {
        "data": [
            {
                "type": "sunburst",
                "ids": ids,
                "labels": text,
                "parents": parents,
                "values": values,
                "branchvalues": "total",
                "marker": {"colors": colors, "line": {"color": "#fff", "width": 0.5}},
                "hovertemplate": (
                    f"<b>%{{label}}</b><br>{abundance_col}: %{{value}}"
                    "<br>share: %{percentRoot:.2%}<extra></extra>"
                ),
                "insidetextorientation": "auto",
                "maxdepth": depth + 1,
            }
        ],
        "layout": {"margin": {"l": 0, "r": 0, "t": 20, "b": 0}},
    }
