"""
Map Component - Build and Render Utilities.

Provides build_map() for skeleton creation and render_map() for figure generation
using Plotly Express tile-based map functions (scatter_map, density_map).
"""

import math
from typing import Any

from dash import dcc, html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.figure_component.utils import _get_theme_template


def build_map(**kwargs) -> html.Div:
    """Build map component skeleton with stores and graph placeholder.

    Creates the DOM structure for a map component including trigger/metadata
    stores and a dcc.Graph for the Plotly map figure.

    Args:
        **kwargs: Component metadata including index, wf_id, dc_id, etc.

    Returns:
        html.Div containing stores and graph placeholder.
    """
    index = kwargs.get("index", "")

    # Build trigger data for the core rendering callback
    trigger_data = {
        "wf_id": kwargs.get("wf_id"),
        "dc_id": kwargs.get("dc_id"),
        "map_type": kwargs.get("map_type", "scatter_map"),
        "lat_column": kwargs.get("lat_column", ""),
        "lon_column": kwargs.get("lon_column", ""),
        "color_column": kwargs.get("color_column"),
        "size_column": kwargs.get("size_column"),
        "hover_columns": kwargs.get("hover_columns", []),
        "text_column": kwargs.get("text_column"),
        "map_style": kwargs.get("map_style", "open-street-map"),
        "default_zoom": kwargs.get("default_zoom"),
        "default_center": kwargs.get("default_center"),
        "opacity": kwargs.get("opacity", 0.8),
        "size_max": kwargs.get("size_max", 15),
        "z_column": kwargs.get("z_column"),
        "radius": kwargs.get("radius"),
        "selection_enabled": kwargs.get("selection_enabled", False),
        "selection_column": kwargs.get("selection_column"),
        "dict_kwargs": kwargs.get("dict_kwargs", {}),
    }

    return html.Div(
        [
            dcc.Store(
                id={"type": "map-trigger", "index": index},
                data=trigger_data,
            ),
            dcc.Store(
                id={"type": "map-metadata", "index": index},
                data={},
            ),
            dcc.Store(
                id={"type": "stored-metadata-component", "index": index},
                data=kwargs,
            ),
            dcc.Graph(
                id={"type": "map-graph", "index": index},
                config={
                    "scrollZoom": True,
                    "displayModeBar": True,
                    "modeBarButtonsToRemove": ["toImage"],
                },
                style={
                    "height": "100%",
                    "width": "100%",
                },
            ),
        ],
        style={
            "height": "100%",
            "width": "100%",
            "display": "flex",
            "flexDirection": "column",
        },
    )


def _compute_auto_zoom(lats: list[float], lons: list[float]) -> tuple[dict[str, float], int]:
    """Compute center and zoom level from coordinate extent.

    Uses the bounding box of all points to determine an appropriate
    center point and zoom level for the map.

    Args:
        lats: List of latitude values.
        lons: List of longitude values.

    Returns:
        Tuple of (center_dict, zoom_level).
    """
    if not lats or not lons:
        return {"lat": 0.0, "lon": 0.0}, 2

    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    center = {
        "lat": (min_lat + max_lat) / 2,
        "lon": (min_lon + max_lon) / 2,
    }

    # Compute zoom from extent using log2-based formula
    lat_range = max_lat - min_lat
    lon_range = max_lon - min_lon
    max_range = max(lat_range, lon_range)

    if max_range == 0:
        return center, 12  # Single point

    # Approximate zoom: 360 degrees at zoom 0, halving each level
    zoom = int(math.log2(360 / max(max_range, 0.001))) + 1
    zoom = max(1, min(zoom, 18))

    return center, zoom


def render_map(
    df: Any,
    trigger_data: dict,
    theme: str = "light",
) -> tuple[Any, dict]:
    """Render a Plotly map figure from DataFrame and configuration.

    Supports scatter_map and density_map. Converts Polars DataFrames to pandas,
    builds kwargs for Plotly Express, and applies theme styling.

    Args:
        df: Polars or pandas DataFrame with data.
        trigger_data: Configuration dict from map-trigger store.
        theme: Theme name ('light' or 'dark').

    Returns:
        Tuple of (plotly_figure, data_info_dict).
    """
    import plotly.express as px
    import plotly.graph_objects as go

    map_type = trigger_data.get("map_type", "scatter_map")
    lat_column = trigger_data.get("lat_column", "")
    lon_column = trigger_data.get("lon_column", "")
    color_column = trigger_data.get("color_column")
    size_column = trigger_data.get("size_column")
    hover_columns = trigger_data.get("hover_columns", [])
    text_column = trigger_data.get("text_column")
    map_style = trigger_data.get("map_style", "open-street-map")
    default_zoom = trigger_data.get("default_zoom")
    default_center = trigger_data.get("default_center")
    opacity = trigger_data.get("opacity", 0.8)
    size_max = trigger_data.get("size_max", 15)
    z_column = trigger_data.get("z_column")
    radius = trigger_data.get("radius")
    selection_enabled = trigger_data.get("selection_enabled", False)
    selection_column = trigger_data.get("selection_column")
    extra_kwargs = trigger_data.get("dict_kwargs", {})

    # Auto-switch map_style for dark theme
    if theme == "dark" and map_style == "open-street-map":
        map_style = "carto-darkmatter"
    elif theme == "dark" and map_style == "carto-positron":
        map_style = "carto-darkmatter"

    # Convert Polars to pandas
    if hasattr(df, "to_pandas"):
        pandas_df = df.to_pandas()
    else:
        pandas_df = df

    total_count = len(pandas_df)

    # Drop rows with missing lat/lon
    if lat_column in pandas_df.columns and lon_column in pandas_df.columns:
        pandas_df = pandas_df.dropna(subset=[lat_column, lon_column])
    displayed_count = len(pandas_df)

    if displayed_count == 0:
        template = _get_theme_template(theme)
        fig = px.scatter(template=template)
        fig.add_annotation(
            text="No valid coordinates found",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        data_info = {"displayed_count": 0, "total_count": total_count}
        return fig, data_info

    # Compute center and zoom
    if default_center and default_zoom is not None:
        center = default_center
        zoom = default_zoom
    else:
        lats = pandas_df[lat_column].tolist()
        lons = pandas_df[lon_column].tolist()
        center, zoom = _compute_auto_zoom(lats, lons)
        if default_zoom is not None:
            zoom = default_zoom
        if default_center is not None:
            center = default_center

    # Build kwargs common to all map types
    common_kwargs: dict[str, Any] = {
        "map_style": map_style,
        "zoom": zoom,
        "center": center,
        "opacity": opacity,
    }

    try:
        if map_type == "scatter_map":
            fig = _render_scatter_map(
                pandas_df,
                lat_column=lat_column,
                lon_column=lon_column,
                color_column=color_column,
                size_column=size_column,
                hover_columns=hover_columns,
                text_column=text_column,
                size_max=size_max,
                selection_enabled=selection_enabled,
                selection_column=selection_column,
                extra_kwargs=extra_kwargs,
                **common_kwargs,
            )
        elif map_type == "density_map":
            fig = _render_density_map(
                pandas_df,
                lat_column=lat_column,
                lon_column=lon_column,
                z_column=z_column,
                radius=radius,
                extra_kwargs=extra_kwargs,
                **common_kwargs,
            )
        else:
            logger.warning(f"Unsupported map_type: {map_type}, falling back to scatter_map")
            fig = _render_scatter_map(
                pandas_df,
                lat_column=lat_column,
                lon_column=lon_column,
                color_column=color_column,
                size_column=size_column,
                hover_columns=hover_columns,
                text_column=text_column,
                size_max=size_max,
                selection_enabled=selection_enabled,
                selection_column=selection_column,
                extra_kwargs=extra_kwargs,
                **common_kwargs,
            )

        # Common layout updates
        fig.update_layout(
            margin={"l": 0, "r": 0, "t": 0, "b": 0},
            paper_bgcolor="rgba(0,0,0,0)",
        )

    except Exception as e:
        logger.error(f"Map rendering failed: {e}", exc_info=True)
        template = _get_theme_template(theme)
        fig = go.Figure()
        fig.update_layout(template=template)
        fig.add_annotation(
            text=f"Map error: {e}",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "red"},
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)

    data_info = {
        "displayed_count": displayed_count,
        "total_count": total_count,
    }

    return fig, data_info


def _render_scatter_map(
    df: Any,
    lat_column: str,
    lon_column: str,
    color_column: str | None,
    size_column: str | None,
    hover_columns: list[str],
    text_column: str | None,
    size_max: int,
    selection_enabled: bool,
    selection_column: str | None,
    extra_kwargs: dict,
    **common_kwargs: Any,
) -> Any:
    """Render a scatter_map figure."""
    import plotly.express as px

    kwargs: dict[str, Any] = {
        "data_frame": df,
        "lat": lat_column,
        "lon": lon_column,
        "size_max": size_max,
        **common_kwargs,
    }

    if color_column and color_column in df.columns:
        kwargs["color"] = color_column
    if size_column and size_column in df.columns:
        kwargs["size"] = size_column
    if text_column and text_column in df.columns:
        kwargs["text"] = text_column
    if hover_columns:
        valid_hover = [c for c in hover_columns if c in df.columns]
        if valid_hover:
            kwargs["hover_data"] = valid_hover

    # Inject selection_column into custom_data
    if selection_enabled and selection_column and selection_column in df.columns:
        kwargs["custom_data"] = [selection_column]

    # Apply extra kwargs
    for k, v in extra_kwargs.items():
        if v is not None:
            kwargs[k] = v

    fig = px.scatter_map(**kwargs)

    # Enable selection mode
    if selection_enabled:
        fig.update_layout(
            clickmode="event+select",
            dragmode="lasso",
        )

    return fig


def _render_density_map(
    df: Any,
    lat_column: str,
    lon_column: str,
    z_column: str | None,
    radius: int | None,
    extra_kwargs: dict,
    **common_kwargs: Any,
) -> Any:
    """Render a density_map figure."""
    import plotly.express as px

    kwargs: dict[str, Any] = {
        "data_frame": df,
        "lat": lat_column,
        "lon": lon_column,
        **common_kwargs,
    }

    if z_column and z_column in df.columns:
        kwargs["z"] = z_column
    if radius is not None:
        kwargs["radius"] = radius

    # Apply extra kwargs
    for k, v in extra_kwargs.items():
        if v is not None:
            kwargs[k] = v

    fig = px.density_map(**kwargs)
    return fig
