"""Embedding scatter — PCA / PCoA / t-SNE / UMAP in two dimensions.

Port of ``advanced_viz/EmbeddingRenderer.tsx`` (the ``figure`` useMemo, lines
302-470). The shape of the figure depends on one question: is the colour column
categorical or continuous?

* **categorical** — one trace per category so Plotly draws a real legend, with
  colours assigned off the value *universe* (see ``palette.py``) so filtering
  does not reshuffle them.
* **continuous / unbound** — a single trace with a Spectral colorscale.

Scope notes, both matching the registry's documented "renders at persisted
config state" rule:

* **2D only.** The 3D toggle is browser state, and ``scatter3d`` needs a camera
  the export cannot know.
* **No density contours or centroid labels.** Both are toggles that default off.

In live-compute mode the Celery worker returns vectors keyed literally
``dim_1`` / ``dim_2`` rather than under configured column names, so the key
lookup falls back to those — the same fallback the TSX applies, and without it
the figure silently renders empty.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.color_scale import plotly_colorscale
from depictio.api.v1.services.advanced_viz.figure_registry import register
from depictio.api.v1.services.advanced_viz.palette import TAB10_PALETTE, stable_color_map

_DEFAULT_COLOR = "#4C72B0"


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("dim_1_col"),
        config.get("dim_2_col"),
        config.get("sample_id_col"),
        _default_color_column(config),
    ]


def _default_color_column(config: dict[str, Any]) -> str | None:
    """Colour binding the TSX defaults to: ``cluster_col || color_col || null``.

    Order matters and is easy to get backwards. ``cluster_col`` is a categorical
    assignment and produces the legend users expect; ``color_col`` is often a
    numeric coordinate and would silently render a continuous colorbar instead.
    """
    return config.get("cluster_col") or config.get("color_col")


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@register("embedding", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    dim1_key = config.get("dim_1_col") or "dim_1"
    dim2_key = config.get("dim_2_col") or "dim_2"
    sample_col = config.get("sample_id_col")
    color_col = controls.get("color_by") or _default_color_column(config)

    point_size = float(controls.get("point_size", config.get("point_size", 6)))

    xs = [_as_float(v) for v in (rows.get(dim1_key) or [])]
    ys = [_as_float(v) for v in (rows.get(dim2_key) or [])]
    ids = (
        [str(v if v is not None else "") for v in (rows.get(sample_col) or [])]
        if sample_col
        else []
    )
    color_values = rows.get(color_col) if color_col else None

    # Dense embeddings get smaller points, matching denseAutoSize in the TSX.
    size = min(point_size, 4.0) if len(xs) > 1000 else point_size
    marker_base = {"size": size, "opacity": 0.85, "line": {"width": 0}}

    def customdata(indices: list[int]) -> list[str]:
        return [ids[i] if i < len(ids) else "" for i in indices]

    is_categorical = bool(
        color_values
        and any(v is not None for v in color_values)
        and not isinstance(next((v for v in color_values if v is not None), None), (int, float))
    )

    data: list[dict[str, Any]] = []

    if is_categorical and color_values:
        categories = sorted({str(v) for v in color_values})
        colors = stable_color_map(color_values, TAB10_PALETTE, config.get("category_palette"))
        for category in categories:
            indices = [i for i, v in enumerate(color_values) if str(v) == category]
            data.append(
                {
                    "type": "scatter",
                    "mode": "markers",
                    "name": category,
                    "x": [xs[i] for i in indices],
                    "y": [ys[i] for i in indices],
                    "customdata": customdata(indices),
                    "hovertemplate": (
                        f"<b>%{{customdata}}</b><br>{category}"
                        f"<br>{dim1_key}: %{{x:.3f}}<br>{dim2_key}: %{{y:.3f}}<extra></extra>"
                    ),
                    "marker": {**marker_base, "color": colors.get(category)},
                }
            )
    else:
        numeric = [_as_float(v) for v in color_values] if color_values else None
        marker: dict[str, Any] = {**marker_base}
        if numeric is not None and any(v is not None for v in numeric):
            marker.update(
                {
                    "color": numeric,
                    "colorscale": plotly_colorscale("Spectral"),
                    "showscale": True,
                    "colorbar": {"title": {"text": str(color_col)}, "thickness": 12, "len": 0.9},
                }
            )
        else:
            marker["color"] = _DEFAULT_COLOR
        data.append(
            {
                "type": "scatter",
                "mode": "markers",
                "x": xs,
                "y": ys,
                "customdata": customdata(list(range(len(xs)))),
                "hovertemplate": (
                    f"<b>%{{customdata}}</b><br>{dim1_key}: %{{x:.3f}}"
                    f"<br>{dim2_key}: %{{y:.3f}}<extra></extra>"
                ),
                "marker": marker,
                "showlegend": False,
            }
        )

    method = str(config.get("compute_method") or "").upper()
    axis_label = method or "dim"

    return {
        "data": data,
        "layout": {
            "margin": {"l": 55, "r": 20, "t": 20, "b": 45},
            "xaxis": {
                "title": {"text": f"{axis_label} 1" if method else dim1_key},
                "zeroline": False,
            },
            "yaxis": {
                "title": {"text": f"{axis_label} 2" if method else dim2_key},
                "zeroline": False,
            },
            "showlegend": is_categorical,
            "legend": {"orientation": "v", "x": 1.02, "y": 1, "font": {"size": 10}},
            "hovermode": "closest",
        },
    }
