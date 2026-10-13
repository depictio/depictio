"""Placement of the colour key (legend + colorbar) in the right margin.

These lock in the property that made the key collide with the tick labels in
Depictio: the key used to be positioned with paper-space fractions derived from
``self.width``, and paper x is a fraction of the plotting area rather than of the
figure, so the two only agreed while the figure was rendered at exactly that
width. Responsive consumers drop width/height, and the key then slid inwards over
the row labels. The key is now anchored to the container's right edge and the
right margin is sized to hold the row labels beside it.
"""

from __future__ import annotations

import pandas as pd

from plotly_complexheatmap import ComplexHeatmap, HeatmapAnnotation


def _annotated_heatmap(row_label_len: int = 24) -> ComplexHeatmap:
    """Heatmap with a categorical top annotation, so a legend is emitted."""
    df = pd.DataFrame(
        [[1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0], [2.0, 2.0, 3.0, 3.0]],
        index=[f"row_{i}".ljust(row_label_len, "x") for i in range(3)],
        columns=[f"sample_{j}" for j in range(4)],
    )
    return ComplexHeatmap(
        df,
        top_annotation=HeatmapAnnotation(habitat=["Soil", "Soil", "Water", "Water"]),
        cluster_rows=False,
        cluster_cols=False,
    )


class TestKeyPlacement:
    def test_legend_anchored_to_container_edge(self) -> None:
        legend = _annotated_heatmap().to_plotly().layout.legend
        assert legend.xref == "container"
        assert legend.x == 1.0
        assert legend.xanchor == "right"

    def test_colorbar_anchored_to_container_edge(self) -> None:
        fig = _annotated_heatmap().to_plotly()
        colorbars = [t.colorbar for t in fig.data if getattr(t, "colorbar", None) is not None]
        bar = next(cb for cb in colorbars if cb.xref is not None)
        assert bar.xref == "container"
        assert bar.x == 1.0
        assert bar.xanchor == "right"
        # Bottom-aligned so it shares the band with the top-anchored legend
        # without the two ever meeting.
        assert bar.yanchor == "bottom"

    def test_key_placement_is_independent_of_declared_width(self) -> None:
        """A different ``width`` must not move the key, only the canvas."""
        narrow = _annotated_heatmap()
        narrow.width = 400
        wide = _annotated_heatmap()
        wide.width = 1600
        narrow_legend = narrow.to_plotly().layout.legend
        wide_legend = wide.to_plotly().layout.legend
        assert narrow_legend.x == wide_legend.x
        assert narrow.to_plotly().layout.margin.r == wide.to_plotly().layout.margin.r

    def test_right_margin_holds_row_labels_beside_the_key(self) -> None:
        """Row labels sit inside the margin, the key beside them, never on top."""
        short = _annotated_heatmap(row_label_len=8).to_plotly().layout.margin.r
        long = _annotated_heatmap(row_label_len=40).to_plotly().layout.margin.r
        # The whole extra label width has to be reserved, otherwise the key
        # (anchored to the far edge) would be drawn over the labels.
        assert long - short >= (40 - 8) * 7
