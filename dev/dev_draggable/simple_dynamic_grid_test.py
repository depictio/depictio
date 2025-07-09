#!/usr/bin/env python3
"""
Simple Dash Dynamic Grid Layout Test
====================================

Super simple test with just 2 components:
1. A graph component with custom ID "graph-0"
2. A text box component with custom ID "text-1"

Custom layouts defined for both components.
"""

import dash
import dash_dynamic_grid_layout as dgl
import plotly.express as px
from dash import dcc, html

# Initialize Dash app
app = dash.Dash(__name__)

# Create sample data and figure
df = px.data.iris()
fig = px.scatter(df, x="sepal_length", y="sepal_width", color="species", title="Iris Dataset")

# Define custom layouts for our components
custom_item_layout = [
    {"i": "graph-0", "x": 0, "y": 0, "w": 6, "h": 4},  # Graph takes left half
    {"i": "text-1", "x": 6, "y": 0, "w": 6, "h": 4},  # Text takes right half
]

# Create the two components as regular HTML elements
graph_component = html.Div(
    [html.H3("Graph Component"), dcc.Graph(figure=fig, style={"height": "300px"})],
    style={
        "border": "2px solid #007bff",
        "borderRadius": "8px",
        "padding": "10px",
        "backgroundColor": "#f8f9fa",
        "height": "100%",
    },
)

text_component = html.Div(
    [
        html.H3("Text Component"),
        html.P("This is a simple text component that can be dragged around."),
        html.P("Component ID: text-1"),
        html.P("Layout: x=6, y=0, w=6, h=4"),
        html.Div(
            [
                html.Strong("Features:"),
                html.Ul(
                    [
                        html.Li("Draggable"),
                        html.Li("Resizable"),
                        html.Li("Custom ID"),
                        html.Li("Custom Layout"),
                    ]
                ),
            ]
        ),
    ],
    style={
        "border": "2px solid #28a745",
        "borderRadius": "8px",
        "padding": "10px",
        "backgroundColor": "#f8f9fa",
        "height": "100%",
    },
)

# App layout
app.layout = html.Div(
    # [
    # html.H1("Simple Dynamic Grid Test", style={"textAlign": "center", "marginBottom": "20px"}),
    # html.Div([
    #     html.P("📊 Graph Component (ID: graph-0) - Blue border"),
    #     html.P("📝 Text Component (ID: text-1) - Green border"),
    #     html.P("🎯 Both components have custom layouts and IDs"),
    # ], style={"margin": "20px", "padding": "10px", "backgroundColor": "#e9ecef", "borderRadius": "5px"}),
    # The main grid layout with our 2 components
    dgl.DashGridLayout(
        id="simple-grid",
        items=[graph_component, text_component],  # Use 'items' instead of 'children'
        itemLayout=custom_item_layout,  # Use 'itemLayout' instead of 'layouts'
        # rowHeight=100,
        cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
        # breakpoints={"lg": 1200, "md": 996, "sm": 768, "xs": 480, "xxs": 0},
        # margin=[10, 10],
        autoSize=True,
        showRemoveButton=True,
        showResizeHandles=True,
        # style={"minHeight": "500px", "border": "1px dashed #ccc"},
    ),
    #     html.Div([
    #         html.H3("Debug Info:"),
    #         html.Pre(f"""
    # Custom Item Layout:
    # {custom_item_layout}
    # Component IDs:
    # - graph-0: Graph component
    # - text-1: Text component
    # Grid Configuration:
    # - Remove Button: True
    # - Resize Handles: True
    # - Row Height: 100px
    # - Breakpoints: lg=1200, md=996, sm=768, xs=480, xxs=0
    # - Columns: lg=12, md=10, sm=6, xs=4, xxs=2
    #         """, style={"backgroundColor": "#f8f9fa", "padding": "10px", "fontSize": "12px"})
    #     ], style={"margin": "20px"})
    # ]
)

if __name__ == "__main__":
    print("🚀 Starting Simple Dynamic Grid Test")
    print("🎯 Testing: 2 components with custom IDs and layouts")
    print("📊 graph-0: Iris scatter plot")
    print("📝 text-1: Simple text component")
    print("🌐 Navigate to: http://localhost:8051")

    app.run(debug=True, port=8051)
