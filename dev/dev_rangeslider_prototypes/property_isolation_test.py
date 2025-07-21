#!/usr/bin/env python3
"""
Test to isolate which property is causing the RangeSlider interaction issue
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        html.H1("Property Isolation Test"),
        
        # Test 1: Integer range (working baseline)
        html.H2("Test 1: Integer Range (Baseline)"),
        dmc.RangeSlider(
            id="integer-range",
            min=0,
            max=100,
            value=[25, 75],
        ),
        html.Div(id="integer-output"),
        
        # Test 2: Decimal range, no other properties
        html.H2("Test 2: Decimal Range Only"),
        dmc.RangeSlider(
            id="decimal-range",
            min=1.0,
            max=6.9,
            value=[2.0, 5.0],
        ),
        html.Div(id="decimal-output"),
        
        # Test 3: Integer range with color
        html.H2("Test 3: Integer Range + Color"),
        dmc.RangeSlider(
            id="integer-color",
            min=0,
            max=100,
            value=[25, 75],
            color="#000000",
        ),
        html.Div(id="integer-color-output"),
        
        # Test 4: Decimal range with color
        html.H2("Test 4: Decimal Range + Color"),
        dmc.RangeSlider(
            id="decimal-color",
            min=1.0,
            max=6.9,
            value=[2.0, 5.0],
            color="#000000",
        ),
        html.Div(id="decimal-color-output"),
        
        # Test 5: Integer range with marks
        html.H2("Test 5: Integer Range + Marks"),
        dmc.RangeSlider(
            id="integer-marks",
            min=0,
            max=100,
            value=[25, 75],
            marks=[
                {"value": 0, "label": "0"},
                {"value": 50, "label": "50"},
                {"value": 100, "label": "100"},
            ],
        ),
        html.Div(id="integer-marks-output"),
        
        # Test 6: Decimal range with marks
        html.H2("Test 6: Decimal Range + Marks"),
        dmc.RangeSlider(
            id="decimal-marks",
            min=1.0,
            max=6.9,
            value=[2.0, 5.0],
            marks=[
                {"value": 1.0, "label": "1.0"},
                {"value": 6.9, "label": "6.9"},
            ],
        ),
        html.Div(id="decimal-marks-output"),
    ]
)

@callback(Output("integer-output", "children"), Input("integer-range", "value"))
def update_integer(value):
    print(f"INTEGER: {value}")
    return f"Integer: {value}"

@callback(Output("decimal-output", "children"), Input("decimal-range", "value"))
def update_decimal(value):
    print(f"DECIMAL: {value}")
    return f"Decimal: {value}"

@callback(Output("integer-color-output", "children"), Input("integer-color", "value"))
def update_integer_color(value):
    print(f"INTEGER+COLOR: {value}")
    return f"Integer+Color: {value}"

@callback(Output("decimal-color-output", "children"), Input("decimal-color", "value"))
def update_decimal_color(value):
    print(f"DECIMAL+COLOR: {value}")
    return f"Decimal+Color: {value}"

@callback(Output("integer-marks-output", "children"), Input("integer-marks", "value"))
def update_integer_marks(value):
    print(f"INTEGER+MARKS: {value}")
    return f"Integer+Marks: {value}"

@callback(Output("decimal-marks-output", "children"), Input("decimal-marks", "value"))
def update_decimal_marks(value):
    print(f"DECIMAL+MARKS: {value}")
    return f"Decimal+Marks: {value}"

if __name__ == "__main__":
    print("Testing property isolation...")
    print("Navigate to: http://localhost:8099")
    app.run(debug=True, port=8099)