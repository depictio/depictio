#!/usr/bin/env python3
"""
DCC RangeSlider Mark Positioning Debug
Test different mark positioning strategies to find what works
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, callback, dcc, html

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    html.Div(
        [
            html.H1("RangeSlider Mark Positioning Debug", style={"textAlign": "center"}),
            # Test 1: Exact float positions
            html.Div([html.H3("Test 0"), dcc.RangeSlider(min=0.1, max=6.9, value=[3.1, 5.3])]),
            html.Div(
                [
                    html.H3("Test 0"),
                    dmc.RangeSlider(
                        minRange=0.2,
                        min=0,
                        max=1,
                        step=0.0005,
                        value=[0.1245, 0.5535],
                        showLabelOnHover=True,
                        labelAlwaysOn=False,
                    ),
                ]
            ),
            # Test 1: Exact float positions
            html.Div(
                [
                    html.H3("Test 1: Exact Float Positions"),
                    html.P(
                        "marks = {1.0: '1.0', 2.0: '2.0', 3.0: '3.0', 4.0: '4.0', 5.0: '5.0', 6.0: '6.0', 6.9: '6.9'}"
                    ),
                    dcc.RangeSlider(
                        id="test1",
                        min=1.0,
                        max=6.9,
                        value=[2.0, 5.0],
                        marks={i: f"{i:.1f}" for i in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 6.9]},
                        step=0.1,
                    ),
                    html.Div(id="test1-output"),
                ],
                style={"margin": "20px", "padding": "20px", "border": "1px solid #ddd"},
            ),
            # Test 2: String keys with exact slider bounds
            html.Div(
                [
                    html.H3("Test 2: Force Include Min/Max as First/Last"),
                    html.P("marks = {1.0: '1.0 (MIN)', 6.9: '6.9 (MAX)', ...}"),
                    dcc.RangeSlider(
                        id="test2",
                        min=1.0,
                        max=6.9,
                        value=[2.0, 5.0],
                        marks={
                            1.0: "1.0 (MIN)",
                            2.0: "2.0",
                            3.0: "3.0",
                            4.0: "4.0",
                            5.0: "5.0",
                            6.0: "6.0",
                            6.9: "6.9 (MAX)",
                        },
                        step=0.1,
                    ),
                    html.Div(id="test2-output"),
                ],
                style={"margin": "20px", "padding": "20px", "border": "1px solid #ddd"},
            ),
            # Test 3: Fewer marks to see if it's a density issue
            html.Div(
                [
                    html.H3("Test 3: Sparse Marks (Only Min/Max/Middle)"),
                    html.P("marks = {1.0: '1.0', 4.0: '4.0', 6.9: '6.9'}"),
                    dcc.RangeSlider(
                        id="test3",
                        min=1.0,
                        max=6.9,
                        value=[2.0, 5.0],
                        marks={1.0: "1.0", 4.0: "4.0", 6.9: "6.9"},
                        step=0.1,
                    ),
                    html.Div(id="test3-output"),
                ],
                style={"margin": "20px", "padding": "20px", "border": "1px solid #ddd"},
            ),
            # Test 4: Integer equivalents to see if float precision is the issue
            html.Div(
                [
                    html.H3("Test 4: Scale to Integer Range"),
                    html.P(
                        "min=10, max=69, marks at 10,20,30,40,50,60,69 then divide by 10 for display"
                    ),
                    dcc.RangeSlider(
                        id="test4",
                        min=10,
                        max=69,
                        value=[20, 50],
                        marks={i: f"{i / 10:.1f}" for i in [10, 20, 30, 40, 50, 60, 69]},
                        step=1,
                    ),
                    html.Div(id="test4-output"),
                ],
                style={"margin": "20px", "padding": "20px", "border": "1px solid #ddd"},
            ),
            # Test 5: Check if it's specific to 1.0 as min
            html.Div(
                [
                    html.H3("Test 5: Different Min Value (2.0-6.9)"),
                    html.P("min=2.0, max=6.9 to see if 1.0 is problematic"),
                    dcc.RangeSlider(
                        id="test5",
                        min=2.0,
                        max=6.9,
                        value=[3.0, 5.0],
                        marks={i: f"{i:.1f}" for i in [2.0, 3.0, 4.0, 5.0, 6.0, 6.9]},
                        step=0.1,
                    ),
                    html.Div(id="test5-output"),
                ],
                style={"margin": "20px", "padding": "20px", "border": "1px solid #ddd"},
            ),
        ]
    )
)


# Callbacks
@callback(Output("test1-output", "children"), Input("test1", "value"))
def update_test1(value):
    return f"Test 1: {value}"


@callback(Output("test2-output", "children"), Input("test2", "value"))
def update_test2(value):
    return f"Test 2: {value}"


@callback(Output("test3-output", "children"), Input("test3", "value"))
def update_test3(value):
    return f"Test 3: {value}"


@callback(Output("test4-output", "children"), Input("test4", "value"))
def update_test4(value):
    return f"Test 4: {value} (scaled: {[v / 10 for v in value]})"


@callback(Output("test5-output", "children"), Input("test5", "value"))
def update_test5(value):
    return f"Test 5: {value}"


if __name__ == "__main__":
    print("RangeSlider Mark Positioning Debug")
    print("Navigate to: http://localhost:8104")
    print("Testing different mark positioning strategies")
    app.run(debug=True, port=8104)
