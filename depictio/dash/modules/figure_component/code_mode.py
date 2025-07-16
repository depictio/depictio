"""
Code mode component for figure creation using Python/Plotly code
"""

from typing import Any, Dict

import dash_ace
import dash_mantine_components as dmc
import pandas as pd
from dash import html
from dash_iconify import DashIconify


def create_sample_datasets() -> Dict[str, pd.DataFrame]:
    """Create multiple sample datasets for testing"""
    datasets = {}

    # Simple scatter data
    datasets["scatter"] = pd.DataFrame(
        {
            "x": list(range(1, 21)),
            "y": [2, 5, 3, 8, 7, 4, 9, 6, 1, 10, 12, 15, 11, 18, 16, 13, 19, 14, 17, 20],
            "category": ["A", "B"] * 10,
            "size": [
                10,
                20,
                15,
                25,
                30,
                12,
                18,
                22,
                14,
                28,
                32,
                35,
                25,
                40,
                38,
                28,
                42,
                30,
                36,
                45,
            ],
            "text": [f"Point {i}" for i in range(1, 21)],
        }
    )

    # Time series data
    from datetime import datetime, timedelta

    import numpy as np

    dates = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(30)]
    datasets["timeseries"] = pd.DataFrame(
        {
            "date": dates,
            "value": np.random.normal(100, 10, 30).cumsum(),
            "category": ["Series A", "Series B"] * 15,
        }
    )

    # Bar chart data
    datasets["bar"] = pd.DataFrame(
        {
            "category": ["A", "B", "C", "D", "E"],
            "value": [23, 45, 56, 78, 32],
            "subcategory": ["X", "Y", "X", "Y", "X"],
        }
    )

    # Histogram data
    datasets["histogram"] = pd.DataFrame(
        {
            "values": np.random.normal(50, 15, 200),
            "group": np.random.choice(["Group 1", "Group 2"], 200),
        }
    )

    return datasets


def create_code_mode_interface(component_index: str) -> html.Div:
    """Create the code mode interface for figure creation"""

    return html.Div(
        [
            # Code editor area - flexible height container
            dmc.Stack(
                [
                    # Header with controls
                    dmc.Group(
                        [
                            dmc.Text("Python Code:", fw="bold", size="sm", c="gray"),
                            dmc.Group(
                                [
                                    dmc.Button(
                                        "Execute Code",
                                        id={"type": "code-execute-btn", "index": component_index},
                                        size="xs",
                                        leftSection=DashIconify(icon="mdi:play", width=14),
                                        color="green",
                                        variant="filled",
                                    ),
                                    dmc.Button(
                                        "Clear",
                                        id={"type": "code-clear-btn", "index": component_index},
                                        size="xs",
                                        leftSection=DashIconify(icon="mdi:broom", width=14),
                                        color="gray",
                                        variant="outline",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        justify="space-between",
                        align="center",
                    ),
                    # Enhanced Code Editor with dash-ace - flexible height
                    dmc.Paper(
                        [
                            # Code editor header bar (like in prototype)
                            dmc.Group(
                                [
                                    dmc.Group(
                                        [
                                            dmc.Box(
                                                style={
                                                    "width": "12px",
                                                    "height": "12px",
                                                    "borderRadius": "50%",
                                                    "backgroundColor": "#ff5f57",
                                                }
                                            ),
                                            dmc.Box(
                                                style={
                                                    "width": "12px",
                                                    "height": "12px",
                                                    "borderRadius": "50%",
                                                    "backgroundColor": "#ffbd2e",
                                                }
                                            ),
                                            dmc.Box(
                                                style={
                                                    "width": "12px",
                                                    "height": "12px",
                                                    "borderRadius": "50%",
                                                    "backgroundColor": "#28ca42",
                                                }
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    dmc.Text(
                                        "main.py",
                                        size="sm",
                                        c="gray",
                                        style={"fontFamily": "monospace"},
                                    ),
                                    dmc.Group(
                                        [
                                            dmc.Text("Python", size="xs", c="gray"),
                                            dmc.Text("UTF-8", size="xs", c="gray"),
                                        ],
                                        gap="md",
                                    ),
                                ],
                                justify="space-between",
                                p="sm",
                                style={
                                    "backgroundColor": "var(--mantine-color-gray-1, #f8f9fa)",
                                    "borderBottom": "1px solid var(--mantine-color-gray-3, #dee2e6)",
                                },
                            ),
                            # Code input area with enhanced editor - flexible height
                            dmc.Box(
                                [
                                    dash_ace.DashAceEditor(
                                        id={"type": "code-editor", "index": component_index},
                                        value="",
                                        theme="github",
                                        mode="python",
                                        fontSize=15,
                                        showGutter=True,
                                        showPrintMargin=False,
                                        highlightActiveLine=True,
                                        setOptions={
                                            "enableBasicAutocompletion": True,
                                            "enableLiveAutocompletion": True,
                                            "enableSnippets": True,
                                            "tabSize": 4,
                                            "useSoftTabs": True,
                                            "wrap": True,  # Enable word wrapping
                                            "fontFamily": "Fira Code, JetBrains Mono, Monaco, Consolas, Courier New, monospace",
                                            "printMargin": 55,  # Set print margin at ~55 characters
                                        },
                                        style={
                                            "width": "100%",
                                            "height": "100%",
                                            "minHeight": "200px",
                                            "borderRadius": "0 0 8px 8px",
                                        },
                                        placeholder="# Enter your Python/Plotly code here...\n# Available: df (DataFrame), px (plotly.express), go (plotly.graph_objects), pd (pandas), np (numpy)\n# Example:\n# fig = px.scatter(df, x='your_x_column', y='your_y_column', color='your_color_column')",
                                    ),
                                ],
                                style={
                                    "width": "100%",
                                    "flex": "1",  # Take available space
                                    "minHeight": "200px",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "borderRadius": "0 0 8px 8px",
                                },
                            ),
                        ],
                        radius="md",
                        withBorder=True,
                        style={
                            "backgroundColor": "transparent",
                            "overflow": "hidden",
                            "flex": "1",  # Take available space
                            "display": "flex",
                            "flexDirection": "column",
                        },
                    ),
                ],
                gap="sm",
                style={
                    "flex": "1",  # Take available space
                    "display": "flex",
                    "flexDirection": "column",
                },
            ),
            # Status and data preview area - fixed height, scrollable
            # dmc.ScrollArea(
            #     [
            dmc.Stack(
                [
                    # Available columns information
                    dmc.Alert(
                        id={"type": "columns-info", "index": component_index},
                        title="Available Columns",
                        color="teal",
                        children="Loading column information...",
                        withCloseButton=False,
                        icon=DashIconify(
                            icon="mdi:table",
                            width=16,
                            style={"color": "var(--mantine-color-teal-6, #1de9b6)"},
                        ),
                    ),
                    # Execution status
                    dmc.Alert(
                        id={"type": "code-status", "index": component_index},
                        title="Ready",
                        color="blue",
                        children="Enter code and click 'Execute Code' to generate a figure.",
                        withCloseButton=False,
                        icon=DashIconify(
                            icon="mdi:check-circle",
                            width=16,
                            style={"color": "var(--mantine-color-blue-6, #1e88e5)"},
                        ),
                    ),
                    # Data info (show basic info about the loaded dataframe)
                    dmc.Alert(
                        id={"type": "data-info", "index": component_index},
                        title="Dataset Information",
                        color="blue",
                        children="DataFrame loaded from selected data collection will be available as 'df' variable.",
                        withCloseButton=False,
                        icon=DashIconify(
                            icon="mdi:database",
                            width=16,
                            style={"color": "var(--mantine-color-blue-6, #1e88e5)"},
                        ),
                    ),
                ],
                gap="sm",
            ),
            # ],
            #     style={
            #         # "maxHeight": "200px",
            #         # "flex": "0 0 auto",  # Don't grow, but take needed space
            #         "overflowY": "auto",
            #     },
            # ),
            # Note: code-generated-figure store is created in design_figure function
        ],
        style={
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "gap": "10px",
            "padding": "10px",
        },
    )


def convert_ui_params_to_code(dict_kwargs: Dict[str, Any], visu_type: str) -> str:
    """Convert UI parameters to Python code with proper line wrapping"""
    if not dict_kwargs:
        return ""

    # Maximum line length based on user's screen: "fig = px.scatter(df, x='sepal.length', template='plotly',"
    MAX_LINE_LENGTH = 55

    # Start with basic plot based on visualization type
    if visu_type.lower() == "scatter":
        base_call = "fig = px.scatter(df"
    elif visu_type.lower() == "line":
        base_call = "fig = px.line(df"
    elif visu_type.lower() == "bar":
        base_call = "fig = px.bar(df"
    elif visu_type.lower() == "box":
        base_call = "fig = px.box(df"
    elif visu_type.lower() == "histogram":
        base_call = "fig = px.histogram(df"
    else:
        base_call = "fig = px.scatter(df"  # Default fallback

    # Add parameters
    params = []
    for key, value in dict_kwargs.items():
        if value is not None and value != "" and value != []:
            if isinstance(value, str):
                params.append(f"{key}='{value}'")
            else:
                params.append(f"{key}={repr(value)}")

    if not params:
        return base_call + ")"

    # Build the code with proper line wrapping
    code_lines = []
    current_line = base_call
    indent = " " * 4  # 4 spaces for continuation lines

    for i, param in enumerate(params):
        param_text = f", {param}" if i > 0 or current_line != base_call else f", {param}"

        # Check if adding this parameter would exceed the line length
        if len(current_line + param_text) > MAX_LINE_LENGTH:
            # Start a new line
            code_lines.append(current_line + ",")
            current_line = indent + param
        else:
            # Add to current line
            current_line += param_text

    # Add the closing parenthesis
    if len(current_line + ")") > MAX_LINE_LENGTH and current_line.strip() != base_call.strip():
        code_lines.append(current_line)
        code_lines.append(")")
    else:
        code_lines.append(current_line + ")")

    return "\n".join(code_lines)


def extract_params_from_code(code: str) -> Dict[str, Any]:
    """Extract parameter information from Python code (enhanced parsing)"""
    params = {}

    # Enhanced regex-based extraction for common patterns
    import re

    # Look for px.scatter, px.line, etc. function calls
    plotly_call_pattern = r"px\.\w+\(df(?:,\s*(.+?))?\)"
    match = re.search(plotly_call_pattern, code, re.DOTALL)

    if match and match.group(1):
        params_str = match.group(1)

        # Extract individual parameters (enhanced approach)
        param_patterns = [
            # String parameters (quoted)
            (r"x\s*=\s*['\"]([^'\"]+)['\"]", "x"),
            (r"y\s*=\s*['\"]([^'\"]+)['\"]", "y"),
            (r"color\s*=\s*['\"]([^'\"]+)['\"]", "color"),
            (r"size\s*=\s*['\"]([^'\"]+)['\"]", "size"),
            (r"title\s*=\s*['\"]([^'\"]+)['\"]", "title"),
            (r"facet_col\s*=\s*['\"]([^'\"]+)['\"]", "facet_col"),
            (r"facet_row\s*=\s*['\"]([^'\"]+)['\"]", "facet_row"),
            (r"hover_name\s*=\s*['\"]([^'\"]+)['\"]", "hover_name"),
            (r"animation_frame\s*=\s*['\"]([^'\"]+)['\"]", "animation_frame"),
            (r"animation_group\s*=\s*['\"]([^'\"]+)['\"]", "animation_group"),
            (r"template\s*=\s*['\"]([^'\"]+)['\"]", "template"),
            (r"color_discrete_sequence\s*=\s*['\"]([^'\"]+)['\"]", "color_discrete_sequence"),
            (r"color_continuous_scale\s*=\s*['\"]([^'\"]+)['\"]", "color_continuous_scale"),
            (r"symbol\s*=\s*['\"]([^'\"]+)['\"]", "symbol"),
            (r"line_dash\s*=\s*['\"]([^'\"]+)['\"]", "line_dash"),
            (r"pattern_shape\s*=\s*['\"]([^'\"]+)['\"]", "pattern_shape"),
            (r"orientation\s*=\s*['\"]([^'\"]+)['\"]", "orientation"),
            (r"barmode\s*=\s*['\"]([^'\"]+)['\"]", "barmode"),
            (r"histnorm\s*=\s*['\"]([^'\"]+)['\"]", "histnorm"),
            (r"points\s*=\s*['\"]([^'\"]+)['\"]", "points"),
            (r"violinmode\s*=\s*['\"]([^'\"]+)['\"]", "violinmode"),
            (r"line_shape\s*=\s*['\"]([^'\"]+)['\"]", "line_shape"),
            (r"trendline\s*=\s*['\"]([^'\"]+)['\"]", "trendline"),
            # Boolean parameters
            (r"log_x\s*=\s*(True|False)", "log_x"),
            (r"log_y\s*=\s*(True|False)", "log_y"),
            (r"marginal_x\s*=\s*['\"]([^'\"]+)['\"]", "marginal_x"),
            (r"marginal_y\s*=\s*['\"]([^'\"]+)['\"]", "marginal_y"),
            # Special handling for False as a string value
            (r"points\s*=\s*False", "points"),
        ]

        for pattern, key in param_patterns:
            param_match = re.search(pattern, params_str)
            if param_match:
                # Handle patterns that might not have groups
                if param_match.groups():
                    value = param_match.group(1)

                    # Handle boolean values
                    if value == "True":
                        params[key] = True
                    elif value == "False":
                        params[key] = False
                    else:
                        params[key] = value
                else:
                    # For patterns without groups (like points=False)
                    if key == "points":
                        params[key] = False

    return params
