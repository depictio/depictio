"""
Simple and secure code executor using RestrictedPython.

This replaces the complex custom security implementation with RestrictedPython,
which is battle-tested and maintained by the Zope Foundation.
"""

import traceback
from typing import Any, Dict, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from RestrictedPython import compile_restricted
from RestrictedPython.Guards import safe_builtins, safe_globals

from depictio.api.v1.configs.logging_init import logger


def safe_getitem(obj, key):
    """Safe getitem for pandas DataFrame and Series operations."""
    return obj[key]


def safe_getattr(obj, name, default=None, getattr=getattr):
    """Safe getattr that allows pandas operations."""
    return getattr(obj, name, default)


def safe_setitem(obj, key, value):
    """Safe setitem for pandas DataFrame and Series operations."""
    obj[key] = value
    return obj


def safe_setattr(obj, name, value, setattr=setattr):
    """Safe setattr that allows pandas operations."""
    setattr(obj, name, value)
    return value


class SimpleCodeExecutor:
    """
    Simplified secure code executor using RestrictedPython.

    Provides a much cleaner and more maintainable approach than custom AST parsing.
    """

    def __init__(self):
        """Initialize the executor with safe execution environment."""
        # Create safe execution environment
        self.safe_globals = {
            **safe_globals,
            # Data manipulation libraries
            "pd": pd,
            "pandas": pd,
            "px": px,
            "go": go,
            # Safe builtins
            "__builtins__": safe_builtins,
            # Guards for pandas operations
            "_getitem_": safe_getitem,
            "_getattr_": safe_getattr,
            "_write_": safe_setitem,
            "_setattr_": safe_setattr,
        }

    def execute_code(self, code: str, dataframe: pd.DataFrame) -> Tuple[bool, Any, str]:
        """
        Execute user code safely using RestrictedPython.

        Args:
            code: Python code to execute
            dataframe: DataFrame to make available as 'df'

        Returns:
            (success: bool, result: Any, message: str)
        """
        try:
            # Compile code with RestrictedPython
            byte_code = compile_restricted(code, filename="<user_code>", mode="exec")

            if byte_code is None:
                return (
                    False,
                    None,
                    "Code compilation failed - likely contains restricted operations",
                )

            # Prepare execution environment
            execution_globals = self.safe_globals.copy()
            execution_globals["df"] = dataframe.copy()  # Provide DataFrame copy
            execution_locals: Dict[str, Any] = {}

            # Execute the compiled code
            exec(byte_code, execution_globals, execution_locals)

            # Look for the figure result
            fig = execution_locals.get("fig")
            if fig is None:
                return False, None, "No figure found. Please create a variable named 'fig'."

            # Basic validation that it's a Plotly figure
            if not hasattr(fig, "to_dict"):
                return False, None, "The 'fig' variable is not a valid Plotly figure."

            logger.info("Code executed successfully using RestrictedPython")
            return True, fig, "Code executed successfully!"

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.warning(f"Code execution failed: {error_msg}")
            # Include traceback for debugging (but not full system info)
            tb_lines = traceback.format_exc().split("\n")
            # Only include the last few lines to avoid exposing system details
            safe_tb = "\n".join(tb_lines[-3:])
            return False, None, f"{error_msg}\n{safe_tb}"


def get_code_examples() -> Dict[str, str]:
    """Get predefined code examples for different plot types."""
    return {
        "Scatter Plot": """# Basic scatter plot
fig = px.scatter(df, x='x', y='y', color='category',
                 title='Scatter Plot Example')""",
        "Line Plot": """# Line plot
fig = px.line(df, x='x', y='y', color='category',
              title='Line Plot Example')""",
        "Bar Chart": """# Bar chart
df_agg = df.groupby('category').mean().reset_index()
fig = px.bar(df_agg, x='category', y='y',
             title='Bar Chart Example')""",
        "Histogram": """# Histogram
fig = px.histogram(df, x='y', color='category',
                   title='Histogram Example')""",
        "Box Plot": """# Box plot
fig = px.box(df, x='category', y='y',
             title='Box Plot Example')""",
        "Custom Styling": """# Custom styled plot
fig = px.scatter(df, x='x', y='y', color='category',
                 size='size', hover_data=['category'])
fig.update_layout(
    title='Custom Styled Plot',
    xaxis_title='X Values',
    yaxis_title='Y Values',
    showlegend=True
)""",
        "Data Processing": """# Data processing with visualization
df_means = df.groupby('category')['y'].mean().reset_index()
df_means.rename(columns={'y': 'y_mean'}, inplace=True)

fig = px.bar(df_means, x='category', y='y_mean',
             title='Mean Y Values by Category')""",
    }
