#!/usr/bin/env python3
"""
Simple RangeSlider Prototype
Uses build_interactive function with minimal setup and single callback
"""

import uuid
import dash
import dash_mantine_components as dmc
import polars as pl
from dash import Input, Output, callback, html

# Import depictio components
from depictio.dash.modules.interactive_component.utils import build_interactive

# Initialize Dash app
app = dash.Dash(__name__)

# Simple test data
test_data = pl.DataFrame({
    "values": [1.0, 2.3, 4.5, 3.2, 5.8, 6.1, 4.9, 3.7, 2.1, 5.4]
})

# Mock column specs
cols_json = {
    "values": {
        "type": "float64",
        "description": "Test values",
        "specs": {"min": 1.0, "max": 6.9, "count": 10, "nunique": 10}
    }
}

# Generate component ID
component_id = str(uuid.uuid4())

# App layout
app.layout = dmc.MantineProvider(
    children=[
        html.H1("Simple RangeSlider Test - Fixed Structure"),
        
        html.H2("Generated RangeSlider"),
        html.Div(id="rangeslider-container"),
        html.Div(id="rangeslider-output"),
    ]
)

# Generate the RangeSlider on app start
@callback(
    Output("rangeslider-container", "children"),
    Input("rangeslider-container", "id"),  # Trigger on initial load
)
def create_rangeslider(_):
    print("Creating RangeSlider component...")
    
    # Build the component using build_interactive
    component = build_interactive(
        index=component_id,
        title="Simple RangeSlider Test",
        wf_id="507f1f77bcf86cd799439011",  # Valid ObjectId
        dc_id="507f1f77bcf86cd799439012",  # Valid ObjectId
        dc_config={"test": "config"},
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
        marks_number=5,
        value=[2.0, 5.0],  # Initial value
    )
    
    print(f"Generated component: {type(component)}")
    return component

# Single callback to handle RangeSlider changes - simplified like working version
@callback(
    Output("rangeslider-output", "children"),
    Input({"type": "interactive-component-value", "index": component_id}, "value"),
)
def update_rangeslider(value):
    print(f"RangeSlider callback triggered with value: {value}")
    return f"RangeSlider Value: {value} (Type: {type(value)})"

if __name__ == "__main__":
    print("Starting simple RangeSlider test...")
    print("Navigate to: http://localhost:8090")
    app.run(debug=True, port=8090)