#!/usr/bin/env python3
"""
Minimal DMC RangeSlider test

This is the most basic test to see if DMC RangeSlider works at all.
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

# Create the simplest possible Dash app
app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        dmc.Container(
            [
                dmc.Title("DMC Component Test", order=1, mb="lg"),
                # Test 1: Simple Text
                dmc.Paper(
                    [
                        dmc.Title("Test 1: Simple Text", order=3, mb="md"),
                        dmc.Text("This is a simple text component"),
                    ],
                    p="md",
                    mb="md",
                ),
                # Test 2: Simple Button
                dmc.Paper(
                    [
                        dmc.Title("Test 2: Simple Button", order=3, mb="md"),
                        dmc.Button("Click me", id="test-button"),
                        html.Div(id="button-output"),
                    ],
                    p="md",
                    mb="md",
                ),
                # Test 3: Simple Slider
                dmc.Paper(
                    [
                        dmc.Title("Test 3: Simple Slider", order=3, mb="md"),
                        dmc.Slider(
                            id="test-slider",
                            min=0,
                            max=10,
                            value=5,
                        ),
                        html.Div(id="slider-output"),
                    ],
                    p="md",
                    mb="md",
                ),
                # Test 4: Simple RangeSlider
                dmc.Paper(
                    [
                        dmc.Title("Test 4: Simple RangeSlider", order=3, mb="md"),
                        dmc.RangeSlider(
                            id="test-rangeslider",
                            min=0,
                            max=10,
                            value=[3, 7],
                            step=1,
                        ),
                        html.Div(id="rangeslider-output"),
                    ],
                    p="md",
                    mb="md",
                ),
                # Test 5: RangeSlider with no initial value
                dmc.Paper(
                    [
                        dmc.Title("Test 5: RangeSlider (no value)", order=3, mb="md"),
                        dmc.RangeSlider(
                            id="test-rangeslider-no-value",
                            min=0,
                            max=10,
                            step=1,
                            value=[0, 10],
                        ),
                        html.Div(id="rangeslider-no-value-output"),
                    ],
                    p="md",
                    mb="md",
                ),
            ],
            size="lg",
        ),
    ]
)


# Callbacks
@callback(
    Output("button-output", "children"),
    Input("test-button", "n_clicks"),
    prevent_initial_call=True,
)
def button_click(n_clicks):
    return f"Button clicked {n_clicks} times"


@callback(
    Output("slider-output", "children"),
    Input("test-slider", "value"),
    prevent_initial_call=True,
)
def slider_change(value):
    return f"Slider value: {value}"


@callback(
    Output("rangeslider-output", "children"),
    Input("test-rangeslider", "value"),
    prevent_initial_call=True,
)
def rangeslider_change(value):
    print(f"RangeSlider callback: {value}")
    return f"RangeSlider value: {value}"


@callback(
    Output("rangeslider-no-value-output", "children"),
    Input("test-rangeslider-no-value", "value"),
    prevent_initial_call=True,
)
def rangeslider_no_value_change(value):
    print(f"RangeSlider (no value) callback: {value}")
    return f"RangeSlider (no value) value: {value}"


if __name__ == "__main__":
    print("Starting minimal DMC test...")
    print("Navigate to: http://localhost:8087")
    app.run(debug=True, port=8087)
