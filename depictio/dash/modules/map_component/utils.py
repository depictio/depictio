"""
Map Component - Build and Render Utilities.

Provides build_map() for skeleton creation and render_map() for figure generation
using Plotly Express tile-based map functions (scatter_map, density_map, choropleth_map).
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
        "map_style": kwargs.get("map_style", "carto-positron"),
        "default_zoom": kwargs.get("default_zoom"),
        "default_center": kwargs.get("default_center"),
        "opacity": kwargs.get("opacity", 1.0),
        "size_max": kwargs.get("size_max", 15),
        "z_column": kwargs.get("z_column"),
        "radius": kwargs.get("radius"),
        "selection_enabled": kwargs.get("selection_enabled", False),
        "selection_column": kwargs.get("selection_column"),
        "title": kwargs.get("title"),
        "dict_kwargs": kwargs.get("dict_kwargs", {}),
        # Choropleth-specific fields
        "locations_column": kwargs.get("locations_column"),
        "featureidkey": kwargs.get("featureidkey", "id"),
        "geojson_data": kwargs.get("geojson_data"),
        "geojson_url": kwargs.get("geojson_url"),
        "choropleth_aggregation": kwargs.get("choropleth_aggregation"),
        "color_continuous_scale": kwargs.get("color_continuous_scale"),
        "range_color": kwargs.get("range_color"),
        "geojson_dc_id": kwargs.get("geojson_dc_id"),
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
                    "displayModeBar": "hover",
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
    zoom = max(1, min(zoom, 14))  # Cap at 14 to avoid over-zooming on few points

    return center, zoom


def _compute_geojson_center_zoom(geojson: dict) -> tuple[dict[str, float], int]:
    """Compute center and zoom from GeoJSON FeatureCollection coordinates.

    Recursively extracts all coordinate pairs from GeoJSON geometry
    and delegates to _compute_auto_zoom().

    Args:
        geojson: GeoJSON FeatureCollection dict.

    Returns:
        Tuple of (center_dict, zoom_level).
    """
    lats: list[float] = []
    lons: list[float] = []

    def _extract_coords(obj: Any) -> None:
        """Recursively extract [lon, lat] pairs from GeoJSON geometry coordinates."""
        if isinstance(obj, list):
            # A coordinate pair is [lon, lat] (2 or 3 floats)
            if len(obj) >= 2 and all(isinstance(x, (int, float)) for x in obj[:2]):
                lons.append(float(obj[0]))
                lats.append(float(obj[1]))
            else:
                for item in obj:
                    _extract_coords(item)

    for feature in geojson.get("features", []):
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates", [])
        _extract_coords(coords)

    return _compute_auto_zoom(lats, lons)


def render_map(
    df: Any,
    trigger_data: dict,
    theme: str = "light",
    existing_metadata: dict | None = None,
    active_selection_values: list | None = None,
    access_token: str | None = None,
) -> tuple[Any, dict]:
    """Render a Plotly map figure from DataFrame and configuration.

    Supports scatter_map, density_map, and choropleth_map. Converts Polars
    DataFrames to pandas, builds kwargs for Plotly Express, and applies theme styling.

    Args:
        df: Polars or pandas DataFrame with data.
        trigger_data: Configuration dict from map-trigger store.
        theme: Theme name ('light' or 'dark').
        existing_metadata: Previous render metadata with stored center/zoom
            to preserve viewport when filters change.
        active_selection_values: Values currently selected on the map (from
            interactive-values-store).  When provided, ``selectedpoints`` is
            set so Plotly renders selected/unselected styling.

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
    map_style = trigger_data.get("map_style", "carto-positron")
    default_zoom = trigger_data.get("default_zoom")
    default_center = trigger_data.get("default_center")
    opacity = trigger_data.get("opacity", 1.0)
    size_max = trigger_data.get("size_max", 15)
    z_column = trigger_data.get("z_column")
    radius = trigger_data.get("radius")
    selection_enabled = trigger_data.get("selection_enabled", False)
    selection_column = trigger_data.get("selection_column")
    title = trigger_data.get("title")
    extra_kwargs = trigger_data.get("dict_kwargs", {})
    # Choropleth-specific
    locations_column = trigger_data.get("locations_column")
    featureidkey = trigger_data.get("featureidkey", "id")
    geojson_data = trigger_data.get("geojson_data")
    geojson_url = trigger_data.get("geojson_url")
    choropleth_aggregation = trigger_data.get("choropleth_aggregation")
    color_continuous_scale = trigger_data.get("color_continuous_scale")
    range_color = trigger_data.get("range_color")
    geojson_dc_id = trigger_data.get("geojson_dc_id")

    # Resolve GeoJSON from data collection if no inline/URL source provided
    if map_type == "choropleth_map" and not geojson_data and not geojson_url and geojson_dc_id:
        from depictio.api.v1.deltatables_utils import load_geojson_from_s3

        geojson_data = load_geojson_from_s3(geojson_dc_id, TOKEN=access_token)
        if not geojson_data:
            logger.warning(f"Failed to load GeoJSON from DC {geojson_dc_id}")

    # Auto-switch map_style to match current theme
    if theme == "dark" and map_style in ("open-street-map", "carto-positron"):
        map_style = "carto-darkmatter"
    elif theme != "dark" and map_style == "carto-darkmatter":
        map_style = "carto-positron"

    # Convert Polars to pandas
    if hasattr(df, "to_pandas"):
        pandas_df = df.to_pandas()
    else:
        pandas_df = df

    total_count = len(pandas_df)

    # Drop rows with missing required columns
    if map_type in ("scatter_map", "density_map"):
        if lat_column in pandas_df.columns and lon_column in pandas_df.columns:
            pandas_df = pandas_df.dropna(subset=[lat_column, lon_column])
    elif map_type == "choropleth_map" and locations_column:
        if locations_column in pandas_df.columns:
            pandas_df = pandas_df.dropna(subset=[locations_column])
    displayed_count = len(pandas_df)

    if displayed_count == 0:
        template = _get_theme_template(theme)
        fig = px.scatter(template=template)
        fig.add_annotation(
            text="No valid data found",
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

    # Compute center and zoom - reuse stored values on re-renders to prevent
    # viewport jumping when filters reduce the visible point set
    stored_center = (existing_metadata or {}).get("center")
    stored_zoom = (existing_metadata or {}).get("zoom")

    if default_center and default_zoom is not None:
        center = default_center
        zoom = default_zoom
    elif stored_center and stored_zoom is not None:
        # Re-render after filtering: keep the original viewport
        center = stored_center
        zoom = stored_zoom
    else:
        # First render: compute from data extent
        if map_type == "choropleth_map" and geojson_data:
            center, zoom = _compute_geojson_center_zoom(geojson_data)
        elif lat_column in pandas_df.columns and lon_column in pandas_df.columns:
            lats = pandas_df[lat_column].tolist()
            lons = pandas_df[lon_column].tolist()
            center, zoom = _compute_auto_zoom(lats, lons)
        else:
            center, zoom = {"lat": 0.0, "lon": 0.0}, 2
        if default_zoom is not None:
            zoom = default_zoom
        if default_center is not None:
            center = default_center

    # Lock color mapping so palette doesn't shift when data is filtered
    color_discrete_map = (existing_metadata or {}).get("color_discrete_map")
    if not color_discrete_map and color_column and color_column in pandas_df.columns:
        unique_vals = sorted(pandas_df[color_column].dropna().unique().tolist(), key=str)
        palette = px.colors.qualitative.Plotly
        color_discrete_map = {str(v): palette[i % len(palette)] for i, v in enumerate(unique_vals)}

    # Build kwargs common to all map types
    # NOTE: opacity is NOT passed here — px.scatter_map opacity interacts with
    # size encoding and produces uneven marker transparency. Instead we force
    # uniform marker.opacity via update_traces after figure creation.
    common_kwargs: dict[str, Any] = {
        "map_style": map_style,
        "zoom": zoom,
        "center": center,
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
                opacity=opacity,
                color_discrete_map=color_discrete_map,
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
        elif map_type == "choropleth_map":
            fig = _render_choropleth_map(
                pandas_df,
                geojson_data=geojson_data,
                geojson_url=geojson_url,
                locations_column=locations_column or "",
                featureidkey=featureidkey,
                color_column=color_column,
                hover_columns=hover_columns,
                choropleth_aggregation=choropleth_aggregation,
                color_continuous_scale=color_continuous_scale,
                range_color=range_color,
                opacity=opacity,
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
                opacity=opacity,
                color_discrete_map=color_discrete_map,
                **common_kwargs,
            )

        # Common layout updates
        # map.uirevision preserves the user's current pan/zoom/bearing/pitch
        # across re-renders.  This is map-viewport-specific and does NOT
        # preserve trace selection state (we clear that with selectedpoints=None).
        layout_kwargs: dict[str, Any] = {
            "margin": {"l": 0, "r": 0, "t": 30 if title else 0, "b": 0},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "map": {"uirevision": "preserve"},
        }
        if title:
            layout_kwargs["title"] = {
                "text": title,
                "x": 0.5,
                "xanchor": "center",
                "font": {"size": 14},
            }
        fig.update_layout(**layout_kwargs)

        # Apply per-point opacity to show selection state.  Plotly's
        # selected/unselected trace properties don't work reliably on
        # scatter_map traces, so we set marker.opacity as an array directly.
        # When color encoding is used, px.scatter_map creates one trace per
        # category -- we must set opacity per-trace using each trace's
        # customdata to identify which points are selected.
        if (
            map_type != "choropleth_map"
            and active_selection_values
            and selection_column
            and selection_column in pandas_df.columns
        ):
            selected_set = {str(v) for v in active_selection_values}
            for trace in fig.data:
                cd = trace.customdata
                if cd is not None and len(cd) > 0:
                    trace_opacity = [opacity if str(row[0]) in selected_set else 0.2 for row in cd]
                    trace.marker.opacity = trace_opacity
                else:
                    # No customdata — dim entire trace
                    trace.marker.opacity = 0.2

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
        "center": center,
        "zoom": zoom,
        "color_discrete_map": color_discrete_map,
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
    opacity: float = 1.0,
    color_discrete_map: dict[str, str] | None = None,
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
        if color_discrete_map:
            kwargs["color_discrete_map"] = color_discrete_map
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

    # Force uniform marker opacity (px.scatter_map varies it with size encoding)
    fig.update_traces(marker={"opacity": opacity})

    # Enable selection mode — keep pan as default drag, lasso available in toolbar
    if selection_enabled:
        fig.update_layout(
            clickmode="event+select",
            dragmode="pan",
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

    return px.density_map(**kwargs)


def _render_choropleth_map(
    df: Any,
    geojson_data: dict | None,
    geojson_url: str | None,
    locations_column: str,
    featureidkey: str,
    color_column: str | None,
    hover_columns: list[str],
    choropleth_aggregation: str | None,
    color_continuous_scale: str | None,
    range_color: list[float] | None,
    opacity: float,
    extra_kwargs: dict,
    **common_kwargs: Any,
) -> Any:
    """Render a choropleth_map figure with colored polygon regions.

    Supports inline GeoJSON (geojson_data) or URL-based GeoJSON (geojson_url).
    When choropleth_aggregation is set, groups data by locations_column and
    aggregates color_column before plotting.
    """
    import plotly.express as px

    # Resolve GeoJSON source: inline dict or URL string
    geojson = geojson_data or geojson_url

    plot_df = df

    # Aggregate data if requested (e.g., count samples per country)
    if choropleth_aggregation and locations_column in df.columns:
        if choropleth_aggregation == "count":
            agg_col = color_column or locations_column
            plot_df = (
                df.groupby(locations_column, as_index=False)
                .agg(**{agg_col: (agg_col, "count")})
                .rename(columns={agg_col: agg_col})
            )
            # For count, the aggregated column IS the color column
            if not color_column:
                color_column = locations_column
        elif color_column and color_column in df.columns:
            agg_func = choropleth_aggregation  # sum, mean, min, max
            plot_df = df.groupby(locations_column, as_index=False).agg(
                **{color_column: (color_column, agg_func)}
            )

    kwargs: dict[str, Any] = {
        "data_frame": plot_df,
        "geojson": geojson,
        "locations": locations_column,
        "featureidkey": featureidkey,
        "opacity": opacity,
        **common_kwargs,
    }

    if color_column and color_column in plot_df.columns:
        kwargs["color"] = color_column
    if color_continuous_scale:
        kwargs["color_continuous_scale"] = color_continuous_scale
    if range_color and len(range_color) == 2:
        kwargs["range_color"] = range_color
    if hover_columns:
        valid_hover = [c for c in hover_columns if c in plot_df.columns]
        if valid_hover:
            kwargs["hover_data"] = valid_hover

    # Apply extra kwargs
    for k, v in extra_kwargs.items():
        if v is not None:
            kwargs[k] = v

    return px.choropleth_map(**kwargs)
