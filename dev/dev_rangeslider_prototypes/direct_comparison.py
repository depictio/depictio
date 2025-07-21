#!/usr/bin/env python3
"""
Direct Comparison Test
Compare a working direct DMC RangeSlider with a generated one using identical properties
"""

import uuid
import dash
import dash_mantine_components as dmc
import polars as pl
from dash import Input, Output, callback, html

# Import depictio components
from depictio.dash.modules.interactive_component.utils import build_interactive

app = dash.Dash(__name__)

# Test data and specs
test_data = pl.DataFrame({"values": [1.0, 2.3, 4.5, 3.2, 5.8, 6.1, 4.9, 3.7, 2.1, 5.4]})
cols_json = {
    "values": {
        "type": "float64",
        "specs": {"min": 1.0, "max": 6.9, "count": 10, "nunique": 10}
    }
}

component_id = str(uuid.uuid4())

app.layout = dmc.MantineProvider(
    children=[
        dmc.Container([
            dmc.Title("Direct Comparison Test", order=1, mb="lg"),
            
            # Working direct RangeSlider
            dmc.Paper([
                dmc.Title("Working Direct RangeSlider", order=3, mb="md"),
                dmc.RangeSlider(
                    id="direct-range",
                    min=1.0,
                    max=6.9,
                    value=[2.0, 5.0],
                    step=0.1,  # Same step as our generated one should have
                    size="md",
                    color="#000000",
                    marks=[
                        {"value": 1.0, "label": "1.0"},
                        {"value": 2.95, "label": "2.95"},
                        {"value": 4.9, "label": "4.9"},
                        {"value": 6.9, "label": "6.9"},
                    ],
                ),
                html.Div(id="direct-output"),
            ], p="md", mb="md"),
            
            # Generated RangeSlider
            dmc.Paper([
                dmc.Title("Generated RangeSlider", order=3, mb="md"),
                html.Div(id="generated-container"),
                html.Div(id="generated-output"),
            ], p="md"),
            
        ], size="lg"),
    ]
)

@callback(
    Output("generated-container", "children"),
    Input("generated-container", "id"),
)
def create_generated(_):
    print("Creating generated RangeSlider with exact same properties...")
    
    component = build_interactive(
        index=component_id,
        title="Generated RangeSlider",
        wf_id="507f1f77bcf86cd799439011",
        dc_id="507f1f77bcf86cd799439012",
        dc_config={},
        column_name="values",
        column_type="float64",
        interactive_component_type="RangeSlider",
        cols_json=cols_json,
        df=test_data,
        access_token="test-token",
        stepper=False,
        build_frame=False,
        scale="linear",
        color="#000000",
        marks_number=4,  # Same number as direct slider
        value=[2.0, 5.0],  # Same initial value
    )
    
    return component

@callback(
    Output("direct-output", "children"),
    Input("direct-range", "value"),
)
def update_direct(value):
    print(f"DIRECT RangeSlider: {value}")
    return f"Direct: {value}"

@callback(
    Output("generated-output", "children"),
    Input({"type": "interactive-component-value", "index": component_id}, "value"),
)
def update_generated(value):
    print(f"GENERATED RangeSlider: {value}")
    return f"Generated: {value}"

if __name__ == "__main__":
    print("Starting direct comparison test...")
    print("Navigate to: http://localhost:8091")
    app.run(debug=True, port=8091)