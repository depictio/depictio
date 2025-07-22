#!/usr/bin/env python3
"""
Test DMC RangeSlider with decimal steps based on DMC documentation patterns
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

# Define marks for testing
marks = [
    {"value": 0, "label": "0"},
    {"value": 25, "label": "25"},
    {"value": 50, "label": "50"},
    {"value": 75, "label": "75"},
    {"value": 100, "label": "100"},
]

app.layout = dmc.MantineProvider(
    children=[
        dmc.Container(
            [
                dmc.Title("DMC Decimal Test", order=1, mb="lg"),
                # Test 1: DMC Slider with decimal step (from documentation)
                dmc.Text("DMC Slider - Decimal step", mb="sm"),
                dmc.Slider(
                    id="decimal-slider",
                    value=0,
                    min=-10,
                    max=10,
                    step=0.1,
                    styles={"markLabel": {"display": "none"}},
                ),
                html.Div(id="decimal-slider-output"),
                # Test 2: DMC RangeSlider with decimal step (our use case)
                dmc.Text("DMC RangeSlider - Decimal step", mb="sm", mt="md"),
                dmc.RangeSlider(
                    id="decimal-rangeslider",
                    value=[-2.5, 2.5],
                    min=-10,
                    max=10,
                    step=0.1,
                    styles={"markLabel": {"display": "none"}},
                ),
                html.Div(id="decimal-rangeslider-output"),
                # Test 3: DMC RangeSlider with decimal range (1.0-6.9) and step
                dmc.Text("DMC RangeSlider - Our problematic range", mb="sm", mt="md"),
                dmc.RangeSlider(
                    id="problematic-rangeslider",
                    value=[2.0, 5.0],
                    min=1.0,
                    max=6.9,
                    step=0.1,
                    styles={"markLabel": {"display": "none"}},
                ),
                html.Div(id="problematic-rangeslider-output"),
                # Test 4: DMC RangeSlider with integer marks and decimal step
                dmc.Text("DMC RangeSlider - Integer marks + decimal step", mb="sm", mt="md"),
                dmc.RangeSlider(
                    id="marks-rangeslider",
                    value=[25, 75],
                    min=0,
                    max=100,
                    step=0.5,
                    marks=marks,
                    styles={"markLabel": {"display": "none"}},
                ),
                html.Div(id="marks-rangeslider-output"),
            ],
            p="xl",
        ),
    ]
)


@callback(
    Output("decimal-slider-output", "children"),
    Input("decimal-slider", "value"),
)
def update_decimal_slider(value):
    print(f"DECIMAL SLIDER: {value}")
    return f"Decimal Slider: {value}"


@callback(
    Output("decimal-rangeslider-output", "children"),
    Input("decimal-rangeslider", "value"),
)
def update_decimal_rangeslider(value):
    print(f"DECIMAL RANGESLIDER: {value}")
    return f"Decimal RangeSlider: {value}"


@callback(
    Output("problematic-rangeslider-output", "children"),
    Input("problematic-rangeslider", "value"),
)
def update_problematic_rangeslider(value):
    print(f"PROBLEMATIC RANGESLIDER: {value}")
    return f"Problematic RangeSlider: {value}"


@callback(
    Output("marks-rangeslider-output", "children"),
    Input("marks-rangeslider", "value"),
)
def update_marks_rangeslider(value):
    print(f"MARKS RANGESLIDER: {value}")
    return f"Marks RangeSlider: {value}"


if __name__ == "__main__":
    print("Testing DMC decimal functionality...")
    print("Navigate to: http://localhost:8100")
    app.run(debug=True, port=8100)
