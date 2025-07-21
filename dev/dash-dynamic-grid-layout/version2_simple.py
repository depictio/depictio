#!/usr/bin/env python3
"""
Simple prototype using dash-dynamic-grid-layout with basic components
This version demonstrates a scatter plot, select dropdown, and metrics card
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


def create_simple_app():
    app = dash.Dash(__name__)

    # Generate UUIDs for our components
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    uuid3 = generate_unique_index()

    print(f"=== Simple Dash Dynamic Grid Layout Demo ===")
    print(f"Component UUIDs: {uuid1}, {uuid2}, {uuid3}")

    # Sample data for the scatter plot
    df = px.data.iris()

    # Create basic components
    scatter_component = dcc.Graph(
        figure=px.scatter(
            df,
            x="sepal_width",
            y="sepal_length",
            color="species",
            title="Iris Dataset Scatter Plot",
        ),
        style={"height": "100%"},
    )

    select_component = html.Div(
        [
            html.H4("Select Component"),
            dmc.Select(
                label="Choose an option",
                placeholder="Select something...",
                value="option1",
                data=[
                    {"label": "Option 1", "value": "option1"},
                    {"label": "Option 2", "value": "option2"},
                    {"label": "Option 3", "value": "option3"},
                ],
                style={"width": "100%"},
            ),
            html.P(
                f"UUID: {uuid2[:8]}...",
                style={"marginTop": "20px", "fontSize": "12px", "color": "#666"},
            ),
        ]
    )

    metrics_component = html.Div(
        [
            html.H4("Metrics Card"),
            dmc.Card(
                [
                    dmc.Text("Total Users", size="sm", c="dimmed"),
                    dmc.Text("1,234", size="xl", fw=700, c="blue"),
                    dmc.Text("↗️ +12% from last month", size="sm", c="green"),
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                style={"padding": "20px"},
            ),
            html.P(
                f"UUID: {uuid3[:8]}...",
                style={"marginTop": "20px", "fontSize": "12px", "color": "#666"},
            ),
        ]
    )

    # Create DraggableWrapper components
    draggable_components = [
        dgl.DraggableWrapper(
            children=[
                html.Div(
                    [scatter_component],
                    style={
                        "height": "100%",
                        "border": "2px solid #1f77b4",
                        "borderRadius": "5px",
                        "background": "#f0f8ff",
                        "padding": "10px",
                        "boxSizing": "border-box",
                    },
                    id=f"scatter-component-{uuid1}",
                )
            ],
            handleText="Move Scatter Plot",
        ),
        dgl.DraggableWrapper(
            children=[
                html.Div(
                    [select_component],
                    style={
                        "height": "100%",
                        "border": "2px solid #ff7f0e",
                        "borderRadius": "5px",
                        "background": "#fff8f0",
                        "padding": "15px",
                        "boxSizing": "border-box",
                    },
                    id=f"select-component-{uuid2}",
                )
            ],
            handleText="Move Select",
        ),
        dgl.DraggableWrapper(
            children=[
                html.Div(
                    [metrics_component],
                    style={
                        "height": "100%",
                        "border": "2px solid #2ca02c",
                        "borderRadius": "5px",
                        "background": "#f0fff0",
                        "padding": "15px",
                        "boxSizing": "border-box",
                    },
                    id=f"metrics-component-{uuid3}",
                )
            ],
            handleText="Move Metrics",
        ),
    ]

    # Create the layout
    app.layout = dmc.MantineProvider(
        [
            html.H1("🎯 Simple Dash Dynamic Grid Layout Demo"),
            html.Div(
                [
                    html.H3("Basic Components Demo"),
                    html.P("✅ Scatter plot with Plotly"),
                    html.P("✅ Select dropdown with Mantine"),
                    html.P("✅ Metrics card with Mantine"),
                    html.P("✅ Native drag and drop"),
                    html.P("✅ Responsive breakpoints"),
                    html.P("✅ UUID preservation"),
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
                items=draggable_components,
                rowHeight=120,
                cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                style={"height": "700px"},
                showRemoveButton=False,
                showResizeHandles=False,
                itemLayout=[
                    {"i": "0", "x": 0, "y": 0, "w": 6, "h": 4},  # Scatter plot - larger
                    {"i": "1", "x": 6, "y": 0, "w": 3, "h": 2},  # Select - smaller
                    {"i": "2", "x": 9, "y": 0, "w": 3, "h": 2},  # Metrics - smaller
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

        component_types = ["Scatter Plot", "Select", "Metrics"]
        for i, item in enumerate(current_layout):
            component_type = (
                component_types[i] if i < len(component_types) else f"Component {i + 1}"
            )
            layout_info.append(
                html.P(
                    [
                        html.Strong(f"{component_type}: "),
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
    app = create_simple_app()
    print("🚀 Starting Simple Dash Dynamic Grid Layout demo...")
    print("🎯 Features: Scatter plot, select dropdown, metrics card")
    app.run(debug=True, port=8085)
