"""
Version 4 RangeSlider Prototype

This prototype tests the DMC RangeSlider component with:
- Null value handling from database
- Custom color personalization
- Linear/Log10 scale selection
- Configurable marks (3-10)
- Proper value validation and cleaning
- Theme compatibility (light/dark mode)

Run with: python version4_basic_rangeslider.py
Navigate to: http://localhost:8086
"""

import uuid

import dash
import dash_mantine_components as dmc
import polars as pl
from dash import Input, Output, State, callback, dcc, html
from dash_iconify import DashIconify

# Import depictio components and utilities
from depictio.dash.colors import colors
from depictio.dash.modules.interactive_component.utils import build_interactive

# Initialize Dash app
app = dash.Dash(__name__)

# Sample data for testing
sample_data = pl.DataFrame(
    {
        "numeric_column": [1.0, 2.3, 4.5, 3.2, 5.8, 6.1, 4.9, 3.7, 2.1, 5.4],
        "float_column": [0.5, 1.2, 2.8, 4.1, 5.5, 6.9, 3.3, 2.7, 1.8, 4.6],
        "int_column": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    }
)

# Mock column specs (simulating database structure)
mock_cols_json = {
    "numeric_column": {
        "type": "float64",
        "description": "Sample numeric column for testing",
        "specs": {"min": 1.0, "max": 6.9, "count": 10, "nunique": 10},
    },
    "float_column": {
        "type": "float64",
        "description": "Another floating point column",
        "specs": {"min": 0.5, "max": 6.9, "count": 10, "nunique": 10},
    },
    "int_column": {
        "type": "int64",
        "description": "Integer column for testing",
        "specs": {"min": 1, "max": 10, "count": 10, "nunique": 10},
    },
}

# Minimal theme CSS - remove potentially conflicting styles
theme_css = """
.test-container {
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 20px;
    margin: 10px;
}

.component-display {
    border: 2px solid #ddd;
    border-radius: 8px;
    padding: 20px;
    margin: 10px 0;
    min-height: 150px;
}
"""

# App layout
app.layout = dmc.MantineProvider(
    theme={"colorScheme": "light"},
    children=[
        dcc.Store(id="theme-store", data={"colorScheme": "light"}),
        html.Link(
            rel="stylesheet",
            href="data:text/css;base64,"
            + __import__("base64").b64encode(theme_css.encode()).decode(),
        ),
        dmc.Container(
            [
                dmc.Title("RangeSlider Prototype v4", order=1, ta="center", mb="lg"),
                # Theme Toggle
                dmc.Group(
                    [
                        dmc.Switch(
                            id="theme-toggle",
                            label="Dark Mode",
                            checked=False,
                            size="md",
                        ),
                    ],
                    justify="flex-end",
                    mb="md",
                ),
                # Configuration Panel
                dmc.Paper(
                    [
                        dmc.Title("Configuration", order=3, mb="md"),
                        dmc.Group(
                            [
                                # Column Selection
                                dmc.Select(
                                    label="Select Column",
                                    id="column-select",
                                    data=[
                                        {
                                            "label": "Numeric Column (1.0-6.9)",
                                            "value": "numeric_column",
                                        },
                                        {
                                            "label": "Float Column (0.5-6.9)",
                                            "value": "float_column",
                                        },
                                        {"label": "Integer Column (1-10)", "value": "int_column"},
                                    ],
                                    value="numeric_column",
                                    w=200,
                                ),
                                # Scale Selection
                                dmc.Select(
                                    label="Scale Type",
                                    id="scale-select",
                                    data=[
                                        {"label": "Linear", "value": "linear"},
                                        {"label": "Logarithmic (Log10)", "value": "log10"},
                                    ],
                                    value="linear",
                                    w=200,
                                ),
                                # Color Selection
                                dmc.ColorInput(
                                    label="Custom Color",
                                    id="color-input",
                                    value=colors["black"],
                                    format="hex",
                                    w=200,
                                    leftSection=DashIconify(icon="cil:paint"),
                                    swatches=[
                                        colors["purple"],
                                        colors["blue"],
                                        colors["teal"],
                                        colors["green"],
                                        colors["yellow"],
                                        colors["orange"],
                                        colors["red"],
                                        colors["black"],
                                    ],
                                ),
                                # Marks Count
                                dmc.NumberInput(
                                    label="Number of Marks",
                                    id="marks-input",
                                    value=5,
                                    min=3,
                                    max=10,
                                    step=1,
                                    w=150,
                                ),
                            ],
                            gap="md",
                        ),
                        # Value Testing
                        dmc.Group(
                            [
                                dmc.Button(
                                    "Test with NULL values",
                                    id="test-null-btn",
                                    variant="outline",
                                    color="orange",
                                    leftSection=DashIconify(icon="mdi:null"),
                                ),
                                dmc.Button(
                                    "Test with Invalid values",
                                    id="test-invalid-btn",
                                    variant="outline",
                                    color="red",
                                    leftSection=DashIconify(icon="mdi:alert-circle"),
                                ),
                                dmc.Button(
                                    "Test with Valid values",
                                    id="test-valid-btn",
                                    variant="outline",
                                    color="green",
                                    leftSection=DashIconify(icon="mdi:check-circle"),
                                ),
                                dmc.Button(
                                    "Debug Component Properties",
                                    id="debug-props-btn",
                                    variant="outline",
                                    color="purple",
                                    leftSection=DashIconify(icon="mdi:bug"),
                                ),
                            ],
                            mt="md",
                        ),
                    ],
                    className="test-container",
                ),
                # Component Display
                dmc.Paper(
                    [
                        dmc.Title("RangeSlider Component", order=3, mb="md"),
                        html.Div(id="component-container", className="component-display"),
                    ],
                    className="test-container",
                ),
                # Direct DMC RangeSlider Test - MINIMAL
                dmc.Paper(
                    [
                        dmc.Title("Minimal DMC RangeSlider Test", order=3, mb="md"),
                        dmc.Text("Absolute minimal RangeSlider:", mb="sm"),
                        dmc.RangeSlider(
                            id="direct-rangeslider",
                            min=0,
                            max=100,
                            value=[20, 80],
                            # step=1,
                            size="md",
                            color="blue",
                            style={"margin": "20px 0"},
                        ),
                        html.Div(id="direct-rangeslider-output", style={"marginTop": "10px"}),
                    ],
                    className="test-container",
                ),
                # Even simpler test - just a regular Slider
                dmc.Paper(
                    [
                        dmc.Title("Regular Slider Test", order=3, mb="md"),
                        dmc.Text("Testing if regular Slider works:", mb="sm"),
                        dmc.Slider(
                            id="simple-slider",
                            min=0,
                            max=100,
                            value=50,
                        ),
                        html.Div(id="simple-slider-output", style={"marginTop": "10px"}),
                    ],
                    className="test-container",
                ),
                # Value Display
                dmc.Paper(
                    [
                        dmc.Title("Current Values", order=3, mb="md"),
                        html.Pre(id="value-display", style={"whiteSpace": "pre-wrap"}),
                    ],
                    className="test-container",
                ),
                # Debug Information
                dmc.Paper(
                    [
                        dmc.Title("Debug Information", order=3, mb="md"),
                        html.Pre(id="debug-info", style={"whiteSpace": "pre-wrap"}),
                    ],
                    className="test-container",
                ),
                # Hidden stores for testing
                dcc.Store(id="test-value-store", data=None),
                dcc.Store(id="component-store", data={}),
            ],
            size="xl",
        ),
    ],
    id="mantine-provider",
)


# Theme toggle callback
@callback(
    Output("mantine-provider", "theme"),
    Output("theme-store", "data"),
    Input("theme-toggle", "checked"),
)
def toggle_theme(checked):
    scheme = "dark" if checked else "light"
    return {"colorScheme": scheme}, {"colorScheme": scheme}


# Test value buttons callbacks
@callback(
    Output("test-value-store", "data"),
    [
        Input("test-null-btn", "n_clicks"),
        Input("test-invalid-btn", "n_clicks"),
        Input("test-valid-btn", "n_clicks"),
        Input("debug-props-btn", "n_clicks"),
    ],
    prevent_initial_call=True,
)
def set_test_values(*args):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "test-null-btn":
        return None  # Test null values
    elif button_id == "test-invalid-btn":
        return [None, "invalid"]  # Test invalid values
    elif button_id == "test-valid-btn":
        return [2.0, 5.0]  # Test valid values
    elif button_id == "debug-props-btn":
        print("DEBUG: Component properties debug requested")
        return [1.0, 6.9]  # Test with full range

    return dash.no_update


# Main component generation callback
@callback(
    [
        Output("component-container", "children"),
        Output("value-display", "children"),
        Output("debug-info", "children"),
        Output("component-store", "data"),
    ],
    [
        Input("column-select", "value"),
        Input("scale-select", "value"),
        Input("color-input", "value"),
        Input("marks-input", "value"),
        Input("test-value-store", "data"),
    ],
    prevent_initial_call=False,
)
def update_component(column_name, scale_type, color_value, marks_number, test_value):
    if not column_name:
        return "No column selected", "", "", {}

    # Generate unique ID for component
    component_id = str(uuid.uuid4())

    # Get column info
    column_info = mock_cols_json[column_name]
    column_type = column_info["type"]

    # Prepare component kwargs
    kwargs = {
        "index": component_id,
        "title": f"RangeSlider on {column_name}",
        "wf_id": "507f1f77bcf86cd799439011",  # Valid 24-character hex string
        "dc_id": "507f1f77bcf86cd799439012",  # Valid 24-character hex string
        "dc_config": {"mock": "config"},
        "column_name": column_name,
        "column_type": column_type,
        "interactive_component_type": "RangeSlider",
        "cols_json": mock_cols_json,
        "df": sample_data,
        "access_token": "mock-token",
        "stepper": False,
        "build_frame": False,
        "scale": scale_type,
        "color": color_value,
        "marks_number": marks_number,
        "value": test_value,  # This will be None, [None, "invalid"], or [2.0, 5.0]
    }

    # Build the component
    try:
        component = build_interactive(**kwargs)

        # Enhanced debug: try to inspect the generated component
        print(f"DEBUG: Generated component type: {type(component)}")
        if hasattr(component, "children"):
            print(
                f"DEBUG: Component has children: {len(component.children) if component.children else 0}"
            )
            for i, child in enumerate(component.children or []):
                print(f"DEBUG: Child {i}: {type(child)}")
                if hasattr(child, "id"):
                    print(f"DEBUG: Child {i} ID: {child.id}")
                if hasattr(child, "min") and hasattr(child, "max"):
                    print(f"DEBUG: Child {i} range: min={child.min}, max={child.max}")
                    if hasattr(child, "value"):
                        print(f"DEBUG: Child {i} value: {child.value}")
                    if hasattr(child, "step"):
                        print(f"DEBUG: Child {i} step: {child.step}")
                    if hasattr(child, "marks"):
                        print(f"DEBUG: Child {i} marks: {len(child.marks) if child.marks else 0}")

        # Debug information
        debug_info = {
            "column_name": column_name,
            "column_type": column_type,
            "scale_type": scale_type,
            "color_value": color_value,
            "marks_number": marks_number,
            "test_value": test_value,
            "component_id": component_id,
            "min_value": column_info["specs"]["min"],
            "max_value": column_info["specs"]["max"],
        }

        # Value display
        value_display = f"""Test Value: {test_value}
Column: {column_name} ({column_type})
Scale: {scale_type}
Color: {color_value}
Marks: {marks_number}
Range: {column_info["specs"]["min"]} - {column_info["specs"]["max"]}"""

        debug_display = f"""Debug Information:
{chr(10).join(f"{k}: {v}" for k, v in debug_info.items())}"""

        return component, value_display, debug_display, debug_info

    except Exception as e:
        error_msg = f"Error building component: {str(e)}"
        return (
            html.Div(
                [
                    dmc.Alert(
                        error_msg,
                        title="Component Error",
                        color="red",
                        icon=DashIconify(icon="mdi:alert-circle"),
                    )
                ]
            ),
            f"Error: {str(e)}",
            f"Exception: {str(e)}",
            {},
        )


# Direct RangeSlider callback - removed prevent_initial_call
@callback(
    Output("direct-rangeslider-output", "children"),
    Input("direct-rangeslider", "value"),
)
def update_direct_rangeslider(value):
    print(f"DEBUG: Direct RangeSlider callback triggered with value: {value}")
    return f"Direct RangeSlider Value: {value} (Type: {type(value)})"


# Simple Slider callback - removed prevent_initial_call
@callback(
    Output("simple-slider-output", "children"),
    Input("simple-slider", "value"),
)
def update_simple_slider(value):
    print(f"DEBUG: Simple Slider callback triggered with value: {value}")
    return f"Simple Slider Value: {value} (Type: {type(value)})"


# Component value change callback - fixed with initial_duplicate
@callback(
    Output("value-display", "children", allow_duplicate=True),
    Input({"type": "interactive-component-value", "index": dash.dependencies.ALL}, "value"),
    State("component-store", "data"),
    prevent_initial_call="initial_duplicate",
)
def update_value_display(slider_values, component_data):
    print(f"DEBUG: update_value_display called with slider_values: {slider_values}")

    if not slider_values:
        return dash.no_update

    # Handle the case where we have multiple components
    current_value = slider_values[0] if slider_values else None

    if current_value is None:
        return dash.no_update

    value_display = f"""Current RangeSlider Value: {current_value}
Type: {type(current_value)}
Component Data: {component_data}
Debug Information: {slider_values}"""

    return value_display


if __name__ == "__main__":
    app.run(debug=True, port=8086)
