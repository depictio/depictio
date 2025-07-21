#!/usr/bin/env python3
"""
Basic prototype using dash-dynamic-grid-layout
This version demonstrates the basic setup with editable grid components
"""

import uuid
import dash
from dash import html, Input, Output, State, dcc
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
import plotly.express as px
import json


def generate_unique_index():
    return str(uuid.uuid4())


def create_basic_app():
    app = dash.Dash(__name__)

    # Generate UUIDs for our components
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    uuid3 = generate_unique_index()

    print(f"=== Dash Dynamic Grid Layout Demo ===")
    print(f"Component UUIDs: {uuid1}, {uuid2}, {uuid3}")

    # Sample data for the graph
    df = px.data.iris()

    # Create the layout
    app.layout = dmc.MantineProvider(
        [
            html.H1("🎯 Dash Dynamic Grid Layout Demo"),
            html.Div(
                [
                    html.H3("Using dash-dynamic-grid-layout"),
                    html.P("✅ Native Dash grid layout component"),
                    html.P("✅ Built-in drag and drop functionality"),
                    html.P("✅ Responsive breakpoints"),
                    html.P("✅ UUID preservation"),
                    html.P("🎛️ Edit mode toggle available"),
                ],
                style={"background": "#f9f9f9", "padding": "15px", "margin": "10px 0"},
            ),
            # Edit mode toggle
            html.Div(
                [
                    html.H4("🎛️ Controls"),
                    dmc.Switch(
                        id="edit-mode-toggle",
                        label="Edit Mode",
                        checked=False,
                        color="blue",
                        size="lg",
                        style={"margin": "10px 0"},
                    ),
                    html.P(
                        "Toggle to enable/disable edit mode (shows/hides remove buttons and resize handles)",
                        style={"fontSize": "12px", "color": "#666", "marginTop": "5px"},
                    ),
                ],
                style={
                    "background": "#f0f8ff",
                    "padding": "15px",
                    "margin": "10px 0",
                    "border": "1px solid #ddd",
                },
            ),
            # Storage for edit mode state
            dcc.Store(id="edit-mode-store", storage_type="memory", data=False),
            # Layout display
            html.Div(
                id="layout-display",
                style={"background": "#f5f5f5", "padding": "10px", "margin": "10px 0"},
            ),
            html.Hr(),
            # Dynamic Grid Layout
            dgl.DashGridLayout(
                id="grid-layout",
                items=[
                    dgl.DraggableWrapper(
                        children=[
                            html.Div(
                                [
                                    html.H3("Component 1"),
                                    html.P(f"UUID: {uuid1[:8]}..."),
                                    html.P("🔴 Red component"),
                                    html.P(
                                        "This is a text-based component that can be dragged and resized!"
                                    ),
                                ],
                                style={
                                    "height": "100%",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "border": "2px solid red",
                                    "borderRadius": "5px",
                                    "background": "#fff0f0",
                                    "padding": "10px",
                                    "boxSizing": "border-box",
                                },
                                id=f"component-{uuid1}",
                            )
                        ],
                        handleText="Move Text",
                    ),
                    dgl.DraggableWrapper(
                        children=[
                            dcc.Graph(
                                figure=px.scatter(
                                    df,
                                    x="sepal_width",
                                    y="sepal_length",
                                    color="species",
                                    title="Iris Dataset Scatter Plot",
                                ),
                                style={"height": "100%"},
                            )
                        ],
                        handleText="Move Graph",
                    ),
                    dgl.DraggableWrapper(
                        children=[
                            html.Div(
                                [
                                    html.H3("Component 3"),
                                    html.P(f"UUID: {uuid3[:8]}..."),
                                    html.P("🟢 Green component"),
                                    html.Div(
                                        [
                                            dmc.Button(
                                                "Button 1", color="blue", style={"margin": "5px"}
                                            ),
                                            dmc.Button(
                                                "Button 2", color="green", style={"margin": "5px"}
                                            ),
                                            dmc.Button(
                                                "Button 3", color="orange", style={"margin": "5px"}
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "flexWrap": "wrap",
                                            "justifyContent": "center",
                                        },
                                    ),
                                    html.P("Interactive component with buttons!"),
                                ],
                                style={
                                    "height": "100%",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "border": "2px solid green",
                                    "borderRadius": "5px",
                                    "background": "#f0fff0",
                                    "padding": "10px",
                                    "boxSizing": "border-box",
                                },
                                id=f"component-{uuid3}",
                            )
                        ],
                        handleText="Move Interactive",
                    ),
                ],
                rowHeight=150,
                cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                style={"height": "600px"},
                showRemoveButton=False,  # Will be controlled by edit mode
                showResizeHandles=False,  # Will be controlled by edit mode
                itemLayout=[
                    {"i": "0", "x": 0, "y": 0, "w": 4, "h": 2},
                    {"i": "1", "x": 4, "y": 0, "w": 4, "h": 2},
                    {"i": "2", "x": 8, "y": 0, "w": 4, "h": 2},
                ],
            ),
        ]
    )

    # Callback to handle edit mode toggle
    @app.callback(
        Output("edit-mode-store", "data"),
        Input("edit-mode-toggle", "checked"),
        prevent_initial_call=True,
    )
    def update_edit_mode(edit_mode_checked):
        return edit_mode_checked

    # Callback to update grid layout based on edit mode
    @app.callback(
        [Output("grid-layout", "showRemoveButton"), Output("grid-layout", "showResizeHandles")],
        Input("edit-mode-store", "data"),
    )
    def update_grid_edit_mode(edit_mode_enabled):
        if edit_mode_enabled:
            return True, True
        else:
            return False, False

    # Callback to display current layout
    @app.callback(Output("layout-display", "children"), Input("grid-layout", "currentLayout"))
    def display_layout(current_layout):
        if not current_layout:
            return html.P("No layout data available")

        layout_info = []
        layout_info.append(html.H4("📊 Current Layout:"))

        for i, item in enumerate(current_layout):
            layout_info.append(
                html.P(
                    [
                        html.Strong(f"Item {i + 1}: "),
                        f"id={item.get('i', 'N/A')}, x={item.get('x', 0)}, y={item.get('y', 0)}, w={item.get('w', 1)}, h={item.get('h', 1)}",
                    ]
                )
            )

        # Add collapsible JSON view
        layout_info.append(
            html.Details(
                [html.Summary("Click to see JSON"), html.Pre(json.dumps(current_layout, indent=2))]
            )
        )

        return layout_info

    return app


if __name__ == "__main__":
    app = create_basic_app()
    print("🚀 Starting Dash Dynamic Grid Layout demo...")
    print("🎯 Features: Native grid layout, edit mode toggle, UUID preservation")
    app.run(debug=True, port=8083)
