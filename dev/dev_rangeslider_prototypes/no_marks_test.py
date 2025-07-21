#!/usr/bin/env python3
"""
No Marks Test
Test if the marks are causing the interaction issue
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        dmc.Container([
            dmc.Title("No Marks Test", order=1, mb="lg"),
            
            # Test 1: RangeSlider with marks
            dmc.Paper([
                dmc.Title("With Marks", order=3, mb="md"),
                dmc.RangeSlider(
                    id="with-marks",
                    min=1.0,
                    max=6.9,
                    value=[2.0, 5.0],
                    step=0.1,
                    marks=[
                        {"value": 1.0, "label": "1.0"},
                        {"value": 6.9, "label": "6.9"},
                    ],
                ),
                html.Div(id="with-marks-output"),
            ], p="md", mb="md"),
            
            # Test 2: RangeSlider without marks
            dmc.Paper([
                dmc.Title("Without Marks", order=3, mb="md"),
                dmc.RangeSlider(
                    id="no-marks",
                    min=1.0,
                    max=6.9,
                    value=[2.0, 5.0],
                    step=0.1,
                ),
                html.Div(id="no-marks-output"),
            ], p="md", mb="md"),
            
            # Test 3: RangeSlider with integer range
            dmc.Paper([
                dmc.Title("Integer Range", order=3, mb="md"),
                dmc.RangeSlider(
                    id="integer-range",
                    min=0,
                    max=10,
                    value=[2, 5],
                    step=1,
                ),
                html.Div(id="integer-output"),
            ], p="md"),
            
        ], size="lg"),
    ]
)

@callback(
    Output("with-marks-output", "children"),
    Input("with-marks", "value"),
)
def update_with_marks(value):
    print(f"WITH MARKS: {value}")
    return f"With marks: {value}"

@callback(
    Output("no-marks-output", "children"),
    Input("no-marks", "value"),
)
def update_no_marks(value):
    print(f"NO MARKS: {value}")
    return f"No marks: {value}"

@callback(
    Output("integer-output", "children"),
    Input("integer-range", "value"),
)
def update_integer(value):
    print(f"INTEGER: {value}")
    return f"Integer: {value}"

if __name__ == "__main__":
    print("Starting no marks test...")
    print("Navigate to: http://localhost:8092")
    app.run(debug=True, port=8092)