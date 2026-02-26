"""
Map Component - Edit Save Callback.

Handles saving edited map configuration back to stored-metadata-component.
"""

import dash
from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


def register_map_edit_callback(app):
    """Register edit save callback for map component.

    Args:
        app: Dash application instance.
    """

    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "map-design-store", "index": MATCH}, "data"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def save_map_edit(design_data, current_metadata):
        """Save map design changes to stored metadata."""
        if not design_data or not current_metadata:
            raise dash.exceptions.PreventUpdate

        # Merge design data into current metadata
        _DESIGN_KEYS = {
            "map_type",
            "lat_column",
            "lon_column",
            "color_column",
            "size_column",
            "hover_columns",
            "map_style",
            "opacity",
            "selection_enabled",
            "selection_column",
            "locations_column",
            "featureidkey",
            "geojson_data",
            "geojson_url",
            "geojson_dc_id",
            "choropleth_aggregation",
            "color_continuous_scale",
            "range_color",
        }
        updated = {
            **current_metadata,
            **{k: v for k, v in design_data.items() if k in _DESIGN_KEYS},
        }

        logger.info(
            f"Map edit saved: lat={updated.get('lat_column')}, lon={updated.get('lon_column')}"
        )
        return updated
