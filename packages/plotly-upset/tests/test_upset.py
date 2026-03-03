"""Tests for the main UpSetPlot class."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from plotly_upset import UpSetAnnotation, UpSetPlot


class TestUpSetPlotBasic:
    def test_basic_plot(self, binary_df: pd.DataFrame) -> None:
        plot = UpSetPlot(binary_df)
        fig = plot.to_plotly()

        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_with_title(self, binary_df: pd.DataFrame) -> None:
        plot = UpSetPlot(binary_df, title="Test Plot", subtitle="A subtitle")
        fig = plot.to_plotly()

        assert fig.layout.title.text == "Test Plot"

    def test_sort_by_degree(self, binary_df: pd.DataFrame) -> None:
        plot = UpSetPlot(binary_df, sort_by="degree", sort_order="ascending")
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)

    def test_filtering(self, binary_df: pd.DataFrame) -> None:
        plot = UpSetPlot(binary_df, min_degree=1, max_degree=2)
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)

    def test_no_set_sizes(self, binary_df: pd.DataFrame) -> None:
        plot = UpSetPlot(binary_df, show_set_sizes=False)
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)

    def test_custom_colors(self, binary_df: pd.DataFrame) -> None:
        plot = UpSetPlot(binary_df, color="#FF0000", inactive_color="#EEEEEE")
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)

    def test_custom_size(self, binary_df: pd.DataFrame) -> None:
        plot = UpSetPlot(binary_df, width=1200, height=800, dot_size=16)
        fig = plot.to_plotly()

        assert fig.layout.width == 1200
        assert fig.layout.height == 800

    def test_set_columns_explicit(self, annotated_df: pd.DataFrame) -> None:
        plot = UpSetPlot(annotated_df, set_columns=["SetA", "SetB", "SetC", "SetD"])
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)


class TestUpSetPlotAnnotations:
    def test_with_box_annotation(self, annotated_df: pd.DataFrame) -> None:
        anno = UpSetAnnotation(data=annotated_df, score="score")
        plot = UpSetPlot(
            annotated_df,
            set_columns=["SetA", "SetB", "SetC", "SetD"],
            annotation=anno,
        )
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)

    def test_with_multiple_annotations(self, annotated_df: pd.DataFrame) -> None:
        anno = UpSetAnnotation(
            data=annotated_df,
            score="score",
            quality={"column": "quality", "type": "bar", "agg": "median"},
            category="category",
        )
        plot = UpSetPlot(
            annotated_df,
            set_columns=["SetA", "SetB", "SetC", "SetD"],
            annotation=anno,
        )
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)
        # Should have traces for bars + dot matrix + set sizes + annotations
        assert len(fig.data) > 3


class TestUpSetPlotFromSets:
    def test_from_sets(self) -> None:
        sets = {
            "A": {1, 2, 3, 4, 5},
            "B": {3, 4, 5, 6, 7},
            "C": {5, 6, 7, 8, 9},
        }
        plot = UpSetPlot.from_sets(sets)
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)

    def test_from_sets_with_metadata(self) -> None:
        sets = {
            "A": {1, 2, 3, 4, 5},
            "B": {3, 4, 5, 6, 7},
            "C": {5, 6, 7, 8, 9},
        }
        metadata = pd.DataFrame(
            {"value": [10, 20, 30, 40, 50, 60, 70, 80, 90]},
            index=[1, 2, 3, 4, 5, 6, 7, 8, 9],
        )
        anno = UpSetAnnotation(data=metadata, value="value")
        plot = UpSetPlot.from_sets(sets, data=metadata, annotation=anno)
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)


class TestUpSetPlotPolars:
    def test_polars_input(self, binary_df: pd.DataFrame) -> None:
        try:
            import polars as pl
        except ImportError:
            return  # Skip if polars not installed

        pl_df = pl.from_pandas(binary_df)
        plot = UpSetPlot(pl_df)
        fig = plot.to_plotly()
        assert isinstance(fig, go.Figure)
