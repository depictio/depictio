import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import plotly.express as px
import polars as pl
from bson import ObjectId
from dash_iconify import DashIconify

from dash import dcc, html

# PERFORMANCE OPTIMIZATION: Use centralized config
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite

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
    # Use actual available Plotly templates
    return "mantine_dark" if theme == "dark" else "mantine_light"


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
            # Basic fallbacks for common visualization types
            if visu_type.lower() in ["histogram", "box", "violin"]:
                required_params = ["x"] if visu_type.lower() == "histogram" else ["y"]
            elif visu_type.lower() in ["pie", "sunburst", "treemap"]:
                required_params = ["values"]
            elif visu_type.lower() in ["timeline"]:
                required_params = ["x_start"]
            elif visu_type.lower() in ["umap"]:
                # Clustering visualizations don't have required parameters
                # They can work without explicit parameters (will use all numeric columns)
                required_params = []
            else:
                required_params = ["x", "y"]  # Default for most plots

        return required_params

    except Exception:
        # Fallback if visualization definition not found
        if visu_type.lower() in ["umap"]:
            return []  # Clustering visualizations don't require specific parameters
        return ["x", "y"]


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


def _clean_figure_cache():
    """Remove expired entries from figure cache."""
    import time

    current_time = time.time()
    expired_keys = [
        key
        for key, (_, timestamp) in _figure_result_cache.items()
        if current_time - timestamp > FIGURE_CACHE_TTL
    ]
    for key in expired_keys:
        del _figure_result_cache[key]

    # If cache is still too large, remove oldest entries
    if len(_figure_result_cache) > FIGURE_CACHE_MAX_SIZE:
        # Sort by timestamp and remove oldest entries
        sorted_items = sorted(_figure_result_cache.items(), key=lambda x: x[1][1])
        excess_count = len(_figure_result_cache) - FIGURE_CACHE_MAX_SIZE
        for key, _ in sorted_items[:excess_count]:
            del _figure_result_cache[key]


def render_figure(
    dict_kwargs: Dict[str, Any],
    visu_type: str,
    df: pl.DataFrame,
    cutoff: int = 100000,
    selected_point: Optional[Dict] = None,
    theme: str = "light",
) -> Any:
    """Render a Plotly figure with robust parameter handling and result caching.

    Args:
        dict_kwargs: Figure parameters
        visu_type: Visualization type
        df: Data as Polars DataFrame
        cutoff: Maximum data points before sampling
        selected_point: Point to highlight
        theme: Theme ('light' or 'dark')

    Returns:
        Plotly figure object
    """
    # PERFORMANCE OPTIMIZATION: Check figure result cache first

    # Generate cache key from all inputs
    df_hash = str(hash(str(df.hash_rows()) if not df.is_empty() else "empty"))
    selected_point_clean = selected_point or {}

    cache_key = _get_figure_cache_key(
        dict_kwargs, visu_type, df_hash, cutoff, selected_point_clean, theme
    )

    # TEMPORARY: Disable figure cache to test async rendering performance
    logger.info(f"🚧 CACHE DISABLED: Generating fresh {visu_type} figure for performance testing")

    # Clean cache and check for existing result
    # _clean_figure_cache()
    # if cache_key in _figure_result_cache:
    #     cached_figure, timestamp = _figure_result_cache[cache_key]
    #     logger.info(
    #         f"🚀 FIGURE CACHE HIT: Using cached figure for {visu_type} (saved {int((time.time() - timestamp) * 1000)}ms ago)"
    #     )
    #     return cached_figure

    # logger.info(f"📊 FIGURE CACHE MISS: Generating new {visu_type} figure")

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
            return _create_umap_placeholder(df, dict_kwargs, theme)

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
    logger.info(f"Theme: {theme}")
    logger.info(f"Template: {dict_kwargs.get('template')}")
    logger.info(f"Data shape: {df.shape if df is not None else 'None'}")
    logger.info(f"Selected point: {selected_point is not None}")
    logger.info(f"Parameters: {list(dict_kwargs.keys())}")
    logger.info(f"Full dict_kwargs: {dict_kwargs}")  # Show full parameters for debugging
    logger.info(
        f"Boolean parameters in dict_kwargs: {[(k, v, type(v)) for k, v in dict_kwargs.items() if isinstance(v, bool)]}"
    )
    # logger.info(f"Available columns in df: {df.columns if df is not None else 'None'}")  # Reduced logging

    # Handle empty or invalid data
    if df is None or df.is_empty():
        logger.warning("Empty or invalid dataframe, creating empty figure")
        return px.scatter(template=dict_kwargs.get("template", _get_theme_template(theme)))

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

    # PERFORMANCE OPTIMIZATION: Reduce verbose logging in production
    logger.debug("=== CLEANED PARAMETERS DEBUG ===")
    logger.debug(f"Original dict_kwargs: {dict_kwargs}")
    logger.debug(f"Cleaned kwargs: {cleaned_kwargs}")
    logger.debug(
        f"Boolean parameters in cleaned_kwargs: {[(k, v, type(v)) for k, v in cleaned_kwargs.items() if isinstance(v, bool)]}"
    )

    # Check if required parameters are missing for the visualization type
    required_params = _get_required_parameters(visu_type.lower())
    missing_params = [param for param in required_params if param not in cleaned_kwargs]

    if missing_params:
        logger.warning(
            f"Missing required parameters for {visu_type}: {missing_params}. Available columns: {df.columns}"
        )
        # Create a fallback figure with helpful message
        title = f"Please select {', '.join(missing_params).upper()} column(s) to create {visu_type} plot"
        return px.scatter(
            template=dict_kwargs.get("template", _get_theme_template(theme)), title=title
        )

    # Special handling for hierarchical charts (sunburst, treemap)
    if visu_type.lower() in ["sunburst", "treemap"]:
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

    try:
        if is_clustering:
            # Handle clustering visualizations (e.g., UMAP)
            clustering_function = get_clustering_function(visu_type.lower())

            # Handle large datasets with sampling for clustering
            if df.height > cutoff:
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
                pandas_df = df.to_pandas()
                figure = clustering_function(pandas_df, **cleaned_kwargs)
        else:
            # Handle standard Plotly visualizations
            plot_function = PLOTLY_FUNCTIONS[visu_type.lower()]

            # Handle large datasets with sampling
            if df.height > cutoff:
                cache_key = f"{id(df)}_{cutoff}_{hash(str(cleaned_kwargs))}"

                if cache_key not in _sampling_cache:
                    sampled_df = df.sample(n=cutoff, seed=0).to_pandas()
                    _sampling_cache[cache_key] = sampled_df
                    logger.info(f"Cached sampled data: {cutoff} points from {df.height}")
                else:
                    sampled_df = _sampling_cache[cache_key]
                    logger.info(f"Using cached sampled data: {cutoff} points")

                logger.info("=== CALLING PLOTLY FUNCTION ===")
                logger.info(f"Function: {plot_function.__name__}")
                logger.info(f"Parameters: {cleaned_kwargs}")
                logger.info(
                    f"Boolean params: {[(k, v) for k, v in cleaned_kwargs.items() if isinstance(v, bool)]}"
                )
                figure = plot_function(sampled_df, **cleaned_kwargs)
            else:
                # Use full dataset
                pandas_df = df.to_pandas()
                logger.info("=== CALLING PLOTLY FUNCTION ===")
                logger.info(f"Function: {plot_function.__name__}")
                logger.info(f"Parameters: {cleaned_kwargs}")
                logger.info(
                    f"Boolean params: {[(k, v) for k, v in cleaned_kwargs.items() if isinstance(v, bool)]}"
                )
                figure = plot_function(pandas_df, **cleaned_kwargs)

        # Apply responsive sizing - FORCE for vertical growing
        figure.update_layout(
            autosize=True,
            margin=dict(l=40, r=40, t=40, b=40),
            height=None,  # Let container control height
        )

        # Highlight selected point if provided
        if selected_point and "x" in cleaned_kwargs and "y" in cleaned_kwargs:
            _highlight_selected_point(figure, df, cleaned_kwargs, selected_point)

        # TEMPORARY: Disable figure cache writing for performance testing
        # _figure_result_cache[cache_key] = (figure, time.time())
        logger.info(f"🚧 CACHE DISABLED: Skipping figure cache storage for {visu_type}")

        return figure

    except Exception as e:
        logger.error(f"Error creating figure: {e}")
        # Return fallback figure
        fallback_figure = px.scatter(
            template=dict_kwargs.get("template", _get_theme_template(theme)),
            title=f"Error: {str(e)}",
        )

        # TEMPORARY: Disable fallback figure cache writing for performance testing
        # _figure_result_cache[cache_key] = (fallback_figure, time.time())
        logger.info("🚧 CACHE DISABLED: Skipping fallback figure cache storage")

        return fallback_figure


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
    # Use standard Plotly templates for better compatibility
    template = "plotly_dark" if theme == "dark" else "plotly"

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
    """Build figure component with robust parameter handling.

    Args:
        **kwargs: Figure configuration parameters

    Returns:
        Figure component as HTML div
    """
    # DUPLICATION TRACKING: Enhanced logging to find source of duplicate builds
    import inspect
    import traceback

    caller_info = "UNKNOWN"
    try:
        # Get the calling function details
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_frame = frame.f_back
            caller_info = f"{caller_frame.f_code.co_filename}:{caller_frame.f_lineno} in {caller_frame.f_code.co_name}()"
    except Exception:
        pass

    logger.info("=" * 60)
    logger.info("🔍 BUILD FIGURE CALLED - DUPLICATION TRACKING")
    logger.info(f"📍 CALLER: {caller_info}")
    logger.info(f"🏷️  INDEX: {kwargs.get('index', 'UNKNOWN')}")
    logger.info(f"🎯 STEPPER: {kwargs.get('stepper', False)}")
    logger.info(f"🔧 BUILD_FRAME: {kwargs.get('build_frame', False)}")
    logger.info(f"👤 PARENT_INDEX: {kwargs.get('parent_index', 'NONE')}")

    # Check for bulk data availability
    if "_bulk_component_data" in kwargs:
        logger.info("✅ BULK DATA: Pre-fetched data available")
    else:
        logger.warning("⚠️ NO BULK DATA: Will fetch individually - potential performance hit")

    # Print condensed call stack to see the path
    logger.info("📚 CALL STACK (condensed):")
    stack = traceback.extract_stack()
    for i, frame in enumerate(stack[-5:-1]):  # Last 4 frames before this one
        logger.info(f"   {i + 1}. {frame.filename.split('/')[-1]}:{frame.lineno} in {frame.name}()")
    logger.info("=" * 60)

    index = kwargs.get("index")
    dict_kwargs = kwargs.get("dict_kwargs", {})

    # Defensive handling: ensure dict_kwargs is always a dict
    if not isinstance(dict_kwargs, dict):
        logger.warning(f"Expected dict for dict_kwargs, got {type(dict_kwargs)}: {dict_kwargs}")
        dict_kwargs = {}

    logger.info(f"INDEX: {index}")
    logger.info(f"DICT_KWARGS RECEIVED: {dict_kwargs}")
    logger.info(f"DICT_KWARGS TYPE: {type(dict_kwargs)}")
    logger.info(f"DICT_KWARGS EMPTY: {not dict_kwargs}")
    visu_type = kwargs.get("visu_type", "scatter")
    wf_id = kwargs.get("wf_id")
    dc_id = kwargs.get("dc_id")
    dc_config = kwargs.get("dc_config")
    build_frame = kwargs.get("build_frame", False)
    stepper = kwargs.get("stepper", False)
    parent_index = kwargs.get("parent_index", None)
    df = kwargs.get("df", pl.DataFrame())
    TOKEN = kwargs.get("access_token")
    filter_applied = kwargs.get("filter_applied", False)
    theme = kwargs.get("theme", "light")

    # Handle stepper mode index properly for stored-metadata-component
    # For stepper mode, use the temporary index to avoid conflicts with existing components
    # For normal mode, use the original index (remove -tmp suffix if present)
    if stepper:
        store_index = index  # Use the temporary index with -tmp suffix
        data_index = index.replace("-tmp", "") if index else "unknown"  # Clean index for data
    else:
        store_index = index.replace("-tmp", "") if index else "unknown"

    logger.info(f"Building figure component {index}")
    logger.info(
        f"Stepper mode: {stepper}, store_index: {store_index}, data_index: {data_index if stepper else store_index}"
    )
    logger.info(f"Visualization type: {visu_type}")
    logger.info(f"Theme: {theme}")

    # Log the exact format that will be used for target_components
    if not stepper and build_frame:
        target_id_format = f'{{"index":"{index}","type":"graph"}}'
        logger.info(f"🎯 target_components will use: {target_id_format}")
        logger.info(f'📍 Graph component ID will be: {{"type":"graph","index":"{index}"}}')

    # Clean the component index
    store_index = index.replace("-tmp", "") if index else "unknown"

    # Create component metadata
    store_component_data = {
        "index": str(store_index),
        "component_type": "figure",
        "dict_kwargs": dict_kwargs,
        "visu_type": visu_type,
        "wf_id": wf_id,
        "dc_id": dc_id,
        "dc_config": dc_config,
        "parent_index": parent_index,
        "filter_applied": filter_applied,
        "last_updated": datetime.now().isoformat(),
    }
    logger.info(f"Component metadata: {store_component_data}")

    # Ensure dc_config is available for build_figure
    if not dc_config and wf_id and dc_id:
        # PERFORMANCE OPTIMIZATION: Check bulk data first to avoid individual API calls
        bulk_component_data = kwargs.get("_bulk_component_data")
        if bulk_component_data and "dc_config" in bulk_component_data:
            logger.info(f"✅ BULK DATA: Using pre-fetched dc_config for figure {index}")
            dc_config = bulk_component_data["dc_config"]
            store_component_data["dc_config"] = dc_config
        else:
            logger.warning(
                f"⚠️ INDIVIDUAL FETCH: dc_config missing for figure {index}, fetching from API"
            )
            try:
                import httpx

                from depictio.api.v1.configs.config import API_BASE_URL

                headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
                # Handle joined data collection IDs
                if isinstance(dc_id, str) and "--" in dc_id:
                    # For joined data collections, create synthetic specs
                    dc_specs = {
                        "config": {"type": "table", "metatype": "joined"},
                        "data_collection_tag": f"Joined data collection ({dc_id})",
                        "description": "Virtual joined data collection",
                        "_id": dc_id,
                    }
                else:
                    # Regular data collection - fetch from API
                    dc_specs = httpx.get(
                        f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
                        headers=headers,
                    ).json()
                dc_config = dc_specs.get("config", {})
                store_component_data["dc_config"] = dc_config
                logger.info(f"📡 INDIVIDUAL SUCCESS: Fetched dc_config for figure {index}")
            except Exception as e:
                logger.error(
                    f"❌ INDIVIDUAL FAILED: Failed to fetch dc_config for figure {index}: {e}"
                )
                dc_config = {}

    # Validate and clean parameters
    validated_kwargs = validate_parameters(visu_type, dict_kwargs)

    # Handle data loading
    if df.is_empty() and kwargs.get("refresh", True):
        if wf_id and dc_id:
            logger.info(f"Loading data for {wf_id}:{dc_id}")
            try:
                # Handle joined data collection IDs - don't convert to ObjectId
                if isinstance(dc_id, str) and "--" in dc_id:
                    # For joined data collections, pass the DC ID as string
                    df = load_deltatable_lite(ObjectId(wf_id), dc_id, TOKEN=TOKEN)
                else:
                    # Regular data collection - convert to ObjectId
                    df = load_deltatable_lite(ObjectId(wf_id), ObjectId(dc_id), TOKEN=TOKEN)
            except Exception as e:
                logger.error(f"Failed to load data: {e}")
                df = pl.DataFrame()
        else:
            logger.warning(f"Missing workflow_id ({wf_id}) or data_collection_id ({dc_id})")

    # Create the figure
    logger.info("CALLING render_figure WITH:")
    logger.info(f"  validated_kwargs: {validated_kwargs}")
    logger.info(f"  visu_type: {visu_type}")
    logger.info(f"  df shape: {df.shape if df is not None else 'None'}")
    logger.info(f"  theme: {theme}")

    try:
        figure = render_figure(validated_kwargs, visu_type, df, theme=theme)
        logger.info(f"render_figure SUCCESS: figure type = {type(figure)}")
    except Exception as e:
        logger.error(f"Failed to render figure: {e}")
        figure = px.scatter(title=f"Error: {str(e)}")

    # Create info badges
    badges = _create_info_badges(index or "unknown", df, visu_type, filter_applied, build_frame)

    # Create figure component
    figure_div = html.Div(
        [
            badges,
            dcc.Graph(
                figure=figure,
                id={"type": "graph", "index": index},
                config={
                    "editable": True,
                    "scrollZoom": True,
                    "responsive": True,
                    "displayModeBar": True,
                },
                className="responsive-graph",  # Add responsive graph class for vertical growing
                # style={
                #     "width": "100%",
                #     "height": "100%",  # FIXED: Use full height for vertical growing
                #     "flex": "1",  # Critical for vertical growing
                #     "backgroundColor": "transparent",  # Fix white background issue
                #     # "minHeight": "200px",  # Minimum height for usability
                # },
            ),
            dcc.Store(
                data=store_component_data,
                id={"type": "stored-metadata-component", "index": store_index},
            ),
        ],
        # style={
        #     "width": "100%",
        #     "height": "100%",
        #     "flex": "1",  # Critical for vertical growing
        #     "display": "flex",
        #     "flexDirection": "column",
        #     # "minHeight": "200px",  # Reduce from 400px for better flexibility
        #     "backgroundColor": "transparent",
        # },
    )

    if not build_frame:
        return figure_div
    else:
        # For figure components, we don't create a new frame here because one already exists
        # from the design phase. Instead, we return the content that will populate the existing frame.
        # This prevents duplicate figure-body component IDs.

        # For stepper mode with loading
        if not stepper:
            # Build the figure component with frame
            figure_component = build_figure_frame(index=index, children=figure_div)

            # Add targeted loading for the graph component specifically
            from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
                create_skeleton_component,
            )

            # Use Dash's stringify_id function to generate exact target format
            graph_id_dict = {"type": "graph", "index": index}
            target_id = stringify_id(graph_id_dict)

            logger.info(f"🎯 Using stringify_id for target_components: {target_id}")

            # PERFORMANCE OPTIMIZATION: Conditional loading spinner
            if settings.performance.disable_loading_spinners:
                logger.info("🚀 PERFORMANCE MODE: Loading spinners disabled")
                return figure_component  # Return content directly, no loading wrapper
            else:
                # Optimized loading with fast delays
                return dcc.Loading(
                    children=figure_component,
                    custom_spinner=create_skeleton_component("figure"),
                    target_components={target_id: "figure"},
                    delay_show=5,  # Fast delay for better UX
                    delay_hide=25,  # Quick hide for performance
                    id={"type": "figure-loading", "index": index},
                )
        else:
            return figure_div  # Return content directly for stepper mode


def _create_info_badges(
    index: str, df: pl.DataFrame, visu_type: str, filter_applied: bool, build_frame: bool
) -> html.Div:
    """Create informational badges for the figure."""
    if not build_frame:
        return html.Div()

    badges = []
    cutoff = _config.max_data_points

    # Partial data badge
    if visu_type.lower() == "scatter" and not df.is_empty() and df.shape[0] > cutoff:
        partial_badge = dmc.Tooltip(
            children=dmc.Badge(
                "Partial data displayed",
                id={"type": "graph-partial-data-displayed", "index": index},
                leftSection=DashIconify(icon="mdi:alert-circle", width=20),
                size="lg",
                radius="xl",
                color="red",
            ),
            label=f"Showing {cutoff:,} of {df.shape[0]:,} points for performance.",
            position="top",
            openDelay=500,
            withinPortal=False,
        )
        badges.append(partial_badge)

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


# Async wrapper for background callbacks (following card component pattern)
async def build_figure_async(**kwargs):
    """
    Async wrapper for build_figure function.
    Used in background callbacks where async execution is needed.
    """
    logger.info(
        f"🔄 ASYNC FIGURE: Building figure component asynchronously - Index: {kwargs.get('index', 'UNKNOWN')}"
    )

    # Call the synchronous build_figure function
    # In the future, this could run in a thread pool if needed for true parallelism
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
