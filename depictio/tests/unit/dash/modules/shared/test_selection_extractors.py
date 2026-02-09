"""
Unit tests for selection value extraction functions.

Tests cover:
- Scatter plot selection extraction (selectedData, clickData)
- Table row selection extraction (selectedRows)
"""

from depictio.dash.modules.figure_component.callbacks.selection import (
    extract_scatter_selection_values,
)
from depictio.dash.modules.table_component.callbacks.selection import (
    extract_row_selection_values,
)


class TestExtractScatterSelectionValues:
    """Tests for extract_scatter_selection_values function."""

    def test_extracts_from_selected_data_array_customdata(self):
        """Should extract values from selectedData with array customdata."""
        selected_data = {
            "points": [
                {"pointIndex": 0, "customdata": ["sample1", "cluster_a"]},
                {"pointIndex": 1, "customdata": ["sample2", "cluster_b"]},
                {"pointIndex": 2, "customdata": ["sample3", "cluster_a"]},
            ]
        }

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=0)

        assert set(result) == {"sample1", "sample2", "sample3"}

    def test_extracts_different_column_index(self):
        """Should extract from specified column index."""
        selected_data = {
            "points": [
                {"pointIndex": 0, "customdata": ["sample1", "cluster_a"]},
                {"pointIndex": 1, "customdata": ["sample2", "cluster_b"]},
            ]
        }

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=1)

        assert set(result) == {"cluster_a", "cluster_b"}

    def test_extracts_from_click_data(self):
        """Should extract from clickData when selectedData is None."""
        click_data = {"points": [{"pointIndex": 0, "customdata": ["clicked_sample", "group"]}]}

        result = extract_scatter_selection_values(None, click_data, selection_column_index=0)

        assert result == ["clicked_sample"]

    def test_prefers_selected_data_over_click_data(self):
        """Should prefer selectedData when both are present."""
        selected_data = {"points": [{"pointIndex": 0, "customdata": ["from_selected"]}]}
        click_data = {"points": [{"pointIndex": 0, "customdata": ["from_click"]}]}

        result = extract_scatter_selection_values(
            selected_data, click_data, selection_column_index=0
        )

        assert result == ["from_selected"]

    def test_handles_single_value_customdata(self):
        """Should handle non-array customdata."""
        selected_data = {
            "points": [
                {"pointIndex": 0, "customdata": "single_value"},
                {"pointIndex": 1, "customdata": "another_value"},
            ]
        }

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=0)

        assert set(result) == {"single_value", "another_value"}

    def test_ignores_single_value_for_non_zero_index(self):
        """Should ignore single value customdata when index > 0."""
        selected_data = {
            "points": [
                {"pointIndex": 0, "customdata": "single_value"},
            ]
        }

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=1)

        assert result == []

    def test_returns_empty_for_none_inputs(self):
        """Should return empty list when both inputs are None."""
        result = extract_scatter_selection_values(None, None, selection_column_index=0)

        assert result == []

    def test_returns_empty_for_empty_points(self):
        """Should return empty list when points array is empty."""
        selected_data = {"points": []}

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=0)

        assert result == []

    def test_skips_points_without_customdata(self):
        """Should skip points that have no customdata."""
        selected_data = {
            "points": [
                {"pointIndex": 0, "customdata": ["value1"]},
                {"pointIndex": 1},  # No customdata
                {"pointIndex": 2, "customdata": None},  # Explicit None
                {"pointIndex": 3, "customdata": ["value2"]},
            ]
        }

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=0)

        assert set(result) == {"value1", "value2"}

    def test_skips_none_values_in_customdata(self):
        """Should skip None values in customdata array."""
        selected_data = {
            "points": [
                {"pointIndex": 0, "customdata": [None, "cluster_a"]},
                {"pointIndex": 1, "customdata": ["sample2", "cluster_b"]},
            ]
        }

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=0)

        assert result == ["sample2"]

    def test_handles_index_out_of_range(self):
        """Should handle index beyond customdata array length."""
        selected_data = {
            "points": [
                {"pointIndex": 0, "customdata": ["only_one"]},
            ]
        }

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=5)

        assert result == []

    def test_deduplicates_values(self):
        """Should return unique values only."""
        selected_data = {
            "points": [
                {"pointIndex": 0, "customdata": ["duplicate"]},
                {"pointIndex": 1, "customdata": ["duplicate"]},
                {"pointIndex": 2, "customdata": ["unique"]},
            ]
        }

        result = extract_scatter_selection_values(selected_data, None, selection_column_index=0)

        assert len(result) == 2
        assert set(result) == {"duplicate", "unique"}


class TestExtractRowSelectionValues:
    """Tests for extract_row_selection_values function."""

    def test_extracts_column_values(self):
        """Should extract values from specified column."""
        selected_rows = [
            {"ID": 1, "sample_id": "S1", "name": "Sample 1"},
            {"ID": 2, "sample_id": "S2", "name": "Sample 2"},
            {"ID": 3, "sample_id": "S3", "name": "Sample 3"},
        ]

        result = extract_row_selection_values(selected_rows, "sample_id")

        assert set(result) == {"S1", "S2", "S3"}

    def test_extracts_different_column(self):
        """Should extract from different column."""
        selected_rows = [
            {"ID": 1, "sample_id": "S1", "name": "Sample 1"},
            {"ID": 2, "sample_id": "S2", "name": "Sample 2"},
        ]

        result = extract_row_selection_values(selected_rows, "name")

        assert set(result) == {"Sample 1", "Sample 2"}

    def test_returns_empty_for_none_input(self):
        """Should return empty list for None input."""
        result = extract_row_selection_values(None, "sample_id")

        assert result == []

    def test_returns_empty_for_empty_list(self):
        """Should return empty list for empty input."""
        result = extract_row_selection_values([], "sample_id")

        assert result == []

    def test_skips_rows_without_column(self):
        """Should skip rows missing the specified column."""
        selected_rows = [
            {"ID": 1, "sample_id": "S1"},
            {"ID": 2, "other_col": "value"},  # Missing sample_id
            {"ID": 3, "sample_id": "S3"},
        ]

        result = extract_row_selection_values(selected_rows, "sample_id")

        assert set(result) == {"S1", "S3"}

    def test_skips_none_values(self):
        """Should skip rows where column value is None."""
        selected_rows = [
            {"ID": 1, "sample_id": "S1"},
            {"ID": 2, "sample_id": None},
            {"ID": 3, "sample_id": "S3"},
        ]

        result = extract_row_selection_values(selected_rows, "sample_id")

        assert set(result) == {"S1", "S3"}

    def test_skips_non_dict_rows(self):
        """Should skip non-dict entries in rows list."""
        selected_rows = [
            {"ID": 1, "sample_id": "S1"},
            "not a dict",
            None,
            {"ID": 2, "sample_id": "S2"},
        ]

        result = extract_row_selection_values(selected_rows, "sample_id")

        assert set(result) == {"S1", "S2"}

    def test_deduplicates_values(self):
        """Should return unique values only."""
        selected_rows = [
            {"ID": 1, "category": "A"},
            {"ID": 2, "category": "B"},
            {"ID": 3, "category": "A"},
            {"ID": 4, "category": "A"},
        ]

        result = extract_row_selection_values(selected_rows, "category")

        assert len(result) == 2
        assert set(result) == {"A", "B"}

    def test_handles_numeric_values(self):
        """Should handle numeric column values."""
        selected_rows = [
            {"ID": 1, "score": 95},
            {"ID": 2, "score": 87},
            {"ID": 3, "score": 95},
        ]

        result = extract_row_selection_values(selected_rows, "score")

        assert set(result) == {95, 87}

    def test_handles_mixed_types(self):
        """Should handle mixed value types."""
        selected_rows = [
            {"ID": 1, "value": "string"},
            {"ID": 2, "value": 42},
            {"ID": 3, "value": 3.14},
        ]

        result = extract_row_selection_values(selected_rows, "value")

        assert set(result) == {"string", 42, 3.14}
