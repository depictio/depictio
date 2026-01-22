"""Code mode component for figure creation using Python/Plotly code.

This module provides a code editor interface for creating Plotly figures
using Python code. It includes:

- Interactive Ace editor with Python syntax highlighting
- Code analysis and validation with constraints
- Parameter extraction from code for UI synchronization
- Code generation from UI parameters
- Support for preprocessing with df_modified pattern

Key functions:
- create_code_mode_interface: Creates the full code editor UI
- analyze_constrained_code: Validates code structure and preprocessing
- extract_params_from_code: AST-based parameter extraction
- convert_ui_params_to_code: Generate code from UI selections
"""

from typing import Any, Dict, Literal

import dash_ace
import dash_mantine_components as dmc
import polars as pl
from dash import html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger

from .simple_code_executor import get_code_examples


def create_code_mode_interface(component_index: str, initial_code: str = "") -> html.Div:
    """Create the code mode interface for figure creation.

    Creates a complete code editing environment with:
    - macOS-style editor header with traffic lights
    - Ace editor with Python syntax highlighting and autocompletion
    - Execute/Clear buttons
    - Status alerts for feedback
    - Code examples section

    Args:
        component_index: Component identifier for pattern matching callbacks.
        initial_code: Initial code to populate the editor (for edit mode).

    Returns:
        HTML Div containing the complete code mode interface.
    """
    logger.info(f"Creating code mode interface for component: {component_index}")

    return html.Div(
        [
            _create_editor_section(component_index, initial_code),
            _create_status_section(component_index),
        ],
        style={
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "gap": "10px",
            "padding": "10px",
        },
    )


def _create_traffic_light_dot(color: str) -> dmc.Box:
    """Create a single traffic light dot for the editor header."""
    return dmc.Box(
        style={
            "width": "12px",
            "height": "12px",
            "borderRadius": "50%",
            "backgroundColor": color,
        }
    )


def _create_editor_header() -> dmc.Group:
    """Create the macOS-style editor header bar with traffic lights."""
    traffic_lights = dmc.Group(
        [
            _create_traffic_light_dot("#ff5f57"),
            _create_traffic_light_dot("#ffbd2e"),
            _create_traffic_light_dot("#28ca42"),
        ],
        gap="xs",
    )

    filename = dmc.Text(
        "main.py",
        size="sm",
        c="gray",
        style={"fontFamily": "monospace"},
    )

    file_info = dmc.Group(
        [
            dmc.Text("Python", size="xs", c="gray"),
            dmc.Text("UTF-8", size="xs", c="gray"),
        ],
        gap="md",
    )

    return dmc.Group(
        [traffic_lights, filename, file_info],
        justify="space-between",
        p="sm",
        style={
            "backgroundColor": "var(--mantine-color-gray-1, #f8f9fa)",
            "borderBottom": "1px solid var(--mantine-color-gray-3, #dee2e6)",
        },
    )


def _create_ace_editor(component_index: str, initial_code: str) -> dash_ace.DashAceEditor:
    """Create the Ace code editor component."""
    placeholder_text = """# Enter your Python/Plotly code here...
# Available: df (DataFrame), px (plotly.express), pd (pandas), pl (polars)
#
# CONSTRAINT: Use 'df_modified' for data preprocessing (single line):
# df_modified = df.to_pandas().groupby('column').sum().reset_index()
# fig = px.pie(df_modified, values='value_col', names='name_col')
#
# Simple example (no preprocessing):
# fig = px.scatter(df, x='your_x_column', y='your_y_column', color='your_color_column')"""

    return dash_ace.DashAceEditor(
        id={"type": "code-editor", "index": component_index},
        value=initial_code,
        theme="github",
        mode="python",
        fontSize=11,
        showGutter=True,
        showPrintMargin=False,
        highlightActiveLine=True,
        setOptions={
            "enableBasicAutocompletion": True,
            "enableLiveAutocompletion": True,
            "enableSnippets": True,
            "tabSize": 4,
            "useSoftTabs": True,
            "wrap": True,
            "fontFamily": "Fira Code, JetBrains Mono, Monaco, Consolas, Courier New, monospace",
            "printMargin": 55,
            "enableResize": True,
            "autoIndent": False,
            "behavioursEnabled": False,
        },
        style={
            "width": "100%",
            "height": "100%",
            "minHeight": "200px",
            "borderRadius": "0 0 8px 8px",
        },
        placeholder=placeholder_text,
    )


def _create_editor_section(component_index: str, initial_code: str) -> dmc.Stack:
    """Create the code editor section with header and controls."""
    header_controls = dmc.Group(
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
    )

    editor_container = dmc.Box(
        [_create_ace_editor(component_index, initial_code)],
        style={
            "width": "100%",
            "height": "200px",  # Initial height (user can resize)
            "minHeight": "200px",
            "minWidth": "200px",  # Minimum width constraint
            "maxHeight": "none",  # Allow unlimited vertical growth
            "maxWidth": "none",  # Allow unlimited horizontal growth
            "display": "flex",
            "flexDirection": "column",
            "borderRadius": "0 0 8px 8px",
            "resize": "both",  # Enable both horizontal and vertical resizing
            "overflow": "auto",
        },
    )

    editor_paper = dmc.Paper(
        [_create_editor_header(), editor_container],
        radius="md",
        withBorder=True,
        style={
            "backgroundColor": "transparent",
            "overflow": "hidden",
            "flex": "1",
            "display": "flex",
            "flexDirection": "column",
        },
    )

    return dmc.Stack(
        [header_controls, editor_paper],
        gap="sm",
        style={
            "flex": "1",
            "display": "flex",
            "flexDirection": "column",
        },
    )


AlertColor = Literal[
    "blue",
    "cyan",
    "gray",
    "green",
    "indigo",
    "lime",
    "orange",
    "pink",
    "red",
    "teal",
    "violet",
    "yellow",
    "dark",
    "grape",
]


def _create_alert(
    component_index: str, alert_type: str, title: str, color: AlertColor, icon: str, children
) -> dmc.Alert:
    """Create a styled alert component."""
    color_var = f"var(--mantine-color-{color}-6, #1de9b6)"
    return dmc.Alert(
        id={"type": alert_type, "index": component_index},
        title=title,
        color=color,
        children=children,
        withCloseButton=False,
        icon=DashIconify(icon=icon, width=16, style={"color": color_var}),
    )


def _create_usage_info() -> list:
    """Create the dataset and figure usage information content."""
    return [
        dmc.Text("Code Constraints and Usage:"),
        dmc.List(
            [
                dmc.ListItem("df - Your dataset (Polars DataFrame) - READ ONLY"),
                dmc.ListItem("df_modified - Use for preprocessing (single line only)"),
                dmc.ListItem("fig - Your final Plotly figure (required)"),
                dmc.ListItem(
                    "✅ Valid: fig = px.scatter(df, ...) or fig = px.pie(df_modified, ...)"
                ),
                dmc.ListItem("❌ Invalid: Multiple preprocessing lines or wrong variable names"),
            ],
            size="sm",
            withPadding=True,
            style={"marginTop": "8px"},
        ),
    ]


def _create_code_examples_section(component_index: str) -> dmc.Alert:
    """Create the collapsible code examples section."""
    examples_content = dmc.Stack(
        [
            dmc.Stack(
                [
                    dmc.Text(title, fw="bold", size="sm", c="gray"),
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
        gap="md",
    )

    return dmc.Alert(
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
                children=[examples_content],
            ),
        ],
        withCloseButton=False,
        icon=DashIconify(
            icon="mdi:code-tags",
            width=16,
            style={"color": "var(--mantine-color-teal-6, #1de9b6)"},
        ),
    )


def _create_status_section(component_index: str) -> dmc.Stack:
    """Create the status and information alerts section."""
    columns_alert = _create_alert(
        component_index,
        "columns-info",
        "Available Columns",
        "teal",
        "mdi:table",
        "Loading column information...",
    )

    status_alert = _create_alert(
        component_index,
        "code-status",
        "Ready",
        "blue",
        "mdi:check-circle",
        "Enter code and click 'Execute Code' to see preview on the left.",
    )

    data_info_alert = _create_alert(
        component_index,
        "data-info",
        "Dataset & Figure Usage",
        "blue",
        "mdi:database",
        _create_usage_info(),
    )

    examples_section = _create_code_examples_section(component_index)

    return dmc.Stack(
        [columns_alert, status_alert, data_info_alert, examples_section],
        gap="sm",
    )


def convert_ui_params_to_code(dict_kwargs: Dict[str, Any], visu_type: str) -> str:
    """Convert UI parameters to Python code with proper line wrapping.

    Generates syntactically correct Python code from parameter dictionary,
    handling line length constraints and special visualization types.

    Args:
        dict_kwargs: Dictionary of parameter names to values.
        visu_type: Type of visualization (e.g., 'scatter', 'bar', 'umap').

    Returns:
        Formatted Python code string with proper line wrapping.
    """
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
    - Optional: Multiple lines defining df_modified (multi-line preprocessing support)
    - Required: fig = px.function(df or df_modified, ...)

    Multi-line preprocessing example:
        df_temp = df.filter(pl.col('x') > 0)
        df_modified = df_temp.group_by('y').agg(pl.mean('z'))
        fig = px.bar(df_modified, x='y', y='z')

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

    # Split into lines, preserving structure for multi-line statements
    all_lines = code.split("\n")

    # Remove comments and empty lines while keeping track of original structure
    lines = []
    for line in all_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)

    preprocessing_lines = []
    figure_line = None
    uses_modified_df = False

    # Track multi-line statements
    in_figure_statement = False
    in_preprocessing_statement = False
    figure_parts = []
    preprocessing_parts = []
    figure_open_parens = 0
    preprocessing_open_parens = 0

    for line in lines:
        # Check if this line starts a figure assignment
        if line.startswith("fig =") or line.startswith("fig="):
            in_figure_statement = True
            figure_parts = [line]
            figure_open_parens = line.count("(") - line.count(")")

            # Check if it's a complete single-line statement
            if figure_open_parens == 0:
                figure_line = line
                uses_modified_df = "df_modified" in line
                in_figure_statement = False
                logger.debug(f"Found single-line figure: {line[:80]}...")
        elif in_figure_statement:
            # Continue collecting figure statement lines
            figure_parts.append(line)
            figure_open_parens += line.count("(") - line.count(")")

            # Check if statement is complete
            if figure_open_parens == 0:
                # Join with newlines to preserve Python syntax for multi-line statements
                figure_line = "\n".join(figure_parts)
                uses_modified_df = "df_modified" in figure_line
                in_figure_statement = False
                logger.debug(
                    f"Found multi-line figure: {figure_line[:80]}... ({len(figure_parts)} lines)"
                )
        elif "df_modified" in line or line.startswith("df_"):
            # Start of preprocessing statement
            if not in_preprocessing_statement:
                in_preprocessing_statement = True
                preprocessing_parts = [line]
                preprocessing_open_parens = line.count("(") - line.count(")")

                # Check if it's complete single-line
                if preprocessing_open_parens == 0:
                    preprocessing_lines.append(line)
                    in_preprocessing_statement = False
                    logger.debug(f"Found single-line preprocessing: {line[:80]}...")
            else:
                # Shouldn't happen, but handle gracefully
                preprocessing_lines.append(line)
        elif in_preprocessing_statement:
            # Continue collecting preprocessing statement
            preprocessing_parts.append(line)
            preprocessing_open_parens += line.count("(") - line.count(")")

            # Check if statement is complete
            if preprocessing_open_parens == 0:
                preprocessing_lines.append("\n".join(preprocessing_parts))
                in_preprocessing_statement = False
                logger.debug(f"Found multi-line preprocessing: {len(preprocessing_parts)} lines")

    # Validation
    if not figure_line:
        return {
            "has_preprocessing": len(preprocessing_lines) > 0,
            "preprocessing_code": "\n".join(preprocessing_lines) if preprocessing_lines else None,
            "figure_code": figure_line,
            "uses_modified_df": uses_modified_df,
            "is_valid": False,
            "error_message": 'Code must contain a line starting with "fig = px.function(...)"',
        }

    # Check for invalid patterns - relaxed validation
    # Allow using df directly OR any preprocessing variable (df_modified, df_temp, etc.)
    # Only fail if preprocessing creates variables but figure doesn't use any of them
    if preprocessing_lines and not uses_modified_df:
        logger.debug(
            f"Validating: preprocessing_lines={len(preprocessing_lines)}, uses_modified_df={uses_modified_df}"
        )
        logger.debug(f"Figure line for validation: {figure_line}")

        # Check if figure line uses ANY df variable (df, df_temp, df_filtered, etc.)
        # This is more permissive - allow intermediate variable names
        # Use more precise checks to avoid false matches (e.g., "pdf", "undefined")
        # Match df as a word boundary or followed by . or _ or inside parentheses
        import re

        df_pattern = r"\bdf[\.\(,\)]|df_\w+"
        uses_any_df_var = bool(re.search(df_pattern, figure_line))

        logger.debug(f"uses_any_df_var check result: {uses_any_df_var}")

        # If preprocessing exists but figure doesn't use any dataframe, that's an error
        if not uses_any_df_var:
            logger.error(
                f"Validation failed: preprocessing exists but figure doesn't use df. Figure: {figure_line}"
            )
            return {
                "has_preprocessing": True,
                "preprocessing_code": "\n".join(preprocessing_lines),
                "figure_code": figure_line,
                "uses_modified_df": uses_modified_df,
                "is_valid": False,
                "error_message": "Preprocessing creates variables, but fig line doesn't use any dataframe (df, df_modified, etc.)",
            }

        # Otherwise allow it - user can use df_modified or other intermediate vars
        # Just log a warning if not using df_modified (best practice)
        if "df_modified" not in "\n".join(preprocessing_lines):
            logger.warning(
                "⚠️ Preprocessing doesn't create 'df_modified' variable. Consider using df_modified as final variable name for clarity."
            )

    if uses_modified_df and not preprocessing_lines:
        return {
            "has_preprocessing": False,
            "preprocessing_code": None,
            "figure_code": figure_line,
            "uses_modified_df": uses_modified_df,
            "is_valid": False,
            "error_message": "df_modified is used but not defined. Add: df_modified = df.some_processing()",
        }

    return {
        "has_preprocessing": len(preprocessing_lines) > 0,
        "preprocessing_code": "\n".join(preprocessing_lines) if preprocessing_lines else None,
        "figure_code": figure_line,
        "uses_modified_df": uses_modified_df,
        "is_valid": True,
        "error_message": None,
    }


def extract_visualization_type_from_code(code: str) -> str:
    """Extract visualization type from Python code.

    Parses the code to identify the Plotly Express function or custom
    clustering function being used.

    Args:
        code: Python code string containing a figure creation call.

    Returns:
        Visualization type name (e.g., 'scatter', 'bar', 'umap').
        Defaults to 'scatter' if no pattern is matched.
    """
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
    """Extract ALL parameter information from Python code dynamically.

    Uses AST parsing for accurate extraction, with regex fallback for
    edge cases. Handles both px.function() and create_*_plot() patterns.

    Args:
        code: Python code string containing a figure creation call.

    Returns:
        Dictionary mapping parameter names to their values.
    """
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
    """Evaluate parameter expressions that contain references to df.

    Some parameters may contain expressions like df['column'].unique() that
    need to be evaluated in the execution context with the actual DataFrame.

    Args:
        params: Dictionary of parameter names to values (some may be expressions).
        df: The DataFrame to use for evaluation.

    Returns:
        Dictionary with expression parameters evaluated to their actual values.
    """

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
