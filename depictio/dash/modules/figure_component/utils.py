import ast
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import plotly.express as px
import polars as pl
from dash import dcc, html
from dash_iconify import DashIconify

# PERFORMANCE OPTIMIZATION: Use centralized config
from depictio.api.v1.configs.logging_init import logger

from .clustering import get_clustering_function
from .definitions import get_visualization_definition
from .models import ComponentConfig


def stringify_id(id_dict):
    """Convert dictionary ID to string format exactly as Dash does internally.

    This matches Dash's internal stringify_id function for target_components.
    Keys are sorted alphabetically, values are JSON-encoded.
    """
    if not isinstance(id_dict, dict):
        return id_dict

    def stringify_val(v):
        return v.get("wild") if isinstance(v, dict) and v.get("wild") else json.dumps(v)

    parts = [json.dumps(k) + ":" + stringify_val(id_dict[k]) for k in sorted(id_dict)]
    return "{" + ",".join(parts) + "}"


def _get_theme_template(theme: str) -> str:
    """Get the appropriate Plotly template based on the theme.

    Args:
        theme: Theme name ("light", "dark", or other)

    Returns:
        Plotly template name
    """
    # Handle case where theme is empty dict, None, or other falsy value
    if not theme or theme == {} or theme == "{}":
        theme = "light"

    logger.info(f"Using theme: {theme} for Plotly template")
    # Use mantine templates provided by dmc.add_figure_templates()
    return "mantine_dark" if theme == "dark" else "mantine_light"


def _create_theme_aware_figure(template: str, title: str = "") -> Any:
    """Create a theme-aware placeholder figure with proper template colors.

    Args:
        template: Plotly template name
        title: Figure title

    Returns:
        Plotly figure with theme-aware styling
    """
    fig = px.scatter(template=template, title=title)
    # Let the mantine template handle background colors
    return fig


def build_figure_frame(index, children=None):
    if not children:
        return dbc.Card(
            [
                dbc.CardBody(
                    id={
                        "type": "figure-body",
                        "index": index,
                    },
                    style={
                        "padding": "5px",  # Reduce padding inside the card body
                        "display": "flex",
                        "flexDirection": "column",
                        "flex": "1",  # Allow growth to fill container
                        "height": "100%",  # Make sure it fills the parent container
                        "minHeight": "150px",  # Reduce from 400px for better flexibility
                        "backgroundColor": "transparent",  # Fix white background
                    },
                ),
                html.Div(
                    id={
                        "type": "figure-loading",
                        "index": index,
                    },
                    style={
                        "position": "absolute",
                        "top": "0",
                        "left": "0",
                        "width": "100%",
                        "height": "100%",
                        "display": "none",  # Hidden by default
                        "alignItems": "center",
                        "justifyContent": "center",
                        "backgroundColor": "var(--app-surface-color, #ffffff)",
                        "zIndex": "1000",
                    },
                ),
            ],
            style={
                "position": "relative",
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Remove shadow for a cleaner look
                "border": "none",  # Remove conflicting border - parent handles styling
                "backgroundColor": "transparent",  # Let parent handle theme colors
                # Critical flexbox properties for vertical growing
                "display": "flex",
                "flexDirection": "column",
                "flex": "1",
            },
            id={
                "type": "figure-component",
                "index": index,
            },
        )
    else:
        return dbc.Card(
            [
                dbc.CardBody(
                    children=children,
                    id={
                        "type": "figure-body",
                        "index": index,
                    },
                    style={
                        "padding": "5px",  # Reduce padding inside the card body
                        "display": "flex",
                        "flexDirection": "column",
                        "flex": "1",  # Allow growth to fill container
                        "height": "100%",  # Make sure it fills the parent container
                        "minHeight": "150px",  # Reduce from 400px for better flexibility
                        "backgroundColor": "transparent",  # Fix white background
                    },
                ),
                html.Div(
                    id={
                        "type": "figure-loading",
                        "index": index,
                    },
                    style={
                        "position": "absolute",
                        "top": "0",
                        "left": "0",
                        "width": "100%",
                        "height": "100%",
                        "display": "none",  # Hidden by default
                        "alignItems": "center",
                        "justifyContent": "center",
                        "backgroundColor": "var(--app-surface-color, #ffffff)",
                        "zIndex": "1000",
                    },
                ),
            ],
            style={
                "position": "relative",
                "overflowX": "hidden",
                "width": "100%",
                "height": "100%",  # Ensure the card fills the container's height
                "padding": "0",  # Remove default padding
                "margin": "0",  # Remove default margin
                "boxShadow": "none",  # Remove shadow for a cleaner look
                "border": "none",  # Remove conflicting border - parent handles styling
                "backgroundColor": "transparent",  # Let parent handle theme colors
                # Critical flexbox properties for vertical growing
                "display": "flex",
                "flexDirection": "column",
                "flex": "1",
            },
            id={
                "type": "figure-component",
                "index": index,
            },
        )


# Configuration for figure component
_config = ComponentConfig()

# Cache for sampled data to avoid re-sampling large datasets
_sampling_cache = {}

# PERFORMANCE OPTIMIZATION: Figure result cache to avoid redundant Plotly generation
_figure_result_cache = {}
FIGURE_CACHE_TTL = 300  # 5 minutes
FIGURE_CACHE_MAX_SIZE = 100


# Plotly Express function mapping - dynamically get all available functions
def _get_plotly_functions():
    """Get all available Plotly Express plotting functions."""
    functions = {}
    for name in dir(px):
        obj = getattr(px, name)
        if callable(obj) and not name.startswith("_"):
            # Check if it's a plotting function (has 'data_frame' parameter)
            try:
                import inspect

                sig = inspect.signature(obj)
                if "data_frame" in sig.parameters:
                    functions[name] = obj
            except (ValueError, TypeError):
                pass
    return functions


# Initialize with all available functions
PLOTLY_FUNCTIONS = _get_plotly_functions()


def _get_required_parameters(visu_type: str) -> List[str]:
    """Get required parameters for a visualization type using dynamic discovery.

    Args:
        visu_type: Visualization type name

    Returns:
        List of required parameter names
    """
    try:
        # Use the visualization definition to get required parameters
        viz_def = get_visualization_definition(visu_type)
        required_params = []

        # Extract required parameters from the definition
        for param in viz_def.parameters:
            if param.required:
                required_params.append(param.name)

        # If no required parameters found in definition, use common fallbacks
        if not required_params:
            # Specific visualization requirements
            if visu_type.lower() == "histogram":
                required_params = ["x"]  # Histogram only needs X
            elif visu_type.lower() in ["box", "violin"]:
                required_params = ["y"]  # Box/violin plots need Y (distribution)
            elif visu_type.lower() in ["pie", "sunburst", "treemap"]:
                required_params = ["values"]  # Hierarchical charts need values
            elif visu_type.lower() in ["timeline"]:
                required_params = ["x_start"]  # Timeline needs start time
            elif visu_type.lower() in ["umap", "clustering"]:
                # Clustering visualizations don't have required parameters
                required_params = []
            elif visu_type.lower() in ["bar", "line", "area"]:
                # These can work with either X or Y, but need at least one
                required_params = []  # Let them work without strict validation
            elif visu_type.lower() in ["scatter", "density_contour", "density_heatmap"]:
                # Scatter-like plots typically need both, but can work with just one
                required_params = []  # More flexible - let plotly handle it
            else:
                # For unknown visualization types, don't enforce strict requirements
                # This allows new visualization types to work without code changes
                required_params = []

        return required_params

    except Exception:
        # Fallback if visualization definition not found - be more permissive
        if visu_type.lower() == "histogram":
            return ["x"]
        elif visu_type.lower() in ["box", "violin"]:
            return ["y"]
        elif visu_type.lower() in ["pie", "sunburst", "treemap"]:
            return ["values"]
        elif visu_type.lower() in ["umap", "clustering"]:
            return []
        else:
            # Default: no strict requirements for unknown visualizations
            return []


def _get_figure_cache_key(
    dict_kwargs: dict, visu_type: str, df_hash: str, cutoff: int, selected_point: dict, theme: str
) -> str:
    """Generate cache key for figure results."""
    import hashlib

    # Create a deterministic hash from all input parameters
    cache_data = {
        "dict_kwargs": dict_kwargs,
        "visu_type": visu_type,
        "df_hash": df_hash,
        "cutoff": cutoff,
        "selected_point": selected_point,
        "theme": theme,
    }
    cache_str = str(cache_data)
    return hashlib.md5(cache_str.encode()).hexdigest()


def validate_figure_component_metadata(metadata: dict) -> tuple[bool, str]:
    """
    Validate figure component metadata to prevent empty components.

    Args:
        metadata: Component metadata dictionary

    Returns:
        (is_valid, error_message) tuple
    """
    component_type = metadata.get("component_type")
    if component_type != "figure":
        return True, ""

    mode = metadata.get("mode", "ui")

    if mode == "code":
        # Code mode: requires code_content
        code_content = metadata.get("code_content", "")
        if not code_content or not code_content.strip():
            return False, "Code mode figure requires code_content"
    else:
        # UI mode: requires wf_id, dc_id, AND dict_kwargs
        wf_id = metadata.get("wf_id")
        dc_id = metadata.get("dc_id")
        dict_kwargs = metadata.get("dict_kwargs", {})

        if not wf_id:
            return False, "UI mode figure requires wf_id (workflow ID)"
        if not dc_id:
            return False, "UI mode figure requires dc_id (data collection ID)"
        if not isinstance(dict_kwargs, dict) or len(dict_kwargs) == 0:
            return False, "UI mode figure requires non-empty dict_kwargs"

    return True, ""


def _clean_figure_cache():
    """Remove expired entries from figure cache."""
    import time

    current_time = time.time()
    expired_keys = []

    for key, cached_result in _figure_result_cache.items():
        # Handle both old format (figure, timestamp) and new format (figure, data_info, timestamp)
        if isinstance(cached_result, tuple) and len(cached_result) == 3:
            _, _, timestamp = cached_result
        else:
            # Old format - just figure and timestamp
            _, timestamp = cached_result

        if current_time - timestamp > FIGURE_CACHE_TTL:
            expired_keys.append(key)

    for key in expired_keys:
        del _figure_result_cache[key]

    # If cache is still too large, remove oldest entries
    if len(_figure_result_cache) > FIGURE_CACHE_MAX_SIZE:
        # Sort by timestamp and remove oldest entries
        def get_timestamp(item):
            cached_result = item[1]
            if isinstance(cached_result, tuple) and len(cached_result) == 3:
                return cached_result[2]  # timestamp is third element
            else:
                return cached_result[1]  # timestamp is second element (old format)

        sorted_items = sorted(_figure_result_cache.items(), key=get_timestamp)
        excess_count = len(_figure_result_cache) - FIGURE_CACHE_MAX_SIZE
        for key, _ in sorted_items[:excess_count]:
            del _figure_result_cache[key]


def render_figure(
    dict_kwargs: Dict[str, Any],
    visu_type: str,
    df: pl.DataFrame,
    cutoff: int = _config.max_data_points,
    selected_point: Optional[Dict] = None,
    theme: str = "light",
    skip_validation: bool = False,
    mode: str = "ui",
    force_full_data: bool = False,
) -> tuple[Any, dict]:
    """Render a Plotly figure with robust parameter handling and result caching.

    Args:
        dict_kwargs: Figure parameters
        visu_type: Visualization type
        df: Data as Polars DataFrame
        cutoff: Maximum data points before sampling
        selected_point: Point to highlight
        theme: Theme ('light' or 'dark')
        skip_validation: Skip parameter validation
        mode: Component mode ('ui' or 'code') for parameter evaluation
        force_full_data: If True, bypass sampling and load all data points

    Returns:
        Tuple of (Plotly figure object, data_info dict with counts)
    """
    # PERFORMANCE OPTIMIZATION: Check figure result cache first

    # Initialize data counts - will be populated during rendering
    data_info = {
        "total_data_count": 0,
        "displayed_data_count": 0,
        "was_sampled": False,
    }

    # Safety check: ensure df is not None
    if df is None:
        logger.error("DataFrame is None, cannot build figure")
        error_div = html.Div(
            dmc.Alert(
                "Error: No data available to build figure",
                title="Data Error",
                color="red",
            ),
            style={"height": "400px", "display": "flex", "alignItems": "center"},
        )
        return error_div, data_info

    # Generate cache key from all inputs
    df_hash = str(hash(str(df.hash_rows()) if df is not None and not df.is_empty() else "empty"))
    selected_point_clean = selected_point or {}

    cache_key = _get_figure_cache_key(
        dict_kwargs, visu_type, df_hash, cutoff, selected_point_clean, theme
    )

    # PERFORMANCE OPTIMIZATION: Check figure result cache first
    import time

    _clean_figure_cache()
    if cache_key in _figure_result_cache:
        cached_result = _figure_result_cache[cache_key]
        # Handle both old format (just figure) and new format (figure, data_info, timestamp)
        if isinstance(cached_result, tuple) and len(cached_result) == 3:
            cached_figure, cached_data_info, timestamp = cached_result
        else:
            # Old format - just figure and timestamp
            cached_figure, timestamp = cached_result
            # Create default data_info for old cached entries
            cached_data_info = {
                "total_data_count": 0,
                "displayed_data_count": 0,
                "was_sampled": False,
            }
        logger.info(
            f"🚀 FIGURE CACHE HIT: Using cached figure for {visu_type} (saved {int((time.time() - timestamp) * 1000)}ms ago)"
        )
        return cached_figure, cached_data_info

    logger.info(f"📊 FIGURE CACHE MISS: Generating new {visu_type} figure")

    # Log when full data loading is forced
    if force_full_data:
        logger.warning(
            f"🔓 FORCE FULL DATA: Bypassing {cutoff:,} point sampling limit - will load all data!"
        )

    # Check if it's a clustering visualization
    is_clustering = visu_type.lower() in ["umap"]

    # Validate visualization type
    if not is_clustering and visu_type.lower() not in PLOTLY_FUNCTIONS:
        logger.warning(f"Unknown visualization type: {visu_type}, falling back to scatter")
        visu_type = "scatter"

    # Smart UMAP computation deferral based on context and data size
    if is_clustering and df is not None and not df.is_empty():
        # Determine context from various signals
        context = "unknown"
        if selected_point is None:
            context = "dashboard_restore"  # Likely dashboard loading
        elif selected_point:
            context = "interactive"  # User-initiated action

        # Use context-aware decision making
        if _should_defer_umap_computation(df, context):
            placeholder = _create_umap_placeholder(df, dict_kwargs, theme)
            # UMAP placeholder - set data info with actual counts
            data_info["total_data_count"] = df.height
            data_info["displayed_data_count"] = 0  # Not computed yet
            data_info["was_sampled"] = False
            return placeholder, data_info

    # Add theme-appropriate template using Mantine-compatible themes
    # Apply theme template if no template is specified, if template is None, or if template is empty
    template_value = dict_kwargs.get("template")
    if not template_value:  # This handles None, empty string, and missing key cases
        dict_kwargs["template"] = _get_theme_template(theme)
        logger.info(f"Applied theme-based template: {dict_kwargs['template']} for theme: {theme}")
    else:
        logger.info(f"Using existing template: {template_value}")

    logger.info("=== FIGURE RENDER DEBUG ===")
    logger.info(f"Visualization: {visu_type}")
    logger.warning(f"🎨 THEME: {theme} -> TEMPLATE: {dict_kwargs.get('template')}")
    logger.info(f"Data shape: {df.shape if df is not None else 'None'}")
    logger.info(f"Selected point: {selected_point is not None}")
    logger.info(f"Parameters: {list(dict_kwargs.keys())}")
    logger.debug(f"Full dict_kwargs: {dict_kwargs}")  # Reduced to debug level
    logger.debug(
        f"Boolean parameters in dict_kwargs: {[(k, v, type(v)) for k, v in dict_kwargs.items() if isinstance(v, bool)]}"
    )

    # Handle empty or invalid data
    if df is None or df.is_empty():
        logger.warning("Empty or invalid dataframe, creating empty figure")
        empty_fig = _create_theme_aware_figure(
            dict_kwargs.get("template", _get_theme_template(theme))
        )
        return empty_fig, data_info

    # Clean parameters - remove None values and problematic empty strings
    # Keep certain parameters that can legitimately be empty strings (like parents for hierarchical charts)
    keep_empty_string_params = {
        "parents",
        "names",
        "ids",
        "hover_name",
        "hover_data",
        "custom_data",
    }
    cleaned_kwargs = {}
    for k, v in dict_kwargs.items():
        if v is not None:
            # Keep the parameter if it's not empty, or if it's in the allowed empty string list
            # Also keep boolean parameters (including False values)
            if (
                v != ""
                and v != []
                or (k in keep_empty_string_params and v == "")
                or isinstance(v, bool)
            ):
                cleaned_kwargs[k] = v

    # Parse JSON string parameters that Plotly expects as Python objects
    json_params = [
        "color_discrete_map",
        "color_discrete_sequence",
        "color_continuous_scale",
        "category_orders",
        "labels",
        "path",  # For sunburst/treemap hierarchical visualizations
    ]
    for param_name in json_params:
        if param_name in cleaned_kwargs and isinstance(cleaned_kwargs[param_name], str):
            # Special handling for color sequences/scales: check for Plotly named color palettes
            if param_name in ["color_discrete_sequence", "color_continuous_scale"]:
                param_value = cleaned_kwargs[param_name]
                # Try to get named color sequence from px.colors.qualitative (discrete)
                if hasattr(px.colors.qualitative, param_value):
                    color_sequence = getattr(px.colors.qualitative, param_value)
                    cleaned_kwargs[param_name] = color_sequence
                    logger.debug(
                        f"Resolved Plotly qualitative color '{param_value}' to {len(color_sequence)} colors"
                    )
                    continue
                # Also check px.colors.sequential for sequential/continuous color scales
                elif hasattr(px.colors.sequential, param_value):
                    color_sequence = getattr(px.colors.sequential, param_value)
                    cleaned_kwargs[param_name] = color_sequence
                    logger.debug(
                        f"Resolved Plotly sequential color '{param_value}' to {len(color_sequence)} colors"
                    )
                    continue
                # Also check px.colors.diverging for diverging color scales
                elif hasattr(px.colors.diverging, param_value):
                    color_sequence = getattr(px.colors.diverging, param_value)
                    cleaned_kwargs[param_name] = color_sequence
                    logger.debug(
                        f"Resolved Plotly diverging color '{param_value}' to {len(color_sequence)} colors"
                    )
                    continue
                # Also check px.colors.cyclical for cyclical color scales
                elif hasattr(px.colors.cyclical, param_value):
                    color_sequence = getattr(px.colors.cyclical, param_value)
                    cleaned_kwargs[param_name] = color_sequence
                    logger.debug(
                        f"Resolved Plotly cyclical color '{param_value}' to {len(color_sequence)} colors"
                    )
                    continue

            try:
                # First try JSON parsing
                parsed_value = json.loads(cleaned_kwargs[param_name])
                cleaned_kwargs[param_name] = parsed_value
                logger.debug(f"Parsed JSON parameter {param_name}: {cleaned_kwargs[param_name]}")
            except json.JSONDecodeError:
                # Check if this looks like a complex Python expression (contains function calls)
                param_value = cleaned_kwargs[param_name]
                if any(
                    pattern in param_value
                    for pattern in ["(", ".", "sorted", "unique", "to_list", "df["]
                ):
                    if mode == "code" and df is not None:
                        # In code mode, try to evaluate the expression with df available
                        try:
                            from depictio.dash.modules.figure_component.code_mode import (
                                evaluate_params_in_context,
                            )

                            temp_params = {param_name: param_value}
                            evaluated_params = evaluate_params_in_context(temp_params, df)
                            if param_name in evaluated_params:
                                cleaned_kwargs[param_name] = evaluated_params[param_name]
                                logger.info(
                                    f"Evaluated code mode parameter {param_name}: {param_value} -> {evaluated_params[param_name]}"
                                )
                                continue
                        except Exception as e:
                            logger.warning(
                                f"Failed to evaluate code mode parameter {param_name}: {e}"
                            )

                    logger.info(
                        f"Skipping complex Python expression for {param_name}: {param_value}"
                    )
                    # Remove complex expressions that can't be safely evaluated
                    del cleaned_kwargs[param_name]
                    continue

                try:
                    # Fallback to ast.literal_eval for simple Python literal expressions
                    parsed_value = ast.literal_eval(param_value)
                    cleaned_kwargs[param_name] = parsed_value
                    logger.debug(
                        f"Parsed Python literal parameter {param_name}: {cleaned_kwargs[param_name]}"
                    )
                except (ValueError, SyntaxError) as e:
                    logger.warning(
                        f"Invalid parameter format for {param_name}: {param_value} - {e}"
                    )
                    # Remove invalid parameter to avoid Plotly errors
                    del cleaned_kwargs[param_name]

    # PERFORMANCE OPTIMIZATION: Reduce verbose logging in production
    logger.debug("=== CLEANED PARAMETERS DEBUG ===")
    logger.debug(f"Original dict_kwargs: {dict_kwargs}")
    logger.debug(f"Cleaned kwargs: {cleaned_kwargs}")
    logger.debug(
        f"Boolean parameters in cleaned_kwargs: {[(k, v, type(v)) for k, v in cleaned_kwargs.items() if isinstance(v, bool)]}"
    )

    # PARAMETER CONVERSION: Handle line_dash and symbol parameters
    # These parameters can be either:
    # 1. A column name (for categorical grouping by dash/symbol)
    # 2. A style literal (for uniform styling)
    # When a style literal is provided, convert to _sequence parameter
    VALID_DASH_STYLES = ["solid", "dot", "dash", "longdash", "dashdot", "longdashdot"]
    VALID_SYMBOL_STYLES = [
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
    ]

    # Handle line_dash parameter conversion
    if "line_dash" in cleaned_kwargs:
        dash_value = cleaned_kwargs["line_dash"]
        if dash_value in VALID_DASH_STYLES:
            # Convert style literal to line_dash_sequence for uniform styling
            cleaned_kwargs["line_dash_sequence"] = [dash_value]
            del cleaned_kwargs["line_dash"]
            logger.debug(
                f"Converted line_dash style '{dash_value}' to line_dash_sequence for uniform styling"
            )
        elif dash_value not in df.columns:
            # Invalid column name - remove to avoid Plotly error
            logger.warning(
                f"line_dash value '{dash_value}' is not a valid column or style. Removing parameter."
            )
            del cleaned_kwargs["line_dash"]
        # else: valid column name, keep as-is for categorical grouping

    # Handle symbol parameter conversion (same pattern as line_dash)
    if "symbol" in cleaned_kwargs:
        symbol_value = cleaned_kwargs["symbol"]
        if symbol_value in VALID_SYMBOL_STYLES:
            # Convert style literal to symbol_sequence for uniform styling
            cleaned_kwargs["symbol_sequence"] = [symbol_value]
            del cleaned_kwargs["symbol"]
            logger.debug(
                f"Converted symbol style '{symbol_value}' to symbol_sequence for uniform styling"
            )
        elif symbol_value not in df.columns:
            # Invalid column name - remove to avoid Plotly error
            logger.warning(
                f"symbol value '{symbol_value}' is not a valid column or style. Removing parameter."
            )
            del cleaned_kwargs["symbol"]
        # else: valid column name, keep as-is for categorical grouping

    # Check if required parameters are missing for the visualization type (skip in code mode)
    if not skip_validation:
        required_params = _get_required_parameters(visu_type.lower())

        # Smart validation: For most plots, allow either X or Y (not require both)
        if required_params == ["x"] and visu_type.lower() in ["bar", "line", "scatter", "area"]:
            # These plots can work with either X or Y, check if at least one is present
            if "x" not in cleaned_kwargs and "y" not in cleaned_kwargs:
                logger.warning(
                    f"Missing required parameters for {visu_type}: need either X or Y. Available columns: {df.columns}"
                )
                title = f"Please select X or Y column to create {visu_type} plot"
                validation_fig = _create_theme_aware_figure(
                    dict_kwargs.get("template", _get_theme_template(theme)), title=title
                )
                return validation_fig, data_info
        else:
            # Standard validation for specific requirements (pie: values, box: y, etc.)
            missing_params = [param for param in required_params if param not in cleaned_kwargs]
            if missing_params:
                logger.warning(
                    f"Missing required parameters for {visu_type}: {missing_params}. Available columns: {df.columns}"
                )
                title = f"Please select {', '.join(missing_params).upper()} column(s) to create {visu_type} plot"
                validation_fig = _create_theme_aware_figure(
                    dict_kwargs.get("template", _get_theme_template(theme)), title=title
                )
                return validation_fig, data_info
    else:
        logger.info(f"🚀 CODE MODE: Skipping parameter validation for {visu_type}")

    # Special handling for hierarchical charts (sunburst, treemap)
    if visu_type.lower() in ["sunburst", "treemap"]:
        # Filter out non-leaf rows (rows with empty hierarchy values)
        if "path" in cleaned_kwargs and cleaned_kwargs["path"]:
            path_columns = cleaned_kwargs["path"]
            original_rows = df.height

            # Filter out rows where any path column is empty/null
            for col in path_columns:
                if col in df.columns:
                    df = df.filter(
                        (pl.col(col).is_not_null())
                        & (pl.col(col) != "")
                        & (pl.col(col).str.strip_chars() != "")
                    )

            filtered_rows = original_rows - df.height
            if filtered_rows > 0:
                logger.info(
                    f"🌳 Filtered {filtered_rows} non-leaf rows from {visu_type} data (empty hierarchy values)"
                )

        # Ensure parents parameter is handled correctly
        if "parents" in cleaned_kwargs and cleaned_kwargs["parents"] == "":
            # Empty string is valid for root-level hierarchical charts
            cleaned_kwargs["parents"] = None

        # Validate that columns exist in the dataframe
        for param_name, column_name in cleaned_kwargs.items():
            if param_name in ["values", "names", "ids", "parents", "color"] and column_name:
                if column_name not in df.columns:
                    logger.warning(
                        f"Column '{column_name}' not found in dataframe for parameter '{param_name}'"
                    )
                    # Remove invalid column reference
                    cleaned_kwargs[param_name] = None

    # Early check: if no valid plotting parameters are provided, return empty figure
    valid_plot_params = [
        param
        for param, value in cleaned_kwargs.items()
        if value is not None and value != "" and param != "template"
    ]

    if not valid_plot_params and not is_clustering:
        logger.info(f"No valid plotting parameters for {visu_type}, returning empty figure")
        empty_params_fig = _create_theme_aware_figure(
            dict_kwargs.get("template", _get_theme_template(theme)),
            title=f"Select columns to create {visu_type} plot",
        )
        return empty_params_fig, data_info

    try:
        if is_clustering:
            # Handle clustering visualizations (e.g., UMAP)
            clustering_function = get_clustering_function(visu_type.lower())

            # Handle large datasets with sampling for clustering
            if df.height > cutoff and not force_full_data:
                cache_key = f"{id(df)}_{cutoff}_{hash(str(cleaned_kwargs))}"

                if cache_key not in _sampling_cache:
                    sampled_df = df.sample(n=cutoff, seed=0).to_pandas()
                    _sampling_cache[cache_key] = sampled_df
                    logger.info(
                        f"Cached sampled data for clustering: {cutoff} points from {df.height}"
                    )
                else:
                    sampled_df = _sampling_cache[cache_key]
                    logger.info(f"Using cached sampled data for clustering: {cutoff} points")

                figure = clustering_function(sampled_df, **cleaned_kwargs)
            else:
                # Use full dataset
                # pandas_df = df.to_pandas()
                figure = clustering_function(df, **cleaned_kwargs)
        else:
            # Handle standard Plotly visualizations
            plot_function = PLOTLY_FUNCTIONS[visu_type.lower()]

            # PRE-PROCESSING: For box/violin plots without 'color' param, extract color params
            # to handle manually in post-processing (Plotly Express ignores them without 'color')
            manual_color_map = None
            manual_color_sequence = None

            if visu_type.lower() in ["box", "violin", "strip"] and "color" not in cleaned_kwargs:
                # Extract color parameters that will be applied manually
                if "color_discrete_map" in cleaned_kwargs:
                    manual_color_map = cleaned_kwargs.pop("color_discrete_map")
                    logger.info(
                        f"🎨 Extracted color_discrete_map for manual application: {len(manual_color_map)} colors - {list(manual_color_map.keys())}"
                    )
                if "color_discrete_sequence" in cleaned_kwargs:
                    manual_color_sequence = cleaned_kwargs.pop("color_discrete_sequence")
                    logger.info(
                        f"🎨 Extracted color_discrete_sequence for manual application: {len(manual_color_sequence)} colors"
                    )
            else:
                # For plots WITH color parameter, color_discrete_map should be used by Plotly
                if "color_discrete_map" in cleaned_kwargs:
                    logger.info(
                        f"🎨 Keeping color_discrete_map in kwargs for Plotly: {len(cleaned_kwargs['color_discrete_map'])} colors - {list(cleaned_kwargs['color_discrete_map'].keys())}"
                    )

            # Track data counts for partial data warning
            data_info["total_data_count"] = df.height

            # Handle large datasets with sampling
            if df.height > cutoff and not force_full_data:
                cache_key = f"{id(df)}_{cutoff}_{hash(str(cleaned_kwargs))}"

                if cache_key not in _sampling_cache:
                    sampled_df = df.sample(n=cutoff, seed=0)
                    _sampling_cache[cache_key] = sampled_df
                    logger.info(f"Cached sampled data: {cutoff} points from {df.height}")
                else:
                    sampled_df = _sampling_cache[cache_key]
                    logger.info(f"Using cached sampled data: {cutoff} points")

                # Track sampling info
                data_info["displayed_data_count"] = sampled_df.height
                data_info["was_sampled"] = True

                logger.info("=== CALLING PLOTLY FUNCTION (SAMPLED DATA) ===")
                logger.info(f"Function: {plot_function.__name__}")
                logger.warning(f"🚨 SAMPLED DATA SIZE: {sampled_df.shape[0]:,} rows")
                logger.warning(
                    f"📊 DATA COUNTS: {data_info['displayed_data_count']:,} displayed / {data_info['total_data_count']:,} total"
                )

                # PERFORMANCE: Time the Plotly function call
                import time

                plot_start = time.time()
                figure = plot_function(sampled_df, **cleaned_kwargs)
                plot_end = time.time()
                logger.warning(f"🕐 PLOTLY FUNCTION TIME: {(plot_end - plot_start) * 1000:.0f}ms")
            else:
                # Use full dataset - no sampling
                data_info["displayed_data_count"] = df.height
                data_info["was_sampled"] = False

                logger.info("=== CALLING PLOTLY FUNCTION ===")
                logger.info(f"Function: {plot_function.__name__}")
                logger.info(f"Parameters: {cleaned_kwargs}")
                logger.info(
                    f"Boolean params: {[(k, v) for k, v in cleaned_kwargs.items() if isinstance(v, bool)]}"
                )
                figure = plot_function(df, **cleaned_kwargs)

            # POST-PROCESSING: Apply color_discrete_sequence OR color_discrete_map to box/violin plots
            # When colors are provided WITHOUT a color parameter, manually apply colors
            # This avoids the spacing/grouping issues that occur when using color parameter
            if (
                visu_type.lower() in ["box", "violin", "strip"]
                and (manual_color_sequence or manual_color_map)
                and "color" not in cleaned_kwargs
            ):
                color_map = manual_color_map
                color_sequence = manual_color_sequence
                # Validate that we have at least one color source
                if (isinstance(color_sequence, (list, tuple)) and len(color_sequence) > 0) or (
                    isinstance(color_map, dict) and len(color_map) > 0
                ):
                    # When no color param is used, px creates ONE trace with multiple boxes
                    # We need to color each box individually, not the trace as a whole
                    if len(figure.data) == 1:
                        trace = figure.data[0]
                        # Determine which axis has categorical data (boxes)
                        # For vertical: x is categorical, y is numeric
                        # For horizontal: y is categorical, x is numeric
                        orientation = cleaned_kwargs.get("orientation", "v")
                        categorical_column = (
                            cleaned_kwargs.get("x")
                            if orientation == "v"
                            else cleaned_kwargs.get("y")
                        )

                        if categorical_column and categorical_column in df.columns:
                            # Check if user specified category_orders for this column
                            category_orders = cleaned_kwargs.get("category_orders", {})
                            if (
                                isinstance(category_orders, dict)
                                and categorical_column in category_orders
                            ):
                                # Use user-specified order
                                unique_categories = category_orders[categorical_column]
                                logger.debug(
                                    f"Using user-specified category order for '{categorical_column}': {unique_categories}"
                                )
                            else:
                                # Preserve order of first appearance to ensure consistent category ordering
                                unique_categories = (
                                    df.get_column(categorical_column)
                                    .unique(maintain_order=True)
                                    .to_list()
                                )
                                logger.debug(
                                    f"Using dataframe order for '{categorical_column}': {unique_categories}"
                                )
                            num_boxes = len(unique_categories)

                            # WORKAROUND: Box plots don't support color arrays in a single trace
                            # Solution: Recreate with individual traces (one per category)
                            if visu_type.lower() in ["box", "violin"]:
                                import plotly.graph_objects as go

                                # Get original parameters
                                numeric_column = (
                                    cleaned_kwargs.get("y")
                                    if orientation == "v"
                                    else cleaned_kwargs.get("x")
                                )

                                # Type guard: ensure numeric_column is a string
                                if isinstance(numeric_column, str):
                                    # Clear existing traces
                                    figure.data = []

                                    # Create one trace per category with its own color
                                    for i, category in enumerate(unique_categories):
                                        # Filter data for this category
                                        category_data = df.filter(
                                            pl.col(categorical_column) == category
                                        )
                                        values = category_data.get_column(numeric_column).to_list()

                                        # Determine color: use color_map if available, else color_sequence
                                        category_str = str(category)
                                        if color_map:
                                            logger.debug(
                                                f"🎨 Looking for color for '{category_str}' in color_map keys: {list(color_map.keys())}"
                                            )
                                            if category_str in color_map:
                                                color = color_map[category_str]
                                                logger.debug(
                                                    f"✅ Found color for '{category_str}': {color}"
                                                )
                                            else:
                                                # Fallback to default if not in map
                                                color = px.colors.qualitative.Plotly[i % 10]
                                                logger.warning(
                                                    f"⚠️ Category '{category_str}' not found in color_map, using default color"
                                                )
                                        elif color_sequence:
                                            color = color_sequence[i % len(color_sequence)]
                                        else:
                                            # Fallback to default plotly color
                                            color = px.colors.qualitative.Plotly[i % 10]

                                        # Create box/violin trace with explicit positioning
                                        if visu_type.lower() == "box":
                                            box_params = {
                                                "name": str(category),
                                                "marker_color": color,
                                                "boxmean": cleaned_kwargs.get("boxmean"),
                                                "notched": cleaned_kwargs.get("notched", False),
                                                "boxpoints": cleaned_kwargs.get(
                                                    "points"
                                                ),  # all, outliers, suspectedoutliers, False
                                                "showlegend": False,
                                            }
                                            if orientation == "v":
                                                trace_obj = go.Box(
                                                    y=values,
                                                    x=[str(category)]
                                                    * len(values),  # Explicit x position
                                                    **box_params,
                                                )
                                            else:
                                                trace_obj = go.Box(
                                                    x=values,
                                                    y=[str(category)]
                                                    * len(values),  # Explicit y position
                                                    **box_params,
                                                )
                                        else:  # violin
                                            if orientation == "v":
                                                trace_obj = go.Violin(
                                                    y=values,
                                                    x=[str(category)] * len(values),
                                                    name=str(category),
                                                    marker_color=color,
                                                    showlegend=False,
                                                )
                                            else:
                                                trace_obj = go.Violin(
                                                    x=values,
                                                    y=[str(category)] * len(values),
                                                    name=str(category),
                                                    marker_color=color,
                                                    showlegend=False,
                                                )

                                        figure.add_trace(trace_obj)

                                    # Ensure categorical axis maintains order and minimize gaps
                                    if orientation == "v":
                                        figure.update_xaxes(
                                            type="category",
                                            categoryorder="array",
                                            categoryarray=[str(c) for c in unique_categories],
                                        )
                                    else:
                                        figure.update_yaxes(
                                            type="category",
                                            categoryorder="array",
                                            categoryarray=[str(c) for c in unique_categories],
                                        )

                                    # Use overlay mode to minimize spacing (like px.box with color param)
                                    figure.update_layout(
                                        boxmode="overlay",  # Overlay mode for compact positioning
                                    )

                                    color_source = (
                                        "color_discrete_map"
                                        if color_map
                                        else "color_discrete_sequence"
                                    )
                                    logger.debug(
                                        f"Recreated {num_boxes} {visu_type} traces using {color_source}, preserving order, minimal spacing"
                                    )
                            elif visu_type.lower() == "strip":
                                # Strip plots: set single color (limitation without color param)
                                if color_sequence:
                                    try:
                                        if hasattr(trace, "marker"):
                                            trace["marker"]["color"] = color_sequence[0]
                                        logger.debug(
                                            "Applied first color from sequence to strip plot (single trace limitation)"
                                        )
                                    except (TypeError, KeyError) as e:
                                        logger.debug(
                                            f"Could not update trace marker color (trace may be immutable): {e}"
                                        )
                    else:
                        # Multiple traces: apply one color per trace
                        for i, trace in enumerate(figure.data):
                            trace_name = trace.name if hasattr(trace, "name") else None
                            # Try color_map first (by trace name), then color_sequence
                            applied_color = None
                            if color_map and trace_name and str(trace_name) in color_map:
                                applied_color = color_map[str(trace_name)]
                                try:
                                    if hasattr(trace, "marker"):
                                        trace["marker"]["color"] = applied_color
                                except (TypeError, KeyError) as e:
                                    logger.debug(f"Could not update trace marker color: {e}")
                            elif color_sequence:
                                color_idx = i % len(color_sequence)
                                applied_color = color_sequence[color_idx]
                                try:
                                    if hasattr(trace, "marker"):
                                        trace["marker"]["color"] = applied_color
                                except (TypeError, KeyError) as e:
                                    logger.debug(f"Could not update trace marker color: {e}")
                            # Also update line color for consistency
                            if hasattr(trace, "line") and applied_color:
                                try:
                                    trace["line"]["color"] = applied_color
                                except (TypeError, KeyError) as e:
                                    logger.debug(f"Could not update trace line color: {e}")
                        if color_map:
                            color_source = f"color_discrete_map ({len(color_map)} colors)"
                        elif color_sequence:
                            color_source = f"color_discrete_sequence ({len(color_sequence)} colors)"
                        else:
                            color_source = "default colors"
                        logger.debug(f"Applied {color_source} to {len(figure.data)} traces")

        # Fix for marginal plots: Disable axis matches to prevent infinite loop warnings
        # When using marginal_x and marginal_y, Plotly Express creates conflicting axis constraints
        if "marginal_x" in cleaned_kwargs or "marginal_y" in cleaned_kwargs:
            # Disable matches on all axes to prevent infinite loop warnings
            figure.update_xaxes(matches=None)
            figure.update_yaxes(matches=None)
            logger.debug(
                "Disabled axis matches for marginal plot to prevent infinite loop warnings"
            )

        # Apply responsive sizing - let mantine templates handle colors
        figure.update_layout(
            autosize=True,
            margin=dict(l=40, r=40, t=40, b=40),
            height=None,  # Let container control height
            # Don't override background colors - let mantine templates handle them
        )

        # Highlight selected point if provided
        if selected_point and "x" in cleaned_kwargs and "y" in cleaned_kwargs:
            _highlight_selected_point(figure, df, cleaned_kwargs, selected_point)

        # PERFORMANCE OPTIMIZATION: Cache the generated figure with data info
        _figure_result_cache[cache_key] = (figure, data_info, time.time())
        logger.info(
            f"💾 FIGURE CACHE STORED: Cached {visu_type} figure with data counts for future use"
        )
        logger.info(
            f"📊 FINAL DATA COUNTS: {data_info['displayed_data_count']:,} displayed / {data_info['total_data_count']:,} total (sampled: {data_info['was_sampled']})"
        )

        return figure, data_info

    except Exception as e:
        logger.error(f"Error creating figure: {e}")
        # Return fallback figure
        fallback_figure = _create_theme_aware_figure(
            dict_kwargs.get("template", _get_theme_template(theme)),
            title=f"Error: {str(e)}",
        )

        # Cache the fallback figure to avoid repeated errors with default data info
        _figure_result_cache[cache_key] = (fallback_figure, data_info, time.time())
        logger.info("💾 FALLBACK CACHE STORED: Cached error figure")

        return fallback_figure, data_info


def _create_umap_placeholder(df: pl.DataFrame, dict_kwargs: Dict[str, Any], theme: str) -> Any:
    """Create a placeholder figure for UMAP that will be computed on user interaction."""
    template = dict_kwargs.get("template", _get_theme_template(theme))

    # Create a simple scatter plot with a message
    placeholder_fig = px.scatter(
        template=template,
        title=f"UMAP Visualization ({df.height:,} data points)",
    )

    # Add annotation to indicate computation is deferred
    placeholder_fig.add_annotation(
        text="🚀 UMAP computation deferred for faster dashboard loading<br>🔄 Interact with this chart to compute the projection",
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14),
        bgcolor="rgba(255,255,255,0.9)",
        bordercolor="#ddd",
        borderwidth=1,
        borderradius=8,
    )

    # Add invisible scatter points to enable click interactions
    # This allows the graph to respond to clicks and trigger re-computation
    placeholder_fig.add_scatter(
        x=[0],
        y=[0],
        mode="markers",
        marker=dict(opacity=0, size=1),
        showlegend=False,
        hoverinfo="skip",
    )

    return placeholder_fig


def create_figure_placeholder(theme: str = "light", visu_type: str = "scatter") -> Any:
    """Create a placeholder figure when auto-generation is disabled.

    Args:
        theme: Theme for the placeholder ('light' or 'dark')
        visu_type: Visualization type for the placeholder

    Returns:
        Plotly figure object with placeholder content
    """
    # Use mantine templates for consistency
    template = _get_theme_template(theme)

    # Create an empty scatter plot as base
    placeholder_fig = px.scatter(
        template=template,
        title="",
    )

    # Add annotation to indicate auto-generation is disabled
    placeholder_fig.add_annotation(
        text="📊 Figure auto-generation is disabled<br>🔧 Configure parameters to generate visualization",
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=16),
        bgcolor="rgba(255,255,255,0.9)" if theme == "light" else "rgba(50,50,50,0.9)",
        bordercolor="#ddd" if theme == "light" else "#666",
        borderwidth=1,
    )

    # Style the placeholder appropriately for the theme
    placeholder_fig.update_layout(
        autosize=True,
        margin=dict(l=40, r=40, t=60, b=40),
        height=None,
        showlegend=False,
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False, title=""),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False, title=""),
    )

    return placeholder_fig


def analyze_figure_structure(fig: Any, dict_kwargs: dict, visu_type: str) -> dict:
    """
    Analyze figure structure and store original trace data for efficient patching.

    Inspired by MultiQC's analyze_multiqc_plot_structure - stores original trace data
    and parameter mappings to enable efficient Dash Patch operations.

    Args:
        fig: Plotly Figure object to analyze
        dict_kwargs: Parameter dictionary used to create the figure
        visu_type: Visualization type name

    Returns:
        Dictionary containing:
            - original_data: List of trace info with original x, y, z, marker, line data
            - parameter_mapping: Which columns mapped to which parameters
            - visu_type: Visualization type
            - summary: Trace count and metadata summary
    """

    if not fig or not hasattr(fig, "data"):
        return {"original_data": [], "parameter_mapping": {}, "summary": "No data"}

    # Store complete original data for each trace
    original_data = []
    trace_types = []

    for i, trace in enumerate(fig.data):
        trace_info = {
            "index": i,
            "type": trace.type if hasattr(trace, "type") else "",
            "name": trace.name if hasattr(trace, "name") else "",
            "mode": trace.mode if hasattr(trace, "mode") else "",
            "orientation": trace.orientation if hasattr(trace, "orientation") else "v",
            # Store original data arrays (preserve type for Plotly compatibility)
            "original_x": (
                tuple(trace.x)
                if hasattr(trace, "x") and trace.x is not None and isinstance(trace.x, tuple)
                else (list(trace.x) if hasattr(trace, "x") and trace.x is not None else [])
            ),
            "original_y": (
                tuple(trace.y)
                if hasattr(trace, "y") and trace.y is not None and isinstance(trace.y, tuple)
                else (list(trace.y) if hasattr(trace, "y") and trace.y is not None else [])
            ),
            "original_z": (
                tuple(trace.z)
                if hasattr(trace, "z") and trace.z is not None and isinstance(trace.z, tuple)
                else (list(trace.z) if hasattr(trace, "z") and trace.z is not None else [])
            ),
            # Store styling info for efficient patching
            "original_marker": trace.marker.to_plotly_json() if hasattr(trace, "marker") else {},
            "original_line": trace.line.to_plotly_json() if hasattr(trace, "line") else {},
            "visible": trace.visible if hasattr(trace, "visible") else True,
        }
        original_data.append(trace_info)
        trace_types.append(trace.type if hasattr(trace, "type") else "unknown")

    # Extract parameter mapping from dict_kwargs
    parameter_mapping = {
        "x": dict_kwargs.get("x"),
        "y": dict_kwargs.get("y"),
        "z": dict_kwargs.get("z"),
        "color": dict_kwargs.get("color"),
        "size": dict_kwargs.get("size"),
        "symbol": dict_kwargs.get("symbol"),
        "facet_row": dict_kwargs.get("facet_row"),
        "facet_col": dict_kwargs.get("facet_col"),
        "animation_frame": dict_kwargs.get("animation_frame"),
    }
    # Remove None values
    parameter_mapping = {k: v for k, v in parameter_mapping.items() if v is not None}

    # Extract color mapping if present (for categorical colors)
    color_discrete_map = dict_kwargs.get("color_discrete_map", {})

    # Create summary
    unique_types = list(set(trace_types))
    summary = {
        "traces": len(original_data),
        "types": ", ".join(unique_types),
        "has_color": "color" in parameter_mapping,
        "has_size": "size" in parameter_mapping,
        "has_facets": any(k in parameter_mapping for k in ["facet_row", "facet_col"]),
    }

    logger.debug(
        f"Analyzed figure structure: {summary['traces']} traces, "
        f"types: {summary['types']}, color: {summary['has_color']}"
    )

    return {
        "original_data": original_data,
        "parameter_mapping": parameter_mapping,
        "color_discrete_map": color_discrete_map,
        "visu_type": visu_type,
        "summary": summary,
    }


def extract_columns_from_preprocessing(
    preprocessing_code: str, df_columns: list[str] | None = None
) -> set[str]:
    """
    Extract source column references from code mode preprocessing code.

    Parses AST to find all column references (df['col'], df.col, groupby(['col']))
    and filters to only columns that exist in the source data.

    Args:
        preprocessing_code: The df_modified preprocessing line
        df_columns: Available source columns (optional, for validation)

    Returns:
        Set of source column names needed for preprocessing
    """
    columns = set()

    try:
        # Parse the preprocessing code
        tree = ast.parse(preprocessing_code)

        for node in ast.walk(tree):
            # Find subscript operations: df['column'] or chained_call['column']
            if isinstance(node, ast.Subscript):
                # Get column name from subscript
                if isinstance(node.slice, ast.Constant):
                    col_name = node.slice.value
                    # Only add if it looks like a column name (string, not numeric index)
                    if isinstance(col_name, str):
                        columns.add(col_name)
                # Handle list subscripts like df[['col1', 'col2']]
                elif isinstance(node.slice, ast.List):
                    for elt in node.slice.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            columns.add(elt.value)

            # Find function calls with column references
            elif isinstance(node, ast.Call):
                # Check for .groupby() calls with column lists
                if isinstance(node.func, ast.Attribute) and node.func.attr == "groupby":
                    for arg in node.args:
                        if isinstance(arg, ast.List):
                            for elt in arg.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    columns.add(elt.value)
                        elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            columns.add(arg.value)

                # Check for aggregation methods that might reference columns
                elif isinstance(node.func, ast.Attribute) and node.func.attr in [
                    "agg",
                    "sum",
                    "mean",
                    "median",
                    "std",
                    "var",
                    "min",
                    "max",
                    "count",
                ]:
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            columns.add(arg.value)

        # Filter to only columns that exist in source data (if provided)
        if df_columns:
            original_count = len(columns)
            columns = {col for col in columns if col in df_columns}
            logger.debug(
                f"Filtered columns from {original_count} to {len(columns)} based on available columns"
            )

        logger.info(
            f"✅ Extracted {len(columns)} source columns from preprocessing: {sorted(columns)}"
        )

    except Exception as e:
        logger.error(f"❌ Failed to parse preprocessing code: {e}")
        logger.exception("Full traceback:")
        # Return empty set on error - will fall back to loading all columns

    return columns


def extract_needed_columns(
    new_params: dict,
    trace_metadata: dict | None = None,
    interactive_components: dict | None = None,
    join_columns: list[str] | None = None,
    code_content: str | None = None,
    df_columns: list[str] | None = None,
) -> list[str]:
    """
    Extract all columns needed for figure rendering and interactive filtering.

    This enables column projection in load_deltatable_lite() for efficient data loading.
    Only loads the 3-5 columns actually needed instead of all 50+ columns in wide tables.

    CRITICAL: For code mode with df_modified preprocessing, extracts source columns from
    preprocessing code instead of figure parameters to avoid requesting computed columns.

    Args:
        new_params: Figure parameters (x, y, z, color, etc.)
        trace_metadata: Existing trace metadata with original column mappings
        interactive_components: Interactive component values (range sliders, dropdowns)
        join_columns: Join columns if this is a joined DC (CRITICAL for join integrity)
        code_content: Full code content for code mode (optional)
        df_columns: Available source columns for validation (optional)

    Returns:
        List of column names needed for the figure
    """
    columns = set()

    # CODE MODE PREPROCESSING: Extract source columns from preprocessing instead of figure params
    if code_content:
        from .code_mode import analyze_constrained_code

        logger.debug("Code mode detected: analyzing preprocessing for source columns")
        analysis = analyze_constrained_code(code_content)

        if analysis["has_preprocessing"]:
            # Extract columns from preprocessing code
            preprocessing_cols = extract_columns_from_preprocessing(
                analysis["preprocessing_code"], df_columns
            )

            if preprocessing_cols:
                logger.info(
                    f"✅ CODE MODE: Using {len(preprocessing_cols)} source columns from preprocessing: {sorted(preprocessing_cols)}"
                )
                columns.update(preprocessing_cols)

                # ESSENTIAL COLUMNS: Always include these for code mode
                essential_columns = [
                    "depictio_run_id",  # Required for joins and run isolation
                ]
                columns.update(essential_columns)

                # JOIN COLUMNS: CRITICAL - include all join columns for joined DCs
                if join_columns:
                    columns.update(join_columns)
                    logger.debug(
                        f"Added {len(join_columns)} join columns to projection: {join_columns}"
                    )

                # Return early - preprocessing columns are sufficient
                result = sorted([col for col in columns if col is not None and col != ""])
                logger.info(
                    f"📊 CODE MODE PROJECTION: {len(result)} columns for data loading: {result}"
                )
                return result
            else:
                logger.warning(
                    "⚠️ CODE MODE: Failed to extract columns from preprocessing, falling back to figure params"
                )
        else:
            logger.debug("CODE MODE: No preprocessing, extracting from figure params")

    # STANDARD EXTRACTION: Extract from figure parameters (non-code mode or no preprocessing)
    columns = set()

    # 1. PLOT PARAMETERS: Extract columns from visualization parameters
    plot_columns = [
        "x",
        "y",
        "z",
        "color",
        "symbol",
        "size",
        "facet_col",
        "facet_row",
        "error_x",
        "error_y",
        "error_z",
        "text",
    ]

    for param in plot_columns:
        if param in new_params and new_params[param]:
            col = new_params[param]
            if isinstance(col, str):
                columns.add(col)

    # 2. HOVER DATA: Extract columns from hover_data configuration
    if "hover_data" in new_params and new_params["hover_data"]:
        hover_data = new_params["hover_data"]
        if isinstance(hover_data, list):
            columns.update(hover_data)
        elif isinstance(hover_data, dict):
            columns.update(hover_data.keys())

    # 3. CUSTOM DATA: Extract columns from custom_data
    if "custom_data" in new_params and new_params["custom_data"]:
        custom_data = new_params["custom_data"]
        if isinstance(custom_data, list):
            columns.update(custom_data)

    # 4. TRACE METADATA: Extract columns from existing trace data
    if trace_metadata and "parameter_mapping" in trace_metadata:
        param_mapping = trace_metadata["parameter_mapping"]
        for key in ["x_column", "y_column", "z_column", "color_column", "symbol_column"]:
            if key in param_mapping and param_mapping[key]:
                columns.add(param_mapping[key])

    # 5. INTERACTIVE COMPONENTS: Extract columns from interactive filters
    # This would be for range sliders, dropdowns, etc. targeting specific columns
    if interactive_components:
        # Extract column names from interactive component values
        # Format: {"column_name": {"min": 0, "max": 100}} for range sliders
        # or {"column_name": ["value1", "value2"]} for dropdowns
        for key in interactive_components.keys():
            # Check if key is a column name (not a metadata field)
            if not key.startswith("_") and key not in ["mode", "theme"]:
                columns.add(key)

    # 6. ESSENTIAL COLUMNS: Always include these if they exist
    essential_columns = [
        "depictio_run_id",  # Required for joins and run isolation
    ]
    columns.update(essential_columns)

    # 7. JOIN COLUMNS: CRITICAL - include all join columns for joined DCs
    if join_columns:
        columns.update(join_columns)
        logger.debug(f"Added {len(join_columns)} join columns to projection: {join_columns}")

    # Filter out None values and return sorted list
    result = sorted([col for col in columns if col is not None and col != ""])

    logger.debug(f"Extracted {len(result)} needed columns for data loading: {result}")

    return result


def get_parameter_impact_type(param_name: str) -> str:
    """
    Determine impact type for a parameter change.

    Args:
        param_name: Name of the parameter

    Returns:
        Impact type: "categorical" | "continuous" | "axis" | "layout"
    """
    # Axis parameters - require data swap
    if param_name in ["x", "y", "z", "r", "theta"]:
        return "axis"

    # Layout parameters - only update layout, no data changes
    if param_name in [
        "title",
        "template",
        "showlegend",
        "width",
        "height",
        "xaxis_title",
        "yaxis_title",
        "range_x",
        "range_y",
        "range_z",
        "log_x",
        "log_y",
        "log_z",
    ]:
        return "layout"

    # Categorical parameters - may add/remove traces or change grouping
    if param_name in [
        "color",
        "symbol",
        "line_dash",
        "pattern_shape",
        "facet_row",
        "facet_col",
        "animation_frame",
        "animation_group",
    ]:
        return "categorical"

    # Continuous parameters - update properties only
    # opacity, size (when continuous), line_width, marker properties
    return "continuous"


def detect_parameter_changes(old_params: dict, new_params: dict, visu_type: str) -> dict:
    """
    Detect what changed between parameter sets and categorize by impact.

    Args:
        old_params: Current parameter dictionary
        new_params: New parameter dictionary
        visu_type: Visualization type name

    Returns:
        Dictionary with categorized changes and re-render flag:
        {
            "categorical_changes": ["color", "symbol"],
            "continuous_changes": ["opacity", "marker_size"],
            "axis_changes": ["x", "y"],
            "layout_changes": ["title", "template"],
            "requires_full_rerender": bool,
        }
    """
    changes = {
        "categorical_changes": [],
        "continuous_changes": [],
        "axis_changes": [],
        "layout_changes": [],
        "requires_full_rerender": False,
    }

    # Only check parameters that are in new_params
    # Parameters in old_params but not in new_params are not being updated
    for key in new_params.keys():
        old_value = old_params.get(key)
        new_value = new_params.get(key)

        # Skip if values are the same
        if old_value == new_value:
            continue

        # Detect impact type
        impact = get_parameter_impact_type(key)

        if impact == "categorical":
            changes["categorical_changes"].append(key)
        elif impact == "continuous":
            changes["continuous_changes"].append(key)
        elif impact == "axis":
            changes["axis_changes"].append(key)
        elif impact == "layout":
            changes["layout_changes"].append(key)

    # Determine if full re-render is required
    # Categorical changes or visualization type change requires full re-render
    if changes["categorical_changes"]:
        changes["requires_full_rerender"] = True

    # Check if visualization type changed (requires full re-render)
    if old_params.get("visu_type") != new_params.get("visu_type"):
        changes["requires_full_rerender"] = True

    logger.debug(
        f"Parameter changes detected: "
        f"categorical={len(changes['categorical_changes'])}, "
        f"continuous={len(changes['continuous_changes'])}, "
        f"axis={len(changes['axis_changes'])}, "
        f"layout={len(changes['layout_changes'])}, "
        f"full_rerender={changes['requires_full_rerender']}"
    )

    return changes


def patch_layout_parameter(patch: Any, param_name: str, new_value: Any) -> Any:
    """
    Patch layout-only parameter changes (most efficient).

    Args:
        patch: Dash Patch object
        param_name: Parameter name to update
        new_value: New value for the parameter

    Returns:
        Updated Patch object
    """
    from dash import Patch

    if not isinstance(patch, Patch):
        patch = Patch()

    if param_name == "title":
        patch["layout"]["title"]["text"] = new_value
    elif param_name == "template":
        # Template needs to be a template object, not string
        import plotly.io as pio

        if new_value in pio.templates:
            patch["layout"]["template"] = pio.templates[new_value]
    elif param_name == "showlegend":
        patch["layout"]["showlegend"] = new_value
    elif param_name == "xaxis_title":
        patch["layout"]["xaxis"]["title"]["text"] = new_value
    elif param_name == "yaxis_title":
        patch["layout"]["yaxis"]["title"]["text"] = new_value
    elif param_name == "range_x":
        patch["layout"]["xaxis"]["range"] = new_value
    elif param_name == "range_y":
        patch["layout"]["yaxis"]["range"] = new_value
    elif param_name == "range_z":
        patch["layout"]["zaxis"]["range"] = new_value
    elif param_name == "log_x":
        patch["layout"]["xaxis"]["type"] = "log" if new_value else "linear"
    elif param_name == "log_y":
        patch["layout"]["yaxis"]["type"] = "log" if new_value else "linear"
    elif param_name == "log_z":
        patch["layout"]["zaxis"]["type"] = "log" if new_value else "linear"

    logger.debug(f"Patched layout parameter: {param_name} = {new_value}")
    return patch


def patch_continuous_parameter(
    patch: Any, param_name: str, new_value: Any, trace_indices: list[int] | None = None
) -> Any:
    """
    Patch continuous parameter changes (very efficient).

    Args:
        patch: Dash Patch object
        param_name: Parameter name to update
        new_value: New value for the parameter
        trace_indices: Specific trace indices to update (default: all)

    Returns:
        Updated Patch object
    """
    from dash import Patch

    if not isinstance(patch, Patch):
        patch = Patch()

    # If no trace indices specified, will apply to all traces via dict update
    if trace_indices is None:
        # Apply to all traces using wildcard pattern
        if param_name == "opacity":
            patch["data"][0]["marker"]["opacity"] = new_value
        elif param_name == "marker_size" or param_name == "size":
            patch["data"][0]["marker"]["size"] = new_value
        elif param_name == "line_width":
            patch["data"][0]["line"]["width"] = new_value
    else:
        # Apply to specific traces
        for i in trace_indices:
            if param_name == "opacity":
                patch["data"][i]["marker"]["opacity"] = new_value
            elif param_name == "marker_size" or param_name == "size":
                patch["data"][i]["marker"]["size"] = new_value
            elif param_name == "line_width":
                patch["data"][i]["line"]["width"] = new_value

    logger.debug(
        f"Patched continuous parameter: {param_name} = {new_value} "
        f"(traces: {trace_indices or 'all'})"
    )
    return patch


def patch_axis_parameter(
    fig_dict: dict,
    trace_metadata: dict,
    param_name: str,
    new_value: str,
    df: pl.DataFrame,
) -> dict:
    """
    Patch axis parameter changes (moderate - requires data loading).

    Args:
        fig_dict: Figure dictionary (from current_figure)
        trace_metadata: Original trace metadata with parameter mappings
        param_name: Parameter name ('x', 'y', or 'z')
        new_value: New column name
        df: DataFrame with new data

    Returns:
        Updated figure dictionary
    """
    import copy

    patched_fig = copy.deepcopy(fig_dict)
    original_data = trace_metadata.get("original_data", [])

    # Update each trace with new data from the specified column
    for i, _trace_info in enumerate(original_data):
        if i < len(patched_fig.get("data", [])):
            try:
                if param_name == "x":
                    patched_fig["data"][i]["x"] = df[new_value].to_list()
                elif param_name == "y":
                    patched_fig["data"][i]["y"] = df[new_value].to_list()
                elif param_name == "z":
                    patched_fig["data"][i]["z"] = df[new_value].to_list()

                logger.debug(f"Patched trace {i} axis {param_name} with column {new_value}")
            except Exception as e:
                logger.error(f"Failed to patch trace {i} axis {param_name}: {e}")
                continue

    logger.info(f"Patched axis parameter: {param_name} → {new_value}")
    return patched_fig


def _should_defer_umap_computation(df: pl.DataFrame, context: str = "unknown") -> bool:
    """Determine if UMAP computation should be deferred based on data size and context."""
    if df is None or df.is_empty():
        return False

    data_size = df.height

    # Different thresholds based on context
    thresholds = {
        "dashboard_restore": 1000,  # Very conservative for restore
        "interactive": 5000,  # More lenient for user-initiated actions
        "unknown": 2000,  # Middle ground
    }

    threshold = thresholds.get(context, thresholds["unknown"])
    should_defer = data_size > threshold

    if should_defer:
        logger.info(
            f"📄 UMAP computation deferred: {data_size} rows > {threshold} threshold (context: {context})"
        )

    return should_defer


def _highlight_selected_point(figure, df, dict_kwargs, selected_point):
    """Highlight a selected point on the figure."""
    try:
        selected_x = selected_point["x"]
        selected_y = selected_point["y"]

        x_col = df[dict_kwargs["x"]]
        y_col = df[dict_kwargs["y"]]

        # Create boolean mask for selected points
        is_selected = (x_col == selected_x) & (y_col == selected_y)

        # Update marker colors
        colors = ["red" if sel else "blue" for sel in is_selected]
        opacities = [1.0 if sel else 0.3 for sel in is_selected]

        figure.update_traces(marker=dict(color=colors, opacity=opacities))
    except Exception as e:
        logger.warning(f"Failed to highlight selected point: {e}")


def get_available_columns(df: pl.DataFrame) -> Dict[str, List[str]]:
    """Get available columns categorized by data type.

    Args:
        df: Polars DataFrame

    Returns:
        Dictionary with column categories
    """
    if df is None or df.is_empty():
        return {"all": [], "numeric": [], "categorical": [], "datetime": []}

    columns = {"all": df.columns, "numeric": [], "categorical": [], "datetime": []}

    for col in df.columns:
        dtype = str(df[col].dtype)
        if dtype in ["Int64", "Float64", "Int32", "Float32"]:
            columns["numeric"].append(col)
        elif dtype in ["Utf8", "Boolean"]:
            columns["categorical"].append(col)
        elif "Date" in dtype or "Time" in dtype:
            columns["datetime"].append(col)

    return columns


def validate_parameters(visu_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clean parameters for a visualization type.

    Args:
        visu_type: Visualization type
        parameters: Raw parameters

    Returns:
        Validated and cleaned parameters
    """
    # Defensive handling: ensure parameters is a dict
    if not isinstance(parameters, dict):
        logger.warning(f"Expected dict for parameters, got {type(parameters)}: {parameters}")
        return {}

    # Essential parameters that should always be preserved regardless of visualization type
    ESSENTIAL_PARAMETERS = {
        "template",  # Theme-based template
        "title",  # Figure title
        "width",  # Figure width
        "height",  # Figure height
        "opacity",  # Marker opacity
        "log_x",  # Log X scale
        "log_y",  # Log Y scale
        "range_x",  # X axis range
        "range_y",  # Y axis range
    }

    try:
        viz_def = get_visualization_definition(visu_type)
        valid_params = {p.name for p in viz_def.parameters}

        # Include essential parameters even if not in visualization definition
        valid_params.update(ESSENTIAL_PARAMETERS)

        # Filter to valid parameters only
        cleaned = {k: v for k, v in parameters.items() if k in valid_params and v is not None}

        logger.info(f"Validated parameters for {visu_type}: {list(cleaned.keys())}")
        return cleaned

    except Exception as e:
        logger.warning(f"Parameter validation failed: {e}, returning original")
        # Additional defensive handling in exception case
        if isinstance(parameters, dict):
            return {k: v for k, v in parameters.items() if v is not None}
        else:
            return {}


def build_figure(**kwargs) -> html.Div | dcc.Loading:
    """Build figure component - Phase 1: View mode only.

    This simplified version creates a skeleton structure that will be populated
    by the batch rendering callback (callbacks/core.py). No stepper mode, no code mode,
    no parameter interface building - just the basic structure for view mode rendering.

    Args:
        **kwargs: Figure configuration parameters
            - index: Component index (required)
            - visu_type: Visualization type (default: "scatter")
            - dict_kwargs: Figure parameters (default: {})
            - wf_id: Workflow ID
            - dc_id: Data collection ID
            - theme: Theme (default: "light")

    Returns:
        Figure component as HTML div with skeleton loader
    """
    # Extract essential parameters
    index = kwargs.get("index")
    visu_type = kwargs.get("visu_type", "scatter")
    dict_kwargs = kwargs.get("dict_kwargs", {})
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    theme = kwargs.get("theme", "light")

    # Defensive handling: ensure dict_kwargs is always a dict
    if not isinstance(dict_kwargs, dict):
        logger.warning(f"Expected dict for dict_kwargs, got {type(dict_kwargs)}: {dict_kwargs}")
        dict_kwargs = {}

    logger.info(f"Building figure component {index} (visu_type: {visu_type}, theme: {theme})")

    # Phase 1: Create simple skeleton structure that will be populated by callback
    # The batch rendering callback in callbacks/core.py handles all data loading and figure generation

    # Component metadata for dashboard save/restore
    store_component_data = {
        "index": str(index),
        "component_type": "figure",
        "visu_type": visu_type,
        "dict_kwargs": dict_kwargs,
        "wf_id": wf_id,
        "dc_id": dc_id,
        "last_updated": datetime.now().isoformat(),
    }

    # Phase 1: Simple structure - Trigger store + Skeleton + Graph + Metadata store
    return html.Div(
        id={"type": "figure-container", "index": index},
        className="figure-container",
        children=[
            # Trigger store - initiates batch rendering callback
            dcc.Store(
                id={"type": "figure-trigger", "index": index},
                data={
                    "index": index,
                    "wf_id": wf_id,
                    "dc_id": dc_id,
                    "visu_type": visu_type,
                    "dict_kwargs": dict_kwargs,
                },
            ),
            # Metadata store - for callback results
            dcc.Store(
                id={"type": "figure-metadata", "index": index},
                data={},
            ),
            # Component metadata store - for dashboard save/restore
            dcc.Store(
                id={"type": "stored-metadata-component", "index": index},
                data=store_component_data,
            ),
            # Graph (populated by callback) - No Loading wrapper to allow dynamic updates
            dcc.Graph(
                id={"type": "figure-graph", "index": index},
                figure={},  # Empty - populated by batch rendering callback
                config={"displayModeBar": True, "responsive": True},
                style={"height": "100%", "width": "100%"},
            ),
        ],
        style={
            "height": "100%",
            "width": "100%",
            "display": "flex",
            "flexDirection": "column",
        },
    )


def _create_info_badges(
    index: str, df: pl.DataFrame, visu_type: str, filter_applied: bool, build_frame: bool
) -> html.Div:
    """Create informational badges for the figure.

    Note: Partial data warning has been moved to an ActionIcon button in edit.py
    for better integration with component controls.
    """
    if not build_frame:
        return html.Div()

    badges = []

    # Filter applied badge
    if filter_applied:
        filter_badge = dmc.Tooltip(
            children=dmc.Badge(
                "Filter applied",
                id={"type": "graph-filter-badge", "index": index},
                leftSection=DashIconify(icon="mdi:filter", width=20),
                size="lg",
                radius="xl",
                color="orange",
            ),
            label="Data has been filtered.",
            position="top",
            openDelay=500,
            withinPortal=False,
        )
        badges.append(filter_badge)

    if badges:
        return html.Div(dbc.Row(dmc.Group(badges, gap="md", style={"margin-left": "12px"})))

    return html.Div()


def create_stepper_figure_button(n, disabled=False):
    """Create the stepper figure button.

    Args:
        n: Button index
        disabled: Whether button is disabled

    Returns:
        Button and store components
    """
    from depictio.dash.utils import UNSELECTED_STYLE

    button = dbc.Col(
        dmc.Button(
            "Figure",
            id={
                "type": "btn-option",
                "index": n,
                "value": "Figure",
            },
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="grape",
            leftSection=DashIconify(icon="mdi:graph-box", color="white"),
            disabled=disabled,
        )
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Figure",
        },
        data=0,
        storage_type="memory",
    )
    return button, store


# Async wrapper for background callbacks - now calls sync version
async def build_figure_async(**kwargs):
    """
    Async wrapper for build_figure function - async functionality disabled, calls sync version.
    """
    logger.info(
        f"🔄 ASYNC FIGURE: Building figure component (using sync) - Index: {kwargs.get('index', 'UNKNOWN')}"
    )

    # Call the synchronous build_figure function
    result = build_figure(**kwargs)

    logger.info(
        f"✅ ASYNC FIGURE: Figure component built successfully - Index: {kwargs.get('index', 'UNKNOWN')}"
    )
    return result


# Legacy exports for backward compatibility
# These will be removed in future versions
def get_available_visualizations():
    """Get available visualization types."""
    return list(PLOTLY_FUNCTIONS.keys())


def get_visualization_options():
    """Get visualization options for UI."""
    return [{"label": name.title(), "value": name} for name in PLOTLY_FUNCTIONS.keys()]
