#!/usr/bin/env python3
"""
Test script for dash-draggable with Dash v3 - Testing UUID ID behavior
"""

import uuid

import dash
import dash_draggable
from dash import Input, Output, State, callback, dcc, html


# Generate UUID-based IDs like in depictio
def generate_unique_index():
    return str(uuid.uuid4())


# Test UUIDs
uuid1 = generate_unique_index()
uuid2 = generate_unique_index()

print(f"Dash version: {dash.__version__}")
print(f"dash-draggable version: {dash_draggable.__version__}")
print(f"UUID 1: {uuid1}")
print(f"UUID 2: {uuid2}")

# Create the app
app = dash.Dash(__name__)

# Initial layout with UUID-based IDs
initial_layout = {
    "lg": [
        {"i": f"box-{uuid1}", "x": 0, "y": 0, "w": 6, "h": 4},
        {"i": f"box-{uuid2}", "x": 6, "y": 0, "w": 6, "h": 4},
    ]
}

# Initial children with UUID-based IDs
initial_children = [
    html.Div(
        id=f"box-{uuid1}",
        key=f"box-{uuid1}",
        children=[
            html.H3(f"Component 1"),
            html.P(f"UUID: {uuid1}"),
            html.P("This should be draggable with UUID ID"),
        ],
        style={"border": "1px solid #ccc", "padding": "10px", "background": "#f9f9f9"},
    ),
    html.Div(
        id=f"box-{uuid2}",
        key=f"box-{uuid2}",
        children=[
            html.H3(f"Component 2"),
            html.P(f"UUID: {uuid2}"),
            html.P("This should also be draggable with UUID ID"),
        ],
        style={"border": "1px solid #ccc", "padding": "10px", "background": "#f0f0f0"},
    ),
]

app.layout = html.Div(
    [
        html.H1("Dash v3 + dash-draggable UUID ID Test"),
        html.Div(id="output"),
        html.Hr(),
        dash_draggable.ResponsiveGridLayout(
            id="draggable-grid",
            children=initial_children,
            layouts=initial_layout,
            clearSavedLayout=False,
            isDraggable=True,
            isResizable=True,
            save=False,  # Disable saving for testing
            style={"height": "400px", "border": "2px solid #333"},
        ),
    ]
)


# Callback to monitor layout changes
@app.callback(
    Output("output", "children"), Input("draggable-grid", "layouts"), prevent_initial_call=True
)
def update_output(layouts):
    if layouts:
        return html.Div([html.H3("Current Layout:"), html.Pre(str(layouts))])
    return "No layout data received"


if __name__ == "__main__":
    print("Starting Dash v3 test...")
    app.run(debug=True, port=8051)
