#!/usr/bin/env python3
"""
Test if HTML div wrapper is causing the RangeSlider interaction issue
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html, dcc

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        html.H1("Wrapper Test"),
        
        # Test 1: Direct RangeSlider (working)
        html.H2("Test 1: Direct RangeSlider"),
        dmc.RangeSlider(
            id="direct-range",
            min=0,
            max=100,
            value=[25, 75],
        ),
        html.Div(id="direct-output"),
        
        # Test 2: RangeSlider wrapped in html.Div (like build_interactive)
        html.H2("Test 2: RangeSlider wrapped in html.Div"),
        html.Div([
            html.H5("Wrapped RangeSlider", style={"marginBottom": "0.5rem"}),
            dmc.RangeSlider(
                id="wrapped-range",
                min=0,
                max=100,
                value=[25, 75],
            ),
            dcc.Store(id="dummy-store", data={"test": "data"}),
        ]),
        html.Div(id="wrapped-output"),
        
        # Test 3: RangeSlider wrapped in dmc.Container
        html.H2("Test 3: RangeSlider wrapped in dmc.Container"),
        dmc.Container([
            dmc.Title("Container RangeSlider", order=5),
            dmc.RangeSlider(
                id="container-range",
                min=0,
                max=100,
                value=[25, 75],
            ),
        ]),
        html.Div(id="container-output"),
    ]
)

@callback(
    Output("direct-output", "children"),
    Input("direct-range", "value"),
)
def update_direct(value):
    print(f"DIRECT: {value}")
    return f"Direct: {value}"

@callback(
    Output("wrapped-output", "children"),
    Input("wrapped-range", "value"),
)
def update_wrapped(value):
    print(f"WRAPPED: {value}")
    return f"Wrapped: {value}"

@callback(
    Output("container-output", "children"),
    Input("container-range", "value"),
)
def update_container(value):
    print(f"CONTAINER: {value}")
    return f"Container: {value}"

if __name__ == "__main__":
    print("Testing wrapper effects on RangeSlider...")
    print("Navigate to: http://localhost:8097")
    app.run(debug=True, port=8097)