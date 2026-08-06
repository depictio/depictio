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
    "datetime": ["DateRangePicker", "Timeline"],
    "timedelta": [],  # No interactive component supported for timedelta
    "category": ["Select", "MultiSelect", "SegmentedControl"],
    "object": ["Select", "MultiSelect", "SegmentedControl"],
}

# ---------------------------------------------------------------------------
# Interactive component placement options
# ---------------------------------------------------------------------------

INTERACTIVE_PLACEMENTS: tuple[str, ...] = ("left", "top")

# Interactive component types that may opt into the top panel.
TOP_PANEL_INTERACTIVE_TYPES: tuple[str, ...] = ("Timeline",)

# Valid timescales for the Timeline interactive component.
TIMELINE_TIMESCALES: tuple[str, ...] = ("year", "month", "day", "hour", "minute")

# Maximum number of interactive components that may share the same `group`.
# The cap guards against a group card so tall it defeats the point of grouping.
# It was 3 when a group was an always-expanded stack; groups are collapsible and
# render their members compact now, so a taller card stays usable.
MAX_INTERACTIVE_GROUP_SIZE: int = 6

# ---------------------------------------------------------------------------
# Valid map types and styles
# ---------------------------------------------------------------------------

MAP_TYPES: tuple[str, ...] = (
    "scatter_map",
    "density_map",
    "choropleth_map",
)

MAP_STYLES: tuple[str, ...] = (
    "open-street-map",
    "carto-positron",
    "carto-darkmatter",
)

# Where a map renders: as a normal dashboard tile, or lifted out of the grid
# into the panel that is available from every tab of the dashboard family.
MAP_PLACEMENTS: tuple[str, ...] = ("grid", "floating")

# How that panel presents itself on a viewer's first visit. 'compact' and
# 'expanded' are the two sizes; as a draggable card they are its footprint, and
# 'docked' pins it below the dashboard's filter panel where they are its height.
# The viewer's own saved preference takes over from then on.
FLOATING_PANEL_STATES: tuple[str, ...] = ("compact", "expanded", "docked", "hidden")

# ---------------------------------------------------------------------------
# Card aggregation × column_type compatibility
# column_type → list of valid aggregation names
# ---------------------------------------------------------------------------

AGGREGATION_COMPATIBILITY: dict[str, list[str]] = {
    "int64": [
        "count",
        "nunique",
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
        # Quantiles are well defined on integers, the builder has always offered
        # this option, and the precompute step already records it — the omission
        # here was the outlier, and it rejected cards the UI could produce.
        "percentile",
        "q1",
        "q3",
        "box_plot_stats",
    ],
    "float64": [
        "count",
        "nunique",
        "sum",
        "average",
        "median",
        "min",
        "max",
        "range",
        "variance",
        "std_dev",
        "percentile",
        "q1",
        "q3",
        "box_plot_stats",
        "skewness",
        "kurtosis",
    ],
    "bool": ["count", "sum", "min", "max"],
    "datetime": ["count", "min", "max"],
    "timedelta": ["count", "sum", "min", "max"],
    "category": ["count", "mode"],
    "object": ["count", "mode", "nunique"],
}
