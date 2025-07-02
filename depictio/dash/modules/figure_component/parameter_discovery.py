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
)


class ParameterInspector:
    """Inspects Plotly Express functions to discover parameters dynamically."""

    # Core parameters that are essential for most visualizations
    CORE_PARAMETERS = {
        "x": {"type": ParameterType.COLUMN, "required": True, "description": "X-axis column"},
        "y": {"type": ParameterType.COLUMN, "required": False, "description": "Y-axis column"},
        "color": {
            "type": ParameterType.COLUMN,
            "required": False,
            "description": "Color encoding column",
        },
        "z": {
            "type": ParameterType.COLUMN,
            "required": False,
            "description": "Z-axis column (for 3D plots)",
        },
    }

    # Common parameters shared across many visualizations
    COMMON_PARAMETERS = {
        "title": {"type": ParameterType.STRING, "description": "Figure title"},
        "width": {
            "type": ParameterType.INTEGER,
            "min_value": 100,
            "max_value": 2000,
            "description": "Figure width in pixels",
        },
        "height": {
            "type": ParameterType.INTEGER,
            "min_value": 100,
            "max_value": 2000,
            "description": "Figure height in pixels",
        },
        "template": {
            "type": ParameterType.SELECT,
            "options": [
                "plotly",
                "plotly_white",
                "plotly_dark",
                "ggplot2",
                "seaborn",
                "simple_white",
            ],
            "description": "Plotly template",
            "default": "plotly",
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
        "labels": {"type": ParameterType.STRING, "description": "Axis labels mapping"},
        "color_discrete_sequence": {
            "type": ParameterType.STRING,
            "description": "Discrete color sequence",
        },
        "color_continuous_scale": {
            "type": ParameterType.STRING,
            "description": "Continuous color scale",
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
        "category_orders": {"type": ParameterType.STRING, "description": "Category ordering"},
        "color_discrete_map": {
            "type": ParameterType.STRING,
            "description": "Color mapping for discrete values",
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
            "description": "Plot orientation",
            "default": "v",
        },
        "barmode": {
            "type": ParameterType.SELECT,
            "options": ["relative", "group", "overlay", "stack"],
            "description": "Bar display mode",
            "default": "relative",
        },
        "histnorm": {
            "type": ParameterType.SELECT,
            "options": ["", "percent", "probability", "density", "probability density"],
            "description": "Histogram normalization",
            "default": "",
        },
        "points": {
            "type": ParameterType.SELECT,
            "options": ["outliers", "suspectedoutliers", "all", False],
            "description": "Show individual points",
            "default": "outliers",
        },
        "violinmode": {
            "type": ParameterType.SELECT,
            "options": ["group", "overlay"],
            "description": "Violin display mode",
            "default": "group",
        },
        "line_shape": {
            "type": ParameterType.SELECT,
            "options": ["linear", "spline", "vhv", "hvh", "vh", "hv"],
            "description": "Line shape",
            "default": "linear",
        },
        "trendline": {
            "type": ParameterType.SELECT,
            "options": ["ols", "lowess", "rolling", "expanding", "ewm"],
            "description": "Trendline type",
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

        # Numeric parameters
        if any(
            keyword in param_name for keyword in ["width", "height", "size", "opacity", "nbins"]
        ):
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

    def discover_parameters(self, func_name: str) -> List[ParameterDefinition]:
        """Discover parameters for a Plotly Express function.

        Args:
            func_name: Name of the Plotly Express function

        Returns:
            List of parameter definitions
        """
        if func_name in self._parameter_cache:
            return self._parameter_cache[func_name]

        signature = self.get_function_signature(func_name)
        if not signature:
            return []

        parameters = []

        for param_name, param in signature.parameters.items():
            # Skip special parameters
            if param_name in ["data_frame", "kwargs", "args"]:
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
                label=param_name.replace("_", " ").title(),
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
    }

    functions = get_available_plotly_functions()
    visualizations = {}

    for func_name in functions:
        try:
            viz_def = parameter_inspector.create_visualization_definition(
                func_name=func_name, icon=ICON_MAPPING.get(func_name, "mdi:chart-line")
            )
            visualizations[func_name] = viz_def
            logger.debug(f"Created visualization definition for {func_name}")

        except Exception as e:
            logger.warning(f"Failed to create definition for {func_name}: {e}")

    logger.info(f"Discovered {len(visualizations)} visualizations")
    return visualizations


def get_common_visualizations() -> List[str]:
    """Get list of commonly used visualization types for UI display.

    Returns:
        List of common visualization function names
    """
    return ["scatter", "line", "bar", "histogram", "box", "area", "pie"]
