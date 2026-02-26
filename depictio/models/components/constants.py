"""
Shared domain constants for component validation.

Extracted from dash modules so the model layer can validate enum-like fields
without importing Dash/DMC dependencies (which would cause circular imports).

Sources:
    - VISU_TYPES: dash/modules/figure_component/definitions.py (ALLOWED_VISUALIZATIONS)
    - INTERACTIVE_COMPATIBILITY: dash/modules/interactive_component/utils.py (agg_functions dict)
    - AGGREGATION_COMPATIBILITY: dash/modules/card_component/utils.py (agg_functions dict)
"""

# ---------------------------------------------------------------------------
# Valid column data types
# ---------------------------------------------------------------------------

COLUMN_TYPES: tuple[str, ...] = (
    "int64",
    "float64",
    "bool",
    "datetime",
    "timedelta",
    "category",
    "object",
)

# ---------------------------------------------------------------------------
# Valid figure visualization types
# ---------------------------------------------------------------------------

VISU_TYPES: tuple[str, ...] = (
    "scatter",
    "line",
    "bar",
    "box",
    "histogram",
    "heatmap",
)

# ---------------------------------------------------------------------------
# Interactive component type × column_type compatibility
# column_type → list of valid interactive_component_type values
# ---------------------------------------------------------------------------

INTERACTIVE_COMPATIBILITY: dict[str, list[str]] = {
    "int64": ["Slider", "RangeSlider"],
    "float64": ["Slider", "RangeSlider"],
    # "bool": ["Checkbox", "Switch"],  # Not yet implemented in frontend
    "bool": [],
    "datetime": ["DateRangePicker"],
    "timedelta": [],  # No interactive component supported for timedelta
    "category": ["Select", "MultiSelect", "SegmentedControl"],
    "object": ["Select", "MultiSelect", "SegmentedControl"],
}

# ---------------------------------------------------------------------------
# Card aggregation × column_type compatibility
# column_type → list of valid aggregation names
# ---------------------------------------------------------------------------

AGGREGATION_COMPATIBILITY: dict[str, list[str]] = {
    "int64": [
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
    ],
    "float64": [
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
    ],
    "bool": ["count", "sum", "min", "max"],
    "datetime": ["count", "min", "max"],
    "timedelta": ["count", "sum", "min", "max"],
    "category": ["count", "mode"],
    "object": ["count", "mode", "nunique"],
}
