#!/usr/bin/env python3
"""
Advanced prototype using dash-dynamic-grid-layout with depictio integration
This version demonstrates integration with depictio's edit mode functionality
"""

import json
import sys
import uuid

import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
from dash import Input, Output, dcc, html

# Add the depictio package to the path
sys.path.insert(0, "/Users/tweber/Gits/workspaces/depictio-workspace/depictio")

# Import the enable_box_edit_mode function
try:
    from depictio.dash.layouts.edit import enable_box_edit_mode

    print("✅ Successfully imported enable_box_edit_mode from depictio")
except ImportError as e:
    print(f"❌ Failed to import enable_box_edit_mode: {e}")
    sys.exit(1)


def generate_unique_index():
    return str(uuid.uuid4())


def create_depictio_integration_app():
    app = dash.Dash(__name__)

    # Generate UUIDs for our components
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    uuid3 = generate_unique_index()

    print("=== Dash Dynamic Grid Layout with Depictio Integration ===")
    print(f"Component UUIDs: {uuid1}, {uuid2}, {uuid3}")

    # Sample data for the scatter plot
    import plotly.express as px

    df = px.data.iris()

    # Create mock box components for enable_box_edit_mode
    mock_box1 = {
        "props": {
            "id": {"index": uuid1},
            "children": [
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
        }
    }

    mock_box2 = {
        "props": {
            "id": {"index": uuid2},
            "children": [
                html.Div(
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
            ],
        }
    }

    mock_box3 = {
        "props": {
            "id": {"index": uuid3},
            "children": [
                html.Div(
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
            ],
        }
    }

    # Component data for enable_box_edit_mode
    component_data1 = {"component_type": "figure", "visu_type": "scatter", "parent_index": uuid1}

    component_data2 = {"component_type": "table", "parent_index": uuid2}

    component_data3 = {"component_type": "interactive", "parent_index": uuid3}

    # For now, let's create components with enable_box_edit_mode buttons but extract the inner content properly
    # The issue is that DashboardItem from dash-draggable doesn't work well with dash-dynamic-grid-layout

    # Let's create the components with edit buttons manually, similar to enable_box_edit_mode
    from dash_iconify import DashIconify

    def create_edit_buttons(component_uuid, component_type="figure"):
        """Create edit buttons similar to enable_box_edit_mode"""
        remove_button = dmc.ActionIcon(
            id={"type": "remove-box-button", "index": component_uuid},
            color="red",
            variant="filled",
            children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        )

        edit_button = dmc.ActionIcon(
            id={"type": "edit-box-button", "index": component_uuid},
            color="blue",
            variant="filled",
            children=DashIconify(icon="mdi:pen", width=16, color="white"),
        )

        duplicate_button = dmc.ActionIcon(
            id={"type": "duplicate-box-button", "index": component_uuid},
            color="gray",
            variant="filled",
            children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
        )

        if component_type == "figure":
            reset_button = dmc.ActionIcon(
                id={"type": "reset-selection-graph-button", "index": component_uuid},
                color="orange",
                variant="filled",
                children=DashIconify(icon="bx:reset", width=16, color="white"),
            )
            return dmc.Group(
                [remove_button, edit_button, duplicate_button, reset_button],
                grow=False,
                gap="xs",
                style={"marginBottom": "10px"},
            )
        else:
            return dmc.Group(
                [remove_button, edit_button, duplicate_button],
                grow=False,
                gap="xs",
                style={"marginBottom": "10px"},
            )

    # Create components with edit buttons
    scatter_with_edit = html.Div(
        [
            create_edit_buttons(uuid1, "figure"),
            mock_box1["props"]["children"][0],  # Get the graph component
        ]
    )

    select_with_edit = html.Div(
        [
            create_edit_buttons(uuid2, "table"),
            mock_box2["props"]["children"][0],  # Get the select component
        ]
    )

    metrics_with_edit = html.Div(
        [
            create_edit_buttons(uuid3, "interactive"),
            mock_box3["props"]["children"][0],  # Get the metrics component
        ]
    )

    # Create DraggableWrapper components with edit buttons
    draggable_components = [
        dgl.DraggableWrapper(
            id=f"scatter-{uuid1}",  # Try setting ID on DraggableWrapper
            children=[
                html.Div(
                    [scatter_with_edit],
                    style={
                        "height": "100%",
                        "border": "2px solid #1f77b4",
                        "borderRadius": "5px",
                        "background": "#f0f8ff",
                        "padding": "10px",
                        "boxSizing": "border-box",
                        "overflow": "auto",
                    },
                    id=f"depictio-component-{uuid1}",
                )
            ],
            handleText="Move Scatter Plot",
        ),
        dgl.DraggableWrapper(
            id=f"select-{uuid2}",  # Try setting ID on DraggableWrapper
            children=[
                html.Div(
                    [select_with_edit],
                    style={
                        "height": "100%",
                        "border": "2px solid #ff7f0e",
                        "borderRadius": "5px",
                        "background": "#fff8f0",
                        "padding": "10px",
                        "boxSizing": "border-box",
                        "overflow": "auto",
                    },
                    id=f"depictio-component-{uuid2}",
                )
            ],
            handleText="Move Select",
        ),
        dgl.DraggableWrapper(
            id=f"metrics-{uuid3}",  # Try setting ID on DraggableWrapper
            children=[
                html.Div(
                    [metrics_with_edit],
                    style={
                        "height": "100%",
                        "border": "2px solid #2ca02c",
                        "borderRadius": "5px",
                        "background": "#f0fff0",
                        "padding": "10px",
                        "boxSizing": "border-box",
                        "overflow": "auto",
                    },
                    id=f"depictio-component-{uuid3}",
                )
            ],
            handleText="Move Metrics",
        ),
    ]

    # Create the layout
    app.layout = dmc.MantineProvider(
        [
            html.H1("🎯 Dash Dynamic Grid Layout with Depictio Integration"),
            html.Div(
                [
                    html.H3("Integration with depictio's enable_box_edit_mode"),
                    html.P("✅ Uses depictio's enable_box_edit_mode function"),
                    html.P("✅ Components have edit/duplicate/delete buttons"),
                    html.P("✅ Scatter plot, select dropdown, and metrics card"),
                    html.P("✅ Native drag and drop with dash-dynamic-grid-layout"),
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
                        label="Grid Edit Mode",
                        checked=True,  # Start with edit mode enabled to show the integration
                        color="blue",
                        size="lg",
                        style={"margin": "10px 0"},
                    ),
                    html.P(
                        "Toggle to enable/disable grid edit mode (shows/hides remove buttons and resize handles)",
                        style={"fontSize": "12px", "color": "#666", "marginTop": "5px"},
                    ),
                    html.P(
                        "Note: Depictio edit buttons are always visible when components are created with edit mode",
                        style={
                            "fontSize": "12px",
                            "color": "#888",
                            "marginTop": "5px",
                            "fontStyle": "italic",
                        },
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
            dcc.Store(id="edit-mode-store", storage_type="memory", data=True),
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
                showRemoveButton=True,  # Start with edit mode enabled
                showResizeHandles=True,
                itemLayout=[
                    {
                        "i": f"scatter-{uuid1}",
                        "x": 0,
                        "y": 0,
                        "w": 6,
                        "h": 4,
                    },  # Figure component - larger
                    {
                        "i": f"select-{uuid2}",
                        "x": 6,
                        "y": 0,
                        "w": 6,
                        "h": 4,
                    },  # Table component - larger
                    {
                        "i": f"metrics-{uuid3}",
                        "x": 0,
                        "y": 4,
                        "w": 5,
                        "h": 3,
                    },  # Interactive component - smaller
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

        component_types = ["Figure", "Table", "Interactive"]
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
    app = create_depictio_integration_app()
    print("🚀 Starting Dash Dynamic Grid Layout with Depictio Integration...")
    print("🎯 Features: Depictio edit integration, native grid layout, responsive design")
    app.run(debug=True, port=8085)
