from datetime import datetime
from typing import Any, Dict, List, Optional

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import plotly.express as px
import polars as pl
from bson import ObjectId
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite

from .clustering import get_clustering_function
from .definitions import get_visualization_definition
from .models import ComponentConfig


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
    return "plotly_dark" if theme == "dark" else "plotly_white"


def build_figure_frame(index, children=None):
    if not children:
        return dbc.Card(
            [
                dcc.Loading(
                    children=dbc.CardBody(
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
                    type="default",  # Use default Dash spinner
                    delay_show=500,  # Longer delay to avoid showing during initial load
                    delay_hide=100,  # Quick dismissal
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
                dcc.Loading(
                    children=dbc.CardBody(
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
                    type="default",  # Use default Dash spinner
                    delay_show=500,  # Longer delay to avoid showing during initial load
                    delay_hide=100,  # Quick dismissal
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


def render_figure(
    dict_kwargs: Dict[str, Any],
    visu_type: str,
    df: pl.DataFrame,
    cutoff: int = 100000,
    selected_point: Optional[Dict] = None,
    theme: str = "light",
) -> Any:
    """Render a Plotly figure with robust parameter handling.

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
    # Check if it's a clustering visualization
    is_clustering = visu_type.lower() in ["umap"]

    # Validate visualization type
    if not is_clustering and visu_type.lower() not in PLOTLY_FUNCTIONS:
        logger.warning(f"Unknown visualization type: {visu_type}, falling back to scatter")
        visu_type = "scatter"

    # Add theme-appropriate template using Mantine-compatible themes
    if "template" not in dict_kwargs:
        dict_kwargs["template"] = _get_theme_template(theme)

    logger.info("=== FIGURE RENDER DEBUG ===")
    logger.info(f"Visualization: {visu_type}")
    logger.info(f"Theme: {theme}")
    logger.info(f"Template: {dict_kwargs.get('template')}")
    logger.info(f"Data shape: {df.shape if df is not None else 'None'}")
    logger.info(f"Parameters: {list(dict_kwargs.keys())}")
    logger.info(f"Full dict_kwargs: {dict_kwargs}")
    logger.info(f"Available columns in df: {df.columns if df is not None else 'None'}")

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

                figure = plot_function(sampled_df, **cleaned_kwargs)
            else:
                # Use full dataset
                pandas_df = df.to_pandas()
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

        return figure

    except Exception as e:
        logger.error(f"Error creating figure: {e}")
        # Return fallback figure
        return px.scatter(
            template=dict_kwargs.get("template", _get_theme_template(theme)),
            title=f"Error: {str(e)}",
        )


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

    try:
        viz_def = get_visualization_definition(visu_type)
        valid_params = {p.name for p in viz_def.parameters}

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


def build_figure(**kwargs) -> html.Div:
    """Build figure component with robust parameter handling.

    Args:
        **kwargs: Figure configuration parameters

    Returns:
        Figure component as HTML div
    """
    logger.info("=== BUILD FIGURE CALLED ===")
    logger.info(f"All kwargs: {kwargs}")
    logger.info(f"All kwargs keys: {list(kwargs.keys())}")

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

    logger.info(f"Building figure component {index}")
    logger.info(f"Visualization type: {visu_type}")
    logger.info(f"Theme: {theme}")

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

    # Ensure dc_config is available for build_figure
    if not dc_config and wf_id and dc_id:
        logger.warning(f"dc_config missing for figure {index}, attempting to fetch")
        try:
            import httpx

            from depictio.api.v1.configs.config import API_BASE_URL

            headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
            dc_specs = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
                headers=headers,
            ).json()
            dc_config = dc_specs.get("config", {})
            store_component_data["dc_config"] = dc_config
            logger.info(f"Successfully fetched dc_config for figure {index}")
        except Exception as e:
            logger.error(f"Failed to fetch dc_config for figure {index}: {e}")
            dc_config = {}

    # Validate and clean parameters
    validated_kwargs = validate_parameters(visu_type, dict_kwargs)

    # Handle data loading
    if df.is_empty() and kwargs.get("refresh", True):
        if wf_id and dc_id:
            logger.info(f"Loading data for {wf_id}:{dc_id}")
            try:
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
                id={"type": "stored-metadata-component", "index": index},
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
            # Return figure_div directly - loading is now handled at the figure-body level
            return html.Div(
                figure_div,
                id={"index": index},  # Preserve the expected id structure
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


# Legacy exports for backward compatibility
# These will be removed in future versions
def get_available_visualizations():
    """Get available visualization types."""
    return list(PLOTLY_FUNCTIONS.keys())


def get_visualization_options():
    """Get visualization options for UI."""
    return [{"label": name.title(), "value": name} for name in PLOTLY_FUNCTIONS.keys()]
