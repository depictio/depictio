#!/usr/bin/env python3
"""
Simple test for dash-draggable custom IDs
"""

import dash
import dash_draggable
import dash_mantine_components as dmc
from dash import html

app = dash.Dash(__name__)

app.layout = html.Div([
    html.H1("Simple Draggable Test"),
    html.P("Testing custom IDs: 'my-card-A' and 'my-card-B'"),
    
    dash_draggable.ResponsiveGridLayout(
        id="simple-draggable",
        clearSavedLayout=True,
        layouts={
            "lg": [
                {"i": "my-card-A", "x": 0, "y": 0, "w": 6, "h": 4},
                {"i": "my-card-B", "x": 6, "y": 0, "w": 6, "h": 4},
            ]
        },
        children=[
            html.Div(
                "Card A - Should be on LEFT",
                id="my-card-A",
                style={
                    "backgroundColor": "lightblue",
                    "border": "2px solid blue",
                    "padding": "20px",
                    "height": "100%"
                }
            ),
            html.Div(
                "Card B - Should be on RIGHT",
                id="my-card-B", 
                style={
                    "backgroundColor": "lightgreen",
                    "border": "2px solid green", 
                    "padding": "20px",
                    "height": "100%"
                }
            ),
        ],
        isDraggable=True,
        isResizable=True,
        style={"height": "400px", "width": "100%"}
    )
])

if __name__ == "__main__":
    print("Simple test app running on http://127.0.0.1:8052")
    app.run(debug=True, host="127.0.0.1", port=8052)