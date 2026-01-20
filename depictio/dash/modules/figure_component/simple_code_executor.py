"""
Simple and secure code executor using RestrictedPython.

This replaces the complex custom security implementation with RestrictedPython,
which is battle-tested and maintained by the Zope Foundation.
"""

import traceback
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import polars as pl
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


def safe_iter_unpack_sequence(seq, *args):
    """Safe implementation of _iter_unpack_sequence_ for RestrictedPython."""
    # RestrictedPython may pass additional arguments, so we accept them but only use seq
    return iter(seq)


def safe_getiter(obj):
    """Safe implementation of _getiter_ for RestrictedPython."""
    return iter(obj)


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
            # Visualization libraries only - no data import/export
            "px": px,
            # Note: go (plotly.graph_objects) available for code mode
            "go": go,
            # Polars & Pandas
            "pl": pl,
            "pd": pd,
            "np": np,
            # Safe builtins
            "__builtins__": safe_builtins,
            # Guards for dataframe operations
            "_getitem_": safe_getitem,
            "_getattr_": safe_getattr,
            "_write_": safe_setitem,
            "_setattr_": safe_setattr,
            # Additional safe functions for complex operations
            "_iter_unpack_sequence_": safe_iter_unpack_sequence,
            "_getiter_": safe_getiter,
            "enumerate": enumerate,
            "zip": zip,
            "len": len,
            "range": range,
            "list": list,
            "dict": dict,
            "tuple": tuple,
        }

    def _validate_no_df_assignment(self, code: str) -> Tuple[bool, str]:
        """
        Validate that the code doesn't attempt to reassign the 'df' variable.

        Args:
            code: Python code to validate

        Returns:
            (is_valid: bool, error_message: str)
        """
        import ast

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Syntax error in code: {e}"

        # Check for df assignment
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "df":
                        return False, "❌ Cannot reassign 'df' variable. Use the provided dataset."
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "df":
                    return (
                        False,
                        "❌ Cannot modify 'df' variable assignment. Use the provided dataset.",
                    )

        return True, ""

    def execute_code(self, code: str, dataframe: pl.DataFrame) -> Tuple[bool, Any, str]:
        """
        Execute user code safely using RestrictedPython with df_modified constraint support.

        Args:
            code: Python code to execute
            dataframe: DataFrame to make available as 'df'

        Returns:
            (success: bool, result: Any, message: str)
        """
        from .code_mode import analyze_constrained_code

        # Analyze code structure first
        analysis = analyze_constrained_code(code)

        if not analysis["is_valid"]:
            return False, None, f"❌ Code validation failed: {analysis['error_message']}"
        try:
            # First, validate that df is not being reassigned
            is_valid, validation_error = self._validate_no_df_assignment(code)
            if not is_valid:
                return False, None, validation_error

            # Prepare execution environment
            execution_globals = self.safe_globals.copy()
            execution_globals["df"] = dataframe.clone()  # Provide DataFrame copy
            execution_locals: Dict[str, Any] = {}

            # Handle preprocessing if needed
            if analysis["has_preprocessing"]:
                logger.info("🔄 Executing preprocessing step")

                # Compile and execute preprocessing code
                preprocessing_code = analysis["preprocessing_code"]
                preprocessing_bytecode = compile_restricted(
                    preprocessing_code, filename="<preprocessing>", mode="exec"
                )

                if preprocessing_bytecode is None:
                    return (
                        False,
                        None,
                        "❌ Preprocessing compilation failed - likely contains restricted operations",
                    )

                # Execute preprocessing
                exec(preprocessing_bytecode, execution_globals, execution_locals)

                # Verify some preprocessing variable was created
                preprocessing_vars = [k for k in execution_locals.keys() if k.startswith("df")]
                if not preprocessing_vars:
                    return (
                        False,
                        None,
                        "❌ Preprocessing failed: No dataframe variables created",
                    )

                logger.info(f"✅ Preprocessing successful: Created {', '.join(preprocessing_vars)}")

            # Execute figure generation code
            logger.info("🎨 Executing figure generation code")
            figure_code = analysis["figure_code"]
            figure_bytecode = compile_restricted(figure_code, filename="<figure_code>", mode="exec")

            if figure_bytecode is None:
                return (
                    False,
                    None,
                    "❌ Figure code compilation failed - likely contains restricted operations",
                )

            # Execute figure generation (execution_locals already contains df_modified if created)
            exec(figure_bytecode, execution_globals, execution_locals)

            # Look for the figure result
            fig = execution_locals.get("fig")
            if fig is None:
                return False, None, "❌ No figure found. Please create a variable named 'fig'."

            # Basic validation that it's a Plotly figure
            if not hasattr(fig, "to_dict"):
                return False, None, "❌ The 'fig' variable is not a valid Plotly figure."

            preprocessing_msg = " with preprocessing" if analysis["has_preprocessing"] else ""
            logger.info(f"✅ Code executed successfully using RestrictedPython{preprocessing_msg}")
            return True, fig, f"✅ Code executed successfully{preprocessing_msg}!"

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.warning(f"Code execution failed: {error_msg}")
            # Include traceback for debugging (but not full system info)
            tb_lines = traceback.format_exc().split("\n")
            # Only include the last few lines to avoid exposing system details
            safe_tb = "\n".join(tb_lines[-3:])
            return False, None, f"{error_msg}\n{safe_tb}"

    def execute_preprocessing_only(
        self, code: str, dataframe: pl.DataFrame
    ) -> Tuple[bool, Any, str]:
        """
        Execute only preprocessing code and return df_modified.

        Args:
            code: Full user code (will extract preprocessing part)
            dataframe: DataFrame to make available as 'df'

        Returns:
            (success: bool, df_modified: DataFrame, message: str)
        """
        from .code_mode import analyze_constrained_code

        # Analyze code structure first
        analysis = analyze_constrained_code(code)

        if not analysis["is_valid"]:
            return False, None, f"❌ Code validation failed: {analysis['error_message']}"

        if not analysis["has_preprocessing"]:
            return False, None, "❌ No preprocessing code found"

        try:
            # Prepare execution environment
            execution_globals = self.safe_globals.copy()
            execution_globals["df"] = dataframe.clone()  # Provide DataFrame copy
            execution_locals: Dict[str, Any] = {}

            # Compile and execute preprocessing code only
            preprocessing_code = analysis["preprocessing_code"]
            preprocessing_bytecode = compile_restricted(
                preprocessing_code, filename="<preprocessing>", mode="exec"
            )

            if preprocessing_bytecode is None:
                return (
                    False,
                    None,
                    "❌ Preprocessing compilation failed - likely contains restricted operations",
                )

            # Execute preprocessing
            exec(preprocessing_bytecode, execution_globals, execution_locals)

            # Verify df_modified was created
            if "df_modified" not in execution_locals:
                return False, None, "❌ Preprocessing failed: 'df_modified' variable not created"

            df_modified = execution_locals["df_modified"]
            logger.info("✅ Preprocessing-only execution successful: df_modified created")

            # Verify that df_modified is a Polars DataFrame
            if not isinstance(df_modified, pl.DataFrame):
                return (
                    False,
                    None,
                    f"❌ Expected Polars DataFrame, got {type(df_modified)}: {df_modified}",
                )
            logger.info("df_modified is already a Polars DataFrame")
            logger.info(f"df_modified head:\n{df_modified.head()}")
            return True, df_modified, "✅ Preprocessing successful"

        except Exception as e:
            error_msg = f"Preprocessing execution error: {str(e)}"
            logger.warning(f"Preprocessing execution failed: {error_msg}")
            return False, None, error_msg


def get_code_examples() -> Dict[str, str]:
    """Get predefined code examples for different plot types using iris dataset."""
    return {
        "Scatter Plot": """# Basic scatter plot
fig = px.scatter(df, x='sepal.length', y='sepal.width', color='variety', title='Sepal Dimensions')""",
        "Histogram": """# Histogram
fig = px.histogram(df, x='petal.length', color='variety', title='Petal Length Distribution')""",
        "Box Plot": """# Box plot
fig = px.box(df, x='variety', y='petal.width', title='Petal Width by Variety')""",
        "Pie Chart": """# Pie chart with groupby
df_modified = df.to_pandas().groupby('variety')['sepal.length'].sum().reset_index()
fig = px.pie(df_modified, values='sepal.length', names='variety', title='Sepal Length Distribution by Variety')""",
        "Pandas Processing": """# Data processing with pandas
df_modified = df.to_pandas().groupby('variety')['sepal.width'].mean().reset_index()
fig = px.bar(df_modified, x='variety', y='sepal.width', color='variety', title='Average Sepal Width by Variety')""",
        "Polars Processing": """# Data processing with polars
df_modified = df.group_by('variety').agg(pl.col('petal.length').mean())
fig = px.bar(df_modified, x='variety', y='petal.length', color='variety', title='Average Petal Length by Variety')""",
        "Custom Styling": """# Custom styled plot
fig = px.scatter(df, x='sepal.length', y='petal.length', color='variety', size='sepal.width', hover_data=['petal.width'])
fig.update_layout(title='Sepal vs Petal Length', xaxis_title='Sepal Length (cm)', yaxis_title='Petal Length (cm)')""",
    }
