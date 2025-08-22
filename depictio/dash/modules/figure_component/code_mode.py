"""
Code mode component for figure creation using Python/Plotly code
"""

from typing import Any, Dict

import dash_ace
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from dash import html

from .simple_code_executor import get_code_examples


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
                                            "enableResize": True,  # Enable the resize handle
                                        },
                                        style={
                                            "width": "100%",
                                            "height": "100%",
                                            "minHeight": "200px",
                                            "borderRadius": "0 0 8px 8px",
                                        },
                                        placeholder="# Enter your Python/Plotly code here...\n# Available: df (DataFrame), px (plotly.express), pd (pandas), pl (polars)\n# Example:\n# fig = px.scatter(df, x='your_x_column', y='your_y_column', color='your_color_column')",
                                    ),
                                ],
                                style={
                                    "width": "100%",
                                    "flex": "1",  # Take available space
                                    "minHeight": "200px",
                                    "maxHeight": "600px",  # Set max height for resize
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "borderRadius": "0 0 8px 8px",
                                    "resize": "vertical",
                                    "overflow": "auto",
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
                        title="Dataset & Figure Usage",
                        color="blue",
                        children=[
                            dmc.Text(
                                "Use 'df' for dataset operations and 'fig' for your final figure:"
                            ),
                            dmc.List(
                                [
                                    dmc.ListItem("df - Your dataset (Polars DataFrame)"),
                                    dmc.ListItem("fig - Your final Plotly figure"),
                                    dmc.ListItem(
                                        "Operations: Both pandas (.to_pandas()) and polars methods allowed"
                                    ),
                                ],
                                size="sm",
                                withPadding=True,
                                style={"marginTop": "8px"},
                            ),
                        ],
                        withCloseButton=False,
                        icon=DashIconify(
                            icon="mdi:database",
                            width=16,
                            style={"color": "var(--mantine-color-blue-6, #1e88e5)"},
                        ),
                    ),
                    # Code examples section - separate from dataset info
                    dmc.Alert(
                        title="Code Examples (Iris Dataset)",
                        color="teal",
                        children=[
                            dmc.Button(
                                "Show Code Examples",
                                id={"type": "toggle-examples-btn", "index": component_index},
                                variant="subtle",
                                size="xs",
                                leftSection=DashIconify(icon="mdi:code-braces", width=14),
                                color="teal",
                                style={"marginBottom": "8px"},
                            ),
                            dmc.Collapse(
                                id={"type": "code-examples-collapse", "index": component_index},
                                opened=False,
                                children=[
                                    dmc.Stack(
                                        [
                                            *[
                                                dmc.Stack(
                                                    [
                                                        dmc.Text(
                                                            title, fw="bold", size="sm", c="gray"
                                                        ),
                                                        dmc.CodeHighlight(
                                                            language="python",
                                                            code=code,
                                                            withCopyButton=True,
                                                            style={"fontSize": "12px"},
                                                        ),
                                                    ],
                                                    gap="xs",
                                                )
                                                for title, code in get_code_examples().items()
                                            ],
                                        ],
                                        gap="md",
                                    )
                                ],
                            ),
                        ],
                        withCloseButton=False,
                        icon=DashIconify(
                            icon="mdi:code-tags",
                            width=16,
                            style={"color": "var(--mantine-color-teal-6, #1de9b6)"},
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
    visu_lower = visu_type.lower()

    # Handle clustering visualizations (custom functions)
    if visu_lower == "umap":
        # For UMAP, we need to import and use the clustering function
        base_call = "# Import clustering function\nfrom depictio.dash.modules.figure_component.clustering import create_umap_plot\n\n# Create UMAP plot\nfig = create_umap_plot(df"
    else:
        # Standard Plotly Express visualizations
        base_call = f"fig = px.{visu_lower}(df"

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

    # Handle multi-line base_call (like UMAP)
    if "\n" in base_call:
        # Split the base_call and work with the last line
        base_lines = base_call.split("\n")
        initial_lines = base_lines[:-1]
        function_call_line = base_lines[-1]
    else:
        initial_lines = []
        function_call_line = base_call

    # Build the code with proper line wrapping
    code_lines = initial_lines.copy() if initial_lines else []
    current_line = function_call_line
    indent = " " * 4  # 4 spaces for continuation lines

    for i, param in enumerate(params):
        param_text = f", {param}" if i > 0 or current_line != function_call_line else f", {param}"

        # Check if adding this parameter would exceed the line length
        if len(current_line + param_text) > MAX_LINE_LENGTH:
            # Start a new line
            code_lines.append(current_line + ",")
            current_line = indent + param
        else:
            # Add to current line
            current_line += param_text

    # Add the closing parenthesis
    if (
        len(current_line + ")") > MAX_LINE_LENGTH
        and current_line.strip() != function_call_line.strip()
    ):
        code_lines.append(current_line)
        code_lines.append(")")
    else:
        code_lines.append(current_line + ")")

    return "\n".join(code_lines)


def extract_visualization_type_from_code(code: str) -> str:
    """Extract visualization type from Python code"""
    import re

    # Look for px.function_name patterns
    px_pattern = r"px\.(\w+)\("
    px_match = re.search(px_pattern, code)
    if px_match:
        return px_match.group(1).lower()  # e.g., "scatter", "box", "violin"

    # Look for clustering functions
    cluster_pattern = r"create_(\w+)_plot\("
    cluster_match = re.search(cluster_pattern, code)
    if cluster_match:
        return cluster_match.group(1).lower()  # e.g., "umap"

    # Default fallback
    return "scatter"


def extract_params_from_code(code: str) -> Dict[str, Any]:
    """Extract parameter information from Python code (enhanced parsing)"""
    params = {}

    # Enhanced regex-based extraction for common patterns
    import re

    # Look for px.scatter, px.line, etc. function calls OR clustering functions
    plotly_call_pattern = r"(px\.\w+\(df(?:,\s*(.+?))?\)|create_\w+_plot\(df(?:,\s*(.+?))?\))"
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
