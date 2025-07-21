"""
Prototype Dash app for testing Plotly code execution with security
Leverages the figure component builder logic from depictio/dash
"""

import ast
import re
import sys
from typing import Any

import dash
import dash_mantine_components as dmc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc

# Import depictio utilities (optional)
sys.path.append("/Users/tweber/Gits/workspaces/depictio-workspace/depictio")
try:
    from depictio.dash.modules.figure_component.definitions import get_available_visualizations
    from depictio.dash.modules.figure_component.utils import render_figure

    DEPICTIO_AVAILABLE = True
except ImportError:
    DEPICTIO_AVAILABLE = False
    print("Warning: depictio modules not available, running in standalone mode")


class SecureCodeExecutor:
    """
    Secure code executor that only allows safe Plotly/Pandas operations
    """

    # Allowed imports and functions
    ALLOWED_IMPORTS = {
        "pandas": [
            "DataFrame",
            "Series",
            "concat",
            "merge",
            "pivot_table",
            "crosstab",
            "cut",
            "qcut",
        ],
        "plotly.express": ["*"],  # All plotly express functions are allowed
        "plotly.graph_objects": [
            "Figure",
            "Scatter",
            "Bar",
            "Line",
            "Histogram",
            "Box",
            "Violin",
            "Pie",
        ],
        "numpy": [
            "array",
            "arange",
            "linspace",
            "mean",
            "std",
            "min",
            "max",
            "sum",
            "count_nonzero",
        ],
        "datetime": ["datetime", "date", "timedelta"],
        "math": ["sqrt", "log", "exp", "sin", "cos", "tan", "pi", "e"],
    }

    # Dangerous patterns to block
    DANGEROUS_PATTERNS = [
        r"import\s+os",
        r"import\s+sys",
        r"import\s+subprocess",
        r"import\s+shutil",
        r"import\s+requests",
        r"import\s+urllib",
        r"import\s+socket",
        r"import\s+pickle",
        r"import\s+eval",
        r"import\s+exec",
        r"import\s+compile",
        r"__import__",
        r"getattr",
        r"setattr",
        r"delattr",
        r"globals",
        r"locals",
        r"vars",
        r"dir",
        r"open\s*\(",
        r"file\s*\(",
        r"input\s*\(",
        r"raw_input\s*\(",
        r"execfile",
        r"reload",
        r"\.system",
        r"\.popen",
        r"\.call",
        r"\.run",
        r"\.Popen",
    ]

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.allowed_globals = {
            "df": df,
            "pd": pd,
            "px": px,
            "go": go,
            "__builtins__": {
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "list": list,
                "dict": dict,
                "tuple": tuple,
                "set": set,
                "range": range,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "sorted": sorted,
                "reversed": reversed,
                "min": min,
                "max": max,
                "sum": sum,
                "abs": abs,
                "round": round,
                "type": type,
                "isinstance": isinstance,
                "print": print,  # Allow print for debugging
            },
        }

    def validate_code(self, code: str) -> tuple[bool, str]:
        """
        Validate code for security issues
        Returns (is_valid, error_message)
        """
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return False, f"Dangerous pattern detected: {pattern}"

        # Parse AST to check for forbidden constructs
        try:
            tree = ast.parse(code)

            # Check for forbidden AST nodes
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    # Check if imports are allowed
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name not in self.ALLOWED_IMPORTS:
                                return False, f"Import '{alias.name}' not allowed"
                    elif isinstance(node, ast.ImportFrom):
                        if node.module not in self.ALLOWED_IMPORTS:
                            return False, f"Import from '{node.module}' not allowed"

                elif isinstance(node, ast.Call):
                    # Check for dangerous function calls
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ["eval", "exec", "compile", "__import__"]:
                            return False, f"Function '{node.func.id}' not allowed"

                elif isinstance(node, ast.Attribute):
                    # Check for dangerous attribute access
                    dangerous_attrs = ["__globals__", "__locals__", "__builtins__", "__code__"]
                    if node.attr in dangerous_attrs:
                        return False, f"Attribute '{node.attr}' not allowed"

        except SyntaxError as e:
            return False, f"Syntax error: {str(e)}"

        return True, ""

    def execute_code(self, code: str) -> tuple[bool, Any, str]:
        """
        Execute code safely
        Returns (success, result, error_message)
        """
        # Validate code first
        is_valid, error_msg = self.validate_code(code)
        if not is_valid:
            return False, None, error_msg

        try:
            # Execute code in restricted environment
            local_vars = {}
            exec(code, self.allowed_globals, local_vars)

            # Look for a figure object in the local variables
            fig = None
            for var_name, var_value in local_vars.items():
                if isinstance(var_value, (go.Figure, type(px.scatter(pd.DataFrame())))):
                    fig = var_value
                    break

            if fig is None:
                return (
                    False,
                    None,
                    "No Plotly figure found in code. Make sure to create a figure object.",
                )

            return True, fig, ""

        except Exception as e:
            return False, None, f"Execution error: {str(e)}"


def create_sample_dataframe() -> pd.DataFrame:
    """Create a sample DataFrame for testing"""
    return pd.DataFrame(
        {
            "x": list(range(1, 11)),
            "y": [2, 5, 3, 8, 7, 4, 9, 6, 1, 10],
            "category": ["A", "B", "A", "B", "A", "B", "A", "B", "A", "B"],
            "size": [10, 20, 15, 25, 30, 12, 18, 22, 14, 28],
            "color_val": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        }
    )


def create_app() -> dash.Dash:
    """Create the Dash application"""
    app = dash.Dash(__name__)

    # Sample DataFrame
    df = create_sample_dataframe()

    app.layout = dmc.MantineProvider(
        theme={"colorScheme": "light"},
        children=[
            dmc.Container(
                size="xl",
                children=[
                    dmc.Title(
                        "Plotly Code Prototype",
                        order=1,
                        style={"textAlign": "center", "margin": "20px"},
                    ),
                    dmc.Grid(
                        [
                            dmc.Col(
                                [
                                    dmc.Card(
                                        [
                                            dmc.CardSection(
                                                [
                                                    dmc.Title("Sample DataFrame", order=3),
                                                    dmc.Text("Available as 'df' in your code:"),
                                                    dmc.Code(
                                                        str(df.head()),
                                                        block=True,
                                                        style={"fontSize": "12px"},
                                                    ),
                                                ],
                                                withBorder=True,
                                                inheritPadding=True,
                                                py="xs",
                                            ),
                                            dmc.CardSection(
                                                [
                                                    dmc.Title("Available Libraries", order=3),
                                                    dmc.List(
                                                        [
                                                            dmc.ListItem("pandas as pd"),
                                                            dmc.ListItem("plotly.express as px"),
                                                            dmc.ListItem(
                                                                "plotly.graph_objects as go"
                                                            ),
                                                            dmc.ListItem(
                                                                "numpy functions (math operations)"
                                                            ),
                                                        ]
                                                    ),
                                                ],
                                                withBorder=True,
                                                inheritPadding=True,
                                                py="xs",
                                            ),
                                            dmc.CardSection(
                                                [
                                                    dmc.Title("Example Code", order=3),
                                                    dmc.Code(
                                                        """fig = px.scatter(df, x='x', y='y', 
                     color='category', 
                     size='size',
                     title='Sample Scatter Plot')""",
                                                        block=True,
                                                        style={"fontSize": "12px"},
                                                    ),
                                                ],
                                                withBorder=True,
                                                inheritPadding=True,
                                                py="xs",
                                            ),
                                        ]
                                    )
                                ],
                                span=4,
                            ),
                            dmc.Col(
                                [
                                    dmc.Card(
                                        [
                                            dmc.CardSection(
                                                [
                                                    dmc.Title("Python Code", order=3),
                                                    dmc.Textarea(
                                                        id="code-input",
                                                        placeholder="Enter your Plotly code here...",
                                                        value="fig = px.scatter(df, x='x', y='y', color='category', size='size', title='Sample Scatter Plot')",
                                                        minRows=10,
                                                        maxRows=20,
                                                        style={
                                                            "fontFamily": "monospace",
                                                            "fontSize": "14px",
                                                        },
                                                    ),
                                                    dmc.Space(h=10),
                                                    dmc.Button(
                                                        "Execute Code",
                                                        id="execute-btn",
                                                        color="blue",
                                                        fullWidth=True,
                                                    ),
                                                ],
                                                withBorder=True,
                                                inheritPadding=True,
                                                py="xs",
                                            ),
                                            dmc.CardSection(
                                                [
                                                    dmc.Title("Status", order=3),
                                                    dmc.Text(
                                                        "Ready to execute code",
                                                        id="status-text",
                                                        color="green",
                                                    ),
                                                ],
                                                withBorder=True,
                                                inheritPadding=True,
                                                py="xs",
                                            ),
                                        ]
                                    )
                                ],
                                span=8,
                            ),
                        ]
                    ),
                    dmc.Space(h=20),
                    dmc.Card(
                        [
                            dmc.CardSection(
                                [
                                    dmc.Title("Generated Plot", order=3),
                                    dcc.Graph(id="output-graph", style={"height": "500px"}),
                                ],
                                withBorder=True,
                                inheritPadding=True,
                                py="xs",
                            ),
                        ]
                    ),
                ],
            )
        ],
    )

    @callback(
        [
            Output("output-graph", "figure"),
            Output("status-text", "children"),
            Output("status-text", "color"),
        ],
        Input("execute-btn", "n_clicks"),
        State("code-input", "value"),
        prevent_initial_call=False,
    )
    def execute_code(n_clicks, code):
        if code is None or code.strip() == "":
            return {}, "No code provided", "orange"

        # Create executor with sample dataframe
        executor = SecureCodeExecutor(df)

        # Execute the code
        success, result, error_msg = executor.execute_code(code)

        if success:
            return result, "Code executed successfully!", "green"
        else:
            return {}, f"Error: {error_msg}", "red"

    return app


if __name__ == "__main__":
    app = create_app()
    print("Plotly Code Prototype App Created!")
    print("To run: app.run_server(debug=True)")
    print("Features:")
    print("- Secure code execution (only Plotly/Pandas allowed)")
    print("- Sample DataFrame available as 'df'")
    print("- Real-time plot generation")
    print("- Security validation against dangerous operations")
