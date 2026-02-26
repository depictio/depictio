"""Map Component - Theme Callbacks.

Handles theme switching for map components using Dash Patch.
Switches the tile layer style between carto-positron (light) and
carto-darkmatter (dark) without triggering a full re-render.
"""

import dash
from dash import ALL, Input, Output, Patch, State

# Tile style mapping: user-chosen style -> dark equivalent and vice versa.
_LIGHT_TO_DARK = {
    "carto-positron": "carto-darkmatter",
    "open-street-map": "carto-darkmatter",
}
_DARK_TO_LIGHT = {
    "carto-darkmatter": "carto-positron",
}


def register_theme_callbacks(app):
    """Register theme update callback for map components."""

    @app.callback(
        Output({"type": "map-graph", "index": ALL}, "figure", allow_duplicate=True),
        Input("theme-store", "data"),
        State({"type": "map-graph", "index": ALL}, "figure"),
        State({"type": "map-graph", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def update_map_theme(theme_data, current_figures, graph_ids):
        """Switch map tile style to match the current light/dark mode."""
        if not graph_ids:
            return []

        is_dark = theme_data == "dark"
        patches = []

        for fig in current_figures:
            patch = Patch()

            # Determine current tile style from the figure layout
            current_style = None
            if isinstance(fig, dict):
                map_layout = fig.get("layout", {}).get("map", {})
                current_style = map_layout.get("style")

            # Switch style based on theme direction
            if is_dark:
                new_style = _LIGHT_TO_DARK.get(current_style, "carto-darkmatter")
            else:
                new_style = _DARK_TO_LIGHT.get(current_style, "carto-positron")

            patch.layout.map.style = new_style
            patches.append(patch)

        return patches
