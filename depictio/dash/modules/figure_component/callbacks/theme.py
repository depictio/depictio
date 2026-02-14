"""Figure Component - Theme Callbacks.

Handles theme switching for figure components using Dash Patch.
Works for both UI mode and code mode figures without re-executing code.
"""

import plotly.io as pio
from dash import MATCH, Input, Output, Patch


def register_theme_callbacks(app):
    """Register theme update callback for figure components."""

    @app.callback(
        Output({"type": "figure-graph", "index": MATCH}, "figure", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )
    def update_figure_theme(theme_data):
        """Update figure theme template to match the current light/dark mode."""
        template_name = "mantine_dark" if theme_data == "dark" else "mantine_light"

        patch = Patch()
        patch.layout.template = pio.templates[template_name]

        return patch
