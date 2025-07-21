#!/usr/bin/env python3
"""
Simple debug app to test DMC 2.0+ Select component with dynamic data loading.
This will help isolate the issue with project selection in the dashboard modal.
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, State, callback
from dash_iconify import DashIconify

# Create app
app = dash.Dash(__name__)

# Layout
app.layout = dmc.MantineProvider(
    children=[
        dmc.Container(
            [
                dmc.Title("DMC Select Debug Test", order=1),
                dmc.Space(h=20),
                dmc.Button("Open Modal", id="open-modal-btn", color="blue"),
                # Modal with Select component
                dmc.Modal(
                    id="test-modal",
                    opened=False,
                    centered=True,
                    title="Test Modal with Select",
                    children=[
                        dmc.Stack(
                            [
                                dmc.Text("This modal tests dynamic Select data loading:"),
                                dmc.Select(
                                    label="Dynamic Projects",
                                    description="This should populate when modal opens",
                                    id="dynamic-select",
                                    data=[],  # Start empty
                                    placeholder="Loading...",
                                    leftSection=DashIconify(icon="mdi:jira"),
                                    searchable=True,
                                    clearable=True,
                                ),
                                dmc.Select(
                                    label="Static Projects (for comparison)",
                                    description="This has static data",
                                    id="static-select",
                                    data=[
                                        {"value": "static-1", "label": "Static Project 1"},
                                        {"value": "static-2", "label": "Static Project 2"},
                                    ],
                                    placeholder="Select static project",
                                    leftSection=DashIconify(icon="mdi:jira"),
                                    searchable=True,
                                    clearable=True,
                                ),
                                dmc.Text(id="debug-output", c="gray"),
                                dmc.Button("Close", id="close-modal-btn", color="gray"),
                            ]
                        )
                    ],
                ),
            ],
            size="sm",
            pt=50,
        )
    ]
)


# Callback to toggle modal
@callback(
    Output("test-modal", "opened"),
    [Input("open-modal-btn", "n_clicks"), Input("close-modal-btn", "n_clicks")],
    State("test-modal", "opened"),
    prevent_initial_call=True,
)
def toggle_modal(open_clicks, close_clicks, opened):
    ctx = dash.callback_context
    if not ctx.triggered:
        return opened

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    if button_id == "open-modal-btn":
        return True
    elif button_id == "close-modal-btn":
        return False
    return opened


# Callback to load projects when modal opens
@callback(
    [
        Output("dynamic-select", "data"),
        Output("dynamic-select", "placeholder"),
        Output("debug-output", "children"),
    ],
    Input("test-modal", "opened"),
    prevent_initial_call=True,
)
def load_projects_when_modal_opens(modal_opened):
    print(f"Modal opened: {modal_opened}")

    if not modal_opened:
        return [], "Modal closed", "Modal is closed"

    # Simulate loading projects
    mock_projects = [
        {"value": "project-1", "label": "Dynamic Project 1"},
        {"value": "project-2", "label": "Dynamic Project 2 (Very Long Name)"},
        {"value": "project-3", "label": "Dynamic Project 3"},
    ]

    print(f"Returning projects: {mock_projects}")

    return (
        mock_projects,
        f"Select from {len(mock_projects)} projects",
        f"Loaded {len(mock_projects)} projects dynamically when modal opened",
    )


if __name__ == "__main__":
    print("Starting DMC Select debug app...")
    print("Open http://localhost:8051 in your browser")
    print("Click 'Open Modal' and check if dynamic Select gets populated")
    app.run(debug=True, port=8051)
