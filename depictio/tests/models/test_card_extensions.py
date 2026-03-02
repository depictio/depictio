"""Tests for card and interactive component extensions: multi-metric, conditional
aggregations, and scoped interactive filters."""

from __future__ import annotations

import polars as pl
import pytest
from pydantic import ValidationError

from depictio.models.components.filter_expr import (
    apply_filter_expr,
    validate_filter_expr,
)
from depictio.models.components.lite import CardLiteComponent, InteractiveLiteComponent

# ---------------------------------------------------------------------------
# CardLiteComponent model tests
# ---------------------------------------------------------------------------


class TestCardLiteComponentBackwardsCompat:
    """Existing single-metric cards still work unchanged."""

    def test_single_metric_card(self) -> None:
        """Basic single-metric card creation works."""
        card = CardLiteComponent(
            tag="test-card",
            aggregation="average",
            column_name="sepal.length",
            column_type="float64",
        )
        assert card.aggregation == "average"
        assert card.aggregations is None
        assert card.filter_expr is None

    def test_single_metric_no_column_type(self) -> None:
        """Cards without column_type skip aggregation validation."""
        card = CardLiteComponent(
            tag="test-card",
            aggregation="average",
            column_name="some_col",
        )
        assert card.column_type is None


class TestCardLiteComponentMultiMetric:
    """Multi-metric (aggregations) field validation."""

    def test_valid_aggregations(self) -> None:
        """Valid secondary aggregations accepted."""
        card = CardLiteComponent(
            tag="summary",
            aggregation="average",
            aggregations=["median", "std_dev", "min", "max"],
            column_name="cell_count",
            column_type="float64",
        )
        assert card.aggregations == ["median", "std_dev", "min", "max"]

    def test_invalid_secondary_aggregation(self) -> None:
        """Invalid secondary aggregation rejected when column_type is set."""
        with pytest.raises(ValidationError, match="Invalid secondary aggregation 'mode'"):
            CardLiteComponent(
                tag="bad",
                aggregation="average",
                aggregations=["median", "mode"],  # mode not valid for float64
                column_name="cell_count",
                column_type="float64",
            )

    def test_aggregations_without_column_type(self) -> None:
        """When column_type is None, no validation is applied."""
        card = CardLiteComponent(
            tag="no-type",
            aggregation="average",
            aggregations=["mode"],
            column_name="some_col",
        )
        assert card.aggregations == ["mode"]


class TestCardLiteComponentFilterExpr:
    """filter_expr field validation."""

    def test_valid_filter_expr(self) -> None:
        """Valid Polars expression accepted."""
        card = CardLiteComponent(
            tag="filtered",
            aggregation="count",
            column_name="cell_count",
            column_type="float64",
            filter_expr="col('cell_count') >= 5",
        )
        assert card.filter_expr == "col('cell_count') >= 5"

    def test_compound_filter_expr(self) -> None:
        """Compound AND expression accepted."""
        expr = "(col('cell_count') >= 5) & (col('pop') == 'AMR')"
        card = CardLiteComponent(
            tag="compound",
            aggregation="count",
            column_name="cell_count",
            filter_expr=expr,
        )
        assert card.filter_expr == expr

    def test_unsafe_filter_expr_rejected(self) -> None:
        """Expression with import statement rejected."""
        with pytest.raises(ValidationError, match="disallowed construct"):
            CardLiteComponent(
                tag="bad",
                aggregation="count",
                column_name="x",
                filter_expr="import os; col('x') >= 5",
            )

    def test_unsafe_dunder_rejected(self) -> None:
        """Expression with dunder access rejected."""
        with pytest.raises(ValidationError, match="disallowed construct"):
            CardLiteComponent(
                tag="bad",
                aggregation="count",
                column_name="x",
                filter_expr="col('x').__class__",
            )


# ---------------------------------------------------------------------------
# filter_expr validation and execution tests
# ---------------------------------------------------------------------------


class TestValidateFilterExpr:
    """Test the validate_filter_expr function."""

    def test_valid_simple(self) -> None:
        validate_filter_expr("col('x') >= 5")

    def test_valid_compound(self) -> None:
        validate_filter_expr("(col('x') >= 5) & (col('y') == 'AMR')")

    def test_valid_is_in(self) -> None:
        validate_filter_expr("col('status').is_in(['pass', 'warn'])")

    def test_valid_is_null(self) -> None:
        validate_filter_expr("col('x').is_null()")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            validate_filter_expr("")

    def test_import_rejected(self) -> None:
        with pytest.raises(ValueError, match="disallowed construct"):
            validate_filter_expr("import os")

    def test_exec_rejected(self) -> None:
        with pytest.raises(ValueError, match="disallowed construct"):
            validate_filter_expr("exec('bad')")

    def test_disallowed_function(self) -> None:
        with pytest.raises(ValueError, match="disallowed"):
            validate_filter_expr("open('/etc/passwd')")

    def test_unbalanced_parens(self) -> None:
        with pytest.raises(ValueError, match="unbalanced"):
            validate_filter_expr("col('x') >= 5)")


class TestApplyFilterExpr:
    """Test apply_filter_expr on actual Polars DataFrames."""

    @pytest.fixture
    def sample_df(self) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "cell_count": [1, 3, 5, 7, 10],
                "pop": ["AMR", "EUR", "AMR", "AMR", "EUR"],
                "status": ["pass", "fail", "pass", "warn", "pass"],
            }
        )

    def test_simple_threshold(self, sample_df: pl.DataFrame) -> None:
        result = apply_filter_expr(sample_df, "col('cell_count') >= 5")
        assert len(result) == 3
        assert result["cell_count"].to_list() == [5, 7, 10]

    def test_compound_condition(self, sample_df: pl.DataFrame) -> None:
        result = apply_filter_expr(
            sample_df,
            "(col('cell_count') >= 5) & (col('pop') == 'AMR')",
        )
        assert len(result) == 2
        assert result["cell_count"].to_list() == [5, 7]

    def test_is_in(self, sample_df: pl.DataFrame) -> None:
        result = apply_filter_expr(
            sample_df,
            "col('status').is_in(['pass', 'warn'])",
        )
        assert len(result) == 4

    def test_invalid_expr_raises_runtime_error(self, sample_df: pl.DataFrame) -> None:
        with pytest.raises(RuntimeError, match="Failed to evaluate"):
            apply_filter_expr(sample_df, "col('nonexistent_col') >= invalid_var")

    def test_wrong_column_raises_runtime_error(self, sample_df: pl.DataFrame) -> None:
        with pytest.raises(RuntimeError, match="Failed to apply"):
            apply_filter_expr(sample_df, "col('nonexistent') >= 5")


# ---------------------------------------------------------------------------
# compute_multi_values test
# ---------------------------------------------------------------------------


class TestComputeMultiValues:
    """Test compute_multi_values utility.

    These tests require Dash dependencies (dash_mantine_components) to be installed.
    """

    def test_compute_multiple_aggregations(self) -> None:
        pytest.importorskip("dash_mantine_components", reason="Dash deps required")
        from depictio.dash.modules.card_component.utils import compute_multi_values

        df = pl.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        results = compute_multi_values(
            df, "x", ["average", "median", "min", "max"], has_filters=True
        )
        assert results["average"] == pytest.approx(3.0)
        assert results["median"] == pytest.approx(3.0)
        assert results["min"] == pytest.approx(1.0)
        assert results["max"] == pytest.approx(5.0)

    def test_invalid_aggregation_returns_none(self) -> None:
        pytest.importorskip("dash_mantine_components", reason="Dash deps required")
        from depictio.dash.modules.card_component.utils import compute_multi_values

        df = pl.DataFrame({"x": [1.0, 2.0, 3.0]})
        results = compute_multi_values(df, "x", ["average", "skewness"])
        # skewness may or may not work depending on Polars version, but should not raise
        assert "average" in results
        assert "skewness" in results


# ---------------------------------------------------------------------------
# InteractiveLiteComponent filter_expr tests
# ---------------------------------------------------------------------------


class TestInteractiveLiteComponentBackwardsCompat:
    """Existing interactive components still work unchanged."""

    def test_standard_multiselect(self) -> None:
        comp = InteractiveLiteComponent(
            tag="filter-1",
            interactive_component_type="MultiSelect",
            column_name="variety",
            column_type="object",
        )
        assert comp.filter_expr is None

    def test_standard_rangeslider(self) -> None:
        comp = InteractiveLiteComponent(
            tag="filter-2",
            interactive_component_type="RangeSlider",
            column_name="value",
            column_type="float64",
        )
        assert comp.filter_expr is None


class TestInteractiveLiteComponentFilterExpr:
    """filter_expr field validation for interactive components."""

    def test_valid_filter_expr(self) -> None:
        comp = InteractiveLiteComponent(
            tag="scoped-filter",
            interactive_component_type="MultiSelect",
            column_name="variety",
            column_type="object",
            filter_expr="col('sepal.length') > 5",
        )
        assert comp.filter_expr == "col('sepal.length') > 5"

    def test_compound_filter_expr(self) -> None:
        expr = "(col('sepal.length') > 5) & (col('petal.width') < 2)"
        comp = InteractiveLiteComponent(
            tag="compound",
            interactive_component_type="MultiSelect",
            column_name="variety",
            filter_expr=expr,
        )
        assert comp.filter_expr == expr

    def test_unsafe_filter_expr_rejected(self) -> None:
        with pytest.raises(ValidationError, match="disallowed construct"):
            InteractiveLiteComponent(
                tag="bad",
                interactive_component_type="MultiSelect",
                column_name="variety",
                filter_expr="import os; col('x') > 0",
            )

    def test_unsafe_dunder_rejected(self) -> None:
        with pytest.raises(ValidationError, match="disallowed construct"):
            InteractiveLiteComponent(
                tag="bad",
                interactive_component_type="MultiSelect",
                column_name="variety",
                filter_expr="col('x').__class__",
            )

    def test_filter_expr_with_rangeslider(self) -> None:
        """filter_expr works with numeric slider components too."""
        comp = InteractiveLiteComponent(
            tag="scoped-slider",
            interactive_component_type="RangeSlider",
            column_name="sepal.length",
            column_type="float64",
            filter_expr="col('variety') == 'setosa'",
        )
        assert comp.filter_expr == "col('variety') == 'setosa'"


# ---------------------------------------------------------------------------
# Expanded filter_expr capabilities (bioinformatics patterns)
# ---------------------------------------------------------------------------


class TestExpandedFilterExpressions:
    """Tests for expanded filter_expr capabilities: is_between, string methods,
    aggregation window functions (.over()), and compound patterns common in
    bioinformatics workflows."""

    @pytest.fixture
    def iris_like_df(self) -> pl.DataFrame:
        """Small iris-like DataFrame for testing."""
        return pl.DataFrame(
            {
                "sepal_length": [5.1, 4.9, 7.0, 6.4, 5.9, 6.3, 4.6, 5.0, 6.7, 5.5],
                "petal_length": [1.4, 1.4, 4.7, 4.5, 4.2, 6.0, 1.0, 1.5, 5.2, 1.3],
                "petal_width": [0.2, 0.2, 1.4, 1.5, 1.5, 2.5, 0.2, 0.2, 2.3, 0.2],
                "variety": [
                    "Setosa",
                    "Setosa",
                    "Versicolor",
                    "Versicolor",
                    "Versicolor",
                    "Virginica",
                    "Setosa",
                    "Setosa",
                    "Virginica",
                    "Setosa",
                ],
            }
        )

    # -- Validation tests (expression is accepted) --

    def test_is_between_valid(self) -> None:
        """is_between() passes validation."""
        validate_filter_expr("col('x').is_between(2.0, 4.0)")

    def test_over_valid(self) -> None:
        """.mean().over() passes validation."""
        validate_filter_expr("col('x').mean().over('group') > 5.0")

    def test_to_lowercase_valid(self) -> None:
        """str.to_lowercase() passes validation."""
        validate_filter_expr("col('name').str.to_lowercase().str.contains('set')")

    def test_strip_valid(self) -> None:
        """str.strip_chars() pattern passes validation (strip is allowed)."""
        validate_filter_expr("col('x').str.strip(' ')")

    # -- Runtime tests (correct Polars behavior) --

    def test_is_between_runtime(self, iris_like_df: pl.DataFrame) -> None:
        """is_between() filters to rows in a numeric range."""
        result = apply_filter_expr(iris_like_df, "col('sepal_length').is_between(5.0, 6.0)")
        assert all(5.0 <= v <= 6.0 for v in result["sepal_length"].to_list())
        # is_between is inclusive by default: [5.0, 6.0]
        # Qualifying: 5.1, 5.9, 5.0, 5.5 (4.9 excluded)
        assert len(result) == 4
        expected = [v for v in iris_like_df["sepal_length"].to_list() if 5.0 <= v <= 6.0]
        assert result["sepal_length"].to_list() == expected

    def test_column_to_column_runtime(self, iris_like_df: pl.DataFrame) -> None:
        """col('a') > col('b') keeps rows where a exceeds b."""
        result = apply_filter_expr(iris_like_df, "col('sepal_length') > col('petal_length')")
        for row in result.iter_rows(named=True):
            assert row["sepal_length"] > row["petal_length"]

    def test_negated_is_in_runtime(self, iris_like_df: pl.DataFrame) -> None:
        """~col('x').is_in([...]) excludes matching rows."""
        result = apply_filter_expr(iris_like_df, "~col('variety').is_in(['Setosa'])")
        assert "Setosa" not in result["variety"].to_list()
        assert len(result) == 5  # 3 Versicolor + 2 Virginica

    def test_count_over_runtime(self, iris_like_df: pl.DataFrame) -> None:
        """count().over() filters by group size."""
        # Setosa: 5, Versicolor: 3, Virginica: 2
        result = apply_filter_expr(iris_like_df, "col('variety').count().over('variety') >= 5")
        # Only Setosa has 5 members
        assert set(result["variety"].unique().to_list()) == {"Setosa"}
        assert len(result) == 5

    def test_mean_over_runtime(self, iris_like_df: pl.DataFrame) -> None:
        """mean().over() filters by group mean."""
        # Setosa mean sepal: (5.1+4.9+4.6+5.0+5.5)/5 = 5.02
        # Versicolor mean sepal: (7.0+6.4+5.9)/3 = 6.43
        # Virginica mean sepal: (6.3+6.7)/2 = 6.5
        result = apply_filter_expr(
            iris_like_df,
            "col('sepal_length').mean().over('variety') > 6.0",
        )
        varieties = set(result["variety"].unique().to_list())
        assert "Setosa" not in varieties
        assert "Versicolor" in varieties
        assert "Virginica" in varieties

    def test_compound_group_and_row_runtime(self, iris_like_df: pl.DataFrame) -> None:
        """Compound: row-level AND group-level condition."""
        # Row: sepal > 5.0 AND group: variety count >= 3
        # Setosa count=5 (>=3), Versicolor count=3 (>=3), Virginica count=2 (<3)
        result = apply_filter_expr(
            iris_like_df,
            "(col('sepal_length') > 5.0) & (col('variety').count().over('variety') >= 3)",
        )
        # Virginica excluded (group size 2 < 3)
        assert "Virginica" not in result["variety"].to_list()
        # Setosa rows with sepal > 5.0: 5.1, 5.5 (4.9, 4.6, 5.0 excluded by row condition)
        # Versicolor rows with sepal > 5.0: 7.0, 6.4, 5.9
        assert len(result) == 5
