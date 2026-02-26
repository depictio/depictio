"""Tests for the annotations module."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from plotly_complexheatmap.annotations import (
    CategoricalTrack,
    HeatmapAnnotation,
    NumericBarTrack,
    NumericScatterTrack,
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
