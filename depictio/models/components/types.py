"""
Component Type Definitions.

Literal types for dashboard components, providing type safety and validation
for component configuration.
"""

from typing import Literal

# Component types
ComponentType = Literal["card", "figure", "interactive", "table", "text", "jbrowse", "image", "map"]

# Map visualization types
MapType = Literal["scatter_map", "density_map", "choropleth_map"]

# Chart/visualization types (from figure_component/definitions.py)
ChartType = Literal["scatter", "line", "bar", "box", "histogram"]

# Aggregation functions (from card_component/utils.py AGGREGATION_MAPPING)
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
    "skewness",
    "kurtosis",
    "percentile",
    "nunique",
    "mode",
]

# Interactive component types (from interactive_component/utils.py)
InteractiveType = Literal[
    "Select",
    "MultiSelect",
    "SegmentedControl",
    "Slider",
    "RangeSlider",
    "DateRangePicker",
    "Switch",
]

# Column types for data columns
ColumnType = Literal[
    "int64",
    "float64",
    "bool",
    "datetime",
    "timedelta",
    "category",
    "object",
    "string",
]

# Figure mode (UI-based or code-based)
FigureMode = Literal["ui", "code"]
