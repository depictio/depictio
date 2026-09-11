"""Tests for the annotations module."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from plotly_complexheatmap.annotations import (
    CategoricalTrack,
    HeatmapAnnotation,
    NumericBarTrack,
    NumericScatterTrack,
    brick_gap,
)


class TestCategoricalTrack:
    def test_auto_assigns_colors(self) -> None:
        track = CategoricalTrack(name="group", values=["A", "B", "A", "C"])
        assert track.colors is not None
        assert set(track.colors.keys()) == {"A", "B", "C"}

    def test_custom_colors_preserved(self) -> None:
        colors = {"A": "#ff0000", "B": "#00ff00"}
        track = CategoricalTrack(name="group", values=["A", "B", "A"], colors=colors)
        assert track.colors == colors

    def test_to_traces_x(self) -> None:
        track = CategoricalTrack(name="type", values=["X", "Y", "X"])
        pos = np.arange(3, dtype=float)
        traces = track.to_traces("x", pos)
        assert len(traces) == 1
        assert isinstance(traces[0], go.Heatmap)
        assert traces[0].z.shape == (1, 3)

    def test_to_traces_y(self) -> None:
        track = CategoricalTrack(name="type", values=["X", "Y", "X"])
        pos = np.arange(3, dtype=float)
        traces = track.to_traces("y", pos)
        assert len(traces) == 1
        assert traces[0].z.shape == (3, 1)

    def test_legend_items(self) -> None:
        track = CategoricalTrack(name="grp", values=["A", "B", "C"])
        items = track.legend_items()
        assert len(items) == 3
        names = [it.name for it in items]
        assert "grp: A" in names


class TestAnnotationBrickDensity:
    """The border gap is dropped where the brick can't spare a pixel.

    Plotly paints each brick at ``span - gap`` px between integer-rounded
    boundaries. On a 500-row strip at tile height the span is ~1 px, so the
    unconditional 1 px gap left nothing to paint: the strip rendered blank
    while its legend listed every category with the right swatch. It read as a
    colour bug; it was a paint bug.
    """

    @staticmethod
    def _track() -> CategoricalTrack:
        return CategoricalTrack(name="consensus_set", values=["A", "B", "A", "B"])

    def test_a_dense_track_drops_its_border_gap(self) -> None:
        pos = np.arange(4, dtype=float)
        trace = self._track().to_traces("y", pos, pitch_px=0.95)[0]
        assert trace.ygap == 0
        # The cross axis spans the whole strip width — it keeps its border.
        assert trace.xgap == 1

    def test_a_sparse_track_keeps_its_border_gap(self) -> None:
        pos = np.arange(4, dtype=float)
        trace = self._track().to_traces("y", pos, pitch_px=20.0)[0]
        assert trace.ygap == 1
        assert trace.xgap == 1

    def test_a_dense_column_track_drops_the_gap_on_its_own_axis(self) -> None:
        pos = np.arange(4, dtype=float)
        trace = self._track().to_traces("x", pos, pitch_px=0.95)[0]
        assert trace.xgap == 0
        assert trace.ygap == 1

    def test_an_unknown_pitch_keeps_the_gap(self) -> None:
        """Callers that don't know the density get the pre-guard rendering."""
        pos = np.arange(4, dtype=float)
        trace = self._track().to_traces("y", pos)[0]
        assert trace.xgap == 1
        assert trace.ygap == 1

    def test_the_rule_is_the_paint_left_over_not_the_pitch(self) -> None:
        """A pitch wider than the gap can still be too thin to see.

        2.4 px per row is comfortably above a 1 px gap, yet what is left is 1.4
        px between integer-rounded boundaries: a pinstripe of background in the
        export, and nothing at all once the same figure is drawn into a shorter
        tile, because the gap is in pixels and does not scale with it.
        """
        pos = np.arange(4, dtype=float)
        assert self._track().to_traces("y", pos, pitch_px=2.4)[0].ygap == 0
        # The matrix asks for half that gap, so the same pitch still leaves it
        # 1.9 px — under the floor as well.
        assert brick_gap(2.4, 0.5) == 0
        # Two more pixels of room and the border is worth drawing again.
        assert brick_gap(4.4, 1.0) == 1.0


class TestNumericBarTrack:
    def test_to_traces_x(self) -> None:
        track = NumericBarTrack(name="expr", values=[1.0, 2.0, 3.0])
        pos = np.arange(3, dtype=float)
        traces = track.to_traces("x", pos)
        assert len(traces) == 1
        assert isinstance(traces[0], go.Bar)

    def test_to_traces_y(self) -> None:
        track = NumericBarTrack(name="expr", values=[1.0, 2.0, 3.0])
        pos = np.arange(3, dtype=float)
        traces = track.to_traces("y", pos)
        assert len(traces) == 1
        assert traces[0].orientation == "h"


class TestNumericScatterTrack:
    def test_to_traces(self) -> None:
        track = NumericScatterTrack(name="score", values=[0.5, 1.5, 2.5])
        pos = np.arange(3, dtype=float)
        traces = track.to_traces("x", pos)
        assert len(traces) == 1
        assert isinstance(traces[0], go.Scatter)
        assert traces[0].mode == "markers"


class TestHeatmapAnnotation:
    def test_infer_categorical(self) -> None:
        ha = HeatmapAnnotation(group=["A", "B", "A"])
        assert ha.n_tracks == 1
        assert isinstance(ha.tracks[0], CategoricalTrack)

    def test_infer_numeric(self) -> None:
        ha = HeatmapAnnotation(score=[1.0, 2.0, 3.0, 4.0])
        assert ha.n_tracks == 1
        assert isinstance(ha.tracks[0], NumericBarTrack)

    def test_multiple_tracks(self) -> None:
        ha = HeatmapAnnotation(
            group=["A", "B", "A"],
            score=[1.0, 2.0, 3.0],
        )
        assert ha.n_tracks == 2

    def test_dict_config(self) -> None:
        ha = HeatmapAnnotation(
            expr={"values": [1.0, 2.0, 3.0], "type": "scatter", "color": "#ff0000"},
        )
        assert ha.n_tracks == 1
        assert isinstance(ha.tracks[0], NumericScatterTrack)

    def test_reorder(self) -> None:
        ha = HeatmapAnnotation(group=["A", "B", "C"])
        order = np.array([2, 0, 1])
        reordered = ha.reorder(order)
        assert reordered.tracks[0].values == ["C", "A", "B"]

    def test_total_size(self) -> None:
        ha = HeatmapAnnotation(
            gap=0.01,
            a=["X", "Y"],
            b=[1.0, 2.0],
        )
        # categorical=0.025 + numeric_bar=0.06 + 1 gap × 0.01 = 0.095
        assert abs(ha.total_size() - 0.095) < 1e-6
