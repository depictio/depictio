#!/usr/bin/env python3
"""
Debug RangeSlider issue

Ultra minimal test to debug what's wrong with RangeSlider interaction
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        html.H1("Debug RangeSlider"),
        html.H2("Test 1: Basic RangeSlider"),
        dmc.RangeSlider(
            id="range1",
            min=0,
            max=100,
            value=[25, 75],
        ),
        html.Div(id="output1"),
        html.H2("Test 2: RangeSlider with step"),
        dmc.RangeSlider(
            id="range2",
            min=0,
            max=100,
            value=[25, 75],
            step=5,
        ),
        html.Div(id="output2"),
        html.H2("Test 3: RangeSlider with marks"),
        dmc.RangeSlider(
            id="range3",
            min=0,
            max=100,
            value=[25, 75],
            marks=[
                {"value": 0, "label": "0"},
                {"value": 50, "label": "50"},
                {"value": 100, "label": "100"},
            ],
        ),
        html.Div(id="output3"),
        html.H2("Test 4: Simple Slider for comparison"),
        dmc.Slider(
            id="slider1",
            min=0,
            max=100,
            value=50,
        ),
        html.Div(id="output4"),
        html.H2("Test 5: Button for sanity check"),
        dmc.Button("Click me", id="button"),
        html.Div(id="output5"),
    ]
)


@callback(Output("output1", "children"), Input("range1", "value"))
def update1(value):
    print(f"Range1 callback: {value}")
    return f"Range1: {value}"


@callback(Output("output2", "children"), Input("range2", "value"))
def update2(value):
    print(f"Range2 callback: {value}")
    return f"Range2: {value}"


@callback(Output("output3", "children"), Input("range3", "value"))
def update3(value):
    print(f"Range3 callback: {value}")
    return f"Range3: {value}"


@callback(Output("output4", "children"), Input("slider1", "value"))
def update4(value):
    print(f"Slider1 callback: {value}")
    return f"Slider1: {value}"


@callback(Output("output5", "children"), Input("button", "n_clicks"))
def update5(n_clicks):
    print(f"Button callback: {n_clicks}")
    return f"Button clicked: {n_clicks}"


if __name__ == "__main__":
    print("Starting debug RangeSlider test...")
    print("Navigate to: http://localhost:8088")
    print("Try interacting with each component and check console output")
    app.run(debug=True, port=8088)
