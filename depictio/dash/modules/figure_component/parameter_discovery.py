"""
Dynamic parameter discovery for Plotly Express functions.

This module provides a robust way to automatically discover and validate
parameters from Plotly Express functions, making the system future-proof
against Plotly version changes.
"""

import inspect
from typing import Any, Dict, List, Optional, Union

import plotly.express as px

from depictio.api.v1.configs.logging_init import logger

from .models import (
    ParameterCategory,
    ParameterDefinition,
    ParameterType,
    VisualizationDefinition,
    VisualizationGroup,
)


class ParameterInspector:
    """Inspects Plotly Express functions to discover parameters dynamically.

    This class provides automatic parameter discovery for Plotly Express functions,
    enabling dynamic creation of UI controls for visualization configuration. It
    maintains knowledge bases for core, common, and advanced parameters with their
    metadata (types, descriptions, options, constraints).

    Key features:
    - Automatic function signature inspection with caching
    - Parameter type inference from annotations and naming patterns
    - Categorization into core/common/advanced/specific groups
    - Special handling for specific visualization types (violin, sunburst, etc.)

    Attributes:
        CORE_PARAMETERS: Essential parameters (x, y, z, color) for most plots.
        COMMON_PARAMETERS: Widely shared parameters (title, template, hover, etc.).
        ADVANCED_PARAMETERS: Expert-level parameters (log scales, faceting, etc.).
        TYPE_MAPPING: Maps Python types to ParameterType enum values.
    """

    # Core parameters that are essential for most visualizations.
    # Each entry has a `label` (human-friendly name shown in the form), a
    # short `description` (what it does + when to use), and an explicit `type`
    # (so the React ParameterField renders the matching control).
    # `x*`/`y*`/`z*` carry the `*` suffix because at least one is required.
    CORE_PARAMETERS = {
        "x": {
            "type": ParameterType.COLUMN,
            "required": False,
            "label": "X axis*",
            "description": "Column whose values map to the horizontal axis. At least one of X / Y is required.",
        },
        "y": {
            "type": ParameterType.COLUMN,
            "required": False,
            "label": "Y axis*",
            "description": "Column whose values map to the vertical axis. At least one of X / Y is required.",
        },
        "color": {
            "type": ParameterType.COLUMN,
            "required": False,
            "label": "Color by",
            "description": "Column whose values map to point color. Categorical → discrete palette; numeric → continuous scale.",
        },
        "z": {
            "type": ParameterType.COLUMN,
            "required": False,
            "label": "Z axis*",
            "description": "Column whose values map to the depth axis (3D plots). At least one * parameter is required.",
        },
    }

    # Common parameters shared across many visualizations.
    COMMON_PARAMETERS = {
        "title": {
            "type": ParameterType.STRING,
            "label": "Title",
            "description": "Headline shown above the figure.",
        },
        "subtitle": {
            "type": ParameterType.STRING,
            "label": "Subtitle",
            "description": "Sub-line shown under the title.",
        },
        "template": {
            "type": ParameterType.SELECT,
            "label": "Theme",
            "options": [
                "mantine_light",
                "mantine_dark",
                "plotly",
                "plotly_white",
                "plotly_dark",
                "ggplot2",
                "seaborn",
                "simple_white",
                "presentation",
                "none",
            ],
            "description": "Plotly template that controls the plot's overall look (background, fonts, gridlines).",
            "default": None,
        },
        "opacity": {
            "type": ParameterType.FLOAT,
            "label": "Opacity",
            "min_value": 0.0,
            "max_value": 1.0,
            "description": "Marker / line transparency. 0 = invisible, 1 = solid (default).",
        },
        "hover_name": {
            "type": ParameterType.COLUMN,
            "label": "Hover title",
            "description": "Column whose values appear bolded as the tooltip title on hover.",
        },
        "hover_data": {
            "type": ParameterType.MULTI_SELECT,
            "label": "Hover fields",
            "description": "Extra columns to surface in the hover tooltip alongside the default x/y values.",
            "options": [],  # Will be populated with column names by component builder
        },
        "custom_data": {
            "type": ParameterType.MULTI_SELECT,
            "label": "Custom data",
            "description": "Columns kept as customdata for downstream interactions (selection events, callbacks).",
            "options": [],  # Will be populated with column names by component builder
        },
        "labels": {
            "type": ParameterType.STRING,
            "label": "Axis labels (JSON)",
            "description": 'Override axis / legend labels. JSON dict, e.g. {"x": "Time (hours)", "y": "Temperature (°C)"}.',
        },
        "color_discrete_sequence": {
            "type": ParameterType.SELECT,
            "label": "Discrete palette",
            "options": [
                "Plotly",
                "Set1",
                "Set2",
                "Set3",
                "Pastel1",
                "Pastel2",
                "Dark2",
                "Vivid",
                "Custom",
            ],
            "description": "Palette used when Color by is a categorical column. Pick a named palette or 'Custom' to supply your own list.",
        },
        "color_continuous_scale": {
            "type": ParameterType.SELECT,
            "label": "Continuous scale",
            "options": [
                "Viridis",
                "Plasma",
                "Inferno",
                "Magma",
                "Cividis",
                "Blues",
                "Greens",
                "Reds",
                "RdBu",
                "RdYlBu",
                "RdYlGn",
                "Spectral",
                "Turbo",
                "Custom",
            ],
            "description": "Scale used when Color by is a numeric column. Diverging scales (RdBu, Spectral) shine when values cross a midpoint.",
        },
        "color_continuous_midpoint": {
            "type": ParameterType.FLOAT,
            "label": "Color midpoint",
            "description": "Value to center the diverging color scale on (e.g. 0 for signed deltas).",
        },
        "range_color": {
            "type": ParameterType.RANGE,
            "label": "Color range",
            "description": "Min / max bounds for the continuous color scale. Useful for clipping outliers.",
        },
        "category_orders": {
            "type": ParameterType.STRING,
            "label": "Category order (JSON)",
            "description": 'Force the order of categorical values. JSON dict, e.g. {"day": ["Mon", "Tue", "Wed"]}.',
        },
        "color_discrete_map": {
            "type": ParameterType.STRING,
            "label": "Color map (JSON)",
            "description": 'Pin specific values to specific colors. JSON dict, e.g. {"A": "red", "B": "blue"}.',
        },
    }

    # Advanced parameters for expert users.
    ADVANCED_PARAMETERS = {
        "log_x": {
            "type": ParameterType.BOOLEAN,
            "label": "Log X axis",
            "description": "Plot the X axis on a logarithmic scale. Useful for values spanning multiple orders of magnitude.",
            "default": False,
        },
        "log_y": {
            "type": ParameterType.BOOLEAN,
            "label": "Log Y axis",
            "description": "Plot the Y axis on a logarithmic scale.",
            "default": False,
        },
        "range_x": {
            "type": ParameterType.RANGE,
            "label": "X axis range",
            "description": "Min / max bounds for the X axis. Leave blank to autoscale.",
        },
        "range_y": {
            "type": ParameterType.RANGE,
            "label": "Y axis range",
            "description": "Min / max bounds for the Y axis. Leave blank to autoscale.",
        },
        "boxmode": {
            "type": ParameterType.SELECT,
            "label": "Box mode",
            "options": ["group", "overlay"],
            "description": "How to lay out boxes when Color is set. 'group' = side-by-side, 'overlay' = stacked.",
            "default": "group",
        },
        "violinmode": {
            "type": ParameterType.SELECT,
            "label": "Violin mode",
            "options": ["group", "overlay"],
            "description": "How to lay out violins when Color is set. 'group' = side-by-side, 'overlay' = stacked.",
            "default": "group",
        },
        "barmode": {
            "type": ParameterType.SELECT,
            "label": "Bar mode",
            "options": ["relative", "group", "overlay", "stack"],
            "description": "How multi-series bars are arranged. 'group' = side-by-side, 'stack' = stacked totals, 'overlay' = drawn on top, 'relative' = stacked with negatives below 0.",
            "default": "relative",
        },
        "animation_frame": {
            "type": ParameterType.COLUMN,
            "label": "Animation frame",
            "description": "Column whose distinct values become animation frames (one frame per value).",
        },
        "animation_group": {
            "type": ParameterType.COLUMN,
            "label": "Animation group",
            "description": "Column linking the same item across frames so transitions animate smoothly.",
        },
        "facet_row": {
            "type": ParameterType.COLUMN,
            "label": "Facet rows by",
            "description": "Split the figure into a row of subplots, one per distinct value of this column.",
        },
        "facet_col": {
            "type": ParameterType.COLUMN,
            "label": "Facet columns by",
            "description": "Split the figure into a column of subplots, one per distinct value of this column.",
        },
        "facet_col_wrap": {
            "type": ParameterType.INTEGER,
            "label": "Facet wrap",
            "min_value": 1,
            "description": "Number of facet columns before wrapping to a new row.",
        },
        "orientation": {
            "type": ParameterType.SELECT,
            "label": "Orientation",
            "options": ["v", "h"],
            "description": "Plot orientation. 'v' = vertical (default), 'h' = horizontal (X and Y swap roles).",
            "default": "v",
        },
        "histnorm": {
            "type": ParameterType.SELECT,
            "label": "Normalization",
            "options": ["", "percent", "probability", "density", "probability density"],
            "description": "How to normalize bin counts. '' = raw count, 'percent' = % of total, 'density' = count divided by bin width.",
            "default": "",
        },
        "histfunc": {
            "type": ParameterType.SELECT,
            "label": "Aggregation",
            "options": ["count", "sum", "avg", "min", "max"],
            "description": "Aggregation function applied to bin contents. 'count' (default) tallies rows; others aggregate Y values per bin.",
            "default": "count",
        },
        "nbins": {
            "type": ParameterType.INTEGER,
            "label": "Bin count",
            "min_value": 1,
            "description": "Target number of bins. Higher = finer resolution. Leave blank for Plotly's auto-binning.",
        },
        "nbinsx": {
            "type": ParameterType.INTEGER,
            "label": "Bins (X)",
            "min_value": 1,
            "description": "Target number of bins along the X axis (2D density plots).",
        },
        "nbinsy": {
            "type": ParameterType.INTEGER,
            "label": "Bins (Y)",
            "min_value": 1,
            "description": "Target number of bins along the Y axis (2D density plots).",
        },
        "cumulative": {
            "type": ParameterType.BOOLEAN,
            "label": "Cumulative",
            "description": "Plot the running cumulative count instead of per-bin counts.",
            "default": False,
        },
        "ecdfnorm": {
            "type": ParameterType.SELECT,
            "label": "ECDF normalization",
            "options": ["probability", "percent"],
            "description": "How to scale the cumulative axis. 'probability' = 0…1, 'percent' = 0…100. Leave blank for raw counts.",
        },
        "ecdfmode": {
            "type": ParameterType.SELECT,
            "label": "ECDF direction",
            "options": ["standard", "complementary", "reversed"],
            "description": "'standard' = P(X ≤ x), 'complementary' = P(X > x), 'reversed' = same as standard but right-to-left.",
            "default": "standard",
        },
        "points": {
            "type": ParameterType.SELECT,
            "label": "Show points",
            "options": ["outliers", "suspectedoutliers", "all", False],
            "description": "Which individual observations to overlay on box / violin plots. False hides all points.",
            "default": "outliers",
        },
        "notched": {
            "type": ParameterType.BOOLEAN,
            "label": "Notched box",
            "description": "Draw confidence-interval notches around the median. Non-overlapping notches suggest a real difference.",
            "default": False,
        },
        "line_shape": {
            "type": ParameterType.SELECT,
            "label": "Line shape",
            "options": ["linear", "spline", "vhv", "hvh", "vh", "hv"],
            "description": "Line interpolation. 'linear' = straight, 'spline' = smooth curve, the rest are stepwise.",
            "default": "linear",
        },
        "markers": {
            "type": ParameterType.BOOLEAN,
            "label": "Show markers",
            "description": "Draw a marker at each line point in addition to the line itself.",
            "default": False,
        },
        "trendline": {
            "type": ParameterType.SELECT,
            "label": "Trendline",
            "options": ["ols", "lowess", "rolling", "expanding", "ewm"],
            "description": "Overlay a fitted trend. 'ols' = linear regression, 'lowess' = locally weighted, others are moving-window aggregates.",
        },
        "marginal_x": {
            "type": ParameterType.SELECT,
            "label": "Marginal X",
            "options": ["histogram", "rug", "box", "violin"],
            "description": "Add a marginal subplot above the main chart showing the X distribution.",
        },
        "marginal_y": {
            "type": ParameterType.SELECT,
            "label": "Marginal Y",
            "options": ["histogram", "rug", "box", "violin"],
            "description": "Add a marginal subplot to the right showing the Y distribution.",
        },
        "size": {
            "type": ParameterType.COLUMN,
            "label": "Size by",
            "description": "Column whose numeric values map to marker size. Rows with NaN are dropped.",
        },
        "size_max": {
            "type": ParameterType.INTEGER,
            "label": "Max size",
            "min_value": 1,
            "max_value": 100,
            "description": "Pixel diameter of the largest marker when using Size by.",
            "default": 20,
        },
        "text": {
            "type": ParameterType.COLUMN,
            "label": "Text by",
            "description": "Column whose values appear as text labels next to each marker.",
        },
        "mode": {
            "type": ParameterType.SELECT,
            "label": "Trace mode",
            "options": [
                "lines",
                "markers",
                "lines+markers",
                "text",
                "lines+text",
                "markers+text",
                "lines+markers+text",
            ],
            "description": "What to draw for each trace: lines, markers, text, or any combination.",
            "default": "lines",
        },
        "symbol": {
            "type": ParameterType.SELECT,
            "label": "Marker symbol",
            "options": [
                "circle",
                "square",
                "diamond",
                "cross",
                "x",
                "triangle-up",
                "triangle-down",
                "triangle-left",
                "triangle-right",
                "pentagon",
                "hexagon",
                "star",
            ],
            "description": "Fixed marker shape applied to all points. Pick a column instead to vary by category.",
            # "default": "circle",
        },
        "line_dash": {
            "type": ParameterType.SELECT,
            "label": "Line dash",
            "options": ["solid", "dot", "dash", "longdash", "dashdot", "longdashdot"],
            "description": "Fixed dash pattern applied to all lines. Pick a column instead to vary by category.",
            "default": "solid",
        },
        "dimensions": {
            # Populated with the dataset's numeric column names by the React
            # ParameterField when it sees `name == 'dimensions'`. Pinned to
            # SPECIFIC so it surfaces under the per-viz Specialized accordion
            # rather than the generic Advanced one.
            "type": ParameterType.MULTI_SELECT,
            "category": ParameterCategory.SPECIFIC,
            "label": "Dimensions",
            "options": [],
            "description": "Numeric columns to include in the scatter matrix. Pick at least two.",
            "required": True,
        },
    }

    # Per-visualization Specialized parameter sets. These params live in the
    # ADVANCED knowledge base (so they share labels/descriptions across viz)
    # but are *promoted* to the SPECIFIC category for the listed viz types so
    # they surface in the per-viz "{Viz} Options" accordion alongside truly
    # bespoke params (like `dimensions` for scatter_matrix). This keeps the
    # generic Advanced accordion focused on cross-cutting tweaks (log axes,
    # range, faceting, animation) and the Specialized accordion focused on
    # the knobs that meaningfully change *this* viz type.
    VIZ_SPECIFIC_PARAMS: Dict[str, set] = {
        "scatter": {"size", "size_max", "text", "trendline", "marginal_x", "marginal_y", "symbol"},
        "line": {"line_shape", "markers", "line_dash", "text"},
        "bar": {"barmode", "text"},
        "box": {"points", "notched", "boxmode"},
        "violin": {"points", "violinmode"},
        "histogram": {"histfunc", "histnorm", "nbins", "cumulative", "barmode", "marginal_x"},
        "density_heatmap": {
            "histfunc",
            "histnorm",
            "nbinsx",
            "nbinsy",
            "marginal_x",
            "marginal_y",
        },
        "density_contour": {
            "trendline",
            "histfunc",
            "histnorm",
            "nbinsx",
            "nbinsy",
            "marginal_x",
            "marginal_y",
        },
        "funnel": {"text"},
        "ecdf": {"ecdfnorm", "ecdfmode", "markers"},
        "strip": {"points"},
        "area": {"line_shape"},
        "scatter_matrix": {"size", "symbol"},
    }

    # Type mapping from Python types to our ParameterType enum
    TYPE_MAPPING = {
        str: ParameterType.STRING,
        int: ParameterType.INTEGER,
        float: ParameterType.FLOAT,
        bool: ParameterType.BOOLEAN,
        list: ParameterType.MULTI_SELECT,
        dict: ParameterType.STRING,  # Treat dicts as JSON strings
    }

    def __init__(self):
        """Initialize the parameter inspector."""
        self._function_cache: Dict[str, inspect.Signature] = {}
        self._parameter_cache: Dict[str, List[ParameterDefinition]] = {}

    def get_function_signature(self, func_name: str) -> Optional[inspect.Signature]:
        """Get function signature with caching.

        Args:
            func_name: Name of the Plotly Express function

        Returns:
            Function signature or None if not found
        """
        if func_name in self._function_cache:
            return self._function_cache[func_name]

        try:
            func = getattr(px, func_name)
            signature = inspect.signature(func)
            self._function_cache[func_name] = signature
            return signature
        except AttributeError:
            logger.warning(f"Function {func_name} not found in plotly.express")
            return None

    # Regex patterns for column-type parameters
    _COLUMN_PATTERNS = [
        "^x$",
        "^y$",
        "^z$",
        "^color$",
        "^size$",
        "^symbol$",
        "^text$",
        "hover_name",
        "^parent",
        "^ids",
        "facet_row$",
        "facet_col$",  # But not facet_col_wrap, facet_col_spacing
        "animation_frame",
        "animation_group",
    ]

    # Keywords indicating boolean parameters
    _BOOLEAN_KEYWORDS = ["log_", "show_", "is_", "has_", "cumulative", "notched", "markers"]

    # Keywords indicating numeric parameters
    _NUMERIC_KEYWORDS = ["size", "opacity", "nbins"]

    # Parameter names that should be SELECT type
    _SELECT_PARAMS = {
        "orientation",
        "barmode",
        "histnorm",
        "points",
        "violinmode",
        "line_shape",
        "trendline",
        "marginal_x",
        "marginal_y",
    }

    # Keywords indicating multi-select parameters
    _MULTISELECT_KEYWORDS = ["hover_data", "custom_data"]

    def _get_type_from_annotation(self, annotation: Any) -> Optional[ParameterType]:
        """Extract parameter type from type annotation.

        Args:
            annotation: The type annotation from the function signature.

        Returns:
            The inferred ParameterType or None if not determinable.
        """
        # Handle Union types (like Optional[str])
        if hasattr(annotation, "__origin__") and annotation.__origin__ is Union:
            for arg in annotation.__args__:
                if arg is not type(None):
                    annotation = arg
                    break

        return self.TYPE_MAPPING.get(annotation)

    def _infer_type_from_name(self, param_name: str) -> ParameterType:
        """Infer parameter type from parameter name patterns.

        Args:
            param_name: The lowercase parameter name.

        Returns:
            The inferred ParameterType based on naming conventions.
        """
        import re

        # Check column patterns
        if any(re.search(pattern, param_name) for pattern in self._COLUMN_PATTERNS):
            return ParameterType.COLUMN

        # Check boolean patterns
        if any(keyword in param_name for keyword in self._BOOLEAN_KEYWORDS):
            return ParameterType.BOOLEAN

        # Check numeric patterns (excluding width/height)
        if any(keyword in param_name for keyword in self._NUMERIC_KEYWORDS) and param_name not in [
            "width",
            "height",
        ]:
            if "size" in param_name and "max" in param_name:
                return ParameterType.INTEGER
            return ParameterType.FLOAT if "opacity" in param_name else ParameterType.INTEGER

        # Check select parameters
        if param_name in self._SELECT_PARAMS:
            return ParameterType.SELECT

        # Check multi-select patterns
        if any(keyword in param_name for keyword in self._MULTISELECT_KEYWORDS):
            return ParameterType.MULTI_SELECT

        return ParameterType.STRING

    def infer_parameter_type(self, param: inspect.Parameter) -> ParameterType:
        """Infer parameter type from function signature.

        First attempts to determine type from the parameter's type annotation,
        then falls back to name-based pattern matching.

        Args:
            param: Function parameter from inspect.signature().

        Returns:
            Inferred parameter type for UI control generation.
        """
        # Try annotation first
        if param.annotation != inspect.Parameter.empty:
            inferred = self._get_type_from_annotation(param.annotation)
            if inferred is not None:
                return inferred

        # Fallback to name-based inference
        return self._infer_type_from_name(param.name.lower())

    def categorize_parameter(self, param_name: str, func_name: str) -> ParameterCategory:
        """Categorize a parameter based on its name and function context.

        Order:
        1. CORE (x/y/z/color) — always.
        2. COMMON — generic across viz types (title, theme, hover, palette).
        3. **Per-viz SPECIFIC promotion** — params in `VIZ_SPECIFIC_PARAMS[func_name]`
           are pulled out of ADVANCED into the Specialized accordion so the
           per-viz "{Viz} Options" panel surfaces the most relevant knobs.
        4. ADVANCED — cross-cutting expert tweaks (log axes, range, faceting).
        5. SPECIFIC — anything we didn't explicitly categorize (auto-discovered).
        """
        if param_name in self.CORE_PARAMETERS:
            return ParameterCategory.CORE
        elif param_name in self.COMMON_PARAMETERS:
            return ParameterCategory.COMMON
        elif param_name in self.VIZ_SPECIFIC_PARAMS.get(func_name, set()):
            return ParameterCategory.SPECIFIC
        elif param_name in self.ADVANCED_PARAMETERS:
            return ParameterCategory.ADVANCED
        else:
            # Function-specific parameters (auto-discovered, no overrides)
            return ParameterCategory.SPECIFIC

    def get_parameter_metadata(self, param_name: str) -> Dict[str, Any]:
        """Get metadata for a parameter from our knowledge base.

        Args:
            param_name: Parameter name

        Returns:
            Parameter metadata
        """
        # Check our knowledge bases
        for knowledge_base in [
            self.CORE_PARAMETERS,
            self.COMMON_PARAMETERS,
            self.ADVANCED_PARAMETERS,
        ]:
            if param_name in knowledge_base:
                return knowledge_base[param_name]

        # Return default metadata
        return {"description": f"Parameter: {param_name}"}

    def _get_special_parameter_overrides(
        self, func_name: str
    ) -> Optional[List[ParameterDefinition]]:
        """Get special parameter overrides for visualizations that need custom parameter definitions.

        Args:
            func_name: Name of the visualization function

        Returns:
            List of parameter definitions if override exists, None otherwise
        """
        overrides = {
            "violin": self._create_violin_parameters,
            "sunburst": self._create_sunburst_parameters,
            "treemap": self._create_treemap_parameters,
            "pie": self._create_pie_parameters,
            "timeline": self._create_timeline_parameters,
        }

        if func_name in overrides:
            return overrides[func_name]()
        return None

    def _create_violin_parameters(self) -> List[ParameterDefinition]:
        """Hand-curated parameter set for violin plots.

        Returns a focused subset of Plotly's full violin signature — just the
        knobs that meaningfully change the violin output. Labels and copy
        match the knowledge-base conventions so the form reads consistently.
        """
        return [
            ParameterDefinition(
                name="y",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Y axis*",
                description="Numeric column whose distribution is drawn as the violin shape. At least one of X / Y is required.",
                required=False,
            ),
            ParameterDefinition(
                name="x",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="X axis",
                description="Categorical column to group violins side-by-side.",
                required=False,
            ),
            ParameterDefinition(
                name="color",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Color by",
                description="Column whose values map to violin color (categorical → discrete palette).",
                required=False,
            ),
            *self._get_common_plot_parameters(),
            ParameterDefinition(
                name="box",
                type=ParameterType.BOOLEAN,
                category=ParameterCategory.SPECIFIC,
                label="Show inner box",
                description="Embed a thin box plot inside each violin for quick median + IQR reference.",
                default=False,
                required=False,
            ),
            ParameterDefinition(
                name="points",
                type=ParameterType.SELECT,
                category=ParameterCategory.SPECIFIC,
                label="Show points",
                description="Which observations to overlay on each violin. False hides all points.",
                options=["outliers", "suspectedoutliers", "all", False],
                default=False,
                required=False,
            ),
            ParameterDefinition(
                name="violinmode",
                type=ParameterType.SELECT,
                category=ParameterCategory.SPECIFIC,
                label="Violin mode",
                description="Layout when Color by is set. 'group' = side-by-side, 'overlay' = stacked.",
                options=["group", "overlay"],
                default="group",
                required=False,
            ),
            ParameterDefinition(
                name="orientation",
                type=ParameterType.SELECT,
                category=ParameterCategory.ADVANCED,
                label="Orientation",
                description="'v' = vertical (default), 'h' = horizontal (X and Y swap roles).",
                options=["v", "h"],
                default="v",
                required=False,
            ),
        ]

    def _create_sunburst_parameters(self) -> List[ParameterDefinition]:
        """Create proper parameters for sunburst charts."""
        return [
            # Core parameters
            ParameterDefinition(
                name="values",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Values",
                description="Values for each segment size",
                required=True,
            ),
            ParameterDefinition(
                name="parents",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Parents",
                description="Parent categories for hierarchy (leave empty for root-level charts)",
                required=False,
            ),
            ParameterDefinition(
                name="names",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Names",
                description="Names for each segment",
                required=False,
            ),
            ParameterDefinition(
                name="ids",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="IDs",
                description="Unique identifiers for segments",
                required=False,
            ),
            ParameterDefinition(
                name="color",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Color",
                description="Column for color encoding",
                required=False,
            ),
            # Common parameters
            *self._get_common_plot_parameters(),
            # Specific sunburst parameters
            ParameterDefinition(
                name="maxdepth",
                type=ParameterType.INTEGER,
                category=ParameterCategory.SPECIFIC,
                label="Max Depth",
                description="Maximum depth of hierarchy to show",
                min_value=1,
                max_value=10,
                required=False,
            ),
        ]

    def _create_treemap_parameters(self) -> List[ParameterDefinition]:
        """Create proper parameters for treemap charts."""
        return [
            # Core parameters
            ParameterDefinition(
                name="values",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Values",
                description="Values for each rectangle size",
                required=True,
            ),
            ParameterDefinition(
                name="parents",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Parents",
                description="Parent categories for hierarchy (leave empty for root-level charts)",
                required=False,
            ),
            ParameterDefinition(
                name="names",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Names",
                description="Names for each rectangle",
                required=False,
            ),
            ParameterDefinition(
                name="ids",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="IDs",
                description="Unique identifiers for rectangles",
                required=False,
            ),
            ParameterDefinition(
                name="color",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Color",
                description="Column for color encoding",
                required=False,
            ),
            # Common parameters
            *self._get_common_plot_parameters(),
            # Specific treemap parameters
            ParameterDefinition(
                name="maxdepth",
                type=ParameterType.INTEGER,
                category=ParameterCategory.SPECIFIC,
                label="Max Depth",
                description="Maximum depth of hierarchy to show",
                min_value=1,
                max_value=10,
                required=False,
            ),
        ]

    def _create_pie_parameters(self) -> List[ParameterDefinition]:
        """Create proper parameters for pie charts."""
        return [
            # Core parameters
            ParameterDefinition(
                name="values",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="values*",
                description="Values for each slice size (at least one * parameter is required)",
                required=False,  # Semi-required
            ),
            ParameterDefinition(
                name="names",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="names*",
                description="Names for each slice (at least one * parameter is required)",
                required=False,  # Semi-required
            ),
            ParameterDefinition(
                name="color",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="color",
                description="Column for color encoding",
                required=False,
            ),
            # Common parameters
            *self._get_common_plot_parameters(),
            # Specific pie parameters
            ParameterDefinition(
                name="hole",
                type=ParameterType.FLOAT,
                category=ParameterCategory.SPECIFIC,
                label="Hole Size",
                description="Size of hole in center (0 = pie, >0 = donut)",
                min_value=0.0,
                max_value=0.9,
                default=0.0,
                required=False,
            ),
        ]

    def _create_timeline_parameters(self) -> List[ParameterDefinition]:
        """Create proper parameters for timeline charts."""
        return [
            # Core parameters
            ParameterDefinition(
                name="x_start",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Start Time",
                description="Start time/date for timeline events",
                required=True,
            ),
            ParameterDefinition(
                name="x_end",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="End Time",
                description="End time/date for timeline events",
                required=False,
            ),
            ParameterDefinition(
                name="y",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Category",
                description="Categories for timeline rows",
                required=False,
            ),
            ParameterDefinition(
                name="color",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="Color",
                description="Column for color encoding",
                required=False,
            ),
            # Common parameters
            *self._get_common_plot_parameters(),
        ]

    def _get_common_plot_parameters(self) -> List[ParameterDefinition]:
        """Get common parameters that apply to most visualizations.

        Labels and copy mirror the knowledge-base entries in
        `COMMON_PARAMETERS` so curated overrides (violin, sunburst, …) read
        consistently with the auto-introspected viz types.
        """
        return [
            ParameterDefinition(
                name="title",
                type=ParameterType.STRING,
                category=ParameterCategory.COMMON,
                label="Title",
                description="Headline shown above the figure.",
                required=False,
            ),
            ParameterDefinition(
                name="hover_name",
                type=ParameterType.COLUMN,
                category=ParameterCategory.COMMON,
                label="Hover title",
                description="Column whose values appear bolded as the tooltip title on hover.",
                required=False,
            ),
            ParameterDefinition(
                name="hover_data",
                type=ParameterType.MULTI_SELECT,
                category=ParameterCategory.COMMON,
                label="Hover fields",
                description="Extra columns to surface in the hover tooltip alongside the default x/y values.",
                required=False,
                options=[],
            ),
        ]

    def discover_parameters(self, func_name: str) -> List[ParameterDefinition]:
        """Discover parameters for a Plotly Express function.

        Args:
            func_name: Name of the Plotly Express function

        Returns:
            List of parameter definitions
        """
        if func_name in self._parameter_cache:
            return self._parameter_cache[func_name]

        # Check for special parameter overrides first
        special_params = self._get_special_parameter_overrides(func_name)
        if special_params:
            self._parameter_cache[func_name] = special_params
            return special_params

        signature = self.get_function_signature(func_name)
        if not signature:
            return []

        parameters = []

        for param_name, param in signature.parameters.items():
            # Skip special parameters and disabled parameters
            if param_name in ["data_frame", "kwargs", "args", "width", "height"]:
                continue

            # Get parameter metadata
            metadata = self.get_parameter_metadata(param_name)

            # Infer parameter type from the Plotly Express signature, then let
            # the metadata override it. This ensures that params like
            # `template`, `color_continuous_scale`, `line_dash`, `histfunc`
            # — declared as `select` in COMMON/ADVANCED_PARAMETERS — surface
            # to the React ParameterField as Selects rather than free-form
            # TextInputs even though Plotly's signature types them as `str`.
            inferred_type = self.infer_parameter_type(param)
            param_type = metadata.get("type", inferred_type)

            # Categorize parameter. Knowledge-base entries can pin their own
            # category via `metadata["category"]` — otherwise fall back to the
            # name-based default. This lets `dimensions` (Scatter Matrix) sit
            # under the per-viz Specialized accordion instead of Advanced.
            inferred_category = self.categorize_parameter(param_name, func_name)
            category = metadata.get("category", inferred_category)

            # Create parameter definition
            param_def = ParameterDefinition(
                name=param_name,
                type=param_type,
                category=category,
                label=metadata.get(
                    "label", param_name
                ),  # Use label from metadata or parameter name
                description=metadata.get("description", f"Parameter: {param_name}"),
                default=metadata.get(
                    "default", param.default if param.default != inspect.Parameter.empty else None
                ),
                required=metadata.get("required", param.default == inspect.Parameter.empty),
                options=metadata.get("options"),
                min_value=metadata.get("min_value"),
                max_value=metadata.get("max_value"),
                depends_on=metadata.get("depends_on"),
            )

            parameters.append(param_def)

        # Cache the result
        self._parameter_cache[func_name] = parameters

        return parameters

    def create_visualization_definition(
        self,
        func_name: str,
        label: Optional[str] = None,
        description: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> VisualizationDefinition:
        """Create a visualization definition for a Plotly Express function.

        Args:
            func_name: Name of the Plotly Express function
            label: Human-readable label
            description: Visualization description
            icon: Icon name

        Returns:
            Visualization definition
        """
        parameters = self.discover_parameters(func_name)

        return VisualizationDefinition(
            name=func_name,
            function_name=func_name,
            label=label or func_name.replace("_", " ").title(),
            description=description or f"Create a {func_name} plot",
            parameters=parameters,
            icon=icon or "mdi:chart-line",
        )


# Global parameter inspector instance
parameter_inspector = ParameterInspector()


def get_available_plotly_functions() -> List[str]:
    """Get list of available Plotly Express functions.

    Returns:
        List of function names
    """
    functions = []
    for name in dir(px):
        obj = getattr(px, name)
        if callable(obj) and not name.startswith("_"):
            # Check if it's a plotting function (has 'data_frame' parameter)
            try:
                sig = inspect.signature(obj)
                if "data_frame" in sig.parameters:
                    functions.append(name)
            except (ValueError, TypeError):
                pass

    return sorted(functions)


def get_visualization_group(func_name: str) -> VisualizationGroup:
    """Determine the group for a visualization function."""
    # Core/Standard visualizations
    core_viz = {"scatter", "line", "bar", "histogram", "box", "violin", "area"}

    # Advanced statistical plots
    advanced_viz = {
        "density_contour",
        "density_heatmap",
        "parallel_coordinates",
        "parallel_categories",
        "ecdf",
        "strip",
        "sunburst",
        "treemap",
        "funnel",
        "funnel_area",
        "icicle",
        "timeline",
        "pie",  # Moved pie to advanced (though it will be disabled)
    }

    # 3D visualizations
    three_d_viz = {"scatter_3d", "line_3d"}

    # Geographic visualizations
    geographic_viz = {
        "choropleth",
        "choropleth_map",
        "choropleth_mapbox",
        "density_map",
        "density_mapbox",
        "line_geo",
        "line_map",
        "line_mapbox",
        "scatter_geo",
        "scatter_map",
        "scatter_mapbox",
    }

    # Clustering visualizations (custom implementations)
    clustering_viz = {"umap"}

    if func_name in core_viz:
        return VisualizationGroup.CORE
    elif func_name in advanced_viz:
        return VisualizationGroup.ADVANCED
    elif func_name in three_d_viz:
        return VisualizationGroup.THREE_D
    elif func_name in geographic_viz:
        return VisualizationGroup.GEOGRAPHIC
    elif func_name in clustering_viz:
        return VisualizationGroup.CLUSTERING
    else:
        return VisualizationGroup.SPECIALIZED


# Icon mapping for visualization types
_VISUALIZATION_ICONS: Dict[str, str] = {
    "scatter": "mdi:chart-scatter-plot",
    "line": "mdi:chart-line",
    "bar": "mdi:chart-bar",
    "histogram": "mdi:chart-histogram",
    "box": "mdi:chart-box-outline",
    "violin": "mdi:violin",
    "pie": "mdi:chart-pie",
    "sunburst": "mdi:chart-donut",
    "treemap": "mdi:view-grid",
    "funnel": "mdi:filter",
    "area": "mdi:chart-areaspline",
    "density_contour": "mdi:chart-scatter-plot",
    "density_heatmap": "mdi:grid",
    "imshow": "mdi:grid",
    "strip": "mdi:chart-scatter-plot",
    "parallel_coordinates": "mdi:chart-line-variant",
    "parallel_categories": "mdi:chart-sankey",
    "umap": "mdi:scatter-plot",
    "heatmap": "mdi:grid-large",
    "ecdf": "mdi:chart-bell-curve-cumulative",
    "scatter_matrix": "mdi:view-grid-outline",
}

# Visualizations temporarily disabled from the UI. `ecdf` and `strip` were
# previously disabled — they're now part of the curated 2D set and must remain
# enabled for the React builder dropdown to populate them.
_DISABLED_VISUALIZATIONS: set[str] = {
    "funnel_area",
    "icicle",
    "parallel_categories",
    "parallel_coordinates",
    "umap",
    "pie",
    "sunburst",
    "timeline",
    "treemap",
}


def discover_all_visualizations() -> Dict[str, VisualizationDefinition]:
    """Discover all available visualizations dynamically.

    Inspects Plotly Express to find available plotting functions, creates
    visualization definitions with appropriate parameters, icons, and groupings.
    Custom visualizations (e.g., UMAP) are also included.

    Returns:
        Dictionary mapping function names to visualization definitions.
    """
    functions = get_available_plotly_functions()
    functions.extend(["umap", "heatmap"])  # Add custom visualization functions

    visualizations = {}

    for func_name in functions:
        if func_name in _DISABLED_VISUALIZATIONS:
            continue

        try:
            if func_name == "umap":
                viz_def = create_umap_visualization_definition()
            elif func_name == "heatmap":
                viz_def = create_heatmap_visualization_definition()
            else:
                viz_def = parameter_inspector.create_visualization_definition(
                    func_name=func_name,
                    icon=_VISUALIZATION_ICONS.get(func_name, "mdi:chart-line"),
                )

            viz_def.group = get_visualization_group(func_name)
            visualizations[func_name] = viz_def

        except Exception as e:
            logger.warning(f"Failed to create definition for {func_name}: {e}")

    logger.debug(f"Discovered {len(visualizations)} visualizations")
    return visualizations


def create_umap_visualization_definition() -> VisualizationDefinition:
    """Create UMAP visualization definition with custom parameters."""

    # Define UMAP-specific parameters
    umap_parameters = [
        # Core parameters
        ParameterDefinition(
            name="features",
            type=ParameterType.MULTI_SELECT,
            category=ParameterCategory.CORE,
            label="Features",
            description="Columns to use for UMAP computation (if empty, uses all numeric columns)",
            required=False,
            options=[],  # Will be populated with column names
        ),
        ParameterDefinition(
            name="color",
            type=ParameterType.COLUMN,
            category=ParameterCategory.CORE,
            label="Color",
            description="Column for color encoding",
            required=False,
        ),
        # UMAP-specific parameters
        ParameterDefinition(
            name="n_neighbors",
            type=ParameterType.INTEGER,
            category=ParameterCategory.SPECIFIC,
            label="Number of Neighbors",
            description="Number of nearest neighbors for UMAP",
            default=15,
            min_value=2,
            max_value=200,
            required=False,
        ),
        ParameterDefinition(
            name="min_dist",
            type=ParameterType.FLOAT,
            category=ParameterCategory.SPECIFIC,
            label="Minimum Distance",
            description="Minimum distance between points in low-dimensional space",
            default=0.1,
            min_value=0.0,
            max_value=1.0,
            required=False,
        ),
        ParameterDefinition(
            name="n_components",
            type=ParameterType.SELECT,
            category=ParameterCategory.SPECIFIC,
            label="Number of Components",
            description="Number of dimensions for UMAP output",
            options=[2, 3],
            default=2,
            required=False,
        ),
        ParameterDefinition(
            name="metric",
            type=ParameterType.SELECT,
            category=ParameterCategory.SPECIFIC,
            label="Distance Metric",
            description="Distance metric for UMAP",
            options=["euclidean", "manhattan", "chebyshev", "minkowski", "cosine", "correlation"],
            default="euclidean",
            required=False,
        ),
        ParameterDefinition(
            name="random_state",
            type=ParameterType.INTEGER,
            category=ParameterCategory.SPECIFIC,
            label="Random State",
            description="Random state for reproducibility",
            default=42,
            min_value=0,
            max_value=10000,
            required=False,
        ),
        # Common visualization parameters
        ParameterDefinition(
            name="hover_name",
            type=ParameterType.COLUMN,
            category=ParameterCategory.COMMON,
            label="Hover Name",
            description="Column for hover tooltip names",
            required=False,
        ),
        ParameterDefinition(
            name="hover_data",
            type=ParameterType.MULTI_SELECT,
            category=ParameterCategory.COMMON,
            label="Hover Data",
            description="Columns to show on hover",
            required=False,
            options=[],
        ),
        ParameterDefinition(
            name="title",
            type=ParameterType.STRING,
            category=ParameterCategory.COMMON,
            label="Title",
            description="Plot title",
            required=False,
        ),
        ParameterDefinition(
            name="width",
            type=ParameterType.INTEGER,
            category=ParameterCategory.COMMON,
            label="Width",
            description="Figure width in pixels",
            min_value=100,
            max_value=2000,
            required=False,
        ),
        ParameterDefinition(
            name="height",
            type=ParameterType.INTEGER,
            category=ParameterCategory.COMMON,
            label="Height",
            description="Figure height in pixels",
            min_value=100,
            max_value=2000,
            required=False,
        ),
        ParameterDefinition(
            name="template",
            type=ParameterType.SELECT,
            category=ParameterCategory.COMMON,
            label="Template",
            description="Plotly template",
            options=[
                "mantine_light",
                "mantine_dark",
                "plotly",
                "plotly_white",
                "plotly_dark",
                "ggplot2",
                "seaborn",
                "simple_white",
                "presentation",
                "none",
            ],
            default=None,
            required=False,
        ),
        ParameterDefinition(
            name="opacity",
            type=ParameterType.FLOAT,
            category=ParameterCategory.COMMON,
            label="Opacity",
            description="Marker opacity",
            min_value=0.0,
            max_value=1.0,
            default=0.7,
            required=False,
        ),
    ]

    return VisualizationDefinition(
        name="umap",
        function_name="umap",  # Custom function name
        label="UMAP",
        description="Uniform Manifold Approximation and Projection for dimensionality reduction",
        parameters=umap_parameters,
        icon="mdi:scatter-plot",
        group=VisualizationGroup.CLUSTERING,
    )


def create_heatmap_visualization_definition() -> VisualizationDefinition:
    """Create ComplexHeatmap visualization definition with custom parameters."""

    heatmap_parameters = [
        # Core parameters
        ParameterDefinition(
            name="index_column",
            type=ParameterType.COLUMN,
            category=ParameterCategory.CORE,
            label="Index Column",
            description="Column to use as row labels",
            required=False,
        ),
        ParameterDefinition(
            name="value_columns",
            type=ParameterType.MULTI_SELECT,
            category=ParameterCategory.CORE,
            label="Value Columns",
            description="Numeric columns for the heatmap matrix (if empty, all numeric columns are used)",
            required=False,
            options=[],
        ),
        ParameterDefinition(
            name="row_annotations",
            type=ParameterType.MULTI_SELECT,
            category=ParameterCategory.CORE,
            label="Row Annotations",
            description="Columns to display as annotation tracks alongside the heatmap",
            required=False,
            options=[],
        ),
        # Heatmap-specific parameters
        ParameterDefinition(
            name="cluster_rows",
            type=ParameterType.BOOLEAN,
            category=ParameterCategory.SPECIFIC,
            label="Cluster Rows",
            description="Perform hierarchical clustering on rows",
            default=True,
            required=False,
        ),
        ParameterDefinition(
            name="cluster_cols",
            type=ParameterType.BOOLEAN,
            category=ParameterCategory.SPECIFIC,
            label="Cluster Columns",
            description="Perform hierarchical clustering on columns",
            default=True,
            required=False,
        ),
        ParameterDefinition(
            name="normalize",
            type=ParameterType.SELECT,
            category=ParameterCategory.SPECIFIC,
            label="Normalize",
            description="Z-score normalization method",
            options=["none", "row", "column", "global"],
            default="none",
            required=False,
        ),
        ParameterDefinition(
            name="colorscale",
            type=ParameterType.SELECT,
            category=ParameterCategory.SPECIFIC,
            label="Colorscale",
            description="Heatmap colorscale",
            options=[
                "RdBu_r",
                "Viridis",
                "Plasma",
                "Inferno",
                "Magma",
                "Cividis",
                "Blues",
                "Reds",
                "YlOrRd",
                "YlGnBu",
                "Picnic",
            ],
            default="RdBu_r",
            required=False,
        ),
        ParameterDefinition(
            name="cluster_method",
            type=ParameterType.SELECT,
            category=ParameterCategory.SPECIFIC,
            label="Cluster Method",
            description="Linkage method for hierarchical clustering",
            options=["ward", "complete", "average", "single", "weighted", "centroid", "median"],
            default="ward",
            required=False,
        ),
        ParameterDefinition(
            name="cluster_metric",
            type=ParameterType.SELECT,
            category=ParameterCategory.SPECIFIC,
            label="Distance Metric",
            description="Distance metric for clustering",
            options=["euclidean", "cityblock", "cosine", "correlation", "chebyshev"],
            default="euclidean",
            required=False,
        ),
        ParameterDefinition(
            name="split_rows_by",
            type=ParameterType.COLUMN,
            category=ParameterCategory.SPECIFIC,
            label="Split Rows By",
            description="Column or annotation track to split the heatmap into row groups",
            required=False,
        ),
        ParameterDefinition(
            name="row_annotation_side",
            type=ParameterType.SELECT,
            category=ParameterCategory.SPECIFIC,
            label="Row Annotation Side",
            description="Side for row annotations",
            options=["right", "left"],
            default="right",
            required=False,
        ),
        ParameterDefinition(
            name="col_annotation_side",
            type=ParameterType.SELECT,
            category=ParameterCategory.SPECIFIC,
            label="Column Annotation Side",
            description="Side for column annotations",
            options=["top", "bottom"],
            default="top",
            required=False,
        ),
        ParameterDefinition(
            name="dendro_ratio",
            type=ParameterType.FLOAT,
            category=ParameterCategory.SPECIFIC,
            label="Dendrogram Ratio",
            description="Fraction of figure allocated to each dendrogram",
            default=0.08,
            min_value=0.01,
            max_value=0.3,
            required=False,
        ),
        # Common visualization parameters
        ParameterDefinition(
            name="name",
            type=ParameterType.STRING,
            category=ParameterCategory.COMMON,
            label="Colorbar Title",
            description="Title for the heatmap colorbar",
            required=False,
        ),
        ParameterDefinition(
            name="width",
            type=ParameterType.INTEGER,
            category=ParameterCategory.COMMON,
            label="Width",
            description="Figure width in pixels",
            default=900,
            min_value=300,
            max_value=2000,
            required=False,
        ),
        ParameterDefinition(
            name="height",
            type=ParameterType.INTEGER,
            category=ParameterCategory.COMMON,
            label="Height",
            description="Figure height in pixels",
            default=700,
            min_value=300,
            max_value=2000,
            required=False,
        ),
    ]

    return VisualizationDefinition(
        name="heatmap",
        function_name="heatmap",
        label="Heatmap",
        description="Clustered heatmap with dendrograms and annotation tracks",
        parameters=heatmap_parameters,
        icon="mdi:grid-large",
        group=VisualizationGroup.SPECIALIZED,
    )


def get_common_visualizations() -> List[str]:
    """Get list of commonly used visualization types for UI display.

    Returns:
        List of common visualization function names
    """
    return ["scatter", "line", "bar", "histogram", "box", "area", "pie"]
