"""
Plotly Express Parameter Validation.

Provides fast validation of dict_kwargs against plotly express function signatures.
This is designed for YAML validation where we need to check parameter names
without actually building figures (which requires data).

Usage:
    from depictio.models.validation.plotly_express import (
        validate_dict_kwargs,
        get_px_parameters,
        SUPPORTED_CHART_TYPES,
    )

    # Validate figure component parameters
    is_valid, errors = validate_dict_kwargs("scatter", {"x": "col1", "colour": "col2"})
    # errors: [{"loc": ("dict_kwargs", "colour"), "msg": "Invalid parameter 'colour'..."}]
"""

import inspect
from typing import Any

import plotly.express as px

# Supported chart types mapped to their px functions
PX_FUNCTIONS: dict[str, Any] = {
    "scatter": px.scatter,
    "line": px.line,
    "bar": px.bar,
    "box": px.box,
    "histogram": px.histogram,
    "violin": px.violin,
    "heatmap": px.density_heatmap,
    "pie": px.pie,
    "area": px.area,
    "funnel": px.funnel,
    "treemap": px.treemap,
    "sunburst": px.sunburst,
    "icicle": px.icicle,
    "scatter_3d": px.scatter_3d,
    "line_3d": px.line_3d,
    "scatter_polar": px.scatter_polar,
    "line_polar": px.line_polar,
    "bar_polar": px.bar_polar,
    "scatter_geo": px.scatter_geo,
    "choropleth": px.choropleth,
    "density_contour": px.density_contour,
    "density_heatmap": px.density_heatmap,
    "imshow": px.imshow,
    "ecdf": px.ecdf,
    "strip": px.strip,
    "parallel_coordinates": px.parallel_coordinates,
    "parallel_categories": px.parallel_categories,
    "scatter_matrix": px.scatter_matrix,
}

SUPPORTED_CHART_TYPES = list(PX_FUNCTIONS.keys())

# Common typos and their corrections
COMMON_TYPOS: dict[str, str] = {
    "colour": "color",
    "colours": "color",
    "x_axis": "x",
    "y_axis": "y",
    "xaxis": "x",
    "yaxis": "y",
    "label": "labels",
    "hover": "hover_data",
    "size_col": "size",
    "color_col": "color",
    "facet": "facet_col",
    "facet_column": "facet_col",
    "facet_row_col": "facet_row",
    "trendline_type": "trendline",
    "animation": "animation_frame",
    "marginal_plot": "marginal_x",
}

# Parameter cache to avoid repeated signature inspection
_parameter_cache: dict[str, set[str]] = {}


def get_px_parameters(visu_type: str) -> set[str]:
    """Get valid parameter names for a plotly express function.

    Args:
        visu_type: Chart type (scatter, line, bar, etc.)

    Returns:
        Set of valid parameter names, empty set if visu_type unknown
    """
    if visu_type in _parameter_cache:
        return _parameter_cache[visu_type]

    func = PX_FUNCTIONS.get(visu_type)
    if not func:
        return set()

    sig = inspect.signature(func)
    params = set(sig.parameters.keys())
    _parameter_cache[visu_type] = params
    return params


def get_common_parameters() -> set[str]:
    """Get parameters common to most px functions.

    Useful for showing users what parameters are typically available.
    """
    common = {
        "data_frame",
        "x",
        "y",
        "color",
        "title",
        "labels",
        "hover_data",
        "hover_name",
        "template",
        "width",
        "height",
        "opacity",
        "color_discrete_sequence",
        "color_continuous_scale",
    }
    return common


def validate_dict_kwargs(
    visu_type: str,
    dict_kwargs: dict[str, Any] | None,
    raise_on_error: bool = False,
) -> tuple[bool, list[dict[str, Any]]]:
    """Validate dict_kwargs against plotly express signature.

    This performs fast parameter name validation suitable for YAML parsing.
    It does NOT validate parameter values (which would require data context).

    Args:
        visu_type: Chart type (scatter, line, bar, etc.)
        dict_kwargs: Dictionary of parameters to validate
        raise_on_error: If True, raise ValidationError instead of returning errors

    Returns:
        Tuple of (is_valid, errors)
        - is_valid: True if all parameters are valid
        - errors: List of error dictionaries with loc, msg, type keys
    """
    if dict_kwargs is None:
        return True, []

    errors: list[dict[str, Any]] = []

    # Check visu_type is valid
    if visu_type not in PX_FUNCTIONS:
        errors.append(
            {
                "loc": ("visu_type",),
                "msg": f"Unknown chart type: '{visu_type}'. Valid types: {SUPPORTED_CHART_TYPES}",
                "type": "value_error",
            }
        )
        # Can't validate kwargs without valid visu_type
        if raise_on_error and errors:
            from pydantic import ValidationError

            raise ValidationError.from_exception_data("PlotlyExpress", errors)
        return False, errors

    # Get valid parameters for this chart type
    valid_params = get_px_parameters(visu_type)

    # Check for invalid parameter names
    for key in dict_kwargs:
        if key not in valid_params:
            # Check if it's a common typo
            suggestion = ""
            if key in COMMON_TYPOS:
                correct = COMMON_TYPOS[key]
                if correct in valid_params:
                    suggestion = f" Did you mean '{correct}'?"

            errors.append(
                {
                    "loc": ("dict_kwargs", key),
                    "msg": f"Invalid parameter '{key}' for px.{visu_type}.{suggestion}",
                    "type": "value_error",
                }
            )

    if raise_on_error and errors:
        from pydantic import ValidationError

        raise ValidationError.from_exception_data("PlotlyExpress", errors)

    return len(errors) == 0, errors


def validate_figure_component(
    visu_type: str,
    dict_kwargs: dict[str, Any] | None,
    mode: str = "ui",
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    """Validate a complete figure component configuration.

    Args:
        visu_type: Chart type
        dict_kwargs: Chart parameters
        mode: "ui" or "code"

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []

    # In code mode, dict_kwargs validation is less strict
    if mode == "code":
        if visu_type not in PX_FUNCTIONS:
            warnings.append(f"Chart type '{visu_type}' not in standard px functions")
        return True, errors, warnings

    # UI mode: full validation
    is_valid, param_errors = validate_dict_kwargs(visu_type, dict_kwargs)
    errors.extend(param_errors)

    # Check for recommended parameters
    if dict_kwargs:
        if "x" not in dict_kwargs and "x" in get_px_parameters(visu_type):
            if visu_type not in ("pie", "treemap", "sunburst", "icicle"):
                warnings.append("Consider specifying 'x' parameter for clearer visualizations")
        if "title" not in dict_kwargs:
            warnings.append("Consider adding a 'title' for better dashboard readability")

    return is_valid, errors, warnings
