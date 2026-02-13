"""MultiQC Component - Theme Callbacks.

Handles theme switching for MultiQC components using Dash Patch.
"""

import plotly.io as pio
from dash import MATCH, Input, Output, Patch


def register_theme_callbacks(app):
    """Register theme update callback for MultiQC components."""

    @app.callback(
        Output({"type": "multiqc-graph", "index": MATCH}, "figure", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )
    def update_multiqc_theme(theme_data):
        """Update MultiQC figure theme template to match the current light/dark mode."""
        template_name = "mantine_dark" if theme_data == "dark" else "mantine_light"

        patch = Patch()
        patch.layout.template = pio.templates[template_name]

        return patch
