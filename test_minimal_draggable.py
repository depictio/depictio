"""
Test/Example file for the minimal draggable layout.
This demonstrates how to use the minimal alternative to draggable.py
"""

import dash
import dash_mantine_components as dmc
from dash import html

from depictio.dash.layouts.draggable_minimal import (
    design_draggable_minimal,
    register_minimal_callbacks,
)


def create_test_app():
    """Create a test Dash app using the minimal draggable layout."""
    app = dash.Dash(__name__)

    # Sample data for testing
    init_layout = {}
    init_children = []  # Start with empty to show welcome message
    dashboard_id = "test-minimal-dashboard"
    local_data = {"access_token": "test-token"}

    # Create the minimal layout
    minimal_layout = design_draggable_minimal(
        init_layout=init_layout,
        init_children=init_children,
        dashboard_id=dashboard_id,
        local_data=local_data,
    )

    # App layout
    app.layout = dmc.MantineProvider(
        children=[
            html.Div(
                [
                    dmc.Title(
                        "Two-Panel Minimal Dashboard Test", order=1, style={"marginBottom": "1rem"}
                    ),
                    dmc.Text(
                        "Left panel (1/4): Create filters with 'Create Filter' button",
                        style={"marginBottom": "0.5rem"},
                    ),
                    dmc.Text(
                        "Right panel (3/4): Create sections with 'Create Section' button",
                        style={"marginBottom": "2rem"},
                    ),
                    html.Div(
                        minimal_layout,
                        id="page-content",
                        style={
                            "backgroundColor": "var(--app-bg-color, #f8f9fa)",
                            "minHeight": "600px",
                            "padding": "1rem",
                        },
                    ),
                ]
            )
        ]
    )

    # Register the minimal callbacks
    register_minimal_callbacks(app)

    return app


if __name__ == "__main__":
    app = create_test_app()
    app.run(debug=True, port=8052)
