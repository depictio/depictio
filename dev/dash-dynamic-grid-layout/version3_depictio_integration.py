#!/usr/bin/env python3
"""
Version 3: Progressive Loading System with Skeleton Components
This version demonstrates independent loading for each component with different timing
"""

import json
import os
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


def create_skeleton_figure(component_uuid):
    """Create a skeleton placeholder for figure components"""
    return html.Div([
        # Skeleton for edit buttons
        dmc.Group([
            dmc.Skeleton(height=28, width=28, radius="sm"),
            dmc.Skeleton(height=28, width=28, radius="sm"),
            dmc.Skeleton(height=28, width=28, radius="sm"),
            dmc.Skeleton(height=28, width=28, radius="sm"),
        ], grow=False, gap="xs", style={"marginBottom": "10px"}),
        # Skeleton for the graph area
        dmc.Stack([
            dmc.Skeleton(height=20, width="60%", radius="sm"),  # Title
            dmc.Skeleton(height=300, width="100%", radius="sm"),  # Graph area
        ], gap="md"),
        # Loading indicator
        html.Div([
            dmc.Loader(size="sm", color="blue"),
            dmc.Text("Loading figure...", size="sm", c="dimmed", style={"marginLeft": "10px"}),
        ], style={"display": "flex", "alignItems": "center", "justifyContent": "center", "marginTop": "10px"})
    ], id=f"skeleton-{component_uuid}")


def create_skeleton_table(component_uuid):
    """Create a skeleton placeholder for table/select components"""
    return html.Div([
        # Skeleton for edit buttons
        dmc.Group([
            dmc.Skeleton(height=28, width=28, radius="sm"),
            dmc.Skeleton(height=28, width=28, radius="sm"), 
            dmc.Skeleton(height=28, width=28, radius="sm"),
        ], grow=False, gap="xs", style={"marginBottom": "10px"}),
        # Skeleton for the component content
        dmc.Stack([
            dmc.Skeleton(height=24, width="40%", radius="sm"),  # Title
            dmc.Skeleton(height=36, width="100%", radius="sm"),  # Select input
            dmc.Skeleton(height=16, width="30%", radius="sm"),  # Helper text
        ], gap="md"),
        # Loading indicator
        html.Div([
            dmc.Loader(size="sm", color="orange"),
            dmc.Text("Loading selector...", size="sm", c="dimmed", style={"marginLeft": "10px"}),
        ], style={"display": "flex", "alignItems": "center", "justifyContent": "center", "marginTop": "10px"})
    ], id=f"skeleton-{component_uuid}")


def create_skeleton_interactive(component_uuid):
    """Create a skeleton placeholder for interactive components"""
    return html.Div([
        # Skeleton for edit buttons
        dmc.Group([
            dmc.Skeleton(height=28, width=28, radius="sm"),
            dmc.Skeleton(height=28, width=28, radius="sm"),
            dmc.Skeleton(height=28, width=28, radius="sm"),
        ], grow=False, gap="xs", style={"marginBottom": "10px"}),
        # Skeleton for the metrics card
        dmc.Stack([
            dmc.Skeleton(height=20, width="40%", radius="sm"),  # Title
            dmc.Card([
                dmc.Skeleton(height=14, width="60%", radius="sm"),  # Label
                dmc.Skeleton(height=32, width="40%", radius="sm"),  # Value
                dmc.Skeleton(height=14, width="80%", radius="sm"),  # Description
            ], withBorder=True, shadow="sm", radius="md", style={"padding": "20px"}),
            dmc.Skeleton(height=12, width="50%", radius="sm"),  # UUID text
        ], gap="md"),
        # Loading indicator
        html.Div([
            dmc.Loader(size="sm", color="green"),
            dmc.Text("Loading metrics...", size="sm", c="dimmed", style={"marginLeft": "10px"}),
        ], style={"display": "flex", "alignItems": "center", "justifyContent": "center", "marginTop": "10px"})
    ], id=f"skeleton-{component_uuid}")


def create_actual_figure_component(component_uuid):
    """Create the actual figure component with edit buttons"""
    import plotly.express as px
    from dash_iconify import DashIconify
    
    # Sample data for the scatter plot
    df = px.data.iris()
    
    # Create edit buttons
    edit_buttons = dmc.Group([
        dmc.ActionIcon(
            id={"type": "remove-box-button", "index": component_uuid},
            color="red",
            variant="filled",
            children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        ),
        dmc.ActionIcon(
            id={"type": "edit-box-button", "index": component_uuid},
            color="blue",
            variant="filled",
            children=DashIconify(icon="mdi:pen", width=16, color="white"),
        ),
        dmc.ActionIcon(
            id={"type": "duplicate-box-button", "index": component_uuid},
            color="gray",
            variant="filled",
            children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
        ),
        dmc.ActionIcon(
            id={"type": "reset-selection-graph-button", "index": component_uuid},
            color="orange",
            variant="filled",
            children=DashIconify(icon="bx:reset", width=16, color="white"),
        ),
    ], grow=False, gap="xs", style={"marginBottom": "10px"})
    
    # Create the graph
    graph = dcc.Graph(
        figure=px.scatter(
            df,
            x="sepal_width",
            y="sepal_length",
            color="species",
            title="Iris Dataset Scatter Plot",
        ),
        style={"height": "100%"},
    )
    
    return html.Div([edit_buttons, graph], id=f"actual-{component_uuid}")


def create_actual_table_component(component_uuid):
    """Create the actual table/select component with edit buttons"""
    from dash_iconify import DashIconify
    
    # Create edit buttons
    edit_buttons = dmc.Group([
        dmc.ActionIcon(
            id={"type": "remove-box-button", "index": component_uuid},
            color="red",
            variant="filled",
            children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        ),
        dmc.ActionIcon(
            id={"type": "edit-box-button", "index": component_uuid},
            color="blue",
            variant="filled",
            children=DashIconify(icon="mdi:pen", width=16, color="white"),
        ),
        dmc.ActionIcon(
            id={"type": "duplicate-box-button", "index": component_uuid},
            color="gray",
            variant="filled",
            children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
        ),
    ], grow=False, gap="xs", style={"marginBottom": "10px"})
    
    # Create the select component
    select_component = html.Div([
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
            f"UUID: {component_uuid[:8]}...",
            style={"marginTop": "20px", "fontSize": "12px", "color": "#666"},
        ),
    ])
    
    return html.Div([edit_buttons, select_component], id=f"actual-{component_uuid}")


def create_actual_interactive_component(component_uuid):
    """Create the actual interactive component with edit buttons"""
    from dash_iconify import DashIconify
    
    # Create edit buttons
    edit_buttons = dmc.Group([
        dmc.ActionIcon(
            id={"type": "remove-box-button", "index": component_uuid},
            color="red",
            variant="filled",
            children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        ),
        dmc.ActionIcon(
            id={"type": "edit-box-button", "index": component_uuid},
            color="blue",
            variant="filled",
            children=DashIconify(icon="mdi:pen", width=16, color="white"),
        ),
        dmc.ActionIcon(
            id={"type": "duplicate-box-button", "index": component_uuid},
            color="gray",
            variant="filled",
            children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
        ),
    ], grow=False, gap="xs", style={"marginBottom": "10px"})
    
    # Create the metrics card
    metrics_component = html.Div([
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
            f"UUID: {component_uuid[:8]}...",
            style={"marginTop": "20px", "fontSize": "12px", "color": "#666"},
        ),
    ])
    
    return html.Div([edit_buttons, metrics_component], id=f"actual-{component_uuid}")


def create_depictio_progressive_loading_app():
    app = dash.Dash(__name__)

    # Generate UUIDs for our components
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    uuid3 = generate_unique_index()

    print(f"=== Progressive Loading Dashboard ===")
    print(f"Component UUIDs: {uuid1}, {uuid2}, {uuid3}")

    # Create initial skeleton components
    initial_components = [
        dgl.DraggableWrapper(
            id=f"scatter-{uuid1}",
            children=[
                html.Div(
                    create_skeleton_figure(uuid1),
                    style={
                        "height": "100%",
                        "border": "2px solid #e0e0e0",
                        "borderRadius": "5px",
                        "background": "#fafafa",
                        "padding": "10px",
                        "boxSizing": "border-box",
                        "overflow": "auto",
                    },
                    id=f"content-scatter-{uuid1}",
                )
            ],
            handleText="Drag Figure",
        ),
        dgl.DraggableWrapper(
            id=f"select-{uuid2}",
            children=[
                html.Div(
                    create_skeleton_table(uuid2),
                    style={
                        "height": "100%",
                        "border": "2px solid #e0e0e0",
                        "borderRadius": "5px",
                        "background": "#fafafa",
                        "padding": "10px",
                        "boxSizing": "border-box",
                        "overflow": "auto",
                    },
                    id=f"content-select-{uuid2}",
                )
            ],
            handleText="Drag Select",
        ),
        dgl.DraggableWrapper(
            id=f"metrics-{uuid3}",
            children=[
                html.Div(
                    create_skeleton_interactive(uuid3),
                    style={
                        "height": "100%",
                        "border": "2px solid #e0e0e0",
                        "borderRadius": "5px",
                        "background": "#fafafa",
                        "padding": "10px",
                        "boxSizing": "border-box",
                        "overflow": "auto",
                    },
                    id=f"content-metrics-{uuid3}",
                )
            ],
            handleText="Drag Metrics",
        ),
    ]

    # Create the layout
    app.layout = dmc.MantineProvider(
        [
            html.H1("🔄 Progressive Loading Dashboard (Version 3)"),
            html.Div([
                html.H3("Progressive Component Loading System"),
                html.P("✅ Full dashboard layout renders immediately"),
                html.P("✅ Independent skeleton loading for each component"),
                html.P("✅ Different loading times: Figure (1s), Select (2s), Metrics (3s)"),
                html.P("✅ Smooth transition from skeleton to actual content"),
                html.P("✅ Edit buttons included in both skeleton and actual components"),
                dmc.Stack([
                    dmc.Text(id="loading-progress-label", children="Loading components...", size="sm", c="dimmed"),
                    dmc.Progress(
                        id="loading-progress",
                        value=0,
                        color="blue",
                        size="lg",
                    ),
                ], gap="xs", style={"marginTop": "10px"}),
            ], style={"background": "#f0f8ff", "padding": "15px", "margin": "10px 0"}),
            
            # Loading control
            html.Div([
                html.H4("🎛️ Loading Controls"),
                dmc.Button(
                    "🔄 Restart Loading",
                    id="restart-loading-btn",
                    color="blue",
                    size="md",
                    style={"margin": "10px 0"},
                ),
                dmc.Switch(
                    id="auto-load-toggle",
                    label="Auto-load on start",
                    checked=True,
                    color="green",
                    size="md",
                    style={"margin": "10px 0"},
                ),
            ], style={
                "background": "#f0fff0",
                "padding": "15px",
                "margin": "10px 0",
                "border": "1px solid #ddd",
            }),
            
            # Loading state tracking
            dcc.Store(id="loading-state", data={
                "figure_loaded": False,
                "table_loaded": False,
                "interactive_loaded": False,
                "start_time": None,
            }),
            
            # Intervals for progressive loading
            dcc.Interval(
                id="figure-interval",
                interval=1000,  # 1 second
                n_intervals=0,
                disabled=False,
                max_intervals=1,
            ),
            dcc.Interval(
                id="table-interval",
                interval=2000,  # 2 seconds
                n_intervals=0,
                disabled=False,
                max_intervals=1,
            ),
            dcc.Interval(
                id="interactive-interval",
                interval=3000,  # 3 seconds
                n_intervals=0,
                disabled=False,
                max_intervals=1,
            ),
            
            # Status display
            html.Div(id="loading-status", style={
                "background": "#f5f5f5",
                "padding": "10px",
                "margin": "10px 0",
                "fontSize": "14px",
            }),
            
            html.Hr(),
            
            # Dynamic Grid Layout
            dgl.DashGridLayout(
                id="grid-layout",
                items=initial_components,
                rowHeight=120,
                cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                style={"height": "700px"},
                showRemoveButton=True,
                showResizeHandles=True,
                itemLayout=[
                    {"i": f"scatter-{uuid1}", "x": 0, "y": 0, "w": 6, "h": 4},
                    {"i": f"select-{uuid2}", "x": 6, "y": 0, "w": 6, "h": 4},
                    {"i": f"metrics-{uuid3}", "x": 0, "y": 4, "w": 5, "h": 3},
                ],
            ),
        ]
    )

    # Callback to restart loading
    @app.callback(
        [
            Output("loading-state", "data"),
            Output("figure-interval", "disabled"),
            Output("table-interval", "disabled"),
            Output("interactive-interval", "disabled"),
            Output("figure-interval", "n_intervals"),
            Output("table-interval", "n_intervals"),
            Output("interactive-interval", "n_intervals"),
        ],
        [
            Input("restart-loading-btn", "n_clicks"),
            Input("auto-load-toggle", "checked"),
        ],
        State("loading-state", "data"),
        prevent_initial_call=False,
    )
    def control_loading(restart_clicks, auto_load, current_state):
        ctx = callback_context
        
        # Initialize loading state
        if not current_state or not current_state.get("start_time"):
            new_state = {
                "figure_loaded": False,
                "table_loaded": False,
                "interactive_loaded": False,
                "start_time": time.time(),
            }
            return new_state, False, False, False, 0, 0, 0
        
        # Check if restart was clicked
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"]
            if "restart-loading-btn" in prop_id and restart_clicks:
                # Reset everything
                new_state = {
                    "figure_loaded": False,
                    "table_loaded": False,
                    "interactive_loaded": False,
                    "start_time": time.time(),
                }
                return new_state, False, False, False, 0, 0, 0
        
        # If auto-load is disabled, disable intervals
        if not auto_load:
            return current_state, True, True, True, 0, 0, 0
        
        return current_state, False, False, False, 0, 0, 0

    # Callback to load figure component
    @app.callback(
        [
            Output(f"content-scatter-{uuid1}", "children"),
            Output(f"content-scatter-{uuid1}", "style"),
            Output("loading-state", "data", allow_duplicate=True),
        ],
        Input("figure-interval", "n_intervals"),
        [
            State("loading-state", "data"),
            State(f"content-scatter-{uuid1}", "style"),
        ],
        prevent_initial_call=True,
    )
    def load_figure_component(n_intervals, loading_state, current_style):
        if n_intervals > 0 and not loading_state.get("figure_loaded"):
            # Update loading state
            new_state = loading_state.copy()
            new_state["figure_loaded"] = True
            
            # Update style to show loaded state
            new_style = current_style.copy()
            new_style["border"] = "2px solid #1f77b4"
            new_style["background"] = "#f0f8ff"
            
            return create_actual_figure_component(uuid1), new_style, new_state
        
        return dash.no_update, dash.no_update, dash.no_update

    # Callback to load table component
    @app.callback(
        [
            Output(f"content-select-{uuid2}", "children"),
            Output(f"content-select-{uuid2}", "style"),
            Output("loading-state", "data", allow_duplicate=True),
        ],
        Input("table-interval", "n_intervals"),
        [
            State("loading-state", "data"),
            State(f"content-select-{uuid2}", "style"),
        ],
        prevent_initial_call=True,
    )
    def load_table_component(n_intervals, loading_state, current_style):
        if n_intervals > 0 and not loading_state.get("table_loaded"):
            # Update loading state
            new_state = loading_state.copy()
            new_state["table_loaded"] = True
            
            # Update style to show loaded state
            new_style = current_style.copy()
            new_style["border"] = "2px solid #ff7f0e"
            new_style["background"] = "#fff8f0"
            
            return create_actual_table_component(uuid2), new_style, new_state
        
        return dash.no_update, dash.no_update, dash.no_update

    # Callback to load interactive component
    @app.callback(
        [
            Output(f"content-metrics-{uuid3}", "children"),
            Output(f"content-metrics-{uuid3}", "style"),
            Output("loading-state", "data", allow_duplicate=True),
        ],
        Input("interactive-interval", "n_intervals"),
        [
            State("loading-state", "data"),
            State(f"content-metrics-{uuid3}", "style"),
        ],
        prevent_initial_call=True,
    )
    def load_interactive_component(n_intervals, loading_state, current_style):
        if n_intervals > 0 and not loading_state.get("interactive_loaded"):
            # Update loading state
            new_state = loading_state.copy()
            new_state["interactive_loaded"] = True
            
            # Update style to show loaded state
            new_style = current_style.copy()
            new_style["border"] = "2px solid #2ca02c"
            new_style["background"] = "#f0fff0"
            
            return create_actual_interactive_component(uuid3), new_style, new_state
        
        return dash.no_update, dash.no_update, dash.no_update

    # Callback to update loading progress
    @app.callback(
        [
            Output("loading-progress", "value"),
            Output("loading-progress-label", "children"),
            Output("loading-progress", "color"),
        ],
        Input("loading-state", "data"),
    )
    def update_loading_progress(loading_state):
        if not loading_state:
            return 0, "Loading components...", "blue"
        
        loaded_count = sum([
            loading_state.get("figure_loaded", False),
            loading_state.get("table_loaded", False),
            loading_state.get("interactive_loaded", False),
        ])
        
        total_count = 3
        progress = int((loaded_count / total_count) * 100)
        
        if progress == 100:
            return 100, "✅ All components loaded!", "green"
        elif progress > 0:
            return progress, f"Loading... {loaded_count}/{total_count} components", "blue"
        else:
            return 0, "Loading components...", "blue"

    # Callback to update loading status
    @app.callback(
        Output("loading-status", "children"),
        Input("loading-state", "data"),
    )
    def update_loading_status(loading_state):
        if not loading_state:
            return "🔄 Initializing..."
        
        start_time = loading_state.get("start_time")
        current_time = time.time()
        elapsed = current_time - start_time if start_time else 0
        
        status_items = []
        
        # Figure status
        if loading_state.get("figure_loaded"):
            status_items.append("✅ Figure Component: Loaded")
        else:
            status_items.append("⏳ Figure Component: Loading... (1s)")
        
        # Table status
        if loading_state.get("table_loaded"):
            status_items.append("✅ Select Component: Loaded")
        else:
            status_items.append("⏳ Select Component: Loading... (2s)")
        
        # Interactive status
        if loading_state.get("interactive_loaded"):
            status_items.append("✅ Metrics Component: Loaded")
        else:
            status_items.append("⏳ Metrics Component: Loading... (3s)")
        
        status_items.append(f"⏱️ Elapsed Time: {elapsed:.1f}s")
        
        return html.Div([
            html.P(item, style={"margin": "2px 0"}) for item in status_items
        ])

    return app


if __name__ == "__main__":
    app = create_depictio_progressive_loading_app()
    print("🚀 Starting Progressive Loading Dashboard (Version 3)...")
    print("🎯 Features: Skeleton loading, independent timers, smooth transitions")
    app.run(debug=True, port=8085)