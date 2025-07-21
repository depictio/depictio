#!/usr/bin/env python3
"""
Ultra Minimal Test - No themes, no styling, just basic DMC RangeSlider
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, html

app = dash.Dash(__name__)

# Fixed: ALL DMC components must be inside MantineProvider
app.layout = dmc.MantineProvider(
    children=[
        html.H1("Ultra Minimal - Fixed with MantineProvider"),
        dmc.RangeSlider(
            id="ultra-minimal-range",
            min=0,
            max=10,
            value=[2, 8],
            step=1,
        ),
        html.Div(id="output"),
    ]
)

@callback(
    Output("output", "children"),
    Input("ultra-minimal-range", "value"),
)
def update_range(value):
    print(f"ULTRA MINIMAL: {value}")
    return f"Value: {value}"

if __name__ == "__main__":
    print("Ultra minimal test - NO themes, NO providers, NO styling")
    print("Navigate to: http://localhost:8093")
    app.run(debug=True, port=8093)