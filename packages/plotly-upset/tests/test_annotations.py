"""Tests for UpSetAnnotation and materialized tracks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from plotly_upset.annotations import (
    MaterializedBarTrack,
    MaterializedBoxTrack,
    MaterializedCategoricalTrack,
    MaterializedScatterTrack,
    MaterializedViolinTrack,
    UpSetAnnotation,
)
from plotly_upset.intersections import compute_intersections, filter_intersections


def _get_test_context(
    annotated_df: pd.DataFrame,
) -> tuple[dict, list[tuple[int, ...]]]:
    """Helper to compute intersection indices and order."""
    set_cols = ["SetA", "SetB", "SetC", "SetD"]
    matrix = annotated_df[set_cols].values.astype(int)
    result = compute_intersections(matrix, set_cols)
    result = filter_intersections(result, exclude_empty=True)
    return result.row_indices, result.patterns


class TestUpSetAnnotation:
    def test_string_spec(self, annotated_df: pd.DataFrame) -> None:
        """String spec auto-detects type from column dtype."""
        anno = UpSetAnnotation(data=annotated_df, score="score")
        assert anno.n_tracks == 1

    def test_dict_spec(self, annotated_df: pd.DataFrame) -> None:
        anno = UpSetAnnotation(
            data=annotated_df,
            quality={"column": "quality", "type": "bar", "agg": "median"},
        )
        assert anno.n_tracks == 1

    def test_multiple_tracks(self, annotated_df: pd.DataFrame) -> None:
        anno = UpSetAnnotation(
            data=annotated_df,
            score="score",
            quality={"column": "quality", "type": "bar"},
            category="category",
        )
        assert anno.n_tracks == 3

    def test_track_sizes(self, annotated_df: pd.DataFrame) -> None:
        anno = UpSetAnnotation(data=annotated_df, score="score")
        sizes = anno.track_sizes()
        assert len(sizes) == 1
        assert sizes[0] > 0


class TestMaterializeBox:
    def test_box_track(self, annotated_df: pd.DataFrame) -> None:
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(data=annotated_df, score="score")
        tracks = anno.materialize(indices, order)

        assert len(tracks) == 1
        track = tracks[0]
        assert isinstance(track, MaterializedBoxTrack)
        assert len(track.values) == len(order)

    def test_box_traces(self, annotated_df: pd.DataFrame) -> None:
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(data=annotated_df, score="score")
        tracks = anno.materialize(indices, order)

        positions = np.arange(len(order), dtype=float)
        traces = tracks[0].to_traces(positions)
        assert len(traces) > 0


class TestMaterializeViolin:
    def test_violin_track(self, annotated_df: pd.DataFrame) -> None:
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(
            data=annotated_df,
            score={"column": "score", "type": "violin"},
        )
        tracks = anno.materialize(indices, order)

        assert len(tracks) == 1
        assert isinstance(tracks[0], MaterializedViolinTrack)


class TestMaterializeBar:
    def test_bar_track(self, annotated_df: pd.DataFrame) -> None:
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(
            data=annotated_df,
            quality={"column": "quality", "type": "bar", "agg": "mean"},
        )
        tracks = anno.materialize(indices, order)

        assert len(tracks) == 1
        track = tracks[0]
        assert isinstance(track, MaterializedBarTrack)
        assert len(track.values) == len(order)

    def test_bar_traces(self, annotated_df: pd.DataFrame) -> None:
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(
            data=annotated_df,
            quality={"column": "quality", "type": "bar", "agg": "median"},
        )
        tracks = anno.materialize(indices, order)

        positions = np.arange(len(order), dtype=float)
        traces = tracks[0].to_traces(positions)
        assert len(traces) == 1


class TestMaterializeScatter:
    def test_scatter_track(self, annotated_df: pd.DataFrame) -> None:
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(
            data=annotated_df,
            quality={"column": "quality", "type": "scatter", "agg": "mean"},
        )
        tracks = anno.materialize(indices, order)

        assert len(tracks) == 1
        assert isinstance(tracks[0], MaterializedScatterTrack)


class TestMaterializeCategorical:
    def test_categorical_auto_detect(self, annotated_df: pd.DataFrame) -> None:
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(data=annotated_df, category="category")
        tracks = anno.materialize(indices, order)

        assert len(tracks) == 1
        track = tracks[0]
        assert isinstance(track, MaterializedCategoricalTrack)
        assert set(track.categories) == {"A", "B", "C"}
        assert len(track.proportions) == len(order)


class TestMaterializeCategoricalStacked:
    def test_categorical_stacked_traces(self, annotated_df: pd.DataFrame) -> None:
        """Categorical track now renders as vertical stacked Bar traces."""
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(data=annotated_df, category="category")
        tracks = anno.materialize(indices, order)

        track = tracks[0]
        positions = np.arange(len(order), dtype=float)
        traces = track.to_traces(positions)

        # Should have one Bar trace per category (A, B, C = 3)
        assert len(traces) == 3
        assert all(isinstance(t, go.Bar) for t in traces)

    def test_categorical_proportions_sum(self, annotated_df: pd.DataFrame) -> None:
        """Proportions for each intersection should sum to ~1.0."""
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(data=annotated_df, category="category")
        tracks = anno.materialize(indices, order)

        track = tracks[0]
        for props in track.proportions:
            if props:  # non-empty intersections
                total = sum(props.values())
                assert abs(total - 1.0) < 1e-6

    def test_categorical_legend_items_empty(self, annotated_df: pd.DataFrame) -> None:
        """Legend is now handled by Bar traces directly, so legend_items returns empty."""
        indices, order = _get_test_context(annotated_df)
        anno = UpSetAnnotation(data=annotated_df, category="category")
        tracks = anno.materialize(indices, order)
        assert tracks[0].legend_items() == []
