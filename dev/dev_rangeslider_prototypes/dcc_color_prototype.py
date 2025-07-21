#!/usr/bin/env python3
"""
DCC Slider Color Customization Prototype
Test how to modify DCC Slider/RangeSlider colors through CSS
"""

import dash
from dash import dcc, html, Input, Output, callback

app = dash.Dash(__name__)

# CSS for customizing DCC Slider colors
custom_css = """
/* Custom CSS for DCC Slider colors */

/* Default slider (blue) */
.slider-blue .rc-slider-track {
    background-color: #1976d2 !important;
}
.slider-blue .rc-slider-handle {
    border-color: #1976d2 !important;
}
.slider-blue .rc-slider-handle:hover {
    border-color: #1565c0 !important;
}
.slider-blue .rc-slider-handle:focus {
    border-color: #1565c0 !important;
    box-shadow: 0 0 0 5px rgba(25, 118, 210, 0.2) !important;
}

/* Red slider */
.slider-red .rc-slider-track {
    background-color: #d32f2f !important;
}
.slider-red .rc-slider-handle {
    border-color: #d32f2f !important;
}
.slider-red .rc-slider-handle:hover {
    border-color: #c62828 !important;
}
.slider-red .rc-slider-handle:focus {
    border-color: #c62828 !important;
    box-shadow: 0 0 0 5px rgba(211, 47, 47, 0.2) !important;
}

/* Green slider */
.slider-green .rc-slider-track {
    background-color: #388e3c !important;
}
.slider-green .rc-slider-handle {
    border-color: #388e3c !important;
}
.slider-green .rc-slider-handle:hover {
    border-color: #2e7d32 !important;
}
.slider-green .rc-slider-handle:focus {
    border-color: #2e7d32 !important;
    box-shadow: 0 0 0 5px rgba(56, 142, 60, 0.2) !important;
}

/* Orange slider */
.slider-orange .rc-slider-track {
    background-color: #f57c00 !important;
}
.slider-orange .rc-slider-handle {
    border-color: #f57c00 !important;
}
.slider-orange .rc-slider-handle:hover {
    border-color: #ef6c00 !important;
}
.slider-orange .rc-slider-handle:focus {
    border-color: #ef6c00 !important;
    box-shadow: 0 0 0 5px rgba(245, 124, 0, 0.2) !important;
}

/* Purple slider */
.slider-purple .rc-slider-track {
    background-color: #7b1fa2 !important;
}
.slider-purple .rc-slider-handle {
    border-color: #7b1fa2 !important;
}
.slider-purple .rc-slider-handle:hover {
    border-color: #6a1b9a !important;
}
.slider-purple .rc-slider-handle:focus {
    border-color: #6a1b9a !important;
    box-shadow: 0 0 0 5px rgba(123, 31, 162, 0.2) !important;
}

/* Black slider */
.slider-black .rc-slider-track {
    background-color: #212121 !important;
}
.slider-black .rc-slider-handle {
    border-color: #212121 !important;
}
.slider-black .rc-slider-handle:hover {
    border-color: #000000 !important;
}
.slider-black .rc-slider-handle:focus {
    border-color: #000000 !important;
    box-shadow: 0 0 0 5px rgba(33, 33, 33, 0.2) !important;
}

/* Mark text visibility - CRITICAL for showing slider marks */
/* Use high specificity to override any conflicting styles */
div .rc-slider .rc-slider-mark .rc-slider-mark-text {
    color: #333 !important;
    font-size: 12px !important;
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    position: relative !important;
    transform: none !important;
    white-space: nowrap !important;
    text-align: center !important;
    font-weight: normal !important;
}

div .rc-slider .rc-slider-mark {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    position: relative !important;
    top: 0 !important;
    left: 0 !important;
    width: auto !important;
    height: auto !important;
}

/* Ensure marks are not hidden by parent containers */
.slider-container .rc-slider {
    position: relative !important;
    height: auto !important;
    padding-bottom: 25px !important;
}

.slider-container {
    overflow: visible !important;
}

/* Container styling */
.slider-container {
    margin: 20px 0;
    padding: 20px;
    border: 1px solid #ddd;
    border-radius: 8px;
    background-color: #f9f9f9;
}

.slider-container h3 {
    margin-top: 0;
    color: #333;
}

/* Custom hex color slider - dynamically set via style */
.slider-custom .rc-slider-track {
    background-color: var(--custom-color) !important;
}
.slider-custom .rc-slider-handle {
    border-color: var(--custom-color) !important;
}
.slider-custom .rc-slider-handle:hover {
    border-color: var(--custom-color) !important;
    opacity: 0.8;
}
.slider-custom .rc-slider-handle:focus {
    border-color: var(--custom-color) !important;
    box-shadow: 0 0 0 5px rgba(var(--custom-color-rgb), 0.2) !important;
}
"""

app.layout = html.Div(
    [
        # Inject custom CSS using html.Link with data URI
        html.Link(
            rel="stylesheet",
            href="data:text/css;base64,"
            + __import__("base64").b64encode(custom_css.encode()).decode(),
        ),
        html.H1("DCC Slider Color Customization Prototype", style={"textAlign": "center"}),
        # Blue Slider (default)
        html.Div(
            [
                html.H3("Blue Slider"),
                html.Div(
                    [
                        dcc.Slider(
                            id="blue-slider",
                            min=0,
                            max=10,
                            value=5,
                            marks={i: str(i) for i in range(11)},
                            step=1,
                        )
                    ],
                    className="slider-blue",
                ),
                html.Div(id="blue-output"),
            ],
            className="slider-container",
        ),
        # Red RangeSlider
        html.Div(
            [
                html.H3("Red RangeSlider"),
                html.Div(
                    [
                        dcc.RangeSlider(
                            id="red-rangeslider",
                            min=0,
                            max=10,
                            value=[2, 8],
                            marks={i: str(i) for i in range(11)},
                            step=1,
                        )
                    ],
                    className="slider-red",
                ),
                html.Div(id="red-output"),
            ],
            className="slider-container",
        ),
        # Green Slider
        html.Div(
            [
                html.H3("Green Slider"),
                html.Div(
                    [
                        dcc.Slider(
                            id="green-slider",
                            min=1.0,
                            max=6.9,
                            value=3.5,
                            marks={i: f"{i:.1f}" for i in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 6.9]},
                            step=0.1,
                        )
                    ],
                    className="slider-green",
                ),
                html.Div(id="green-output"),
            ],
            className="slider-container",
        ),
        # Orange RangeSlider (decimal range)
        html.Div(
            [
                html.H3("Orange RangeSlider (Decimal Range)"),
                html.Div(
                    [
                        dcc.RangeSlider(
                            id="orange-rangeslider",
                            min=1.0,
                            max=6.9,
                            value=[2.0, 5.0],
                            marks={i: f"{i:.1f}" for i in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 6.9]},
                            step=0.1,
                        )
                    ],
                    className="slider-orange",
                ),
                html.Div(id="orange-output"),
            ],
            className="slider-container",
        ),
        # Purple Slider
        html.Div(
            [
                html.H3("Purple Slider"),
                html.Div(
                    [
                        dcc.Slider(
                            id="purple-slider",
                            min=0,
                            max=100,
                            value=50,
                            marks={i: str(i) for i in range(0, 101, 25)},
                            step=5,
                        )
                    ],
                    className="slider-purple",
                ),
                html.Div(id="purple-output"),
            ],
            className="slider-container",
        ),
        # Black RangeSlider
        html.Div(
            [
                html.H3("Black RangeSlider"),
                html.Div(
                    [
                        dcc.RangeSlider(
                            id="black-rangeslider",
                            min=0,
                            max=100,
                            value=[25, 75],
                            marks={i: str(i) for i in range(0, 101, 25)},
                            step=5,
                        )
                    ],
                    className="slider-black",
                ),
                html.Div(id="black-output"),
            ],
            className="slider-container",
        ),
        # Custom hex color slider
        html.Div(
            [
                html.H3("Custom Hex Color Slider (#ff6b35)"),
                html.Div(
                    [
                        dcc.Slider(
                            id="custom-slider",
                            min=0,
                            max=10,
                            value=5,
                            marks={i: str(i) for i in range(11)},
                            step=1,
                        )
                    ],
                    className="slider-custom",
                    style={"--custom-color": "#ff6b35"},
                ),
                html.Div(id="custom-output"),
            ],
            className="slider-container",
        ),
        # Color picker to dynamically change custom slider
        html.Div(
            [
                html.H3("Dynamic Color Picker"),
                dcc.Input(
                    id="color-input",
                    type="text",
                    placeholder="Enter hex color (e.g., #ff0000)",
                    value="#ff6b35",
                    style={"marginRight": "10px"},
                ),
                html.Button("Apply Color", id="apply-color-btn"),
                html.Div(id="color-feedback"),
            ],
            className="slider-container",
        ),
        html.Div(id="dynamic-slider-container"),
    ]
)


# Callbacks for all sliders
@callback(Output("blue-output", "children"), Input("blue-slider", "value"))
def update_blue(value):
    return f"Blue Slider: {value}"


@callback(Output("red-output", "children"), Input("red-rangeslider", "value"))
def update_red(value):
    return f"Red RangeSlider: {value}"


@callback(Output("green-output", "children"), Input("green-slider", "value"))
def update_green(value):
    return f"Green Slider: {value}"


@callback(Output("orange-output", "children"), Input("orange-rangeslider", "value"))
def update_orange(value):
    return f"Orange RangeSlider: {value}"


@callback(Output("purple-output", "children"), Input("purple-slider", "value"))
def update_purple(value):
    return f"Purple Slider: {value}"


@callback(Output("black-output", "children"), Input("black-rangeslider", "value"))
def update_black(value):
    return f"Black RangeSlider: {value}"


@callback(Output("custom-output", "children"), Input("custom-slider", "value"))
def update_custom(value):
    return f"Custom Slider: {value}"


# Dynamic color application
@callback(
    [Output("dynamic-slider-container", "children"), Output("color-feedback", "children")],
    Input("apply-color-btn", "n_clicks"),
    Input("color-input", "value"),
    prevent_initial_call=True,
)
def apply_dynamic_color(_n_clicks, color_value):
    if not color_value or not color_value.startswith("#"):
        return html.Div(), "Please enter a valid hex color (e.g., #ff0000)"

    return html.Div(
        [
            html.H3(f"Dynamic Color Slider ({color_value})"),
            html.Div(
                [
                    dcc.RangeSlider(
                        id="dynamic-rangeslider",
                        min=0,
                        max=10,
                        value=[3, 7],
                        marks={i: str(i) for i in range(11)},
                        step=1,
                    )
                ],
                className="slider-custom",
                style={"--custom-color": color_value},
            ),
        ],
        className="slider-container",
    ), f"Applied color: {color_value}"


if __name__ == "__main__":
    print("DCC Slider Color Customization Prototype")
    print("Navigate to: http://localhost:8102")
    print("This prototype shows how to customize DCC Slider colors using CSS")
    app.run(debug=True, port=8102)
