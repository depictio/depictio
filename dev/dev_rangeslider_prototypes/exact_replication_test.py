#!/usr/bin/env python3
"""
Test that exactly replicates what build_interactive creates
"""

import uuid

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, dcc, html

app = dash.Dash(__name__)

component_id = str(uuid.uuid4())

app.layout = dmc.MantineProvider(
    children=[
        html.H1("Exact Replication Test"),
        # Test 1: Working direct RangeSlider
        html.H2("Test 1: Working Direct"),
        dmc.RangeSlider(
            id="direct-range",
            min=1.0,
            max=6.9,
            value=[2.0, 5.0],
            size="md",
        ),
        html.Div(id="direct-output"),
        # Test 2: Exact replication of build_interactive output
        html.H2("Test 2: Exact Replication"),
        html.Div(
            [
                html.H5(
                    "RangeSlider on values", style={"marginBottom": "0.5rem", "color": "#000000"}
                ),
                dmc.RangeSlider(
                    id={"type": "interactive-component-value", "index": component_id},
                    min=1.0,
                    max=6.9,
                    value=[2.0, 5.0],
                    size="md",
                    color="#000000",
                    marks=[
                        {"value": 1.0, "label": "1.0"},
                        {"value": 2.95, "label": "2.95"},
                        {"value": 4.9, "label": "4.9"},
                        {"value": 6.9, "label": "6.9"},
                    ],
                ),
                dcc.Store(
                    id={"type": "stored-metadata-component", "index": component_id},
                    data={
                        "scale": "linear",
                        "original_value": [2.0, 5.0],
                        "custom_color": "#000000",
                    },
                    storage_type="memory",
                ),
            ]
        ),
        html.Div(id="replication-output"),
        # Test 3: Same as replication but without marks
        html.H2("Test 3: Without Marks"),
        html.Div(
            [
                html.H5(
                    "RangeSlider without marks",
                    style={"marginBottom": "0.5rem", "color": "#000000"},
                ),
                dmc.RangeSlider(
                    id={"type": "interactive-component-value", "index": "no-marks"},
                    min=1.0,
                    max=6.9,
                    value=[2.0, 5.0],
                    size="md",
                    color="#000000",
                ),
                dcc.Store(
                    id={"type": "stored-metadata-component", "index": "no-marks"},
                    data={"scale": "linear"},
                    storage_type="memory",
                ),
            ]
        ),
        html.Div(id="no-marks-output"),
    ]
)


@callback(
    Output("direct-output", "children"),
    Input("direct-range", "value"),
)
def update_direct(value):
    print(f"DIRECT: {value}")
    return f"Direct: {value}"


@callback(
    Output("replication-output", "children"),
    Input({"type": "interactive-component-value", "index": component_id}, "value"),
)
def update_replication(value):
    print(f"REPLICATION: {value}")
    return f"Replication: {value}"


@callback(
    Output("no-marks-output", "children"),
    Input({"type": "interactive-component-value", "index": "no-marks"}, "value"),
)
def update_no_marks(value):
    print(f"NO MARKS: {value}")
    return f"No marks: {value}"


if __name__ == "__main__":
    print("Testing exact replication of build_interactive...")
    print("Navigate to: http://localhost:8098")
    app.run(debug=True, port=8098)
