"""Tests for the clustering module."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from plotly_complexheatmap.clustering import (
    DendrogramResult,
    _rescale_coords,
    compute_dendrogram,
    compute_linkage,
    dendrogram_traces,
)


class TestComputeLinkage:
    def test_returns_2d_array(self, small_matrix: np.ndarray) -> None:
        Z = compute_linkage(small_matrix)
        assert Z.ndim == 2
        # linkage matrix has (n-1) rows and 4 columns
        assert Z.shape == (small_matrix.shape[0] - 1, 4)

    def test_different_methods(self, small_matrix: np.ndarray) -> None:
        for method in ("ward", "single", "complete", "average"):
            Z = compute_linkage(small_matrix, method=method)
            assert Z.shape[0] == small_matrix.shape[0] - 1


class TestComputeDendrogram:
    def test_returns_dendro_result(self, small_matrix: np.ndarray) -> None:
        result = compute_dendrogram(small_matrix)
        assert isinstance(result, DendrogramResult)

    def test_leaf_order_is_permutation(self, small_matrix: np.ndarray) -> None:
        result = compute_dendrogram(small_matrix)
        assert sorted(result.leaf_order.tolist()) == list(range(small_matrix.shape[0]))

    def test_icoord_dcoord_same_length(self, small_matrix: np.ndarray) -> None:
        result = compute_dendrogram(small_matrix)
        assert len(result.icoord) == len(result.dcoord)
        # Each segment has exactly 4 points
        for seg in result.icoord:
            assert len(seg) == 4


class TestRescaleCoords:
    def test_maps_leaf_positions(self) -> None:
        # 3 leaves at positions 5, 15, 25
        coords = [[5.0, 5.0, 15.0, 15.0]]
        rescaled = _rescale_coords(coords, 3)
        assert rescaled == [[0.0, 0.0, 1.0, 1.0]]


class TestDendrogramTraces:
    def test_returns_scatter_traces(self, small_matrix: np.ndarray) -> None:
        result = compute_dendrogram(small_matrix)
        traces = dendrogram_traces(result, orientation="top")
        assert len(traces) > 0
        for tr in traces:
            assert isinstance(tr, go.Scatter)
            assert tr.mode == "lines"
            assert tr.showlegend is False

    def test_left_orientation(self, small_matrix: np.ndarray) -> None:
        result = compute_dendrogram(small_matrix)
        traces = dendrogram_traces(result, orientation="left")
        assert len(traces) > 0
        # For left orientation, x values should be ≤ 0 (root on left)
        for tr in traces:
            assert all(x <= 0 for x in tr.x)
