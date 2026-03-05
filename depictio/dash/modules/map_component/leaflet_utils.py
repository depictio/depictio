"""
Map Component - Dash-Leaflet Tiled Map Utilities.

Provides build_leaflet_map() for creating dash-leaflet based tiled map
components that render PMTiles vector tiles with progressive loading.
"""

from typing import Any

import dash_leaflet as dl
from dash import html
from dash_extensions.javascript import Namespace

# JS namespace references for functions defined in assets/js/leaflet-map-functions.js
_ns = Namespace("dashExtensions", "map")
_style_function = _ns("styleFunction")
_hover_style = _ns("hoverStyle")
_on_each_feature = _ns("onEachFeature")

# Base tile layer URLs for light/dark themes
TILE_URLS = {
    "light": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    "dark": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
}

TILE_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    'contributors &copy; <a href="https://carto.com/">CARTO</a>'
)

# Land cover color mapping (matches the existing choropleth colors)
LAND_COVER_COLORS = {
    "Built-up": "#FF4444",
    "Grassland": "#90EE90",
    "Tree Cover": "#006400",
    "Water": "#4169E1",
    "Cropland": "#DAA520",
    "Bare / sparse vegetation": "#D2B48C",
    "Snow and ice": "#E0FFFF",
    "Herbaceous wetland": "#8FBC8F",
    "Mangroves": "#2E8B57",
    "Moss and lichen": "#9ACD32",
}

# Default fallback color
DEFAULT_FEATURE_COLOR = "#888888"


def _get_base_tile_url(theme: str) -> str:
    """Get the base tile URL for the current theme."""
    if theme == "dark":
        return TILE_URLS["dark"]
    return TILE_URLS["light"]


def build_leaflet_map(
    index: str,
    trigger_data: dict,
    geojson_data: dict | None = None,
    scatter_overlay_data: list[dict] | None = None,
    theme: str = "light",
) -> html.Div:
    """Build a dash-leaflet Map component with tiled base layer and GeoJSON overlay.

    Args:
        index: Component index for Dash IDs.
        trigger_data: Configuration dict from map-trigger store.
        geojson_data: GeoJSON FeatureCollection for the land cover overlay.
        scatter_overlay_data: List of dicts with lat/lon/color for sample point markers.
        theme: Current theme ('light' or 'dark').

    Returns:
        html.Div containing the dash-leaflet Map component.
    """
    default_center = trigger_data.get("default_center", {"lat": 51.0, "lon": 10.5})
    default_zoom = trigger_data.get("default_zoom", 6)
    title = trigger_data.get("title")

    center = [default_center.get("lat", 51.0), default_center.get("lon", 10.5)]
    base_tile_url = _get_base_tile_url(theme)

    children_layers: list[Any] = [
        dl.TileLayer(
            url=base_tile_url,
            attribution=TILE_ATTRIBUTION,
        ),
    ]

    # Add GeoJSON land cover overlay with per-feature styling and tooltips
    if geojson_data and geojson_data.get("features"):
        tile_style = trigger_data.get("tile_layer_style") or {}
        color_config = tile_style.get("color_map", LAND_COVER_COLORS)

        children_layers.append(
            dl.GeoJSON(
                id={"type": "leaflet-geojson", "index": index},
                data=geojson_data,
                style=_style_function,
                hoverStyle=_hover_style,
                onEachFeature=_on_each_feature,
                hideout={
                    "color_map": color_config,
                    "color_prop": "land_cover",
                    "default_color": DEFAULT_FEATURE_COLOR,
                },
                zoomToBounds=False,
            ),
        )

    # Add scatter overlay markers for sample points
    if scatter_overlay_data:
        markers = []
        for point in scatter_overlay_data:
            lat = point.get("lat")
            lon = point.get("lon")
            if lat is None or lon is None:
                continue
            tooltip_text = point.get("tooltip", "")
            color = point.get("color", "#000000")
            markers.append(
                dl.CircleMarker(
                    center=[lat, lon],
                    radius=8,
                    color=color,
                    fill=True,
                    fillColor=color,
                    fillOpacity=0.8,
                    children=[dl.Tooltip(tooltip_text)] if tooltip_text else [],
                ),
            )
        if markers:
            children_layers.append(dl.LayerGroup(markers))

    # Build the map
    leaflet_map = dl.Map(
        id={"type": "leaflet-map", "index": index},
        center=center,
        zoom=default_zoom,
        children=children_layers,
        style={
            "height": "100%",
            "width": "100%",
            "borderRadius": "8px",
        },
    )

    wrapper_children: list[Any] = []
    if title:
        wrapper_children.append(
            html.Div(
                title,
                style={
                    "textAlign": "center",
                    "fontSize": "14px",
                    "fontWeight": "bold",
                    "padding": "4px 0",
                },
            )
        )
    wrapper_children.append(leaflet_map)

    return html.Div(
        wrapper_children,
        style={
            "height": "100%",
            "width": "100%",
            "display": "flex",
            "flexDirection": "column",
        },
    )


def build_scatter_overlay_data(
    df: Any,
    trigger_data: dict,
) -> list[dict]:
    """Convert a DataFrame to scatter overlay point dicts for dash-leaflet markers.

    Args:
        df: Pandas or Polars DataFrame with sample point data.
        trigger_data: Configuration dict with overlay column mappings.

    Returns:
        List of dicts with lat, lon, color, tooltip keys.
    """
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()

    lat_col = trigger_data.get("scatter_overlay_lat_column")
    lon_col = trigger_data.get("scatter_overlay_lon_column")
    if not lat_col or not lon_col or lat_col not in df.columns or lon_col not in df.columns:
        return []

    color_col = trigger_data.get("scatter_overlay_color_column")
    hover_cols = trigger_data.get("scatter_overlay_hover_columns", [])
    color_map = trigger_data.get("scatter_overlay_color_discrete_map") or {}

    df = df.dropna(subset=[lat_col, lon_col])
    if df.empty:
        return []

    points = []
    for _, row in df.iterrows():
        color = "#000000"
        if color_col and color_col in df.columns:
            color = color_map.get(str(row[color_col]), "#000000")

        tooltip_parts = []
        for c in hover_cols:
            if c in df.columns:
                tooltip_parts.append(f"{c}: {row[c]}")
        tooltip = " | ".join(tooltip_parts)

        points.append(
            {
                "lat": float(row[lat_col]),
                "lon": float(row[lon_col]),
                "color": color,
                "tooltip": tooltip,
            }
        )

    return points
