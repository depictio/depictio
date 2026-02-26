"""Legend assembly helpers."""

from __future__ import annotations

import plotly.graph_objects as go

from plotly_complexheatmap.annotations import HeatmapAnnotation


def collect_legend_items(
    *annotations: HeatmapAnnotation | None,
) -> list[go.Scatter]:
    """Gather discrete legend entries from all annotation tracks that provide them."""
    items: list[go.Scatter] = []
    for ha in annotations:
        if ha is None:
            continue
        for track in ha.tracks:
            items.extend(track.legend_items())
    return items
