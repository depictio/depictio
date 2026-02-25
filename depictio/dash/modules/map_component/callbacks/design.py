"""
Map Component - Design Callbacks.

Callbacks for the map design UI in the stepper workflow:
- Toggle selection column based on selection switch
- Live preview update based on configuration changes
"""

import json

import dash
import plotly.express as px
from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.map_component.utils import _compute_auto_zoom


def register_design_callbacks(app):
    """Register design UI callbacks for map component.

    Args:
        app: Dash application instance.
    """

    # Toggle selection column enabled state
    @app.callback(
        Output({"type": "map-selection-column", "index": MATCH}, "disabled"),
        Input({"type": "map-selection-enabled", "index": MATCH}, "checked"),
        prevent_initial_call=True,
    )
    def toggle_selection_column(checked):
        """Enable/disable selection column selector based on switch."""
        return not checked

    # Live preview callback
    @app.callback(
        Output({"type": "map-preview-graph", "index": MATCH}, "figure"),
        Output({"type": "map-design-store", "index": MATCH}, "data"),
        Input({"type": "map-lat-column", "index": MATCH}, "value"),
        Input({"type": "map-lon-column", "index": MATCH}, "value"),
        Input({"type": "map-color-column", "index": MATCH}, "value"),
        Input({"type": "map-size-column", "index": MATCH}, "value"),
        Input({"type": "map-hover-columns", "index": MATCH}, "value"),
        Input({"type": "map-style-selector", "index": MATCH}, "value"),
        Input({"type": "map-opacity", "index": MATCH}, "value"),
        Input({"type": "map-selection-enabled", "index": MATCH}, "checked"),
        Input({"type": "map-selection-column", "index": MATCH}, "value"),
        State("stepper-df-store", "data"),
        State("theme-store", "data"),
        prevent_initial_call=True,
    )
    def update_map_preview(
        lat_col,
        lon_col,
        color_col,
        size_col,
        hover_cols,
        map_style,
        opacity,
        selection_enabled,
        selection_col,
        df_json,
        theme_data,
    ):
        """Update map preview based on design configuration."""
        if not lat_col or not lon_col:
            raise dash.exceptions.PreventUpdate

        # Build design state
        design_data = {
            "component_type": "map",
            "map_type": "scatter_map",
            "lat_column": lat_col,
            "lon_column": lon_col,
            "color_column": color_col,
            "size_column": size_col,
            "hover_columns": hover_cols or [],
            "map_style": map_style or "open-street-map",
            "opacity": opacity or 0.8,
            "selection_enabled": selection_enabled or False,
            "selection_column": selection_col,
        }

        # Try to render a preview if we have data
        try:
            import pandas as pd

            if df_json:
                pandas_df = pd.DataFrame(df_json)
            else:
                # Create empty figure with message
                fig = px.scatter(title="")
                fig.add_annotation(
                    text="Select lat/lon columns to preview",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                )
                fig.update_xaxes(visible=False)
                fig.update_yaxes(visible=False)
                fig_dict = json.loads(fig.to_json())
                return fig_dict, design_data

            if lat_col not in pandas_df.columns or lon_col not in pandas_df.columns:
                raise dash.exceptions.PreventUpdate

            # Drop NaN coordinates
            pandas_df = pandas_df.dropna(subset=[lat_col, lon_col])
            if len(pandas_df) == 0:
                raise dash.exceptions.PreventUpdate

            # Auto-switch style for dark theme
            style = map_style or "open-street-map"
            theme = theme_data if theme_data else "light"
            if theme == "dark" and style in ("open-street-map", "carto-positron"):
                style = "carto-darkmatter"

            # Compute center/zoom
            lats = pandas_df[lat_col].tolist()
            lons = pandas_df[lon_col].tolist()
            center, zoom = _compute_auto_zoom(lats, lons)

            # Build scatter_map kwargs
            kwargs = {
                "data_frame": pandas_df,
                "lat": lat_col,
                "lon": lon_col,
                "map_style": style,
                "zoom": zoom,
                "center": center,
                "opacity": opacity or 0.8,
            }

            if color_col and color_col in pandas_df.columns:
                kwargs["color"] = color_col
            if size_col and size_col in pandas_df.columns:
                kwargs["size"] = size_col
            if hover_cols:
                valid_hover = [c for c in hover_cols if c in pandas_df.columns]
                if valid_hover:
                    kwargs["hover_data"] = valid_hover

            fig = px.scatter_map(**kwargs)
            fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0})

            fig_dict = json.loads(fig.to_json())
            return fig_dict, design_data

        except Exception as e:
            logger.warning(f"Map preview error: {e}")
            raise dash.exceptions.PreventUpdate
