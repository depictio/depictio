#!/usr/bin/env python3
"""
Version 4: Vertical Growing Behavior for Dynamic Component Resizing
This version demonstrates components that dynamically grow vertically based on container size changes
"""

import sys
import time
import uuid

import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
from dash import Input, Output, State, callback_context, dcc, html

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


def create_responsive_figure_component(component_uuid):
    """Create a figure component that grows vertically with container changes"""
    import plotly.express as px
    from dash_iconify import DashIconify

    # Sample data for the scatter plot
    df = px.data.iris()

    # Create edit buttons with hover-only visibility
    edit_buttons = dmc.ActionIconGroup(
        [
            dmc.ActionIcon(
                id={"type": "drag-handle", "index": component_uuid},
                color="gray",
                variant="subtle",
                size="sm",
                children=DashIconify(icon="mdi:dots-grid", width=14, color="#888"),
                className="react-grid-dragHandle",
                style={"cursor": "grab"},
            ),
            dmc.ActionIcon(
                id={"type": "remove-box-button", "index": component_uuid},
                color="red",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
            ),
            dmc.ActionIcon(
                id={"type": "edit-box-button", "index": component_uuid},
                color="blue",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:pen", width=16, color="white"),
            ),
            dmc.ActionIcon(
                id={"type": "duplicate-box-button", "index": component_uuid},
                color="gray",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
            ),
            dmc.ActionIcon(
                id={"type": "reset-selection-graph-button", "index": component_uuid},
                color="orange",
                variant="filled",
                size="sm",
                children=DashIconify(icon="bx:reset", width=16, color="white"),
            ),
        ],
        orientation="horizontal",
    )

    # Create the graph with responsive height
    graph = dcc.Graph(
        figure=px.scatter(
            df,
            x="sepal_width",
            y="sepal_length",
            color="species",
            title="Responsive Iris Dataset Scatter Plot",
        ),
        style={
            "height": "100%",
            "minHeight": "300px",  # Minimum height
        },
        className="responsive-graph",
    )

    # Create wrapper div with responsive styling
    content_div = html.Div(
        [graph],
        className="dashboard-component-hover responsive-content",
        style={
            "overflow": "visible",
            "width": "100%",
            "height": "100%",
            "boxSizing": "border-box",
            "padding": "5px",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "8px",
            "background": "var(--app-surface-color, #ffffff)",
            "position": "relative",
            "minHeight": "100px",
            "transition": "all 0.3s ease",
            "display": "flex",
            "flexDirection": "column",
        },
    )

    # Create DraggableWrapper
    draggable_wrapper = dgl.DraggableWrapper(
        id=f"box-{component_uuid}",
        children=[content_div],
        handleText="Drag",
    )

    # Return with overlay buttons
    return html.Div(
        [
            draggable_wrapper,
            html.Div(
                edit_buttons,
                style={
                    "position": "absolute",
                    "top": "4px",
                    "right": "8px",
                    "zIndex": 1000,
                    "alignItems": "center",
                    "height": "auto",
                    "background": "transparent",
                    "borderRadius": "6px",
                    "padding": "4px",
                },
            ),
        ],
        style={
            "position": "relative",
            "width": "100%",
            "height": "100%",
        },
        className="responsive-wrapper",
    )


def create_responsive_metrics_component(component_uuid):
    """Create a metrics component that adapts to vertical space"""
    from dash_iconify import DashIconify

    # Create edit buttons
    edit_buttons = dmc.ActionIconGroup(
        [
            dmc.ActionIcon(
                id={"type": "drag-handle", "index": component_uuid},
                color="gray",
                variant="subtle",
                size="sm",
                children=DashIconify(icon="mdi:dots-grid", width=14, color="#888"),
                className="react-grid-dragHandle",
                style={"cursor": "grab"},
            ),
            dmc.ActionIcon(
                id={"type": "remove-box-button", "index": component_uuid},
                color="red",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
            ),
            dmc.ActionIcon(
                id={"type": "edit-box-button", "index": component_uuid},
                color="blue",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:pen", width=16, color="white"),
            ),
            dmc.ActionIcon(
                id={"type": "duplicate-box-button", "index": component_uuid},
                color="gray",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
            ),
        ],
        orientation="horizontal",
    )

    # Create multiple metrics cards that stack vertically when space allows
    metrics_cards = [
        dmc.Card(
            [
                dmc.Text("Total Users", size="sm", c="dimmed"),
                dmc.Text("1,234", size="xl", fw=700, c="blue"),
                dmc.Text("↗️ +12% from last month", size="sm", c="green"),
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            style={"padding": "15px", "marginBottom": "10px"},
        ),
        dmc.Card(
            [
                dmc.Text("Revenue", size="sm", c="dimmed"),
                dmc.Text("$45,678", size="xl", fw=700, c="green"),
                dmc.Text("↗️ +8% from last month", size="sm", c="blue"),
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            style={"padding": "15px", "marginBottom": "10px"},
        ),
        dmc.Card(
            [
                dmc.Text("Conversion Rate", size="sm", c="dimmed"),
                dmc.Text("3.24%", size="xl", fw=700, c="orange"),
                dmc.Text("↘️ -2% from last month", size="sm", c="red"),
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            style={"padding": "15px", "marginBottom": "10px"},
        ),
    ]

    # Create responsive metrics container
    metrics_container = html.Div(
        [
            html.H4("📊 Responsive Metrics", style={"marginBottom": "15px"}),
            html.Div(
                metrics_cards,
                className="metrics-stack",
                style={
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "10px",
                    "height": "100%",
                    "overflowY": "auto",
                },
            ),
            html.P(
                f"UUID: {component_uuid[:8]}...",
                style={"marginTop": "auto", "fontSize": "12px", "color": "#666"},
            ),
        ],
        className="dashboard-component-hover responsive-content",
        style={
            "overflow": "visible",
            "width": "100%",
            "height": "100%",
            "boxSizing": "border-box",
            "padding": "5px",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "8px",
            "background": "var(--app-surface-color, #ffffff)",
            "position": "relative",
            "minHeight": "100px",
            "transition": "all 0.3s ease",
            "display": "flex",
            "flexDirection": "column",
        },
    )

    # Create DraggableWrapper
    draggable_wrapper = dgl.DraggableWrapper(
        id=f"box-{component_uuid}",
        children=[metrics_container],
        handleText="Drag",
    )

    # Return with overlay buttons
    return html.Div(
        [
            draggable_wrapper,
            html.Div(
                edit_buttons,
                style={
                    "position": "absolute",
                    "top": "4px",
                    "right": "8px",
                    "zIndex": 1000,
                    "alignItems": "center",
                    "height": "auto",
                    "background": "transparent",
                    "borderRadius": "6px",
                    "padding": "4px",
                },
            ),
        ],
        style={
            "position": "relative",
            "width": "100%",
            "height": "100%",
        },
        className="responsive-wrapper",
    )


def create_responsive_table_component(component_uuid):
    """Create a table component that adapts to vertical space"""
    from dash_iconify import DashIconify

    # Create edit buttons
    edit_buttons = dmc.ActionIconGroup(
        [
            dmc.ActionIcon(
                id={"type": "drag-handle", "index": component_uuid},
                color="gray",
                variant="subtle",
                size="sm",
                children=DashIconify(icon="mdi:dots-grid", width=14, color="#888"),
                className="react-grid-dragHandle",
                style={"cursor": "grab"},
            ),
            dmc.ActionIcon(
                id={"type": "remove-box-button", "index": component_uuid},
                color="red",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
            ),
            dmc.ActionIcon(
                id={"type": "duplicate-box-button", "index": component_uuid},
                color="gray",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
            ),
        ],
        orientation="horizontal",
    )

    # Create sample table data
    table_data = [
        {"Name": "Alice", "Age": 25, "City": "New York", "Role": "Designer"},
        {"Name": "Bob", "Age": 30, "City": "San Francisco", "Role": "Engineer"},
        {"Name": "Charlie", "Age": 35, "City": "Chicago", "Role": "Manager"},
        {"Name": "Diana", "Age": 28, "City": "Boston", "Role": "Analyst"},
        {"Name": "Eve", "Age": 32, "City": "Seattle", "Role": "Developer"},
        {"Name": "Frank", "Age": 29, "City": "Austin", "Role": "Product Manager"},
        {"Name": "Grace", "Age": 27, "City": "Denver", "Role": "UX Designer"},
        {"Name": "Henry", "Age": 33, "City": "Miami", "Role": "Data Scientist"},
    ]

    # Create responsive table
    table_component = html.Div(
        [
            html.H4("📋 Responsive Data Table", style={"marginBottom": "15px"}),
            html.Div(
                [
                    html.Table(
                        [
                            html.Thead(
                                html.Tr([html.Th(col) for col in table_data[0].keys()]),
                                style={
                                    "position": "sticky",
                                    "top": "0",
                                    "backgroundColor": "#f8f9fa",
                                },
                            ),
                            html.Tbody(
                                [
                                    html.Tr([html.Td(row[col]) for col in row.keys()])
                                    for row in table_data
                                ]
                            ),
                        ],
                        className="responsive-table",
                        style={
                            "width": "100%",
                            "borderCollapse": "collapse",
                            "fontSize": "14px",
                        },
                    )
                ],
                style={
                    "overflowY": "auto",
                    "overflowX": "auto",
                    "height": "100%",
                    "border": "1px solid #dee2e6",
                    "borderRadius": "4px",
                },
            ),
            html.P(
                f"UUID: {component_uuid[:8]}...",
                style={"marginTop": "10px", "fontSize": "12px", "color": "#666"},
            ),
        ],
        className="dashboard-component-hover responsive-content",
        style={
            "overflow": "visible",
            "width": "100%",
            "height": "100%",
            "boxSizing": "border-box",
            "padding": "5px",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "8px",
            "background": "var(--app-surface-color, #ffffff)",
            "position": "relative",
            "minHeight": "100px",
            "transition": "all 0.3s ease",
            "display": "flex",
            "flexDirection": "column",
        },
    )

    # Create DraggableWrapper
    draggable_wrapper = dgl.DraggableWrapper(
        id=f"box-{component_uuid}",
        children=[table_component],
        handleText="Drag",
    )

    # Return with overlay buttons
    return html.Div(
        [
            draggable_wrapper,
            html.Div(
                edit_buttons,
                style={
                    "position": "absolute",
                    "top": "4px",
                    "right": "8px",
                    "zIndex": 1000,
                    "alignItems": "center",
                    "height": "auto",
                    "background": "transparent",
                    "borderRadius": "6px",
                    "padding": "4px",
                },
            ),
        ],
        style={
            "position": "relative",
            "width": "100%",
            "height": "100%",
        },
        className="responsive-wrapper",
    )


def create_vertical_growing_app():
    app = dash.Dash(__name__)

    # Generate UUIDs for our components
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    uuid3 = generate_unique_index()

    print("=== Vertical Growing Dashboard ===")
    print(f"Component UUIDs: {uuid1}, {uuid2}, {uuid3}")

    # Create initial components with vertical growing behavior
    initial_components = [
        create_responsive_figure_component(uuid1),
        create_responsive_metrics_component(uuid2),
        create_responsive_table_component(uuid3),
    ]

    # Add custom CSS via app external_stylesheets or inline styles
    app.index_string = """
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            {%favicon%}
            {%css%}
            <style>
            /* Responsive wrapper styles */
            .responsive-wrapper {
                position: relative !important;
                width: 100% !important;
                height: 100% !important;
            }
            
            /* Responsive content that grows vertically */
            .responsive-content {
                display: flex !important;
                flex-direction: column !important;
                height: 100% !important;
                min-height: 150px !important;
            }
            
            /* Responsive graph styling */
            .responsive-graph {
                flex: 1 !important;
                min-height: 200px !important;
                height: 100% !important;
            }
            
            /* Metrics stack styling */
            .metrics-stack {
                flex: 1 !important;
                overflow-y: auto !important;
                padding-right: 5px !important;
            }
            
            /* Responsive table styling */
            .responsive-table th,
            .responsive-table td {
                padding: 8px 12px !important;
                border-bottom: 1px solid #dee2e6 !important;
                text-align: left !important;
            }
            
            .responsive-table th {
                background-color: #f8f9fa !important;
                font-weight: 600 !important;
            }
            
            .responsive-table tbody tr:hover {
                background-color: #f5f5f5 !important;
            }
            
            /* Grid layout modifications for vertical growing */
            .react-grid-layout {
                min-height: 500px !important;
            }
            
            .react-grid-item {
                transition: all 0.2s ease !important;
            }
            
            /* Hide ActionIconGroup by default */
            .react-grid-item .mantine-ActionIconGroup-root {
                opacity: 0 !important;
                transition: opacity 0.2s ease !important;
                pointer-events: none !important;
            }
            
            /* Show ActionIconGroup on hover */
            .react-grid-item:hover .mantine-ActionIconGroup-root {
                opacity: 1 !important;
                pointer-events: auto !important;
            }
            
            /* Hide individual ActionIcons by default */
            .react-grid-item .mantine-ActionIcon-root[id*="remove-box-button"],
            .react-grid-item .mantine-ActionIcon-root[id*="edit-box-button"],
            .react-grid-item .mantine-ActionIcon-root[id*="duplicate-box-button"],
            .react-grid-item .mantine-ActionIcon-root[id*="reset-selection-graph-button"] {
                opacity: 0 !important;
                transition: opacity 0.2s ease !important;
                pointer-events: none !important;
            }
            
            /* Show individual ActionIcons on hover */
            .react-grid-item:hover .mantine-ActionIcon-root[id*="remove-box-button"],
            .react-grid-item:hover .mantine-ActionIcon-root[id*="edit-box-button"],
            .react-grid-item:hover .mantine-ActionIcon-root[id*="duplicate-box-button"],
            .react-grid-item:hover .mantine-ActionIcon-root[id*="reset-selection-graph-button"] {
                opacity: 1 !important;
                pointer-events: auto !important;
            }
            
            /* Hide old drag handle */
            .react-grid-dragHandle:not(.mantine-ActionIcon-root) {
                display: none !important;
                visibility: hidden !important;
                height: 0 !important;
                padding: 0 !important;
                margin: 0 !important;
                min-height: 0 !important;
            }
            
            /* Drag handle functionality */
            .mantine-ActionIcon-root.react-grid-dragHandle {
                cursor: grab !important;
                opacity: 0 !important;
                transition: opacity 0.2s ease !important;
            }
            
            .react-grid-item:hover .mantine-ActionIcon-root.react-grid-dragHandle {
                opacity: 1 !important;
            }
            
            /* Minimize wrapper padding */
            .react-grid-item > div {
                padding: 2px !important;
                max-height: 100% !important;
                max-width: 100% !important;
                height: 100% !important;
                box-sizing: border-box !important;
            }
            
            /* Hide old remove button */
            .react-grid-item .remove {
                display: none !important;
                visibility: hidden !important;
            }
            
            /* Card component padding optimization */
            .react-grid-item [id*="card-component"] {
                padding: 0px !important;
                margin: 0px !important;
            }
            
            .react-grid-item [id*="card-body"] {
                padding: 2px !important;
            }
            
            .react-grid-item [id*="card"] .mantine-Card-root {
                padding: var(--mantine-spacing-xs) !important;
            }
            
            /* Resize handle visibility control */
            .react-resizable-handle {
                opacity: 0 !important;
                transition: opacity 0.2s ease !important;
            }
            
            .react-grid-item:hover .react-resizable-handle {
                opacity: 0.7 !important;
            }
            
            /* Hide resize handles when edit mode is disabled */
            .drag-handles-hidden .react-resizable-handle {
                display: none !important;
                visibility: hidden !important;
            }
            </style>
        </head>
        <body>
            {%app_entry%}
            <footer>
                {%config%}
                {%scripts%}
                {%renderer%}
            </footer>
        </body>
    </html>
    """

    # Create the layout
    app.layout = dmc.MantineProvider(
        [
            html.H1("📏 Vertical Growing Dashboard (Version 4)"),
            html.Div(
                [
                    html.H3("Dynamic Vertical Resizing System"),
                    html.P("✅ Components grow vertically with container size changes"),
                    html.P("✅ Responsive content that adapts to available space"),
                    html.P("✅ Hover-only edit controls for clean interface"),
                    html.P("✅ Optimized padding and spacing"),
                    html.P("✅ Smooth transitions and animations"),
                    html.P("📊 Figure: Responsive graph that scales with container"),
                    html.P("📋 Table: Scrollable content with fixed headers"),
                    html.P("📈 Metrics: Stacked cards that flow vertically"),
                ],
                style={"background": "#e8f4fd", "padding": "15px", "margin": "10px 0"},
            ),
            # Control panel
            html.Div(
                [
                    html.H4("🎛️ Layout Controls"),
                    dmc.Group(
                        [
                            dmc.Button(
                                "🔄 Reset Layout",
                                id="reset-layout-btn",
                                color="blue",
                                size="sm",
                            ),
                            dmc.Switch(
                                id="edit-mode-toggle",
                                label="Edit Mode",
                                checked=True,
                                color="green",
                                size="md",
                            ),
                        ],
                        gap="md",
                    ),
                    html.P(
                        "💡 Try resizing components vertically to see the growing behavior!",
                        style={"marginTop": "10px", "fontStyle": "italic"},
                    ),
                ],
                style={
                    "background": "#f0fff0",
                    "padding": "15px",
                    "margin": "10px 0",
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                },
            ),
            html.Hr(),
            # Dynamic Grid Layout with vertical growing behavior
            dgl.DashGridLayout(
                id="vertical-grid-layout",
                items=initial_components,
                rowHeight=30,  # Smaller row height for more granular vertical control
                cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                style={
                    "minHeight": "600px",
                    "height": "auto",  # Allow grid to grow
                },
                showRemoveButton=False,
                showResizeHandles=True,  # Enable resize functionality
                className="draggable-grid-container",
                itemLayout=[
                    {
                        "i": f"box-{uuid1}",
                        "x": 0,
                        "y": 0,
                        "w": 8,
                        "h": 20,
                    },  # Figure - wide and taller (20*30px = 600px)
                    {
                        "i": f"box-{uuid2}",
                        "x": 8,
                        "y": 0,
                        "w": 4,
                        "h": 25,
                    },  # Metrics - narrow and very tall (25*30px = 750px)
                    {
                        "i": f"box-{uuid3}",
                        "x": 0,
                        "y": 20,
                        "w": 12,
                        "h": 15,
                    },  # Table - full width, good height (15*30px = 450px)
                ],
            ),
        ]
    )

    # Callback to handle layout reset
    @app.callback(
        Output("vertical-grid-layout", "itemLayout"),
        Input("reset-layout-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def reset_layout(n_clicks):
        if n_clicks:
            return [
                {"i": f"box-{uuid1}", "x": 0, "y": 0, "w": 8, "h": 20},  # Figure - 600px
                {"i": f"box-{uuid2}", "x": 8, "y": 0, "w": 4, "h": 25},  # Metrics - 750px
                {"i": f"box-{uuid3}", "x": 0, "y": 20, "w": 12, "h": 15},  # Table - 450px
            ]
        return dash.no_update

    # Callback to toggle edit mode
    @app.callback(
        Output("vertical-grid-layout", "className"),
        Input("edit-mode-toggle", "checked"),
    )
    def toggle_edit_mode(edit_enabled):
        if edit_enabled:
            return "draggable-grid-container"
        else:
            return "draggable-grid-container drag-handles-hidden"

    return app


if __name__ == "__main__":
    app = create_vertical_growing_app()
    print("🚀 Starting Vertical Growing Dashboard (Version 4)...")
    print("🎯 Features: Vertical growing behavior, responsive components, optimized spacing")
    app.run(debug=True, port=8086)
