#!/usr/bin/env python3
"""
Theme Test - Test if MantineProvider theme is causing the issue
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

# Test different theme configurations - ALL components must be inside MantineProvider
app.layout = dmc.MantineProvider(
    children=[
        html.H1("Theme Test - All Inside MantineProvider"),
        
        # Test 1: Basic RangeSlider
        html.H2("Basic RangeSlider"),
        dmc.RangeSlider(
            id="basic-range",
            min=0,
            max=10,
            value=[2, 8],
            step=1,
        ),
        html.Div(id="basic-output"),
        
        html.Hr(),
        
        # Test 2: RangeSlider with theme
        html.H2("RangeSlider with Theme"),
        dmc.RangeSlider(
            id="themed-range",
            min=0,
            max=10,
            value=[2, 8],
            step=1,
            color="blue",
        ),
        html.Div(id="themed-output"),
        
        html.Hr(),
        
        # Test 3: RangeSlider with marks
        html.H2("RangeSlider with Marks"),
        dmc.RangeSlider(
            id="marks-range",
            min=0,
            max=10,
            value=[2, 8],
            step=1,
            marks=[
                {"value": 0, "label": "0"},
                {"value": 5, "label": "5"},
                {"value": 10, "label": "10"},
            ],
        ),
        html.Div(id="marks-output"),
    ]
)

@callback(
    Output("basic-output", "children"),
    Input("basic-range", "value"),
)
def update_basic(value):
    print(f"BASIC: {value}")
    return f"Basic: {value}"

@callback(
    Output("themed-output", "children"),
    Input("themed-range", "value"),
)
def update_themed(value):
    print(f"THEMED: {value}")
    return f"Themed: {value}"

@callback(
    Output("marks-output", "children"),
    Input("marks-range", "value"),
)
def update_marks(value):
    print(f"MARKS: {value}")
    return f"Marks: {value}"

if __name__ == "__main__":
    print("Testing different MantineProvider configurations...")
    print("Navigate to: http://localhost:8094")
    app.run(debug=True, port=8094)