"""Tests for intersection computation engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from plotly_upset.intersections import (
    IntersectionResult,
    compute_intersections,
    compute_set_sizes,
    filter_intersections,
    sort_intersections,
)


class TestComputeIntersections:
    def test_basic(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))

        assert isinstance(result, IntersectionResult)
        assert len(result.set_names) == 4
        # 2^4 = 16 possible patterns
        assert len(result.patterns) == 16
        assert len(result.sizes) == 16
        assert len(result.degrees) == 16

    def test_row_indices_sum(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))

        # All row indices should cover all rows exactly once
        all_indices = np.concatenate(list(result.row_indices.values()))
        assert len(all_indices) == len(binary_df)
        assert set(all_indices) == set(range(len(binary_df)))

    def test_sizes_sum(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))

        # Total size across all intersections must equal number of rows
        assert result.sizes.sum() == len(binary_df)

    def test_degrees(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))

        # Degree 0 = (0,0,0,0) pattern
        zero_idx = result.patterns.index((0, 0, 0, 0))
        assert result.degrees[zero_idx] == 0

        # Full intersection = (1,1,1,1) pattern
        full_idx = result.patterns.index((1, 1, 1, 1))
        assert result.degrees[full_idx] == 4

    def test_specific_pattern(self) -> None:
        # Known data: 3 rows, 2 sets
        df = pd.DataFrame({"A": [1, 1, 0], "B": [0, 1, 1]})
        matrix = df.values.astype(int)
        result = compute_intersections(matrix, ["A", "B"])

        # Pattern (1,0): row 0
        assert result.row_indices[(1, 0)].tolist() == [0]
        # Pattern (1,1): row 1
        assert result.row_indices[(1, 1)].tolist() == [1]
        # Pattern (0,1): row 2
        assert result.row_indices[(0, 1)].tolist() == [2]
        # Pattern (0,0): no rows
        assert len(result.row_indices[(0, 0)]) == 0


class TestFilterIntersections:
    def test_exclude_empty(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))
        filtered = filter_intersections(result, exclude_empty=True)

        assert all(s > 0 for s in filtered.sizes)
        assert len(filtered.patterns) < len(result.patterns)

    def test_min_size(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))
        filtered = filter_intersections(result, exclude_empty=True, min_size=2)

        assert all(s >= 2 for s in filtered.sizes)

    def test_max_degree(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))
        filtered = filter_intersections(result, exclude_empty=True, max_degree=2)

        assert all(d <= 2 for d in filtered.degrees)

    def test_min_degree(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))
        filtered = filter_intersections(result, exclude_empty=True, min_degree=1)

        assert all(d >= 1 for d in filtered.degrees)


class TestSortIntersections:
    def test_sort_by_cardinality_descending(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))
        result = filter_intersections(result, exclude_empty=True)
        sorted_result = sort_intersections(result, sort_by="cardinality", sort_order="descending")

        sizes = sorted_result.sizes.tolist()
        assert sizes == sorted(sizes, reverse=True)

    def test_sort_by_degree_ascending(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))
        result = filter_intersections(result, exclude_empty=True)
        sorted_result = sort_intersections(result, sort_by="degree", sort_order="ascending")

        degrees = sorted_result.degrees.tolist()
        assert degrees == sorted(degrees)

    def test_sort_input_preserves_order(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))
        sorted_result = sort_intersections(result, sort_by="input")

        assert sorted_result.patterns == result.patterns

    def test_invalid_sort_by(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        result = compute_intersections(matrix, list(binary_df.columns))

        with pytest.raises(ValueError, match="Unknown sort_by"):
            sort_intersections(result, sort_by="invalid")


class TestComputeSetSizes:
    def test_basic(self, binary_df: pd.DataFrame) -> None:
        matrix = binary_df.values.astype(int)
        sizes = compute_set_sizes(matrix, list(binary_df.columns))

        assert isinstance(sizes, dict)
        assert len(sizes) == 4
        for name in binary_df.columns:
            assert sizes[name] == binary_df[name].sum()
