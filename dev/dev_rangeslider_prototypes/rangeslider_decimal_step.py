#!/usr/bin/env python3
"""
Test DMC RangeSlider with decimal step parameter (based on DMC Slider documentation)
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        dmc.Container([
            dmc.Title("DMC RangeSlider with Decimal Steps", order=1, mb="lg"),
            
            # Test based on DMC documentation pattern
            dmc.Text("RangeSlider with decimal step=0.1", mb="sm"),
            dmc.RangeSlider(
                id="decimal-step-rangeslider",
                value=[1.0, 5.0],
                min=0,
                max=10,
                step=0.1,
                styles={"markLabel": {"display": "none"}},
            ),
            html.Div(id="decimal-step-output"),
            
            # Test with our problematic range but proper step
            dmc.Text("Our problematic range (1.0-6.9) with step=0.1", mb="sm", mt="md"),
            dmc.RangeSlider(
                id="problematic-fixed",
                value=[2.0, 5.0],
                min=1.0,
                max=6.9,
                step=0.1,
                styles={"markLabel": {"display": "none"}},
            ),
            html.Div(id="problematic-fixed-output"),
            
            # Test with step=0.5 like in documentation
            dmc.Text("RangeSlider with step=0.5", mb="sm", mt="md"),
            dmc.RangeSlider(
                id="half-step-rangeslider",
                value=[2.0, 5.0],
                min=1.0,
                max=6.9,
                step=0.5,
                styles={"markLabel": {"display": "none"}},
            ),
            html.Div(id="half-step-output"),
            
        ], p="xl"),
    ]
)

@callback(
    Output("decimal-step-output", "children"),
    Input("decimal-step-rangeslider", "value"),
)
def update_decimal_step(value):
    print(f"DECIMAL STEP: {value}")
    return f"Decimal step: {value}"

@callback(
    Output("problematic-fixed-output", "children"),
    Input("problematic-fixed", "value"),
)
def update_problematic_fixed(value):
    print(f"PROBLEMATIC FIXED: {value}")
    return f"Problematic fixed: {value}"

@callback(
    Output("half-step-output", "children"),
    Input("half-step-rangeslider", "value"),
)
def update_half_step(value):
    print(f"HALF STEP: {value}")
    return f"Half step: {value}"

if __name__ == "__main__":
    print("Testing DMC RangeSlider with decimal steps...")
    print("Navigate to: http://localhost:8101")
    app.run(debug=True, port=8101)