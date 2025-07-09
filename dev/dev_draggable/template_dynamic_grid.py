#!/usr/bin/env python3
"""
Template: dash-dynamic-grid-layout with callbacks
=================================================

Simplified version based on the provided template with:
- Plots and basic divs with text
- Add/remove components functionality
- Layout management callbacks
- Sequential ID management

Based on the original template but simplified for core functionality testing.
"""

import json
import random
import string
from datetime import datetime

import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
import plotly.express as px
from dash import Input, Output, Patch, State, callback, dcc, html, no_update
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

# Sample data for the graphs
df = px.data.iris()
df_tips = px.data.tips()

# Initialize Dash app
app = dash.Dash(__name__)


# Create a Random String ID for new components
def generate_random_string(length):
    characters = string.ascii_letters + string.digits
    random_string = "".join(random.choice(characters) for _ in range(length))
    return random_string


# Create sample figure functions with responsive sizing
def create_sample_figure(chart_type="scatter", data_type="iris"):
    if data_type == "iris":
        if chart_type == "scatter":
            fig = px.scatter(
                df, x="sepal_width", y="sepal_length", color="species", title="Iris Scatter"
            )
        elif chart_type == "histogram":
            fig = px.histogram(df, x="petal_length", color="species", title="Iris Histogram")
        else:
            fig = px.box(df, x="species", y="sepal_length", title="Iris Box Plot")
    else:  # tips
        if chart_type == "scatter":
            fig = px.scatter(df_tips, x="total_bill", y="tip", color="time", title="Tips Scatter")
        elif chart_type == "histogram":
            fig = px.histogram(df_tips, x="total_bill", color="time", title="Tips Histogram")
        else:
            fig = px.box(df_tips, x="day", y="total_bill", title="Tips Box Plot")
    
    # Configure the figure for responsive resizing
    fig.update_layout(
        autosize=True,
        margin=dict(l=40, r=40, t=50, b=40),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    return fig


# Main component layout
component = html.Div(
    [
        html.Center(html.H4("Current Layout (JSON)")),
        html.Hr(),
        html.Div(children=[], id="layout-output"),
        html.Hr(),
        dmc.Group(
            [
                html.H4("Add items or edit the layout ->"),
                dmc.Menu(
                    [
                        dmc.MenuTarget(
                            dmc.ActionIcon(
                                DashIconify(icon="icon-park:add-web", width=20),
                                size="lg",
                                color="#007bff",
                                variant="filled",
                                id="action-icon",
                                n_clicks=0,
                                mb=8,
                            )
                        ),
                        dmc.MenuDropdown(
                            [
                                dmc.MenuItem(
                                    "Add Graph Component",
                                    id="add-graph-component",
                                    n_clicks=0,
                                ),
                                dmc.MenuItem(
                                    "Add Text Component",
                                    id="add-text-component",
                                    n_clicks=0,
                                ),
                                dmc.MenuItem("Toggle Edit Mode", id="edit-mode", n_clicks=0),
                            ]
                        ),
                    ],
                    transitionProps={
                        "transition": "rotate-right",
                        "duration": 150,
                    },
                    position="right",
                ),
            ]
        ),
        html.Div(
            dgl.DashGridLayout(
                id="grid-layout",
                items=[
                    # Initial graph component
                    dgl.DraggableWrapper(
                        html.Div(
                            dcc.Graph(
                                id="initial-graph",
                                figure=create_sample_figure("scatter", "iris"),
                                style={"height": "100%", "width": "100%"},
                                config={"responsive": True, "displayModeBar": False},
                            ),
                            style={"height": "100%", "width": "100%", "display": "flex", "flex-direction": "column"},
                        ),
                        id="graph-0",
                        handleText="Drag Graph",
                    ),
                    # Initial text component
                    dgl.DraggableWrapper(
                        html.Div(
                            [
                                html.H3("Text Component"),
                                html.P("This is a draggable text component."),
                                html.P(f"Created at: {datetime.now().strftime('%H:%M:%S')}"),
                                html.Div(
                                    [
                                        html.Strong("Features:"),
                                        html.Ul(
                                            [
                                                html.Li("Draggable"),
                                                html.Li("Resizable"),
                                                html.Li("Removable"),
                                                html.Li("Custom ID: text-0"),
                                            ]
                                        ),
                                    ]
                                ),
                            ],
                            style={
                                "padding": "20px",
                                "backgroundColor": "#f8f9fa",
                                "border": "1px solid #dee2e6",
                                "borderRadius": "8px",
                                "height": "100%",
                                "width": "100%",
                                "display": "flex",
                                "flex-direction": "column",
                                "box-sizing": "border-box",
                            },
                        ),
                        id="text-0",
                        handleText="Drag Text",
                    ),
                    # Another graph component
                    dgl.DraggableWrapper(
                        html.Div(
                            dcc.Graph(
                                id="second-graph",
                                figure=create_sample_figure("histogram", "tips"),
                                style={"height": "100%", "width": "100%"},
                                config={"responsive": True, "displayModeBar": False},
                            ),
                            style={"height": "100%", "width": "100%", "display": "flex", "flex-direction": "column"},
                        ),
                        id="graph-1",
                        handleText="Drag Chart",
                    ),
                ],
                itemLayout=[
                    {"i": "graph-0", "x": 0, "y": 0, "w": 6, "h": 30},
                    {"i": "text-0", "x": 6, "y": 0, "w": 6, "h": 30},
                    {"i": "graph-1", "x": 0, "y": 4, "w": 12, "h": 20},
                ],
                rowHeight=10,
                cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                style={"minHeight": "800px", "width": "100%"},
                compactType="vertical",
                showRemoveButton=True,  # Edit mode enabled by default
                showResizeHandles=True,
                margin=[10, 10],
                autoSize=True,
            ),
            className="grid-container",
        ),
        dcc.Store(id="layout-store"),
        dcc.Store(id="component-counter", data={"graph": 2, "text": 1}),
    ],
    className="main-container",
    style={"overflow": "auto"},
)

# App layout
app.layout = dmc.MantineProvider(
    [
        dcc.Store(id="css-store"),
        dmc.Container(
            [dmc.Title("Dash Dynamic Grid Layout Template", order=1, mb="lg"), component], size="xl"
        )
    ]
)


# Callback to inject CSS for proper vertical growth
@callback(Output("css-store", "data"), Input("grid-layout", "id"))
def inject_css(_):
    return None

# Add CSS injection clientside callback
app.clientside_callback(
    """
    function(_) {
        // Inject CSS for proper vertical growth
        const style = document.createElement('style');
        style.textContent = `
            .react-grid-item {
                display: flex !important;
                flex-direction: column !important;
            }
            .react-grid-item > div {
                height: 100% !important;
                width: 100% !important;
                display: flex !important;
                flex-direction: column !important;
            }
            .js-plotly-plot {
                flex-grow: 1 !important;
                height: 100% !important;
            }
        `;
        document.head.appendChild(style);
        return window.dash_clientside.no_update;
    }
    """,
    Output("css-store", "data", allow_duplicate=True),
    Input("grid-layout", "id"),
    prevent_initial_call='initial_duplicate',
)

# Callback to store layout changes
@callback(Output("layout-store", "data"), Input("grid-layout", "currentLayout"))
def store_layout(current_layout):
    return current_layout


# Callback to toggle edit mode
@callback(
    Output("grid-layout", "showRemoveButton"),
    Output("grid-layout", "showResizeHandles"),
    Input("edit-mode", "n_clicks"),
    State("grid-layout", "showRemoveButton"),
    State("grid-layout", "showResizeHandles"),
    prevent_initial_call=True,
)
def toggle_edit_mode(n_clicks, current_remove, current_resize):
    if n_clicks is None:
        raise PreventUpdate
    
    # Toggle edit mode - starts enabled by default, toggles to disabled
    new_remove_state = not current_remove
    new_resize_state = not current_resize
    
    edit_mode_status = "ENABLED" if new_remove_state else "DISABLED"
    print(f"Edit mode toggled to: {edit_mode_status} (Remove buttons = {new_remove_state}, Resize handles = {new_resize_state})")
    
    return new_remove_state, new_resize_state


# Callback to display current layout
@callback(Output("layout-output", "children"), Input("grid-layout", "itemLayout"))
def display_layout(current_layout):
    if current_layout and isinstance(current_layout, list):
        return html.Pre(
            json.dumps(current_layout, indent=2),
            style={
                "backgroundColor": "#f8f9fa",
                "padding": "10px",
                "border": "1px solid #dee2e6",
                "borderRadius": "4px",
                "fontSize": "12px",
                "maxHeight": "200px",
                "overflow": "auto",
            },
        )
    return "No layout data available"


# Callback to add new graph component
@callback(
    Output("grid-layout", "items"),
    Output("grid-layout", "itemLayout"),
    Output("component-counter", "data"),
    Input("add-graph-component", "n_clicks"),
    State("component-counter", "data"),
    prevent_initial_call=True,
)
def add_graph_component(n_clicks, counter_data):
    if n_clicks:
        items = Patch()
        new_id = f"graph-{counter_data['graph']}"

        # Create random chart type
        chart_types = ["scatter", "histogram", "box"]
        data_types = ["iris", "tips"]
        chart_type = random.choice(chart_types)
        data_type = random.choice(data_types)

        new_graph = dgl.DraggableWrapper(
            html.Div(
                dcc.Graph(
                    figure=create_sample_figure(chart_type, data_type),
                    style={"height": "100%", "width": "100%"},
                    config={"responsive": True, "displayModeBar": False},
                ),
                style={"height": "100%", "width": "100%", "display": "flex", "flex-direction": "column"},
            ),
            id=new_id,
            handleText=f"Drag {chart_type.title()}",
        )

        items.append(new_graph)

        # Add layout for new component
        itemLayout = Patch()
        itemLayout.append({"i": new_id, "x": 0, "y": 0, "w": 6, "h": 30})

        # Update counter
        counter_data["graph"] += 1

        return items, itemLayout, counter_data
    return no_update, no_update, no_update


# Callback to add new text component
@callback(
    Output("grid-layout", "items", allow_duplicate=True),
    Output("grid-layout", "itemLayout", allow_duplicate=True),
    Output("component-counter", "data", allow_duplicate=True),
    Input("add-text-component", "n_clicks"),
    State("component-counter", "data"),
    prevent_initial_call=True,
)
def add_text_component(n_clicks, counter_data):
    if n_clicks:
        items = Patch()
        new_id = f"text-{counter_data['text']}"

        new_text = dgl.DraggableWrapper(
            html.Div(
                [
                    html.H3(f"Text Component #{counter_data['text']}"),
                    html.P(f"This is text component with ID: {new_id}"),
                    html.P(f"Created at: {datetime.now().strftime('%H:%M:%S')}"),
                    html.P(f"Random info: {generate_random_string(8)}"),
                    html.Div(
                        [
                            html.Strong("Component Stats:"),
                            html.Ul(
                                [
                                    html.Li(f"ID: {new_id}"),
                                    html.Li("Type: Text"),
                                    html.Li("Status: Active"),
                                    html.Li("Draggable: Yes"),
                                ]
                            ),
                        ]
                    ),
                ],
                style={
                    "padding": "20px",
                    "backgroundColor": "#e3f2fd",
                    "border": "1px solid #2196f3",
                    "borderRadius": "8px",
                    "height": "100%",
                    "width": "100%",
                    "display": "flex",
                    "flex-direction": "column",
                    "box-sizing": "border-box",
                },
            ),
            id=new_id,
            handleText="Drag Text",
        )

        items.append(new_text)

        # Add layout for new component
        itemLayout = Patch()
        itemLayout.append({"i": new_id, "x": 0, "y": 0, "w": 6, "h": 30})

        # Update counter
        counter_data["text"] += 1

        return items, itemLayout, counter_data
    return no_update, no_update, no_update


# Callback to remove components
@callback(
    Output("grid-layout", "items", allow_duplicate=True),
    Input("grid-layout", "itemToRemove"),
    State("grid-layout", "itemLayout"),
    prevent_initial_call=True,
)
def remove_component(key, layout):
    if key:
        items = Patch()
        for i in range(len(layout)):
            if layout[i]["i"] == key:
                del items[i]
                break
        return items
    return no_update


# Add a clientside callback for better performance with dynamic resizing
app.clientside_callback(
    """
    function(layout) {
        // Update all components when layout changes
        if (layout && layout.length > 0) {
            // Small delay to ensure DOM is updated
            setTimeout(function() {
                // Process each layout item
                layout.forEach(function(layoutItem) {
                    // Find the grid item with matching data-grid attribute
                    const gridItem = document.querySelector('[data-grid="' + layoutItem.i + '"]');
                    if (gridItem) {
                        // Calculate new height based on grid layout (10px per unit, min 150px)
                        const newHeight = Math.max(layoutItem.h * 10 - 20, 150); // Account for margins
                        
                        // Find and update any graphs within this grid item
                        const graphElements = gridItem.querySelectorAll('.js-plotly-plot');
                        graphElements.forEach(function(graphElement) {
                            if (window.Plotly) {
                                window.Plotly.relayout(graphElement, {
                                    height: newHeight - 40, // Account for padding
                                    autosize: true
                                });
                            }
                        });
                    }
                });
            }, 100);
        }
        
        return window.dash_clientside.no_update;
    }
    """,
    Output("layout-store", "data", allow_duplicate=True),
    Input("grid-layout", "itemLayout"),
    prevent_initial_call=True,
)


if __name__ == "__main__":
    print("🚀 Starting Dash Dynamic Grid Layout Template")
    print("📊 Features:")
    print("  - Add/remove graph components")
    print("  - Add/remove text components")
    print("  - Toggle edit mode:")
    print("    • Default: Edit mode ENABLED (remove buttons visible)")
    print("    • Toggle: Edit mode DISABLED (remove buttons hidden)")
    print("  - Layout persistence")
    print("  - Sequential ID management")
    print("  - Responsive graphs that grow vertically with container")
    print("  - Flexible row height (10px per unit)")
    print("🌐 Navigate to: http://localhost:8052")

    app.run(debug=True, port=8052)
