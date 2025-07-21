#!/usr/bin/env python3
"""
Test to confirm inverse behavior and try different DMC RangeSlider configurations
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    children=[
        html.H1("Inverse Behavior Test"),
        # Test 1: Different step sizes
        html.H2("Test 1: Step 1.0"),
        dmc.RangeSlider(
            id="step-1",
            min=0,
            max=10,
            value=[2, 8],
            step=1.0,
        ),
        html.Div(id="step-1-output"),
    ]
)


@callback(Output("step-1-output", "children"), Input("step-1", "value"))
def update_step_1(value):
    print(f"Step 1.0: {value}")
    return f"Step 1.0: {value}"


if __name__ == "__main__":
    print("Testing inverse behavior with different configurations...")
    print("Navigate to: http://localhost:8096")
    app.run(debug=True, port=8096)
