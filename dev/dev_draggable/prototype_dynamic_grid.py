#!/usr/bin/env python3
"""
Prototype: dash-dynamic-grid-layout Testing
===========================================

This prototype tests the dash-dynamic-grid-layout package as a potential replacement 
for the current dash-draggable implementation in Depictio.

Features to test:
1. Basic drag and drop functionality
2. Resizable components
3. Responsive breakpoints
4. Sequential ID management
5. Component persistence
6. Performance with multiple components
7. Integration with Dash components

Author: Claude Code
Date: 2024
"""

import json
from datetime import datetime

import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, ctx, dcc, html

# Sample data for testing
df_iris = px.data.iris()
df_tips = px.data.tips()

# Initialize Dash app
app = dash.Dash(__name__)

# Component counter for sequential IDs
component_counter = 0

def get_next_id():
    """Generate sequential IDs like the Depictio system"""
    global component_counter
    current_id = str(component_counter)
    component_counter += 1
    return current_id

def create_sample_figure(data_type="iris", chart_type="scatter"):
    """Create sample plotly figures for testing"""
    if data_type == "iris":
        if chart_type == "scatter":
            fig = px.scatter(df_iris, x="sepal_length", y="sepal_width", 
                           color="species", title="Iris Dataset - Scatter Plot")
        elif chart_type == "histogram":
            fig = px.histogram(df_iris, x="petal_length", color="species", 
                             title="Iris Dataset - Histogram")
        else:
            fig = px.box(df_iris, x="species", y="sepal_length", 
                        title="Iris Dataset - Box Plot")
    else:  # tips
        if chart_type == "scatter":
            fig = px.scatter(df_tips, x="total_bill", y="tip", 
                           color="time", title="Tips Dataset - Scatter Plot")
        elif chart_type == "histogram":
            fig = px.histogram(df_tips, x="total_bill", color="time", 
                             title="Tips Dataset - Histogram")
        else:
            fig = px.box(df_tips, x="day", y="total_bill", 
                        title="Tips Dataset - Box Plot")
    
    fig.update_layout(height=300)
    return fig

def create_card_component(title, content, card_id=None):
    """Create a card component similar to Depictio's card components"""
    if card_id is None:
        card_id = get_next_id()
    
    return dgl.DraggableWrapper(
        id=f"card-{card_id}",
        children=[
            dmc.Card(
                [
                    dmc.CardSection(
                        dmc.Title(title, order=4),
                        withBorder=True,
                        inheritPadding=True,
                        py="xs"
                    ),
                    dmc.CardSection(
                        content,
                        inheritPadding=True,
                        py="xs"
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                style={"height": "100%"}
            )
        ]
    )

def create_figure_component(data_type="iris", chart_type="scatter", fig_id=None):
    """Create a figure component similar to Depictio's figure components"""
    if fig_id is None:
        fig_id = get_next_id()
    
    fig = create_sample_figure(data_type, chart_type)
    
    return dgl.DraggableWrapper(
        id=f"figure-{fig_id}",
        children=[
            dmc.Card(
                [
                    dmc.CardSection(
                        dmc.Title(f"{data_type.title()} - {chart_type.title()}", order=4),
                        withBorder=True,
                        inheritPadding=True,
                        py="xs"
                    ),
                    dmc.CardSection(
                        dcc.Graph(
                            id=f"graph-{fig_id}",
                            figure=fig,
                            style={"height": "300px"}
                        ),
                        inheritPadding=True,
                        py="xs"
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                style={"height": "100%"}
            )
        ]
    )

def create_interactive_component(component_type="slider", comp_id=None):
    """Create interactive components similar to Depictio's interactive components"""
    if comp_id is None:
        comp_id = get_next_id()
    
    if component_type == "slider":
        content = dmc.Slider(
            id=f"slider-{comp_id}",
            min=0,
            max=100,
            step=1,
            value=50,
            marks=[
                {"value": 0, "label": "0"},
                {"value": 50, "label": "50"},
                {"value": 100, "label": "100"}
            ]
        )
    elif component_type == "dropdown":
        content = dmc.Select(
            id=f"dropdown-{comp_id}",
            data=["Option 1", "Option 2", "Option 3"],
            value="Option 1",
            placeholder="Select an option"
        )
    else:  # buttons
        content = dmc.Group([
            dmc.Button("Button 1", id=f"btn1-{comp_id}", variant="outline"),
            dmc.Button("Button 2", id=f"btn2-{comp_id}", variant="filled"),
            dmc.Button("Button 3", id=f"btn3-{comp_id}", variant="light")
        ])
    
    return dgl.DraggableWrapper(
        id=f"interactive-{comp_id}",
        children=[
            dmc.Card(
                [
                    dmc.CardSection(
                        dmc.Title(f"Interactive: {component_type.title()}", order=4),
                        withBorder=True,
                        inheritPadding=True,
                        py="xs"
                    ),
                    dmc.CardSection(
                        content,
                        inheritPadding=True,
                        py="xs"
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                style={"height": "100%"}
            )
        ]
    )

# Create initial components
initial_components = [
    create_card_component("Welcome", "This is a test of dash-dynamic-grid-layout", "0"),
    create_figure_component("iris", "scatter", "1"),
    create_interactive_component("slider", "2"),
    create_figure_component("tips", "histogram", "3"),
    create_interactive_component("dropdown", "4"),
    create_card_component("Statistics", "Component count: 6", "5")
]

# App layout
app.layout = dmc.MantineProvider(
    [
        dmc.Container([
            dmc.Title("Dash Dynamic Grid Layout Prototype", order=1, mb="lg"),
            
            dmc.Group([
                dmc.Button("Add Card", id="add-card-btn", variant="outline"),
                dmc.Button("Add Figure", id="add-figure-btn", variant="outline"),
                dmc.Button("Add Interactive", id="add-interactive-btn", variant="outline"),
                dmc.Button("Clear All", id="clear-all-btn", variant="outline", color="red"),
                dmc.Button("Save Layout", id="save-layout-btn", variant="filled"),
                dmc.Button("Load Layout", id="load-layout-btn", variant="filled")
            ], mb="md"),
            
            dmc.Group([
                dmc.Text("Components:", size="sm", fw=500),
                dmc.Text(id="component-count", size="sm"),
                dmc.Space(w="md"),
                dmc.Text("Layout Status:", size="sm", fw=500),
                dmc.Text(id="layout-status", size="sm")
            ], mb="md"),
            
            # The main grid layout
            dgl.DashGridLayout(
                id="main-grid",
                children=initial_components,
                rowHeight=150,
                cols={
                    'lg': 12, 'md': 10, 'sm': 6, 'xs': 4, 'xxs': 2
                },
                breakpoints={
                    'lg': 1200, 'md': 996, 'sm': 768, 'xs': 480, 'xxs': 0
                },
                margin=[10, 10],
                containerPadding=[20, 20],
                isDraggable=True,
                isResizable=True,
                style={"minHeight": "400px"}
            ),
            
            # Debug information
            dmc.Divider(mt="xl", mb="md"),
            dmc.Title("Debug Information", order=3, mb="md"),
            dmc.Code(
                id="debug-info",
                block=True,
                style={"maxHeight": "200px", "overflowY": "auto"}
            ),
            
            # Hidden stores for state management
            dcc.Store(id="layout-store"),
            dcc.Store(id="component-store", data={"count": len(initial_components)})
        ], size="xl", px="md", py="md")
    ]
)

# Callbacks
@app.callback(
    [Output("main-grid", "children"),
     Output("component-store", "data"),
     Output("component-count", "children")],
    [Input("add-card-btn", "n_clicks"),
     Input("add-figure-btn", "n_clicks"),
     Input("add-interactive-btn", "n_clicks"),
     Input("clear-all-btn", "n_clicks")],
    [State("main-grid", "children"),
     State("component-store", "data")]
)
def manage_components(add_card, add_figure, add_interactive, clear_all, 
                     current_children, component_data):
    """Manage adding and removing components"""
    if not component_data:
        component_data = {"count": len(initial_components)}
    
    triggered_id = ctx.triggered_id
    
    if triggered_id == "add-card-btn" and add_card:
        new_component = create_card_component(
            f"New Card {component_data['count']}", 
            f"Added at {datetime.now().strftime('%H:%M:%S')}"
        )
        current_children.append(new_component)
        component_data["count"] += 1
        
    elif triggered_id == "add-figure-btn" and add_figure:
        data_type = "iris" if component_data["count"] % 2 == 0 else "tips"
        chart_type = ["scatter", "histogram", "box"][component_data["count"] % 3]
        new_component = create_figure_component(data_type, chart_type)
        current_children.append(new_component)
        component_data["count"] += 1
        
    elif triggered_id == "add-interactive-btn" and add_interactive:
        comp_type = ["slider", "dropdown", "buttons"][component_data["count"] % 3]
        new_component = create_interactive_component(comp_type)
        current_children.append(new_component)
        component_data["count"] += 1
        
    elif triggered_id == "clear-all-btn" and clear_all:
        current_children = []
        component_data["count"] = 0
        # Reset global counter
        global component_counter
        component_counter = 0
    
    return current_children, component_data, f"{len(current_children)} components"

@app.callback(
    [Output("layout-store", "data"),
     Output("layout-status", "children")],
    [Input("save-layout-btn", "n_clicks"),
     Input("main-grid", "layout")],
    [State("main-grid", "layout")]
)
def handle_layout_changes(save_clicks, current_layout, layout_state):
    """Handle layout changes and saving"""
    triggered_id = ctx.triggered_id
    
    if triggered_id == "save-layout-btn" and save_clicks:
        # Save layout to localStorage or file
        status = f"Layout saved at {datetime.now().strftime('%H:%M:%S')}"
        return current_layout, status
    
    elif triggered_id == "main-grid" and current_layout:
        # Layout was changed by dragging/resizing
        status = f"Layout updated at {datetime.now().strftime('%H:%M:%S')}"
        return current_layout, status
    
    return dash.no_update, "Ready"

@app.callback(
    Output("debug-info", "children"),
    [Input("main-grid", "layout"),
     Input("component-store", "data")]
)
def update_debug_info(layout, component_data):
    """Update debug information"""
    debug_data = {
        "timestamp": datetime.now().isoformat(),
        "component_count": component_data.get("count", 0) if component_data else 0,
        "layout_items": len(layout) if layout else 0,
        "layout_sample": layout[:2] if layout else [],
        "component_counter": component_counter
    }
    
    return json.dumps(debug_data, indent=2)

if __name__ == "__main__":
    print("🚀 Starting Dash Dynamic Grid Layout Prototype")
    print("📊 Testing features:")
    print("  - Drag and drop components")
    print("  - Resize components")
    print("  - Add/remove components dynamically")
    print("  - Sequential ID management")
    print("  - Responsive breakpoints")
    print("  - Layout persistence")
    print("\n🌐 Navigate to: http://localhost:8050")
    
    app.run_server(debug=True, port=8050)