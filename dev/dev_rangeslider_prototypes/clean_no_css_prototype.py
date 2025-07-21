#!/usr/bin/env python3
"""
Clean DCC RangeSlider Prototype - No Custom CSS
Test if marks show up without any custom styling
"""

import dash
from dash import dcc, html, Input, Output, callback

app = dash.Dash(__name__)

app.layout = html.Div([
    html.H1("Clean RangeSlider Prototype - No CSS", style={"textAlign": "center"}),
    
    # Orange RangeSlider (decimal range) - exactly like the problematic one
    html.Div([
        html.H3("Orange RangeSlider (Decimal Range) - No CSS"),
        dcc.RangeSlider(
            id="orange-rangeslider",
            min=1.0,
            max=6.9,
            value=[2.0, 5.0],
            marks={i: f"{i:.1f}" for i in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 6.9]},
            step=0.1,
        ),
        html.Div(id="orange-output"),
    ], style={"margin": "20px", "padding": "20px", "border": "1px solid #ddd"}),
    
    # Simple integer range for comparison
    html.Div([
        html.H3("Integer RangeSlider - No CSS"),
        dcc.RangeSlider(
            id="int-rangeslider",
            min=0,
            max=10,
            value=[2, 8],
            marks={i: str(i) for i in range(11)},
            step=1,
        ),
        html.Div(id="int-output"),
    ], style={"margin": "20px", "padding": "20px", "border": "1px solid #ddd"}),
])

@callback(Output("orange-output", "children"), Input("orange-rangeslider", "value"))
def update_orange(value):
    return f"Orange RangeSlider: {value}"

@callback(Output("int-output", "children"), Input("int-rangeslider", "value"))
def update_int(value):
    return f"Integer RangeSlider: {value}"

if __name__ == "__main__":
    print("Clean RangeSlider Prototype - No CSS")
    print("Navigate to: http://localhost:8103")
    print("Testing if marks show without any custom CSS")
    app.run(debug=True, port=8103)