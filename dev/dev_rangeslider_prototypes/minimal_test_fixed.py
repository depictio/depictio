#!/usr/bin/env python3
"""
Minimal DMC RangeSlider test - FIXED VERSION
Based on the working debug_rangeslider.py structure
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

# Create the simplest possible Dash app
app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        dmc.Container([
            dmc.Title("DMC Component Test - Fixed", order=1, mb="lg"),
            
            # Test 1: Simple RangeSlider (copied from working debug script)
            dmc.Paper([
                dmc.Title("Test 1: RangeSlider", order=3, mb="md"),
                dmc.RangeSlider(
                    id="range1",
                    min=0,
                    max=100,
                    value=[25, 75],
                ),
                html.Div(id="output1"),
            ], p="md", mb="md"),
            
            # Test 2: RangeSlider with step (copied from working debug script)
            dmc.Paper([
                dmc.Title("Test 2: RangeSlider with step", order=3, mb="md"),
                dmc.RangeSlider(
                    id="range2",
                    min=0,
                    max=100,
                    value=[25, 75],
                    step=5,
                ),
                html.Div(id="output2"),
            ], p="md", mb="md"),
            
            # Test 3: RangeSlider with marks (copied from working debug script)
            dmc.Paper([
                dmc.Title("Test 3: RangeSlider with marks", order=3, mb="md"),
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
            ], p="md", mb="md"),
            
            # Test 4: Simple Slider for comparison (copied from working debug script)
            dmc.Paper([
                dmc.Title("Test 4: Simple Slider", order=3, mb="md"),
                dmc.Slider(
                    id="slider1",
                    min=0,
                    max=100,
                    value=50,
                ),
                html.Div(id="output4"),
            ], p="md", mb="md"),
            
        ], size="lg"),
    ]
)

# Callbacks (copied exactly from working debug script)
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

if __name__ == "__main__":
    print("Starting fixed minimal DMC test...")
    print("Navigate to: http://localhost:8089")
    app.run(debug=True, port=8089)