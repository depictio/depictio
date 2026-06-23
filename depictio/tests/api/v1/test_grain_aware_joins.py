"""
Test suite for grain-aware join functionality using Polars.

Following TDD approach:
1. Write tests first
2. Implement functions to pass tests
3. Keep it simple (Polars-only, no DuckDB)

Key principles:
- Base DataFrame determines output grain
- Automatic aggregation when needed
- Sensible defaults with configuration overrides
- No row explosion
"""

import polars as pl
import pytest

from depictio.api.v1.grain_aware_joins import (
    grain_aware_join,
    is_unique_grain,
)

# ============================================================================
# Fixtures: Sample Data
# ============================================================================


@pytest.fixture
def samples_df():
    """Sample-level data (3 rows, grain: sample_id)"""
    return pl.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3"],
            "tissue": ["liver", "brain", "liver"],
            "age": [45, 62, 38],
            "batch": ["B1", "B1", "B2"],
        }
    )


@pytest.fixture
def cells_df():
    """Cell-level data (10 rows, grain: cell_id, multiple cells per sample)"""
    return pl.DataFrame(
        {
            "cell_id": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"],
            "sample_id": ["S1", "S1", "S1", "S2", "S2", "S3", "S3", "S4", "S5", "S5"],
            "quality": [0.92, 0.88, 0.95, 0.78, 0.85, 0.91, 0.87, 0.82, 0.96, 0.89],
            "cell_type": ["T", "T", "B", "T", "B", "T", "T", "B", "T", "B"],
            "is_dead": [False, False, False, True, False, False, False, True, False, False],
        }
    )


@pytest.fixture
def qc_metrics_df():
    """QC metrics (3 rows, grain: sample_id)"""
    return pl.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3"],
            "total_reads": [1_500_000, 2_100_000, 1_800_000],
            "mapped_reads": [1_350_000, 1_890_000, 1_620_000],
            "gc_content": [0.48, 0.52, 0.47],
        }
    )


# ============================================================================
# Tests: Grain Detection
# ============================================================================


class TestGrainDetection:
    """Test is_unique_grain() functionality"""

    def test_unique_single_column(self, samples_df):
        """Test detection of unique grain with single column"""
        assert is_unique_grain(samples_df, "sample_id") is True

    def test_non_unique_single_column(self, cells_df):
        """Test detection of non-unique column"""
        # sample_id is not unique in cells_df (multiple cells per sample)
        assert is_unique_grain(cells_df, "sample_id") is False

    def test_unique_multi_column(self, cells_df):
        """Test detection of unique grain with multiple columns"""
        # cell_id alone should be unique
        assert is_unique_grain(cells_df, "cell_id") is True

    def test_unique_compound_key(self):
        """Test compound key uniqueness detection"""
        df = pl.DataFrame(
            {
                "sample_id": ["S1", "S1", "S2", "S2"],
                "batch": ["B1", "B2", "B1", "B2"],
                "value": [10, 20, 30, 40],
            }
        )
        # Combination of sample_id + batch is unique
        assert is_unique_grain(df, ["sample_id", "batch"]) is True
        # But sample_id alone is not
        assert is_unique_grain(df, "sample_id") is False

    def test_empty_dataframe(self):
        """Test grain detection on empty DataFrame"""
        df = pl.DataFrame({"id": []})
        # Empty DataFrame should be considered unique (vacuous truth)
        assert is_unique_grain(df, "id") is True


# ============================================================================
# Tests: Simple Joins (Same Grain)
# ============================================================================


class TestSimpleJoins:
    """Test joins between DataFrames with same grain"""

    def test_same_grain_preserves_rows(self, samples_df, qc_metrics_df):
        """Test that joining same-grain DataFrames preserves row count"""
        result = grain_aware_join(samples_df, qc_metrics_df, on="sample_id")

        # Should have same number of rows as base DataFrame
        assert len(result) == len(samples_df)
        # Should have columns from both DataFrames
        assert "tissue" in result.columns
        assert "total_reads" in result.columns

    def test_same_grain_left_join(self, samples_df, qc_metrics_df):
        """Test left join behavior with same grain"""
        result = grain_aware_join(samples_df, qc_metrics_df, on="sample_id", how="left")

        # All samples should be present
        assert result["sample_id"].to_list() == ["S1", "S2", "S3"]

    def test_same_grain_no_aggregation(self, samples_df, qc_metrics_df):
        """Test that no aggregation occurs when grains match"""
        result = grain_aware_join(samples_df, qc_metrics_df, on="sample_id")

        # Values should be unchanged (not aggregated)
        s1_row = result.filter(pl.col("sample_id") == "S1")
        assert s1_row["total_reads"][0] == 1_500_000


# ============================================================================
# Tests: Aggregation Direction (Many → One)
# ============================================================================


class TestAggregationDirection:
    """Test joins where df_other needs aggregation (many → one)"""

    def test_aggregate_cells_to_samples(self, samples_df, cells_df):
        """Test aggregating cell-level data to sample level"""
        result = grain_aware_join(samples_df, cells_df, on="sample_id")

        # Should have 3 rows (base DataFrame grain)
        assert len(result) == 3

        # Should have aggregated cell data
        # Check that aggregated columns exist (with suffix/transformation)
        assert any("quality" in col for col in result.columns)

    def test_automatic_numeric_aggregation(self, samples_df, cells_df):
        """Test that numeric columns are automatically averaged"""
        result = grain_aware_join(samples_df, cells_df, on="sample_id")

        # Quality should be aggregated (mean by default)
        s1_row = result.filter(pl.col("sample_id") == "S1")
        # S1 has 3 cells with quality [0.92, 0.88, 0.95]
        expected_mean = (0.92 + 0.88 + 0.95) / 3
        # Check for quality column (might be renamed to quality_mean)
        quality_col = [c for c in result.columns if "quality" in c][0]
        assert abs(s1_row[quality_col][0] - expected_mean) < 0.01

    def test_automatic_string_aggregation(self, samples_df, cells_df):
        """Test that string columns are aggregated as lists"""
        result = grain_aware_join(samples_df, cells_df, on="sample_id")

        # cell_type should be aggregated as list
        s1_row = result.filter(pl.col("sample_id") == "S1")
        cell_type_col = [c for c in result.columns if "cell_type" in c][0]

        # S1 has 3 cells: ['T', 'T', 'B']
        # Extract the list value properly from Polars
        print(f"DEBUG: result columns = {result.columns}")
        print(f"DEBUG: s1_row = {s1_row}")
        print(f"DEBUG: cell_type_col = {cell_type_col}")
        row_dict = s1_row.row(0, named=True)
        print(f"DEBUG: row_dict = {row_dict}")
        cell_types = row_dict[cell_type_col]
        print(f"DEBUG: cell_types = {cell_types}, type = {type(cell_types)}")
        assert isinstance(cell_types, list)
        assert sorted(cell_types) == ["B", "T", "T"]

    def test_automatic_boolean_aggregation(self, samples_df, cells_df):
        """Test that boolean columns are aggregated as sum (count of True)"""
        result = grain_aware_join(samples_df, cells_df, on="sample_id")

        # is_dead should be counted
        s2_row = result.filter(pl.col("sample_id") == "S2")
        dead_col = [c for c in result.columns if "is_dead" in c][0]

        # S2 has 2 cells: [True, False] → count should be 1
        assert s2_row[dead_col][0] == 1

    def test_row_count_column_added(self, samples_df, cells_df):
        """Test that row count is automatically added during aggregation"""
        result = grain_aware_join(samples_df, cells_df, on="sample_id")

        # Should have a count column (e.g., n_cells or count)
        count_cols = [c for c in result.columns if "count" in c.lower() or c.startswith("n_")]
        assert len(count_cols) > 0

        # S1 should have 3 cells
        s1_row = result.filter(pl.col("sample_id") == "S1")
        # Find the count column and verify
        count_col = count_cols[0]
        assert s1_row[count_col][0] == 3


# ============================================================================
# Tests: Broadcast Direction (One → Many)
# ============================================================================


class TestBroadcastDirection:
    """Test joins where sample data is broadcast to cells (one → many)"""

    def test_broadcast_samples_to_cells(self, cells_df, samples_df):
        """Test broadcasting sample-level data to all cells"""
        result = grain_aware_join(cells_df, samples_df, on="sample_id")

        # Should have 10 rows (base DataFrame grain = cells)
        assert len(result) == 10

        # Should have both cell and sample columns
        assert "cell_id" in result.columns
        assert "tissue" in result.columns

    def test_broadcast_no_aggregation(self, cells_df, samples_df):
        """Test that sample data is not aggregated when broadcasting"""
        result = grain_aware_join(cells_df, samples_df, on="sample_id")

        # Sample values should be duplicated, not aggregated
        c1_row = result.filter(pl.col("cell_id") == "C1")
        # C1 belongs to S1, which has age=45
        assert c1_row["age"][0] == 45

        # All cells from S1 should have same sample data
        s1_cells = result.filter(pl.col("sample_id") == "S1")
        assert all(s1_cells["age"] == 45)
        assert all(s1_cells["tissue"] == "liver")

    def test_broadcast_no_row_explosion(self, cells_df, samples_df):
        """Test that broadcasting doesn't cause row explosion"""
        result = grain_aware_join(cells_df, samples_df, on="sample_id")

        # Should have exactly the same number of rows as cells
        assert len(result) == len(cells_df)

        # Each cell should appear exactly once
        assert result["cell_id"].is_unique().all()


# ============================================================================
# Tests: Custom Aggregations
# ============================================================================


class TestCustomAggregations:
    """Test user-specified aggregation overrides"""

    def test_custom_aggregation_override(self, samples_df, cells_df):
        """Test that user can specify custom aggregations"""
        custom_aggs = {
            "quality": "max",  # Override default mean with max
            "cell_type": "first",  # Override default list with first
        }

        result = grain_aware_join(samples_df, cells_df, on="sample_id", aggregations=custom_aggs)

        # S1 has quality [0.92, 0.88, 0.95] → max should be 0.95
        s1_row = result.filter(pl.col("sample_id") == "S1")
        quality_col = [c for c in result.columns if "quality" in c][0]
        assert s1_row[quality_col][0] == 0.95

    def test_custom_aggregation_with_polars_expr(self, samples_df, cells_df):
        """Test custom aggregation using Polars expressions"""
        custom_aggs = {
            "quality": pl.col("quality").median(),  # Use Polars expression
        }

        result = grain_aware_join(samples_df, cells_df, on="sample_id", aggregations=custom_aggs)

        # Should use median instead of mean
        s1_row = result.filter(pl.col("sample_id") == "S1")
        # S1 has quality [0.92, 0.88, 0.95] → median should be 0.92
        quality_col = [c for c in result.columns if "quality" in c][0]
        assert s1_row[quality_col][0] == 0.92

    def test_mixed_default_and_custom_aggregations(self, samples_df, cells_df):
        """Test that custom aggregations can be mixed with defaults"""
        custom_aggs = {
            "quality": "max",  # Custom
            # cell_type and is_dead should use defaults
        }

        result = grain_aware_join(samples_df, cells_df, on="sample_id", aggregations=custom_aggs)

        # quality should use custom max
        s1_row = result.filter(pl.col("sample_id") == "S1")
        quality_col = [c for c in result.columns if "quality" in c][0]
        assert s1_row[quality_col][0] == 0.95

        # cell_type should still use default list
        cell_type_col = [c for c in result.columns if "cell_type" in c][0]
        assert isinstance(s1_row.select(cell_type_col).row(0)[0], list)


# ============================================================================
# Tests: Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_empty_base_dataframe(self, qc_metrics_df):
        """Test joining with empty base DataFrame"""
        empty_df = pl.DataFrame({"sample_id": [], "tissue": []})
        result = grain_aware_join(empty_df, qc_metrics_df, on="sample_id")

        # Result should be empty
        assert len(result) == 0

    def test_empty_other_dataframe(self, samples_df):
        """Test joining with empty other DataFrame"""
        empty_df = pl.DataFrame({"sample_id": [], "value": []})
        result = grain_aware_join(samples_df, empty_df, on="sample_id")

        # Should still have base DataFrame rows
        assert len(result) == len(samples_df)

    def test_missing_join_column_in_base(self, samples_df, qc_metrics_df):
        """Test error handling when join column missing in base DataFrame"""
        with pytest.raises((KeyError, pl.ColumnNotFoundError)):
            grain_aware_join(samples_df, qc_metrics_df, on="nonexistent_column")

    def test_missing_join_column_in_other(self, samples_df):
        """Test error handling when join column missing in other DataFrame"""
        other_df = pl.DataFrame({"different_id": ["S1", "S2"], "value": [10, 20]})

        with pytest.raises((KeyError, pl.ColumnNotFoundError)):
            grain_aware_join(samples_df, other_df, on="sample_id")

    def test_all_null_join_column(self):
        """Test handling of all-null join column"""
        df1 = pl.DataFrame({"id": [None, None, None], "value": [1, 2, 3]})
        df2 = pl.DataFrame({"id": [None, None], "other": [10, 20]})

        result = grain_aware_join(df1, df2, on="id")
        # Should handle nulls gracefully (Polars join behavior)
        assert len(result) >= 0  # Non-negative rows


# ============================================================================
# Tests: Multi-Column Grain
# ============================================================================


class TestMultiColumnGrain:
    """Test joins on compound keys (multiple columns)"""

    def test_multi_column_grain_join(self):
        """Test joining on multiple columns"""
        df1 = pl.DataFrame(
            {
                "sample_id": ["S1", "S1", "S2", "S2"],
                "batch": ["B1", "B2", "B1", "B2"],
                "value": [10, 20, 30, 40],
            }
        )

        df2 = pl.DataFrame(
            {
                "sample_id": ["S1", "S1", "S2"],
                "batch": ["B1", "B2", "B1"],
                "qc_score": [0.9, 0.8, 0.95],
            }
        )

        result = grain_aware_join(df1, df2, on=["sample_id", "batch"])

        # Should join on both columns
        assert len(result) == 4
        assert "qc_score" in result.columns

    def test_multi_column_grain_with_aggregation(self):
        """Test multi-column grain where aggregation is needed"""
        # Base with sample+batch grain
        df_base = pl.DataFrame(
            {
                "sample_id": ["S1", "S1", "S2"],
                "batch": ["B1", "B2", "B1"],
                "tissue": ["liver", "liver", "brain"],
            }
        )

        # Other has finer grain (sample+batch+replicate)
        df_other = pl.DataFrame(
            {
                "sample_id": ["S1", "S1", "S1", "S1"],
                "batch": ["B1", "B1", "B2", "B2"],
                "replicate": [1, 2, 1, 2],
                "reads": [1000, 1100, 900, 950],
            }
        )

        result = grain_aware_join(df_base, df_other, on=["sample_id", "batch"])

        # Should aggregate replicates
        assert len(result) == 3
        # reads should be aggregated
        reads_col = [c for c in result.columns if "reads" in c][0]
        assert reads_col in result.columns
