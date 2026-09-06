"""Integration tests for ComplexHeatmap."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from plotly_complexheatmap import ComplexHeatmap, HeatmapAnnotation

# Plotly 6+ removed Heatmapgl — detect once
_HEATMAP_TYPES: tuple[type, ...] = (go.Heatmap,)
if hasattr(go, "Heatmapgl"):
    _HEATMAP_TYPES = (go.Heatmap, go.Heatmapgl)


class TestBasicHeatmap:
    def test_minimal(self, small_matrix: np.ndarray) -> None:
        hm = ComplexHeatmap(small_matrix, cluster_rows=False, cluster_cols=False)
        fig = hm.to_plotly()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1

    def test_clustered(self, small_df: pd.DataFrame) -> None:
        hm = ComplexHeatmap(small_df, cluster_rows=True, cluster_cols=True)
        fig = hm.to_plotly()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 1

    def test_dataframe_labels(self, small_df: pd.DataFrame) -> None:
        hm = ComplexHeatmap(small_df, cluster_rows=False, cluster_cols=False)
        fig = hm.to_plotly()
        hm_trace = fig.data[0]
        assert isinstance(hm_trace, _HEATMAP_TYPES)


class TestAnnotations:
    def test_top_annotation(self, small_df: pd.DataFrame, col_groups: list[str]) -> None:
        top_ha = HeatmapAnnotation(group=col_groups)
        hm = ComplexHeatmap(small_df, top_annotation=top_ha, cluster_rows=False, cluster_cols=False)
        fig = hm.to_plotly()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 1

    def test_right_annotation(self, small_df: pd.DataFrame, row_groups: list[str]) -> None:
        right_ha = HeatmapAnnotation(cluster=row_groups, which="row")
        hm = ComplexHeatmap(small_df, right_annotation=right_ha, cluster_rows=False, cluster_cols=False)
        fig = hm.to_plotly()
        assert len(fig.data) > 1

    def test_both_annotations(self, small_df: pd.DataFrame, row_groups: list[str], col_groups: list[str]) -> None:
        top_ha = HeatmapAnnotation(group=col_groups)
        right_ha = HeatmapAnnotation(cluster=row_groups, which="row")
        hm = ComplexHeatmap(
            small_df,
            top_annotation=top_ha,
            right_annotation=right_ha,
        )
        fig = hm.to_plotly()
        assert isinstance(fig, go.Figure)


class TestSplitHeatmap:
    def test_split_by_list(self, small_df: pd.DataFrame) -> None:
        groups = ["A", "A", "B", "B", "C", "C"]
        hm = ComplexHeatmap(
            small_df,
            split_rows_by=groups,
            cluster_rows=True,
            cluster_cols=True,
        )
        fig = hm.to_plotly()
        assert isinstance(fig, go.Figure)
        hm_traces = [t for t in fig.data if isinstance(t, _HEATMAP_TYPES)]
        assert len(hm_traces) == 3

    def test_split_by_annotation_name(self, small_df: pd.DataFrame) -> None:
        groups = ["A", "A", "B", "B", "C", "C"]
        right_ha = HeatmapAnnotation(cluster=groups, which="row")
        hm = ComplexHeatmap(
            small_df,
            right_annotation=right_ha,
            split_rows_by="cluster",
        )
        fig = hm.to_plotly()
        # 3 main heatmaps + 3 categorical annotation heatmaps = 6 go.Heatmap total
        hm_traces = [t for t in fig.data if isinstance(t, _HEATMAP_TYPES)]
        assert len(hm_traces) == 6
        # Exactly 3 groups have z-data matching the data shape (4 columns)
        main_hm = [t for t in hm_traces if t.z is not None and np.asarray(t.z).shape[-1] == 4]
        assert len(main_hm) == 3


class TestWebGL:
    def test_auto_webgl_small(self) -> None:
        """Small matrix should use go.Heatmap (not WebGL)."""
        data = np.random.default_rng(0).standard_normal((10, 5))
        hm = ComplexHeatmap(data, cluster_rows=False, cluster_cols=False)
        fig = hm.to_plotly()
        assert isinstance(fig.data[0], go.Heatmap)

    def test_force_webgl(self) -> None:
        """When forcing WebGL, result is Heatmapgl on Plotly <6, Heatmap on Plotly 6+."""
        data = np.random.default_rng(0).standard_normal((10, 5))
        hm = ComplexHeatmap(data, cluster_rows=False, cluster_cols=False, use_webgl=True)
        fig = hm.to_plotly()
        assert isinstance(fig.data[0], _HEATMAP_TYPES)


class TestNormalization:
    def test_row_normalize(self, small_matrix: np.ndarray) -> None:
        hm = ComplexHeatmap(small_matrix, normalize="row", cluster_rows=False, cluster_cols=False)
        fig = hm.to_plotly()
        z = fig.data[0].z
        for row in z:
            assert abs(np.nanmean(row)) < 1e-10

    def test_column_normalize(self, small_matrix: np.ndarray) -> None:
        hm = ComplexHeatmap(small_matrix, normalize="column", cluster_rows=False, cluster_cols=False)
        fig = hm.to_plotly()
        z = np.array(fig.data[0].z)
        for col_idx in range(z.shape[1]):
            assert abs(np.nanmean(z[:, col_idx])) < 1e-10


class TestRowLabelDensity:
    """Row tick labels are dropped where the row pitch leaves no room."""

    @staticmethod
    def _frame(n_rows: int) -> pd.DataFrame:
        rng = np.random.default_rng(0)
        return pd.DataFrame(
            rng.standard_normal((n_rows, 4)),
            index=[f"interval_{i}" for i in range(n_rows)],
            columns=[f"sample_{j}" for j in range(4)],
        )

    def test_sparse_rows_keep_their_labels(self) -> None:
        hm = ComplexHeatmap(self._frame(12), height=700)
        hm.to_plotly()
        assert hm._row_labels_visible is True

    def test_dense_rows_drop_their_labels(self) -> None:
        hm = ComplexHeatmap(self._frame(250), height=700)
        fig = hm.to_plotly()
        assert hm._row_labels_visible is False
        assert not any(
            fig.layout[ax].showticklabels
            for ax in fig.layout
            if ax.startswith("yaxis") and fig.layout[ax].showticklabels
        )

    def test_dropping_the_labels_gives_the_map_their_margin(self) -> None:
        sparse = ComplexHeatmap(self._frame(12), height=700)
        dense = ComplexHeatmap(self._frame(250), height=700)
        assert dense.to_plotly().layout.margin.r < sparse.to_plotly().layout.margin.r

    def test_show_row_labels_overrides_the_density_rule(self) -> None:
        forced_on = ComplexHeatmap(self._frame(250), height=700, show_row_labels=True)
        forced_on.to_plotly()
        assert forced_on._row_labels_visible is True

        forced_off = ComplexHeatmap(self._frame(12), height=700, show_row_labels=False)
        forced_off.to_plotly()
        assert forced_off._row_labels_visible is False

    def test_a_taller_figure_fits_more_labels(self) -> None:
        short = ComplexHeatmap(self._frame(60), height=300)
        tall = ComplexHeatmap(self._frame(60), height=2000)
        short.to_plotly()
        tall.to_plotly()
        assert short._row_labels_visible is False
        assert tall._row_labels_visible is True
