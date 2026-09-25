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
    impute_for_clustering,
    masked_euclidean_condensed,
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


class TestImputeForClustering:
    def test_leaves_a_complete_matrix_alone(self, small_matrix: np.ndarray) -> None:
        out = impute_for_clustering(small_matrix)
        np.testing.assert_array_equal(out, small_matrix)

    def test_fills_holes_with_the_column_mean(self) -> None:
        data = np.array([[1.0, np.nan], [3.0, 4.0], [np.nan, 8.0]])
        out = impute_for_clustering(data)
        np.testing.assert_allclose(out, [[1.0, 6.0], [3.0, 4.0], [2.0, 8.0]])
        # the caller's array is untouched
        assert np.isnan(data[0, 1])

    def test_fills_an_empty_column_with_zero(self) -> None:
        data = np.array([[1.0, np.nan], [2.0, np.inf]])
        out = impute_for_clustering(data)
        np.testing.assert_allclose(out[:, 1], [0.0, 0.0])

    def test_measures_pairs_on_their_shared_features(self) -> None:
        n = np.nan
        data = np.array([[1.0, n], [1.0, 2.0], [4.0, n]])
        d01, d02, d12 = masked_euclidean_condensed(data)
        assert d01 == 0.0
        # one shared feature out of two, so the distance is scaled by sqrt(2)
        np.testing.assert_allclose(d02, 3.0 * np.sqrt(2.0))
        np.testing.assert_allclose(d12, 3.0 * np.sqrt(2.0))

    def test_pairs_with_nothing_in_common_are_the_farthest(self) -> None:
        n = np.nan
        data = np.array([[1.0, n], [2.0, n], [n, 5.0]])
        d01, d02, d12 = masked_euclidean_condensed(data)
        np.testing.assert_allclose(d01, np.sqrt(2.0))
        assert d02 == d12 == 2.0 * d01

    def test_block_diagonal_distances_cluster(self) -> None:
        # Two blocks of libraries that were never compared with each other:
        # the cross-block cells are empty, as a DESeq2 QC run per antibody
        # leaves them. scipy refused the whole matrix; a column-mean fill
        # would pair rows across the blocks.
        n = np.nan
        data = np.array(
            [
                [0.0, 1.0, n, n],
                [1.0, 0.0, n, n],
                [n, n, 0.0, 1.0],
                [n, n, 1.0, 0.0],
            ]
        )
        result = compute_dendrogram(data)
        order = result.leaf_order.tolist()
        assert sorted(order) == [0, 1, 2, 3]
        # each block stays together
        assert {order[0], order[1]} in ({0, 1}, {2, 3})


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
