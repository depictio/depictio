"""
Code mode component for figure creation using Python/Plotly code
"""

from typing import Any, Dict

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
            # Code editor area
            dmc.Paper(
                [
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
                        style={"marginBottom": "10px"},
                    ),
                    dmc.Textarea(
                        id={"type": "code-editor", "index": component_index},
                        placeholder="Enter your Python/Plotly code here...\n\nExample:\nfig = px.scatter(df, x='x', y='y', color='category')",
                        autosize=True,
                        minRows=8,
                        maxRows=20,
                        style={
                            "fontFamily": "Monaco, Consolas, 'Courier New', monospace",
                            "fontSize": "13px",
                            "lineHeight": "1.4",
                        },
                        value="",
                    ),
                ],
                p="md",
                withBorder=True,
                radius="md",
            ),
            # Status and data preview area
            html.Div(
                [
                    # Execution status
                    dmc.Alert(
                        id={"type": "code-status", "index": component_index},
                        title="Ready",
                        color="blue",
                        children="Enter code and click 'Execute Code' to generate a figure.",
                        style={"marginTop": "15px", "marginBottom": "15px"},
                        withCloseButton=False,
                    ),
                    # Data info (show basic info about the loaded dataframe)
                    dmc.Alert(
                        id={"type": "data-info", "index": component_index},
                        title="Dataset Information",
                        color="blue",
                        children="DataFrame loaded from selected data collection will be available as 'df' variable.",
                        style={"marginTop": "15px"},
                        withCloseButton=False,
                    ),
                ]
            ),
            # Note: code-generated-figure store is created in design_figure function
        ],
        style={"height": "100%", "overflow": "auto"},
    )


def convert_ui_params_to_code(dict_kwargs: Dict[str, Any], visu_type: str) -> str:
    """Convert UI parameters to Python code"""
    if not dict_kwargs:
        return ""

    # Start with basic plot based on visualization type
    if visu_type.lower() == "scatter":
        code_lines = ["fig = px.scatter(df"]
    elif visu_type.lower() == "line":
        code_lines = ["fig = px.line(df"]
    elif visu_type.lower() == "bar":
        code_lines = ["fig = px.bar(df"]
    elif visu_type.lower() == "box":
        code_lines = ["fig = px.box(df"]
    elif visu_type.lower() == "histogram":
        code_lines = ["fig = px.histogram(df"]
    else:
        code_lines = ["fig = px.scatter(df"]  # Default fallback

    # Add parameters
    params = []
    for key, value in dict_kwargs.items():
        if value is not None and value != "" and value != []:
            if isinstance(value, str):
                params.append(f"{key}='{value}'")
            else:
                params.append(f"{key}={repr(value)}")

    if params:
        code_lines[0] += ", " + ", ".join(params)

    code_lines[0] += ")"

    return "\n".join(code_lines)


def extract_params_from_code(code: str) -> Dict[str, Any]:
    """Extract parameter information from Python code (basic parsing)"""
    params = {}

    # Simple regex-based extraction for common patterns
    import re

    # Look for px.scatter, px.line, etc. function calls
    plotly_call_pattern = r"px\.\w+\(df(?:,\s*(.+?))?\)"
    match = re.search(plotly_call_pattern, code)

    if match and match.group(1):
        params_str = match.group(1)

        # Extract individual parameters (basic approach)
        param_patterns = [
            (r"x\s*=\s*['\"]([^'\"]+)['\"]", "x"),
            (r"y\s*=\s*['\"]([^'\"]+)['\"]", "y"),
            (r"color\s*=\s*['\"]([^'\"]+)['\"]", "color"),
            (r"size\s*=\s*['\"]([^'\"]+)['\"]", "size"),
            (r"title\s*=\s*['\"]([^'\"]+)['\"]", "title"),
        ]

        for pattern, key in param_patterns:
            param_match = re.search(pattern, params_str)
            if param_match:
                params[key] = param_match.group(1)

    return params
