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
    """Inspects Plotly Express functions to discover parameters dynamically."""

    # Core parameters that are essential for most visualizations
    CORE_PARAMETERS = {
        "x": {
            "type": ParameterType.COLUMN,
            "required": False,
            "label": "x*",
            "description": "X-axis column (at least one * parameter is required)",
        },
        "y": {
            "type": ParameterType.COLUMN,
            "required": False,
            "label": "y*",
            "description": "Y-axis column (at least one * parameter is required)",
        },
        "color": {
            "type": ParameterType.COLUMN,
            "required": False,
            "description": "Color encoding column",
        },
        "z": {
            "type": ParameterType.COLUMN,
            "required": False,
            "label": "z*",
            "description": "Z-axis column for 3D plots (at least one * parameter is required)",
        },
    }

    # Common parameters shared across many visualizations
    COMMON_PARAMETERS = {
        "title": {"type": ParameterType.STRING, "description": "Figure title"},
        "template": {
            "type": ParameterType.SELECT,
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
            "description": "Plotly template",
            "default": None,
        },
        "opacity": {
            "type": ParameterType.FLOAT,
            "min_value": 0.0,
            "max_value": 1.0,
            "description": "Marker opacity",
        },
        "hover_name": {
            "type": ParameterType.COLUMN,
            "description": "Column for hover tooltip names",
        },
        "hover_data": {
            "type": ParameterType.MULTI_SELECT,
            "description": "Columns to show on hover",
            "options": [],  # Will be populated with column names by component builder
        },
        "custom_data": {
            "type": ParameterType.MULTI_SELECT,
            "description": "Custom data for interactions",
            "options": [],  # Will be populated with column names by component builder
        },
        "labels": {
            "type": ParameterType.STRING,
            "description": 'Custom axis labels dictionary. Format: {"column": "Custom Label"} or JSON string. Example: {"x": "Time (hours)", "y": "Temperature (°C)"}',
        },
        "color_discrete_sequence": {
            "type": ParameterType.SELECT,
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
            "description": "Discrete color sequence for categorical data. Choose from predefined palettes or select 'Custom' to enter a list like ['red', 'blue', 'green']",
        },
        "color_continuous_scale": {
            "type": ParameterType.SELECT,
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
            "description": "Continuous color scale for numerical data. Choose from predefined scales or select 'Custom' to enter a scale name",
        },
        "category_orders": {
            "type": ParameterType.STRING,
            "description": 'Category ordering dictionary. Format: {"column": ["value1", "value2"]} or JSON string. Example: {"day": ["Mon", "Tue", "Wed"]}',
        },
        "color_discrete_map": {
            "type": ParameterType.STRING,
            "description": 'Color mapping for discrete values. Format: {"value": "color"} or JSON string. Example: {"A": "red", "B": "blue"}',
        },
    }

    # Advanced parameters for expert users
    ADVANCED_PARAMETERS = {
        "log_x": {
            "type": ParameterType.BOOLEAN,
            "description": "Use logarithmic scale for x-axis",
            "default": False,
        },
        "log_y": {
            "type": ParameterType.BOOLEAN,
            "description": "Use logarithmic scale for y-axis",
            "default": False,
        },
        "range_x": {"type": ParameterType.RANGE, "description": "X-axis range"},
        "range_y": {"type": ParameterType.RANGE, "description": "Y-axis range"},
        "boxmode": {
            "type": ParameterType.SELECT,
            "options": ["group", "overlay"],
            "description": "Box plot display mode. 'group': boxes are placed beside each other, 'overlay': boxes are drawn on top of one another",
            "default": "group",
        },
        "animation_frame": {
            "type": ParameterType.COLUMN,
            "description": "Column for animation frames",
        },
        "animation_group": {
            "type": ParameterType.COLUMN,
            "description": "Column for animation grouping",
        },
        "facet_row": {"type": ParameterType.COLUMN, "description": "Column for faceting rows"},
        "facet_col": {"type": ParameterType.COLUMN, "description": "Column for faceting columns"},
        "facet_col_wrap": {
            "type": ParameterType.INTEGER,
            "min_value": 1,
            "description": "Number of facet columns before wrapping",
        },
        "orientation": {
            "type": ParameterType.SELECT,
            "options": ["v", "h"],
            "description": "Plot orientation. 'v': vertical (default), 'h': horizontal. Swaps X and Y axes",
            "default": "v",
        },
        "barmode": {
            "type": ParameterType.SELECT,
            "options": ["relative", "group", "overlay", "stack"],
            "description": "Bar display mode. 'group': bars are placed beside each other, 'stack': bars are stacked on top of each other, 'overlay': bars overlap, 'relative': bars are stacked with negative values below zero",
            "default": "relative",
        },
        "histnorm": {
            "type": ParameterType.SELECT,
            "options": ["", "percent", "probability", "density", "probability density"],
            "description": "Histogram normalization mode. '': count, 'percent': percentage, 'probability': probability, 'density': density, 'probability density': probability density",
            "default": "",
        },
        "points": {
            "type": ParameterType.SELECT,
            "options": ["outliers", "suspectedoutliers", "all", False],
            "description": "Show individual points in box/violin plots. 'outliers': show only outliers, 'suspectedoutliers': show suspected outliers, 'all': show all points, False: hide all points",
            "default": "outliers",
        },
        "violinmode": {
            "type": ParameterType.SELECT,
            "options": ["group", "overlay"],
            "description": "Violin plot display mode. 'group': violins are placed beside each other, 'overlay': violins are drawn on top of one another",
            "default": "group",
        },
        "line_shape": {
            "type": ParameterType.SELECT,
            "options": ["linear", "spline", "vhv", "hvh", "vh", "hv"],
            "description": "Line shape interpolation. 'linear': straight lines, 'spline': smooth curved lines, 'vhv': vertical-horizontal-vertical, 'hvh': horizontal-vertical-horizontal, 'vh': vertical-horizontal, 'hv': horizontal-vertical",
            "default": "linear",
        },
        "trendline": {
            "type": ParameterType.SELECT,
            "options": ["ols", "lowess", "rolling", "expanding", "ewm"],
            "description": "Trendline type. 'ols': ordinary least squares regression, 'lowess': locally weighted regression, 'rolling': rolling average, 'expanding': expanding window average, 'ewm': exponentially weighted moving average",
        },
        "marginal_x": {
            "type": ParameterType.SELECT,
            "options": ["histogram", "rug", "box", "violin"],
            "description": "Marginal plot type for X-axis. Adds a small plot above the main plot showing the distribution of X values",
        },
        "marginal_y": {
            "type": ParameterType.SELECT,
            "options": ["histogram", "rug", "box", "violin"],
            "description": "Marginal plot type for Y-axis. Adds a small plot to the right of the main plot showing the distribution of Y values",
        },
        "size_max": {
            "type": ParameterType.INTEGER,
            "min_value": 1,
            "max_value": 100,
            "description": "Maximum marker size when using size mapping in scatter plots",
            "default": 20,
        },
        "mode": {
            "type": ParameterType.SELECT,
            "options": [
                "lines",
                "markers",
                "lines+markers",
                "text",
                "lines+text",
                "markers+text",
                "lines+markers+text",
            ],
            "description": "Line plot display mode. 'lines': show only lines, 'markers': show only points, 'lines+markers': show both lines and points",
            "default": "lines",
        },
        "symbol": {
            "type": ParameterType.SELECT,
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
            "description": "Marker symbol (applied uniformly to all points). To vary symbols by category, select a column from your data.",
            # "default": "circle",
        },
        "line_dash": {
            "type": ParameterType.SELECT,
            "options": ["solid", "dot", "dash", "longdash", "dashdot", "longdashdot"],
            "description": "Line dash pattern (applied uniformly to all lines). To vary dash patterns by category, select a column from your data.",
            "default": "solid",
        },
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

    def infer_parameter_type(self, param: inspect.Parameter) -> ParameterType:
        """Infer parameter type from function signature.

        Args:
            param: Function parameter

        Returns:
            Inferred parameter type
        """
        # Check annotation first
        if param.annotation != inspect.Parameter.empty:
            annotation = param.annotation

            # Handle Union types (like Optional[str])
            if hasattr(annotation, "__origin__"):
                if annotation.__origin__ is Union:
                    # Get the first non-None type
                    for arg in annotation.__args__:
                        if arg is not type(None):
                            annotation = arg
                            break

            # Map to our parameter types
            if annotation in self.TYPE_MAPPING:
                return self.TYPE_MAPPING[annotation]

        # Fallback: infer from parameter name patterns
        param_name = param.name.lower()

        # Column-like parameters (be more specific to avoid false positives)
        column_patterns = [
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
        import re

        if any(re.search(pattern, param_name) for pattern in column_patterns):
            return ParameterType.COLUMN

        # Boolean parameters
        if any(
            keyword in param_name
            for keyword in ["log_", "show_", "is_", "has_", "cumulative", "notched", "markers"]
        ):
            return ParameterType.BOOLEAN

        # Numeric parameters (excluding width and height which we want to disable)
        if any(
            keyword in param_name for keyword in ["size", "opacity", "nbins"]
        ) and param_name not in ["width", "height"]:
            if "size" in param_name and "max" in param_name:
                return ParameterType.INTEGER
            return ParameterType.FLOAT if "opacity" in param_name else ParameterType.INTEGER

        # Select parameters (based on known options)
        if param_name in [
            "orientation",
            "barmode",
            "histnorm",
            "points",
            "violinmode",
            "line_shape",
            "trendline",
            "marginal_x",
            "marginal_y",
        ]:
            return ParameterType.SELECT

        # Multi-select parameters (these will be handled specially in the component builder)
        if any(keyword in param_name for keyword in ["hover_data", "custom_data"]):
            return ParameterType.MULTI_SELECT

        # Default to string
        return ParameterType.STRING

    def categorize_parameter(self, param_name: str, func_name: str) -> ParameterCategory:
        """Categorize a parameter based on its name and function context.

        Args:
            param_name: Parameter name
            func_name: Function name

        Returns:
            Parameter category
        """
        if param_name in self.CORE_PARAMETERS:
            return ParameterCategory.CORE
        elif param_name in self.COMMON_PARAMETERS:
            return ParameterCategory.COMMON
        elif param_name in self.ADVANCED_PARAMETERS:
            return ParameterCategory.ADVANCED
        else:
            # Function-specific parameters
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
        """Create proper parameters for violin plots."""
        return [
            # Core parameters - y is semi-required for violin plots
            ParameterDefinition(
                name="y",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="y*",
                description="Values for violin plot distribution (at least one * parameter is required)",
                required=False,  # Semi-required
            ),
            ParameterDefinition(
                name="x",
                type=ParameterType.COLUMN,
                category=ParameterCategory.CORE,
                label="x",
                description="Categories for grouping violins",
                required=False,
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
            # Specific violin parameters
            ParameterDefinition(
                name="box",
                type=ParameterType.BOOLEAN,
                category=ParameterCategory.SPECIFIC,
                label="box",
                description="Whether to show box plot inside violin",
                default=False,
                required=False,
            ),
            ParameterDefinition(
                name="points",
                type=ParameterType.SELECT,
                category=ParameterCategory.SPECIFIC,
                label="points",
                description="How to display points",
                options=["outliers", "suspectedoutliers", "all", False],
                default=False,
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
        """Get common parameters that apply to most visualizations."""
        return [
            ParameterDefinition(
                name="title",
                type=ParameterType.STRING,
                category=ParameterCategory.COMMON,
                label="title",
                description="Plot title",
                required=False,
            ),
            ParameterDefinition(
                name="hover_name",
                type=ParameterType.COLUMN,
                category=ParameterCategory.COMMON,
                label="hover_name",
                description="Column for hover tooltip names",
                required=False,
            ),
            ParameterDefinition(
                name="hover_data",
                type=ParameterType.MULTI_SELECT,
                category=ParameterCategory.COMMON,
                label="hover_data",
                description="Columns to show on hover",
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

            # Infer parameter type
            param_type = self.infer_parameter_type(param)

            # Categorize parameter
            category = self.categorize_parameter(param_name, func_name)

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
        logger.info(f"Discovered {len(parameters)} parameters for {func_name}")

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


def discover_all_visualizations() -> Dict[str, VisualizationDefinition]:
    """Discover all available visualizations dynamically.

    Returns:
        Dictionary mapping function names to visualization definitions
    """
    # Icon mapping for common visualization types
    ICON_MAPPING = {
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
        # Clustering visualizations
        "umap": "mdi:scatter-plot",
    }

    functions = get_available_plotly_functions()

    # Add custom clustering functions
    functions.extend(["umap"])

    # Disabled visualizations (temporarily removed from dropdown)
    disabled_visualizations = {
        "ecdf",
        "funnel_area",
        "icicle",
        "parallel_categories",
        "parallel_coordinates",
        "strip",
        "umap",  # Disabled UMAP visualization
        "pie",  # Disabled pie charts
        "sunburst",  # Disabled sunburst charts
        "timeline",  # Disabled timeline charts
        "treemap",  # Disabled treemap charts
    }

    visualizations = {}

    for func_name in functions:
        # Skip disabled visualizations
        if func_name in disabled_visualizations:
            logger.debug(f"Skipping disabled visualization: {func_name}")
            continue
        try:
            if func_name == "umap":
                # Create custom UMAP visualization definition
                viz_def = create_umap_visualization_definition()
            else:
                # Create standard Plotly visualization definition
                viz_def = parameter_inspector.create_visualization_definition(
                    func_name=func_name, icon=ICON_MAPPING.get(func_name, "mdi:chart-line")
                )

            # Set the visualization group
            viz_def.group = get_visualization_group(func_name)

            visualizations[func_name] = viz_def
            logger.debug(
                f"Created visualization definition for {func_name} in group {viz_def.group}"
            )

        except Exception as e:
            logger.warning(f"Failed to create definition for {func_name}: {e}")

    logger.info(f"Discovered {len(visualizations)} visualizations")
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


def get_common_visualizations() -> List[str]:
    """Get list of commonly used visualization types for UI display.

    Returns:
        List of common visualization function names
    """
    return ["scatter", "line", "bar", "histogram", "box", "area", "pie"]
