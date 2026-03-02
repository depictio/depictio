"""MultiQC Component - Theme Callbacks.

Handles theme switching for MultiQC components using Dash Patch.
"""

import plotly.io as pio
from dash import MATCH, Input, Output, Patch

# Font colors matching mantine templates
_DARK_FONT_COLOR = "#f2f5fa"
_LIGHT_FONT_COLOR = "#2a3f5f"


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

    @app.callback(
        Output({"type": "general-stats-violin", "index": MATCH}, "figure", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )
    def update_violin_theme(theme_data):
        """Update General Statistics violin plot theme.

        Uses Patch to set the Plotly template and global font color.
        layout.font.color propagates to all text (title, axes, ticks)
        that don't have an explicit color override.
        """
        is_dark = theme_data == "dark"
        template_name = "mantine_dark" if is_dark else "mantine_light"
        font_color = _DARK_FONT_COLOR if is_dark else _LIGHT_FONT_COLOR

        patch = Patch()
        patch.layout.template = pio.templates[template_name]
        patch.layout.font.color = font_color

        return patch
