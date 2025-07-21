#!/usr/bin/env python3
"""
Exact copy of the working debug_rangeslider.py structure
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        html.H1("Exact Copy of Working Structure"),
        html.H2("Test 1: Basic RangeSlider"),
        dmc.RangeSlider(
            id="range1",
            min=0,
            max=100,
            value=[25, 75],
        ),
        html.Div(id="output1"),
    ]
)


@callback(Output("output1", "children"), Input("range1", "value"))
def update1(value):
    print(f"Range1 callback: {value}")
    return f"Range1: {value}"


if __name__ == "__main__":
    print("Starting exact copy test...")
    print("Navigate to: http://localhost:8095")
    app.run(debug=True, port=8095)
