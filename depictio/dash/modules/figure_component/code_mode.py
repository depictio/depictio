"""
Code mode component for figure creation using Python/Plotly code
"""

from typing import Any, Dict

import dash_ace
import dash_mantine_components as dmc
import polars as pl
from dash import html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger

from .simple_code_executor import get_code_examples


def create_code_mode_interface(component_index: str) -> html.Div:
    """Create the code mode interface for figure creation"""

    from depictio.api.v1.configs.logging_init import logger

    logger.info(f"🔧 CREATING CODE MODE INTERFACE for component: {component_index}")

    interface = html.Div(
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
                                        placeholder="# Enter your Python/Plotly code here...\n# Available: df (DataFrame), px (plotly.express), pd (pandas), pl (polars)\n# \n# CONSTRAINT: Use 'df_modified' for data preprocessing (single line):\n# df_modified = df.to_pandas().groupby('column').sum().reset_index()\n# fig = px.pie(df_modified, values='value_col', names='name_col')\n# \n# Simple example (no preprocessing):\n# fig = px.scatter(df, x='your_x_column', y='your_y_column', color='your_color_column')",
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
                            dmc.Text("Code Constraints and Usage:"),
                            dmc.List(
                                [
                                    dmc.ListItem(
                                        "df - Your dataset (Polars DataFrame) - READ ONLY"
                                    ),
                                    dmc.ListItem(
                                        "df_modified - Use for preprocessing (single line only)"
                                    ),
                                    dmc.ListItem("fig - Your final Plotly figure (required)"),
                                    dmc.ListItem(
                                        "✅ Valid: fig = px.scatter(df, ...) or fig = px.pie(df_modified, ...)"
                                    ),
                                    dmc.ListItem(
                                        "❌ Invalid: Multiple preprocessing lines or wrong variable names"
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

    logger.info("✅ CODE MODE INTERFACE CREATED - returning interface")
    return interface


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


def analyze_constrained_code(code: str) -> dict[str, Any]:
    """
    Analyze code with df_modified constraint.

    Expects code format:
    - Optional: df_modified = df.some_processing_chain()
    - Required: fig = px.function(df or df_modified, ...)

    Args:
        code: Python code string

    Returns:
        Dictionary with analysis results
    """
    if not code or not code.strip():
        return {
            "has_preprocessing": False,
            "preprocessing_code": None,
            "figure_code": None,
            "uses_modified_df": False,
            "is_valid": False,
            "error_message": "Empty code",
        }

    lines = [
        line.strip()
        for line in code.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]

    preprocessing_line = None
    figure_line = None
    uses_modified_df = False

    for line in lines:
        if line.startswith("df_modified =") or line.startswith("df_modified="):
            preprocessing_line = line
        elif line.startswith("fig =") or line.startswith("fig="):
            figure_line = line
            uses_modified_df = "df_modified" in line

    # Validation
    if not figure_line:
        return {
            "has_preprocessing": preprocessing_line is not None,
            "preprocessing_code": preprocessing_line,
            "figure_code": figure_line,
            "uses_modified_df": uses_modified_df,
            "is_valid": False,
            "error_message": 'Code must contain a line starting with "fig = px.function(...)"',
        }

    # Check for invalid patterns
    if preprocessing_line and not uses_modified_df:
        return {
            "has_preprocessing": True,
            "preprocessing_code": preprocessing_line,
            "figure_code": figure_line,
            "uses_modified_df": uses_modified_df,
            "is_valid": False,
            "error_message": "If df_modified is created, it must be used in the fig = px.function() call",
        }

    if uses_modified_df and not preprocessing_line:
        return {
            "has_preprocessing": False,
            "preprocessing_code": preprocessing_line,
            "figure_code": figure_line,
            "uses_modified_df": uses_modified_df,
            "is_valid": False,
            "error_message": "df_modified is used but not defined. Add: df_modified = df.some_processing()",
        }

    return {
        "has_preprocessing": preprocessing_line is not None,
        "preprocessing_code": preprocessing_line,
        "figure_code": figure_line,
        "uses_modified_df": uses_modified_df,
        "is_valid": True,
        "error_message": None,
    }


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
    """Extract ALL parameter information from Python code dynamically"""
    params = {}

    import ast
    import re

    try:
        # Parse the code to AST for proper parameter extraction
        tree = ast.parse(code)

        for node in ast.walk(tree):
            # Look for function calls (px.function or create_*_plot)
            if isinstance(node, ast.Call):
                # Check if it's a px.function call or clustering function
                is_px_call = (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "px"
                )

                is_clustering_call = (
                    isinstance(node.func, ast.Name)
                    and node.func.id.startswith("create_")
                    and node.func.id.endswith("_plot")
                )

                if is_px_call or is_clustering_call:
                    # Extract all keyword arguments
                    for keyword in node.keywords:
                        if keyword.arg:  # Skip **kwargs
                            param_name = keyword.arg

                            # Extract the value based on its type
                            if isinstance(keyword.value, ast.Constant):
                                # String, number, boolean literals
                                params[param_name] = keyword.value.value
                            elif isinstance(keyword.value, ast.Name):
                                # Variable references (like column names)
                                params[param_name] = keyword.value.id
                            elif isinstance(keyword.value, ast.Str):  # Python < 3.8 compatibility
                                params[param_name] = keyword.value.s
                            elif isinstance(keyword.value, ast.Num):  # Python < 3.8 compatibility
                                params[param_name] = keyword.value.n
                            elif isinstance(
                                keyword.value, ast.NameConstant
                            ):  # Python < 3.8 compatibility
                                params[param_name] = keyword.value.value
                            # For more complex expressions, try to convert back to string
                            elif hasattr(ast, "unparse"):  # Python 3.9+
                                params[param_name] = ast.unparse(keyword.value)
                            else:
                                # Fallback: convert to string representation
                                params[param_name] = str(keyword.value)

    except (SyntaxError, ValueError):
        # Fallback to regex-based extraction if AST parsing fails
        plotly_call_pattern = (
            r"(px\.\w+\(df\w*(?:,\s*(.+?))?\)|create_\w+_plot\(df\w*(?:,\s*(.+?))?\))"
        )
        match = re.search(plotly_call_pattern, code, re.DOTALL)

        if match and match.group(2):
            params_str = match.group(2)

            # Dynamic parameter extraction using regex
            # Match any parameter=value pattern
            param_pattern = r"(\w+)\s*=\s*([^,)]+)"
            param_matches = re.findall(param_pattern, params_str)

            for param_name, param_value in param_matches:
                # Clean up the parameter value
                param_value = param_value.strip()

                # Remove quotes if present
                if (param_value.startswith("'") and param_value.endswith("'")) or (
                    param_value.startswith('"') and param_value.endswith('"')
                ):
                    param_value = param_value[1:-1]

                # Handle boolean values
                if param_value == "True":
                    params[param_name] = True
                elif param_value == "False":
                    params[param_name] = False
                else:
                    params[param_name] = param_value

    return params


def evaluate_params_in_context(params: Dict[str, Any], df: pl.DataFrame) -> Dict[str, Any]:
    """Evaluate parameter expressions that contain references to df in the execution context"""

    evaluated_params = {}
    for param_name, param_value in params.items():
        if isinstance(param_value, str) and ("df[" in param_value or "sorted(" in param_value):
            try:
                # Create a safe execution environment with df available
                safe_globals = {
                    "__builtins__": {
                        "len": len,
                        "list": list,
                        "set": set,
                        "sorted": sorted,
                        "min": min,
                        "max": max,
                    },
                    "df": df,
                }
                # Evaluate the expression in the safe context
                evaluated_value = eval(param_value, safe_globals, {})
                evaluated_params[param_name] = evaluated_value
                logger.info(f"Evaluated parameter {param_name}: {param_value} -> {evaluated_value}")
            except Exception as e:
                logger.warning(f"Could not evaluate parameter {param_name}: {param_value} - {e}")
                # Keep original value if evaluation fails
                evaluated_params[param_name] = param_value
        else:
            # Keep non-expression parameters as-is
            evaluated_params[param_name] = param_value

    return evaluated_params
