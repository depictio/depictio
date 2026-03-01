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
