"""Integration tests for ComplexHeatmap."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

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


class TestBrickDensity:
    """Border gaps are dropped where the brick is too thin to survive them.

    Reproduces the chipseq "Consensus signal heatmap": a 500-row DC with two
    categorical row-annotation strips. At the figure height the strips get ~1.3
    px per row, so the unconditional 1 px ``ygap`` painted nothing at all and
    both strips came out blank — with a complete, correctly coloured legend
    beside them.
    """

    @staticmethod
    def _frame(n_rows: int) -> pd.DataFrame:
        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            rng.standard_normal((n_rows, 6)),
            index=[f"interval_{i}" for i in range(n_rows)],
            columns=[f"sample_{j}" for j in range(6)],
        )
        df["consensus_set"] = ["EZH2_IP", "FOXA1_IP"] * (n_rows // 2)
        df["support"] = ["2", "3"] * (n_rows // 2)
        return df

    @classmethod
    def _figure(cls, n_rows: int) -> go.Figure:
        return ComplexHeatmap.from_dataframe(
            cls._frame(n_rows),
            value_columns=[f"sample_{j}" for j in range(6)],
            row_annotations=["consensus_set", "support"],
            row_annotation_side="right",
        ).to_plotly()

    @staticmethod
    def _strips(fig: go.Figure, n_rows: int) -> list[go.Heatmap]:
        """The single-column annotation heatmaps, one per track."""
        return [t for t in fig.data if getattr(t, "z", None) is not None and np.asarray(t.z).shape == (n_rows, 1)]

    @staticmethod
    def _matrix(fig: go.Figure, n_rows: int) -> go.Heatmap:
        return next(t for t in fig.data if getattr(t, "z", None) is not None and np.asarray(t.z).shape == (n_rows, 6))

    def test_dense_strips_are_painted(self) -> None:
        fig = self._figure(500)
        strips = self._strips(fig, 500)
        assert len(strips) == 2
        assert all(s.ygap == 0 for s in strips)

    def test_the_dense_matrix_keeps_its_full_cell_too(self) -> None:
        assert self._matrix(self._figure(500), 500).ygap == 0

    def test_sparse_strips_keep_their_border(self) -> None:
        fig = self._figure(20)
        strips = self._strips(fig, 20)
        assert len(strips) == 2
        assert all(s.ygap == 1 for s in strips)
        assert self._matrix(fig, 20).ygap == 0.5

    def test_the_density_that_shipped_blank_is_covered(self) -> None:
        """250 rows: the density the chipseq tile actually renders at.

        The first guard compared the raw pitch against 2 px and measured it
        against the whole figure height, so 250 rows came out at 2.56 px and
        kept the full gap — 1.5 px of paint in the export, and none at all once
        a responsive consumer drew the same figure into a shorter tile. The rule
        is now about the paint that survives the gap, over the plot area rather
        than the figure.
        """
        fig = self._figure(250)
        strips = self._strips(fig, 250)
        assert len(strips) == 2
        assert all(s.ygap == 0 for s in strips)
        assert self._matrix(fig, 250).ygap == 0

    def test_the_margins_come_off_before_the_rows_are_measured(self) -> None:
        """The grid fractions divide the plot area, not the figure."""
        hm = ComplexHeatmap.from_dataframe(
            self._frame(250),
            value_columns=[f"sample_{j}" for j in range(6)],
            row_annotations=["consensus_set", "support"],
            row_annotation_side="right",
        )
        layout = hm._build_layout()
        top, bottom = hm._vertical_margins()
        assert top + bottom > 0
        pitch = hm._row_pitch_px(layout, layout.heatmap_cells[0], 250)
        fraction = layout.row_heights[layout.heatmap_cells[0][0] - 1]
        assert pitch == pytest.approx((hm.height - top - bottom) * fraction / 250)
        assert pitch < hm.height * fraction / 250
