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
    dict_kwargs: dict,
    visu_type: str,
    df_hash: str,
    cutoff: int,
    selected_point: dict,
    theme: str,
    customizations: Optional[dict] = None,
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
        "customizations": customizations or {},
    }
    cache_str = str(cache_data)
    return hashlib.md5(cache_str.encode()).hexdigest()


# ============================================================================
# RENDER_FIGURE HELPER FUNCTIONS
# ============================================================================


def _init_data_info() -> dict:
    """Initialize the data info dictionary for tracking data counts."""
    return {
        "total_data_count": 0,
        "displayed_data_count": 0,
        "was_sampled": False,
    }


def _check_figure_cache(cache_key: str) -> tuple[Any, dict, bool]:
    """
    Check if a figure is cached and return it if available.

    Args:
        cache_key: The cache key to look up

    Returns:
        Tuple of (cached_figure, cached_data_info, cache_hit)
    """

    _clean_figure_cache()
    if cache_key in _figure_result_cache:
        cached_result = _figure_result_cache[cache_key]
        # Handle both old format (just figure) and new format (figure, data_info, timestamp)
        if isinstance(cached_result, tuple) and len(cached_result) == 3:
            cached_figure, cached_data_info, timestamp = cached_result
        else:
            # Old format - just figure and timestamp
            cached_figure, timestamp = cached_result
            cached_data_info = _init_data_info()
        return cached_figure, cached_data_info, True
    return None, _init_data_info(), False


def _clean_figure_parameters(dict_kwargs: dict, df: pl.DataFrame, mode: str) -> dict:
    """
    Clean and parse figure parameters, handling JSON strings and color sequences.

    Args:
        dict_kwargs: Raw parameter dictionary
        df: DataFrame for context in code mode evaluation
        mode: Component mode ('ui' or 'code')

    Returns:
        Cleaned parameter dictionary
    """
    # Parameters that can legitimately be empty strings
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
            if (
                v != ""
                and v != []
                or (k in keep_empty_string_params and v == "")
                or isinstance(v, bool)
            ):
                cleaned_kwargs[k] = v

    # Parse JSON string parameters
    cleaned_kwargs = _parse_json_parameters(cleaned_kwargs, df, mode)

    return cleaned_kwargs


def _parse_json_parameters(cleaned_kwargs: dict, df: pl.DataFrame, mode: str) -> dict:
    """
    Parse JSON string parameters that Plotly expects as Python objects.

    Args:
        cleaned_kwargs: Parameter dictionary to parse
        df: DataFrame for context in code mode evaluation
        mode: Component mode ('ui' or 'code')

    Returns:
        Parameter dictionary with parsed JSON values
    """
    json_params = [
        "color_discrete_map",
        "color_discrete_sequence",
        "color_continuous_scale",
        "category_orders",
        "labels",
        "path",
    ]

    for param_name in json_params:
        if param_name not in cleaned_kwargs or not isinstance(cleaned_kwargs[param_name], str):
            continue

        param_value = cleaned_kwargs[param_name]

        # Try to resolve Plotly named color palettes
        if param_name in ["color_discrete_sequence", "color_continuous_scale"]:
            resolved = _resolve_color_palette(param_value)
            if resolved is not None:
                cleaned_kwargs[param_name] = resolved
                continue

        # Try JSON parsing
        try:
            cleaned_kwargs[param_name] = json.loads(param_value)
            continue
        except json.JSONDecodeError:
            pass

        # Check for complex Python expressions
        if any(
            pattern in param_value for pattern in ["(", ".", "sorted", "unique", "to_list", "df["]
        ):
            if mode == "code" and df is not None:
                evaluated = _evaluate_code_mode_parameter(param_name, param_value, df)
                if evaluated is not None:
                    cleaned_kwargs[param_name] = evaluated
                    continue
            del cleaned_kwargs[param_name]
            continue

        # Fallback to ast.literal_eval
        try:
            cleaned_kwargs[param_name] = ast.literal_eval(param_value)
        except (ValueError, SyntaxError) as e:
            logger.warning(f"Invalid parameter format for {param_name}: {param_value} - {e}")
            del cleaned_kwargs[param_name]

    return cleaned_kwargs


def _resolve_color_palette(param_value: str) -> list | None:
    """
    Resolve a Plotly named color palette to its color list.

    Args:
        param_value: Name of the color palette

    Returns:
        List of colors if found, None otherwise
    """
    color_modules = [
        px.colors.qualitative,
        px.colors.sequential,
        px.colors.diverging,
        px.colors.cyclical,
    ]

    for module in color_modules:
        if hasattr(module, param_value):
            color_sequence = getattr(module, param_value)
            return color_sequence

    return None


def _evaluate_code_mode_parameter(param_name: str, param_value: str, df: pl.DataFrame) -> Any:
    """
    Evaluate a parameter expression in code mode context.

    Args:
        param_name: Name of the parameter
        param_value: Expression string to evaluate
        df: DataFrame for context

    Returns:
        Evaluated value or None if evaluation fails
    """
    try:
        from depictio.dash.modules.figure_component.code_mode import evaluate_params_in_context

        temp_params = {param_name: param_value}
        evaluated_params = evaluate_params_in_context(temp_params, df)
        if param_name in evaluated_params:
            return evaluated_params[param_name]
    except Exception as e:
        logger.warning(f"Failed to evaluate code mode parameter {param_name}: {e}")
    return None


def _convert_style_parameters(cleaned_kwargs: dict, df: pl.DataFrame) -> dict:
    """
    Convert line_dash and symbol style literals to sequence parameters.

    Args:
        cleaned_kwargs: Parameter dictionary
        df: DataFrame to check column existence

    Returns:
        Updated parameter dictionary
    """
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

    # Handle line_dash parameter
    if "line_dash" in cleaned_kwargs:
        dash_value = cleaned_kwargs["line_dash"]
        if dash_value in VALID_DASH_STYLES:
            cleaned_kwargs["line_dash_sequence"] = [dash_value]
            del cleaned_kwargs["line_dash"]
        elif dash_value not in df.columns:
            logger.warning(f"line_dash value '{dash_value}' is not valid. Removing.")
            del cleaned_kwargs["line_dash"]

    # Handle symbol parameter
    if "symbol" in cleaned_kwargs:
        symbol_value = cleaned_kwargs["symbol"]
        if symbol_value in VALID_SYMBOL_STYLES:
            cleaned_kwargs["symbol_sequence"] = [symbol_value]
            del cleaned_kwargs["symbol"]
        elif symbol_value not in df.columns:
            logger.warning(f"symbol value '{symbol_value}' is not valid. Removing.")
            del cleaned_kwargs["symbol"]

    return cleaned_kwargs


def _validate_required_params(
    visu_type: str, cleaned_kwargs: dict, df: pl.DataFrame, theme: str, skip_validation: bool
) -> tuple[bool, Any]:
    """
    Validate that required parameters are present for the visualization type.

    Args:
        visu_type: Visualization type
        cleaned_kwargs: Cleaned parameter dictionary
        df: DataFrame for column reference
        theme: Theme for error figure
        skip_validation: Whether to skip validation

    Returns:
        Tuple of (is_valid, error_figure_or_none)
    """
    if skip_validation:
        return True, None

    required_params = _get_required_parameters(visu_type.lower())

    # Smart validation for plots that can work with either X or Y
    if required_params == ["x"] and visu_type.lower() in ["bar", "line", "scatter", "area"]:
        if "x" not in cleaned_kwargs and "y" not in cleaned_kwargs:
            logger.warning(f"Missing required parameters for {visu_type}: need either X or Y")
            title = f"Please select X or Y column to create {visu_type} plot"
            return False, _create_theme_aware_figure(_get_theme_template(theme), title=title)
    else:
        missing_params = [param for param in required_params if param not in cleaned_kwargs]
        if missing_params:
            logger.warning(f"Missing required parameters for {visu_type}: {missing_params}")
            title = f"Please select {', '.join(missing_params).upper()} column(s) to create {visu_type} plot"
            return False, _create_theme_aware_figure(_get_theme_template(theme), title=title)

    return True, None


def _handle_hierarchical_chart(
    visu_type: str, cleaned_kwargs: dict, df: pl.DataFrame
) -> pl.DataFrame:
    """
    Handle special processing for hierarchical charts (sunburst, treemap).

    Args:
        visu_type: Visualization type
        cleaned_kwargs: Parameter dictionary
        df: DataFrame to filter

    Returns:
        Filtered DataFrame
    """
    if visu_type.lower() not in ["sunburst", "treemap"]:
        return df

    # Filter out non-leaf rows
    if "path" in cleaned_kwargs and cleaned_kwargs["path"]:
        path_columns = cleaned_kwargs["path"]

        for col in path_columns:
            if col in df.columns:
                df = df.filter(
                    (pl.col(col).is_not_null())
                    & (pl.col(col) != "")
                    & (pl.col(col).str.strip_chars() != "")
                )

    # Handle empty parents parameter
    if "parents" in cleaned_kwargs and cleaned_kwargs["parents"] == "":
        cleaned_kwargs["parents"] = None

    # Validate column existence
    for param_name, column_name in cleaned_kwargs.items():
        if param_name in ["values", "names", "ids", "parents", "color"] and column_name:
            if column_name not in df.columns:
                logger.warning(f"Column '{column_name}' not found for parameter '{param_name}'")
                cleaned_kwargs[param_name] = None

    return df


def _extract_manual_color_params(
    visu_type: str, cleaned_kwargs: dict
) -> tuple[dict | None, list | None]:
    """
    Extract color parameters for manual application in box/violin plots.

    Args:
        visu_type: Visualization type
        cleaned_kwargs: Parameter dictionary (will be modified)

    Returns:
        Tuple of (manual_color_map, manual_color_sequence)
    """
    manual_color_map = None
    manual_color_sequence = None

    if visu_type.lower() in ["box", "violin", "strip"] and "color" not in cleaned_kwargs:
        if "color_discrete_map" in cleaned_kwargs:
            manual_color_map = cleaned_kwargs.pop("color_discrete_map")
        if "color_discrete_sequence" in cleaned_kwargs:
            manual_color_sequence = cleaned_kwargs.pop("color_discrete_sequence")

    return manual_color_map, manual_color_sequence


def _apply_sampling(
    df: pl.DataFrame, cutoff: int, cleaned_kwargs: dict, force_full_data: bool
) -> tuple[pl.DataFrame, bool]:
    """
    Apply sampling to large datasets if needed.

    Args:
        df: Input DataFrame
        cutoff: Maximum data points before sampling
        cleaned_kwargs: Parameters for cache key generation
        force_full_data: Whether to bypass sampling

    Returns:
        Tuple of (sampled_or_full_df, was_sampled)
    """
    if df.height <= cutoff or force_full_data:
        return df, False

    cache_key = f"{id(df)}_{cutoff}_{hash(str(cleaned_kwargs))}"

    if cache_key not in _sampling_cache:
        sampled_df = df.sample(n=cutoff, seed=0)
        _sampling_cache[cache_key] = sampled_df
    else:
        sampled_df = _sampling_cache[cache_key]

    return sampled_df, True


def _apply_box_violin_colors(
    figure: Any,
    visu_type: str,
    cleaned_kwargs: dict,
    df: pl.DataFrame,
    manual_color_map: dict | None,
    manual_color_sequence: list | None,
) -> Any:
    """
    Apply custom colors to box/violin plots without a color parameter.

    Args:
        figure: Plotly figure to modify
        visu_type: Visualization type
        cleaned_kwargs: Parameter dictionary
        df: DataFrame for data extraction
        manual_color_map: Color map by category
        manual_color_sequence: Color sequence

    Returns:
        Modified figure
    """
    if visu_type.lower() not in ["box", "violin", "strip"]:
        return figure
    if "color" in cleaned_kwargs:
        return figure
    if not manual_color_map and not manual_color_sequence:
        return figure

    # Validate color sources
    if not (
        (isinstance(manual_color_sequence, (list, tuple)) and len(manual_color_sequence) > 0)
        or (isinstance(manual_color_map, dict) and len(manual_color_map) > 0)
    ):
        return figure

    # Single trace case - need to recreate with individual traces
    if len(figure.data) == 1:
        return _recreate_box_violin_with_colors(
            figure, visu_type, cleaned_kwargs, df, manual_color_map, manual_color_sequence
        )
    else:
        # Multiple traces - apply one color per trace
        return _apply_colors_to_multiple_traces(figure, manual_color_map, manual_color_sequence)


def _recreate_box_violin_with_colors(
    figure: Any,
    visu_type: str,
    cleaned_kwargs: dict,
    df: pl.DataFrame,
    color_map: dict | None,
    color_sequence: list | None,
) -> Any:
    """
    Recreate box/violin plot with individual colored traces.

    Args:
        figure: Original figure
        visu_type: Visualization type
        cleaned_kwargs: Parameter dictionary
        df: DataFrame
        color_map: Color map by category
        color_sequence: Color sequence

    Returns:
        New figure with colored traces
    """

    orientation = cleaned_kwargs.get("orientation", "v")
    categorical_column = cleaned_kwargs.get("x") if orientation == "v" else cleaned_kwargs.get("y")
    numeric_column = cleaned_kwargs.get("y") if orientation == "v" else cleaned_kwargs.get("x")

    if not categorical_column or categorical_column not in df.columns:
        return figure
    if not isinstance(numeric_column, str):
        return figure

    # Get category order
    category_orders = cleaned_kwargs.get("category_orders", {})
    if isinstance(category_orders, dict) and categorical_column in category_orders:
        unique_categories = category_orders[categorical_column]
    else:
        unique_categories = df.get_column(categorical_column).unique(maintain_order=True).to_list()

    # Clear existing traces and recreate
    figure.data = []

    for i, category in enumerate(unique_categories):
        category_data = df.filter(pl.col(categorical_column) == category)
        values = category_data.get_column(numeric_column).to_list()

        # Determine color
        color = _get_category_color(str(category), i, color_map, color_sequence)

        # Create trace
        trace = _create_box_violin_trace(
            visu_type, orientation, values, category, color, cleaned_kwargs
        )
        figure.add_trace(trace)

    # Update axis configuration
    _configure_box_violin_axes(figure, orientation, unique_categories)

    return figure


def _get_category_color(
    category: str, index: int, color_map: dict | None, color_sequence: list | None
) -> str:
    """Get color for a category from map or sequence."""
    if color_map and category in color_map:
        return color_map[category]
    elif color_sequence:
        return color_sequence[index % len(color_sequence)]
    else:
        return px.colors.qualitative.Plotly[index % 10]


def _create_box_violin_trace(
    visu_type: str,
    orientation: str,
    values: list,
    category: Any,
    color: str,
    cleaned_kwargs: dict,
) -> Any:
    """Create a box or violin trace with specified parameters."""
    import plotly.graph_objects as go

    category_str = str(category)
    position_data = [category_str] * len(values)

    if visu_type.lower() == "box":
        base_params = {
            "name": category_str,
            "marker_color": color,
            "boxmean": cleaned_kwargs.get("boxmean"),
            "notched": cleaned_kwargs.get("notched", False),
            "boxpoints": cleaned_kwargs.get("points"),
            "showlegend": False,
        }
        if orientation == "v":
            return go.Box(y=values, x=position_data, **base_params)
        else:
            return go.Box(x=values, y=position_data, **base_params)
    else:  # violin
        base_params = {
            "name": category_str,
            "marker_color": color,
            "showlegend": False,
        }
        if orientation == "v":
            return go.Violin(y=values, x=position_data, **base_params)
        else:
            return go.Violin(x=values, y=position_data, **base_params)


def _configure_box_violin_axes(figure: Any, orientation: str, categories: list) -> None:
    """Configure axes for box/violin plots with proper category ordering."""
    category_array = [str(c) for c in categories]

    if orientation == "v":
        figure.update_xaxes(type="category", categoryorder="array", categoryarray=category_array)
    else:
        figure.update_yaxes(type="category", categoryorder="array", categoryarray=category_array)

    figure.update_layout(boxmode="overlay")


def _apply_colors_to_multiple_traces(
    figure: Any, color_map: dict | None, color_sequence: list | None
) -> Any:
    """Apply colors to multiple existing traces."""
    for i, trace in enumerate(figure.data):
        trace_name = trace.name if hasattr(trace, "name") else None
        applied_color = None

        if color_map and trace_name and str(trace_name) in color_map:
            applied_color = color_map[str(trace_name)]
        elif color_sequence:
            applied_color = color_sequence[i % len(color_sequence)]

        if applied_color:
            try:
                if hasattr(trace, "marker"):
                    trace["marker"]["color"] = applied_color
                if hasattr(trace, "line"):
                    trace["line"]["color"] = applied_color
            except (TypeError, KeyError):
                pass

    return figure


def _finalize_figure(
    figure: Any, cleaned_kwargs: dict, selected_point: dict | None, df: pl.DataFrame
) -> Any:
    """
    Apply final configuration to the figure.

    Args:
        figure: Plotly figure
        cleaned_kwargs: Parameter dictionary
        selected_point: Optional point to highlight
        df: DataFrame

    Returns:
        Finalized figure
    """
    # Fix marginal plot axis constraints
    if "marginal_x" in cleaned_kwargs or "marginal_y" in cleaned_kwargs:
        figure.update_xaxes(matches=None)
        figure.update_yaxes(matches=None)

    # Apply responsive sizing
    figure.update_layout(
        autosize=True,
        margin=dict(l=40, r=40, t=40, b=40),
        height=None,
    )

    # Highlight selected point
    if selected_point and "x" in cleaned_kwargs and "y" in cleaned_kwargs:
        _highlight_selected_point(figure, df, cleaned_kwargs, selected_point)

    return figure


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
    customizations: Optional[Dict[str, Any]] = None,
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
        customizations: Optional dict of post-rendering customizations (axes, reference_lines, etc.)
                       See depictio.dash.modules.figure_component.customizations for schema

    Returns:
        Tuple of (Plotly figure object, data_info dict with counts)
    """
    import time

    data_info = _init_data_info()

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

    # Generate cache key and check cache
    df_hash = str(hash(str(df.hash_rows()) if df is not None and not df.is_empty() else "empty"))
    selected_point_clean = selected_point or {}
    cache_key = _get_figure_cache_key(
        dict_kwargs, visu_type, df_hash, cutoff, selected_point_clean, theme, customizations
    )

    cached_figure, cached_data_info, cache_hit = _check_figure_cache(cache_key)
    if cache_hit:
        return cached_figure, cached_data_info

    if force_full_data:
        logger.warning(f"FORCE FULL DATA: Bypassing {cutoff:,} point sampling limit")

    # Validate and normalize visualization type
    is_clustering = visu_type.lower() in ["umap"]
    if not is_clustering and visu_type.lower() not in PLOTLY_FUNCTIONS:
        logger.warning(f"Unknown visualization type: {visu_type}, falling back to scatter")
        visu_type = "scatter"

    # Handle UMAP deferral
    if is_clustering and df is not None and not df.is_empty():
        context = "dashboard_restore" if selected_point is None else "interactive"
        if _should_defer_umap_computation(df, context):
            placeholder = _create_umap_placeholder(df, dict_kwargs, theme)
            data_info["total_data_count"] = df.height
            return placeholder, data_info

    # Apply theme template
    if not dict_kwargs.get("template"):
        dict_kwargs["template"] = _get_theme_template(theme)

    # Handle empty data
    if df is None or df.is_empty():
        logger.warning("Empty or invalid dataframe, creating empty figure")
        return _create_theme_aware_figure(dict_kwargs.get("template")), data_info

    # Clean and parse parameters
    cleaned_kwargs = _clean_figure_parameters(dict_kwargs, df, mode)
    cleaned_kwargs = _convert_style_parameters(cleaned_kwargs, df)

    # Validate required parameters
    is_valid, error_fig = _validate_required_params(
        visu_type, cleaned_kwargs, df, theme, skip_validation
    )
    if not is_valid:
        return error_fig, data_info

    # Handle hierarchical charts
    df = _handle_hierarchical_chart(visu_type, cleaned_kwargs, df)

    # Early check for valid parameters
    valid_plot_params = [
        param
        for param, value in cleaned_kwargs.items()
        if value is not None and value != "" and param != "template"
    ]
    if not valid_plot_params and not is_clustering:
        return _create_theme_aware_figure(
            dict_kwargs.get("template"),
            title=f"Select columns to create {visu_type} plot",
        ), data_info

    try:
        if is_clustering:
            figure = _render_clustering_figure(
                df, visu_type, cleaned_kwargs, cutoff, force_full_data
            )
        else:
            figure, data_info = _render_standard_figure(
                df, visu_type, cleaned_kwargs, cutoff, force_full_data, data_info
            )

        # Finalize figure
        figure = _finalize_figure(figure, cleaned_kwargs, selected_point, df)

        # Apply post-rendering customizations if provided
        if customizations:
            try:
                from depictio.dash.modules.figure_component.customizations import (
                    apply_customizations,
                )

                # Convert Polars DataFrame to Pandas for customizations that need it
                pandas_df = df.to_pandas() if df is not None and not df.is_empty() else None
                figure = apply_customizations(figure, customizations, df=pandas_df)
            except ImportError as e:
                logger.warning(f"Could not import customizations module: {e}")
            except Exception as e:
                logger.error(f"Error applying customizations: {e}", exc_info=True)

        # Cache the result
        _figure_result_cache[cache_key] = (figure, data_info, time.time())

        return figure, data_info

    except Exception as e:
        logger.error(f"Error creating figure: {e}")
        fallback_figure = _create_theme_aware_figure(
            dict_kwargs.get("template", _get_theme_template(theme)),
            title=f"Error: {str(e)}",
        )
        _figure_result_cache[cache_key] = (fallback_figure, data_info, time.time())
        return fallback_figure, data_info


def _render_clustering_figure(
    df: pl.DataFrame,
    visu_type: str,
    cleaned_kwargs: dict,
    cutoff: int,
    force_full_data: bool,
) -> Any:
    """Render a clustering visualization (e.g., UMAP)."""
    clustering_function = get_clustering_function(visu_type.lower())

    if df.height > cutoff and not force_full_data:
        sampling_cache_key = f"{id(df)}_{cutoff}_{hash(str(cleaned_kwargs))}"
        if sampling_cache_key not in _sampling_cache:
            sampled_df = df.sample(n=cutoff, seed=0).to_pandas()
            _sampling_cache[sampling_cache_key] = sampled_df
        else:
            sampled_df = _sampling_cache[sampling_cache_key]
        return clustering_function(sampled_df, **cleaned_kwargs)
    else:
        return clustering_function(df, **cleaned_kwargs)


def _render_standard_figure(
    df: pl.DataFrame,
    visu_type: str,
    cleaned_kwargs: dict,
    cutoff: int,
    force_full_data: bool,
    data_info: dict,
) -> tuple[Any, dict]:
    """Render a standard Plotly visualization."""
    import time

    plot_function = PLOTLY_FUNCTIONS[visu_type.lower()]

    # Extract manual color params for box/violin plots
    manual_color_map, manual_color_sequence = _extract_manual_color_params(
        visu_type, cleaned_kwargs
    )

    # Track data counts
    data_info["total_data_count"] = df.height

    # Apply sampling if needed
    plot_df, was_sampled = _apply_sampling(df, cutoff, cleaned_kwargs, force_full_data)
    data_info["displayed_data_count"] = plot_df.height
    data_info["was_sampled"] = was_sampled

    # Generate figure
    time.time()
    figure = plot_function(plot_df, **cleaned_kwargs)

    # Apply manual colors to box/violin plots
    figure = _apply_box_violin_colors(
        figure, visu_type, cleaned_kwargs, df, manual_color_map, manual_color_sequence
    )

    return figure, data_info


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
            len(columns)
            columns = {col for col in columns if col in df_columns}

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

        analysis = analyze_constrained_code(code_content)

        if analysis["has_preprocessing"]:
            # Extract columns from preprocessing code
            preprocessing_cols = extract_columns_from_preprocessing(
                analysis["preprocessing_code"], df_columns
            )

            if preprocessing_cols:
                columns.update(preprocessing_cols)

                # ESSENTIAL COLUMNS: Always include these for code mode
                essential_columns = [
                    "depictio_run_id",  # Required for joins and run isolation
                ]
                columns.update(essential_columns)

                # JOIN COLUMNS: CRITICAL - include all join columns for joined DCs
                if join_columns:
                    columns.update(join_columns)

                # Return early - preprocessing columns are sufficient
                result = sorted([col for col in columns if col is not None and col != ""])
                return result
            else:
                logger.warning(
                    "⚠️ CODE MODE: Failed to extract columns from preprocessing, falling back to figure params"
                )
        else:
            pass
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

    # Filter out None values and return sorted list
    result = sorted([col for col in columns if col is not None and col != ""])

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

            except Exception as e:
                logger.error(f"Failed to patch trace {i} axis {param_name}: {e}")
                continue

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
        pass
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
            - mode: Figure mode - "ui" or "code" (default: "ui")
            - code_content: Python code for code mode figures (default: "")
            - selection_enabled: Enable scatter selection filtering (default: False)
            - selection_column: Column to extract from selected points (default: None)
            - customization_ui_state: Customization UI state for view mode controls

    Returns:
        Figure component as HTML div with skeleton loader
    """
    # Extract essential parameters
    index = kwargs.get("index")
    visu_type = kwargs.get("visu_type", "scatter")
    dict_kwargs = kwargs.get("dict_kwargs", {})
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    kwargs.get("theme", "light")
    mode = kwargs.get("mode", "ui")
    code_content = kwargs.get("code_content", "")
    # Selection filtering configuration
    selection_enabled = kwargs.get("selection_enabled", False)
    selection_column = kwargs.get("selection_column")
    customization_ui_state = kwargs.get("customization_ui_state")

    # Defensive handling: ensure dict_kwargs is always a dict
    if not isinstance(dict_kwargs, dict):
        logger.warning(f"Expected dict for dict_kwargs, got {type(dict_kwargs)}: {dict_kwargs}")
        dict_kwargs = {}

    # CRITICAL DEBUG: Log kwargs for code mode figures
    if mode == "code":
        pass
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
        "mode": mode,
        "code_content": code_content,
        "selection_enabled": selection_enabled,
        "selection_column": selection_column,
        "customizations": kwargs.get("customizations"),  # CRITICAL: Pass through for view mode
        "customization_ui_state": kwargs.get("customization_ui_state"),  # For view mode controls
        "last_updated": datetime.now().isoformat(),
    }

    # Create graph component
    graph_component = dcc.Graph(
        id={"type": "figure-graph", "index": index},
        figure={},  # Empty - populated by batch rendering callback
        config={"displayModeBar": "hover", "responsive": True},
        style={"height": "100%", "width": "100%"},
    )

    # Wrap with view controls if customization UI state exists
    if customization_ui_state:
        from .view_controls import wrap_figure_with_controls

        # Use default axis ranges (will be updated by callbacks after figure renders)
        default_axis_ranges = {"x": (0, 100), "y": (0, 100)}
        graph_component = wrap_figure_with_controls(
            graph_component, index, customization_ui_state, default_axis_ranges
        )

    # Phase 1: Simple structure - Trigger store + Skeleton + Graph + Metadata store + Fullscreen button
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
                    "mode": mode,
                    "code_content": code_content,
                    "selection_enabled": selection_enabled,
                    "selection_column": selection_column,
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
            # Graph (possibly wrapped with view controls)
            graph_component,
        ],
        style={
            "height": "100%",
            "width": "100%",
            "display": "flex",
            "flexDirection": "column",
            "position": "relative",  # Required for fullscreen button positioning
        },
    )


def design_figure(
    id, component_data=None, workflow_id=None, data_collection_id=None, local_data=None
):
    """Design figure component - RESTORED from frontend_legacy.py.

    This is the complete working implementation with proper layout, mode toggle, and all features.
    """
    # Get all available visualizations - import from definitions to get VisualizationDefinition objects
    from .definitions import get_available_visualizations as get_viz_definitions
    from .models import VisualizationGroup

    all_vizs = get_viz_definitions()

    # Group visualizations by their group
    grouped_vizs = {}
    for viz in all_vizs:
        group = viz.group
        if group not in grouped_vizs:
            grouped_vizs[group] = []
        grouped_vizs[group].append(viz)

    # Define group order and labels (Geographic and Specialized hidden from dropdown display)
    group_info = {
        VisualizationGroup.CORE: {"label": "Core", "order": 1},
        VisualizationGroup.ADVANCED: {"label": "Advanced", "order": 2},
        VisualizationGroup.THREE_D: {"label": "3D", "order": 3},
        VisualizationGroup.CLUSTERING: {"label": "Clustering", "order": 4},
    }

    # Create flat options ordered by group (DMC Select doesn't support true groups)
    viz_options = []
    for group in sorted(grouped_vizs.keys(), key=lambda g: group_info.get(g, {}).get("order", 99)):
        if group in grouped_vizs and grouped_vizs[group] and group in group_info:
            # Add group header as disabled option
            group_label = group_info.get(group, {"label": group.title()})["label"]
            viz_options.append(
                {
                    "label": f"─── {group_label} ───",
                    "value": f"__group__{group}",
                    "disabled": True,
                }
            )

            # Add visualizations in this group
            for viz in sorted(grouped_vizs[group], key=lambda x: x.label):
                viz_options.append({"label": f"  {viz.label}", "value": viz.name.lower()})

            # Add separator except for last group
            if (
                group
                != list(
                    sorted(
                        grouped_vizs.keys(), key=lambda g: group_info.get(g, {}).get("order", 99)
                    )
                )[-1]
            ):
                viz_options.append(
                    {"label": "", "value": f"__separator__{group}", "disabled": True}
                )

    # Default to scatter if no component data
    default_value = "scatter"
    if component_data and "visu_type" in component_data:
        default_value = component_data["visu_type"].lower()

    # Set initial mode based on component_data mode field only
    initial_mode = "ui"  # Default to UI mode
    if component_data and component_data.get("mode") == "code":
        initial_mode = "code"
    else:
        pass
    # Extract index handling dict pattern-matching IDs
    if isinstance(id, dict):
        actual_index = id.get("index", id)
    else:
        actual_index = id

    # Create layout optimized for fullscreen modal
    figure_row = [
        # Mode toggle (central and prominent) - UI and Code modes only
        dmc.Center(
            [
                dmc.SegmentedControl(
                    id={"type": "figure-mode-toggle", "index": actual_index},
                    data=[
                        {
                            "value": "ui",
                            "label": dmc.Center(
                                [
                                    DashIconify(icon="tabler:eye", width=16),
                                    html.Span("UI Mode"),
                                ],
                                style={
                                    "gap": 10,
                                    "width": "250px",
                                },
                            ),
                        },
                        {
                            "value": "code",
                            "label": dmc.Center(
                                [
                                    DashIconify(icon="tabler:code", width=16),
                                    html.Span("Code Mode (Beta)"),
                                ],
                                style={
                                    "gap": 10,
                                    "width": "250px",
                                },
                            ),
                        },
                    ],
                    value=initial_mode,
                    size="lg",
                    style={"marginBottom": "15px"},
                )
            ]
        ),
        # UI mode header - now empty since controls moved to right column
        html.Div(
            id={"type": "ui-mode-header", "index": actual_index},
            style={"display": "block", "height": "0px"},
        ),
        # Main content area - side-by-side layout
        html.Div(
            id={"type": "main-content-area", "index": actual_index},
            children=[
                # Left side - Figure preview container with graph
                html.Div(
                    [
                        build_figure_frame(
                            index=actual_index,
                            children=[
                                # Loading indicator wrapping the preview graph
                                dcc.Loading(
                                    id={"type": "figure-preview-loading", "index": actual_index},
                                    type="default",  # Options: "default", "circle", "dot", "cube"
                                    color="var(--mantine-primary-color-filled)",
                                    children=[
                                        # UI Mode Preview graph - populated by render callback
                                        dcc.Graph(
                                            id={
                                                "type": "figure-design-preview",
                                                "index": actual_index,
                                            },
                                            figure={},  # Empty - populated by render callback
                                            config={"displayModeBar": "hover", "responsive": True},
                                            style={"height": "100%", "width": "100%"},
                                        ),
                                        # Code Mode Preview graph - populated by execute callback
                                        dcc.Graph(
                                            id={
                                                "type": "code-mode-preview-graph",
                                                "index": actual_index,
                                            },
                                            figure={},  # Empty - populated by execute callback
                                            config={"displayModeBar": "hover", "responsive": True},
                                            style={
                                                "height": "100%",
                                                "width": "100%",
                                                "display": "none",
                                            },
                                        ),
                                    ],
                                )
                            ],
                        )
                    ],
                    id={
                        "type": "component-container",
                        "index": actual_index,
                    },
                    style={
                        "width": "60%",
                        "height": "100%",
                        "display": "inline-block",
                        "verticalAlign": "top",
                        "marginRight": "2%",
                        "minHeight": "400px",
                        "border": "1px solid #eee",
                    },
                ),
                # Right side - Mode-specific controls
                html.Div(
                    children=[
                        # UI Mode Layout (default) - simple controls
                        html.Div(
                            [
                                html.Div(
                                    [
                                        # Visualization and Edit button row
                                        html.Div(
                                            [
                                                # Visualization section (full width)
                                                html.Div(
                                                    [
                                                        dmc.Group(
                                                            [
                                                                DashIconify(
                                                                    icon="mdi:chart-line",
                                                                    width=18,
                                                                    height=18,
                                                                ),
                                                                dmc.Text(
                                                                    "Visualization Type:",
                                                                    fw="bold",
                                                                    size="md",
                                                                    style={"fontSize": "16px"},
                                                                ),
                                                            ],
                                                            gap="xs",
                                                            align="center",
                                                            style={"marginBottom": "10px"},
                                                        ),
                                                        dmc.Select(
                                                            data=viz_options,
                                                            value=default_value,
                                                            id={
                                                                "type": "segmented-control-visu-graph",
                                                                "index": actual_index,
                                                            },
                                                            placeholder="Choose visualization type...",
                                                            clearable=False,
                                                            searchable=True,
                                                            size="md",
                                                            style={
                                                                "width": "100%",
                                                                "fontSize": "14px",
                                                            },
                                                            # TEMPORARILY REMOVED: renderOption will be added back in step 3
                                                            # renderOption={
                                                            #     "function": "renderVisualizationOption"
                                                            # },
                                                        ),
                                                    ],
                                                    style={
                                                        "width": "100%",
                                                    },
                                                ),
                                            ],
                                            style={"marginBottom": "20px"},
                                        ),
                                        # Hidden edit button for callback compatibility
                                        html.Div(
                                            dmc.Button(
                                                "Edit",
                                                id={
                                                    "type": "edit-button",
                                                    "index": actual_index,
                                                },
                                                n_clicks=1,  # Start clicked to show parameters
                                                style={"display": "none"},
                                            )
                                        ),
                                        # Edit panel (always open)
                                        dmc.Collapse(
                                            id={
                                                "type": "collapse",
                                                "index": actual_index,
                                            },
                                            opened=True,
                                            style={
                                                "overflowY": "auto",
                                            },
                                        ),
                                    ],
                                    style={"padding": "20px"},
                                ),
                            ],
                            id={"type": "ui-mode-content", "index": actual_index},
                            style={"display": "block"},
                        ),
                        # Code Mode Layout (hidden by default)
                        html.Div(
                            [
                                html.Div(
                                    id={"type": "code-mode-interface", "index": actual_index},
                                    style={
                                        "width": "100%",
                                        "height": "100%",
                                        "minHeight": "400px",
                                    },
                                ),
                            ],
                            id={"type": "code-mode-content", "index": actual_index},
                            style={"display": "none"},
                        ),
                    ],
                    style={
                        "width": "38%",
                        "display": "inline-block",
                        "verticalAlign": "top",
                        "height": "100%",
                        "minHeight": "400px",
                    },
                ),
            ],
            style={"width": "100%", "marginTop": "10px"},
        ),
        # Store components
        dcc.Store(
            id={"type": "dict_kwargs", "index": actual_index},
            data={},
            storage_type="memory",
        ),
        # Parameter trigger store - updated when any parameter changes
        dcc.Store(
            id={"type": "param-trigger", "index": actual_index},
            data={"timestamp": 0},
            storage_type="memory",
        ),
        dcc.Store(
            id={"type": "stored-metadata-component", "index": actual_index},
            data={
                "index": actual_index.replace("-tmp", ""),
                "component_type": "figure",
                "dict_kwargs": component_data.get("dict_kwargs", {}) if component_data else {},
                "visu_type": component_data.get("visu_type", "scatter")
                if component_data
                else "scatter",
                "wf_id": component_data.get("wf_id") if component_data else workflow_id,
                "dc_id": component_data.get("dc_id") if component_data else data_collection_id,
                "mode": component_data.get("mode", "ui") if component_data else "ui",
                "code_content": component_data.get("code_content", "") if component_data else "",
                "last_updated": component_data.get("last_updated") if component_data else None,
                "parent_index": component_data.get("parent_index") if component_data else None,
            },
            storage_type="memory",
        ),
        # Mode management stores
        dcc.Store(
            id={"type": "figure-mode-store", "index": actual_index},
            data=initial_mode,
            storage_type="memory",
        ),
        dcc.Store(
            id={"type": "code-content-store", "index": actual_index},
            data=component_data.get("code_content", "") if component_data else "",
            storage_type="memory",
        ),
        dcc.Store(
            id={"type": "code-generated-figure", "index": actual_index},
            data=None,
            storage_type="memory",
        ),
        # Hidden stores for scroll position preservation
        dcc.Store(
            id={"type": "scroll-store", "index": actual_index},
            data={},
            storage_type="memory",
        ),
        dcc.Store(
            id={"type": "scroll-restore", "index": actual_index},
            data={},
            storage_type="memory",
        ),
    ]

    return figure_row


def build_figure_design_ui(**kwargs) -> html.Div:
    """Build figure design UI for add/edit mode (simplified, no custom JS).

    This creates a simple parameter input form for creating or editing figures.
    Used in the stepper or edit page to provide a UI for configuring figure parameters.

    Args:
        **kwargs: Configuration parameters
            - index: Component index (required)
            - visu_type: Current visualization type (default: "scatter")
            - dict_kwargs: Current parameters (default: {})
            - wf_id: Workflow ID
            - dc_id: Data collection ID
            - columns: Available columns (required for parameter inputs)

    Returns:
        HTML div with design UI (viz selector + parameter inputs + preview + save button)
    """
    from depictio.dash.modules.figure_component.definitions import get_visualization_registry

    index = kwargs.get("index")
    visu_type = kwargs.get("visu_type", "scatter")
    dict_kwargs = kwargs.get("dict_kwargs", {})
    columns = kwargs.get("columns", [])

    if not columns:
        logger.warning(f"No columns provided for figure {index} design UI")
        return html.Div(
            dmc.Alert(
                "No columns available. Please select a data collection first.",
                title="Missing Data",
                color="red",
            )
        )

    # Build visualization type selector (simple, no custom JS)
    viz_defs = get_visualization_registry()
    viz_options = [{"label": viz_def.label, "value": key} for key, viz_def in viz_defs.items()]

    viz_selector = dmc.Stack(
        [
            dmc.Text("Visualization Type", size="sm", fw="bold"),
            dmc.Select(
                id={"type": "figure-visu-type-selector", "index": index},
                data=viz_options,
                value=visu_type,
                placeholder="Choose visualization type...",
                clearable=False,
                searchable=True,
                size="md",
                style={"width": "100%"},
            ),
        ],
        gap="xs",
    )

    # Get parameters for current visu type
    viz_def = viz_defs.get(visu_type, viz_defs["scatter"])
    # Extract parameter names from ParameterDefinition objects
    params = [p.name for p in viz_def.parameters]

    # Map param names to inputs (simplified - just common params for now)
    param_inputs = []

    common_params = {
        "x": {"label": "X Axis", "type": "column"},
        "y": {"label": "Y Axis", "type": "column"},
        "color": {"label": "Color", "type": "column"},
        "size": {"label": "Size", "type": "column"},
        "title": {"label": "Title", "type": "text"},
        "opacity": {"label": "Opacity", "type": "number"},
        "hover_name": {"label": "Hover Name", "type": "column"},
        "hover_data": {"label": "Hover Data", "type": "multiselect"},
        "labels": {"label": "Labels (JSON)", "type": "text"},
    }

    for param_name in params:
        if param_name in common_params:
            param_info = common_params[param_name]
            current_value = dict_kwargs.get(param_name)

            # Build appropriate input based on type
            if param_info["type"] == "column":
                input_component = dmc.Select(
                    id={"type": f"param-{param_name}", "index": index},
                    data=[{"label": col, "value": col} for col in columns],
                    value=current_value,
                    placeholder=f"Select {param_info['label'].lower()}...",
                    clearable=True,
                    searchable=True,
                    size="sm",
                )
            elif param_info["type"] == "multiselect":
                input_component = dmc.MultiSelect(
                    id={"type": f"param-{param_name}", "index": index},
                    data=[{"label": col, "value": col} for col in columns],
                    value=current_value or [],
                    placeholder=f"Select {param_info['label'].lower()}...",
                    clearable=True,
                    searchable=True,
                    size="sm",
                )
            elif param_info["type"] == "text":
                input_component = dmc.TextInput(
                    id={"type": f"param-{param_name}", "index": index},
                    value=current_value or "",
                    placeholder=f"Enter {param_info['label'].lower()}...",
                    size="sm",
                )
            elif param_info["type"] == "number":
                input_component = dmc.NumberInput(
                    id={"type": f"param-{param_name}", "index": index},
                    value=current_value,
                    placeholder="0.0 - 1.0",
                    min=0,
                    max=1,
                    step=0.1,
                    size="sm",
                )
            else:
                continue

            param_inputs.append(
                dmc.Stack(
                    [dmc.Text(param_info["label"], size="sm", fw="normal"), input_component],
                    gap="xs",
                )
            )

    # Parameters section
    params_section = dmc.Stack(
        [dmc.Text("Parameters", size="sm", fw="bold")] + param_inputs, gap="sm"
    )

    # Preview section (will be populated by callback)
    preview_section = dmc.Stack(
        [
            dmc.Text("Preview", size="sm", fw="bold"),
            dmc.Paper(
                id={"type": "figure-design-preview", "index": index},
                children=[
                    html.Div(
                        dmc.Text("Configure parameters to see preview", c="gray", ta="center"),
                        style={"padding": "40px"},
                    )
                ],
                withBorder=True,
                radius="md",
                style={"minHeight": "300px"},
            ),
        ],
        gap="xs",
    )

    # Save button
    save_button = dmc.Button(
        "Save Figure",
        id={"type": "btn-save-edit-figure", "index": index},
        color="blue",
        size="md",
        fullWidth=True,
        leftSection=DashIconify(icon="mdi:content-save", width=20),
    )

    # Complete design UI
    return html.Div(
        dmc.Stack(
            [viz_selector, params_section, preview_section, save_button],
            gap="md",
            style={"padding": "20px"},
        ),
        id={"type": "figure-design-container", "index": index},
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


def create_stepper_figure_button(n: int, disabled: bool | None = None) -> tuple:
    """Create the stepper figure button and associated store.

    Creates the button used in the component type selection step of the stepper
    to add a figure component to the dashboard.

    Args:
        n: Button index for unique identification.
        disabled: Override enabled state. If None, uses component metadata.

    Returns:
        Tuple containing (button, store) components.
    """
    from depictio.dash.component_metadata import (
        get_component_color,
        get_dmc_button_color,
        is_enabled,
    )
    from depictio.dash.utils import UNSELECTED_STYLE

    if disabled is None:
        disabled = not is_enabled("figure")

    dmc_color = get_dmc_button_color("figure")
    hex_color = get_component_color("figure")

    button = dmc.Button(
        "Figure",
        id={
            "type": "btn-option",
            "index": n,
            "value": "Figure",
        },
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=dmc_color,
        leftSection=DashIconify(icon="mdi:graph-box", color=hex_color),
        disabled=disabled,
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

    # Call the synchronous build_figure function
    result = build_figure(**kwargs)

    return result


# Legacy exports for backward compatibility
# These will be removed in future versions
def get_available_visualizations():
    """Get available visualization types."""
    return list(PLOTLY_FUNCTIONS.keys())


def get_visualization_options():
    """Get visualization options for UI."""
    return [{"label": name.title(), "value": name} for name in PLOTLY_FUNCTIONS.keys()]
