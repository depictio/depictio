"""
Centralized validation rules for dashboard YAML components.

Defines allowed chart types, aggregation functions, and filter types
leveraging existing Dash component models for type safety and consistency.
"""

from functools import cache
from typing import Literal

from pydantic import BaseModel, Field

# Type alias for column types
ColumnType = Literal["int64", "float64", "bool", "datetime", "timedelta", "category", "object"]

# Type aliases for specific validation types
ChartType = Literal["scatter", "line", "bar", "box", "histogram"]
AggregationFunction = Literal[
    "count",
    "sum",
    "average",
    "median",
    "min",
    "max",
    "range",
    "variance",
    "std_dev",
    "percentile",
    "skewness",
    "kurtosis",
    "mode",
    "nunique",
]
FilterType = Literal[
    "Slider",
    "RangeSlider",
    "Checkbox",
    "Switch",
    "DateRangePicker",
    "Select",
    "MultiSelect",
    "SegmentedControl",
]

# Default fallback values when dynamic discovery fails
_DEFAULT_CHART_TYPES = frozenset({"scatter", "line", "bar", "box", "histogram"})
_DEFAULT_VIZ_FIELDS = frozenset(
    {"chart", "x", "y", "color", "size", "title", "template", "opacity"}
)


@cache
def _get_visualization_names_cached() -> frozenset[str]:
    """Get visualization names from figure component registry with caching."""
    try:
        from depictio.dash.modules.figure_component.definitions import get_visualization_names

        return frozenset(get_visualization_names())
    except Exception:
        return _DEFAULT_CHART_TYPES


def get_allowed_visualization_fields(chart_type: str) -> set[str]:
    """
    Get allowed fields for a specific visualization type from figure component models.

    Args:
        chart_type: The chart type (e.g., "scatter", "bar", "line")

    Returns:
        Set of allowed parameter names for this visualization type

    Note:
        This dynamically discovers parameters from the figure component registry,
        ensuring validation stays in sync with the actual implementation.
    """
    try:
        from depictio.dash.modules.figure_component.definitions import get_visualization_definition

        viz_def = get_visualization_definition(chart_type)
        param_names = {param.name for param in viz_def.parameters}
        param_names.add("chart")
        return param_names
    except Exception:
        return set(_DEFAULT_VIZ_FIELDS)


class ChartTypeRules(BaseModel):
    """Chart type validation rules dynamically loaded from figure component registry."""

    @property
    def allowed_types(self) -> frozenset[str]:
        """Get allowed chart types from figure component registry."""
        return _get_visualization_names_cached()

    def is_valid_chart_type(self, chart_type: str) -> bool:
        """Check if a chart type is valid."""
        return chart_type in self.allowed_types

    def get_allowed_types_str(self) -> str:
        """Get formatted string of allowed types."""
        return ", ".join(sorted(self.allowed_types))


class ColumnTypeRules(BaseModel):
    """Validation rules for a specific column type."""

    column_type: ColumnType
    allowed_aggregations: set[str] = Field(default_factory=set)
    allowed_filters: set[str] = Field(default_factory=set)

    def is_valid_aggregation(self, function: str) -> bool:
        """Check if an aggregation function is valid for this column type."""
        return function in self.allowed_aggregations

    def is_valid_filter(self, filter_type: str) -> bool:
        """Check if a filter type is valid for this column type."""
        return filter_type in self.allowed_filters

    def get_allowed_aggregations_str(self) -> str:
        """Get formatted string of allowed aggregation functions."""
        return ", ".join(sorted(self.allowed_aggregations))

    def get_allowed_filters_str(self) -> str:
        """Get formatted string of allowed filter types."""
        return ", ".join(sorted(self.allowed_filters))


class ValidationRules(BaseModel):
    """Complete validation rules for dashboard components."""

    chart_types: ChartTypeRules = Field(default_factory=ChartTypeRules)
    column_type_rules: dict[str, ColumnTypeRules] = Field(default_factory=dict)

    model_config = {"frozen": True}  # Make immutable

    def get_column_type_rules(self, column_type: str) -> ColumnTypeRules | None:
        """Get validation rules for a specific column type."""
        return self.column_type_rules.get(column_type)


# Define allowed fields for aggregation and filter configurations
# (Visualization fields are dynamically discovered from figure component models)
ALLOWED_AGGREGATION_FIELDS = {
    "column",
    "function",
    "column_type",
}

ALLOWED_FILTER_FIELDS = {
    "column",
    "type",
    "column_type",
}


# Singleton instance with validation rules
# (extracted from Dash component modules)
VALIDATION_RULES = ValidationRules(
    chart_types=ChartTypeRules(),
    column_type_rules={
        "int64": ColumnTypeRules(
            column_type="int64",
            allowed_aggregations={
                "count",
                "sum",
                "average",
                "median",
                "min",
                "max",
                "range",
                "variance",
                "std_dev",
                "skewness",
                "kurtosis",
            },
            allowed_filters={"Slider", "RangeSlider"},
        ),
        "float64": ColumnTypeRules(
            column_type="float64",
            allowed_aggregations={
                "count",
                "sum",
                "average",
                "median",
                "min",
                "max",
                "range",
                "variance",
                "std_dev",
                "percentile",
                "skewness",
                "kurtosis",
            },
            allowed_filters={"Slider", "RangeSlider"},
        ),
        "bool": ColumnTypeRules(
            column_type="bool",
            allowed_aggregations={"count", "sum", "min", "max"},
            allowed_filters={"Checkbox", "Switch"},
        ),
        "datetime": ColumnTypeRules(
            column_type="datetime",
            allowed_aggregations={"count", "min", "max"},
            allowed_filters={"DateRangePicker"},
        ),
        "timedelta": ColumnTypeRules(
            column_type="timedelta",
            allowed_aggregations={"count", "sum", "min", "max"},
            allowed_filters=set(),  # No supported filter types
        ),
        "category": ColumnTypeRules(
            column_type="category",
            allowed_aggregations={"count", "mode"},
            allowed_filters={"Select", "MultiSelect", "SegmentedControl"},
        ),
        "object": ColumnTypeRules(
            column_type="object",
            allowed_aggregations={"count", "mode", "nunique"},
            allowed_filters={"Select", "MultiSelect", "SegmentedControl"},
        ),
    },
)
