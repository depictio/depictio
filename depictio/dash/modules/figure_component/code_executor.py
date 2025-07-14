"""
Secure code executor for Plotly code execution with comprehensive security checks
Integrated into depictio figure component system
"""

import ast
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from depictio.api.v1.configs.logging_init import logger


class SecurityError(Exception):
    """Custom exception for security-related errors"""

    pass


class RestrictedBuiltins:
    """
    Restricted builtins that only allow safe operations
    """

    def __init__(self):
        self.safe_builtins = {
            # Type constructors
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "frozenset": frozenset,
            # Utility functions
            "len": len,
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
            "pow": pow,
            "divmod": divmod,
            # String/printing (safe versions)
            "print": print,
            "repr": repr,
            "format": format,
            # Math helpers
            "all": all,
            "any": any,
            # Constants
            "True": True,
            "False": False,
            "None": None,
        }

    def __getitem__(self, name):
        if name in self.safe_builtins:
            return self.safe_builtins[name]
        raise NameError(f"name '{name}' is not defined")

    def get(self, name, default=None):
        return self.safe_builtins.get(name, default)

    def keys(self):
        return self.safe_builtins.keys()


class SecureCodeValidator:
    """
    Validates Python code for security threats using AST parsing
    """

    def __init__(self):
        # Patterns that should never appear in user code
        self.dangerous_patterns = [
            r"__import__",
            r"eval\s*\(",
            r"exec\s*\(",
            r"compile\s*\(",
            r"globals\s*\(",
            r"locals\s*\(",
            r"vars\s*\(",
            r"dir\s*\(",
            r"getattr\s*\(",
            r"setattr\s*\(",
            r"hasattr\s*\(",
            r"delattr\s*\(",
            r"open\s*\(",
            r"file\s*\(",
            r"input\s*\(",
            r"raw_input\s*\(",
            r"\.system\s*\(",
            r"\.popen\s*\(",
            r"\.call\s*\(",
            r"\.run\s*\(",
            r"subprocess",
            r"\.read\s*\(",
            r"\.write\s*\(",
            r"\.delete\s*\(",
            r"\.remove\s*\(",
            r"\.mkdir\s*\(",
            r"\.rmdir\s*\(",
            r"\.chmod\s*\(",
            r"\.chown\s*\(",
        ]

        # Allowed imports
        self.allowed_modules = {
            "pandas",
            "pd",
            "numpy",
            "np",
            "plotly.express",
            "px",
            "plotly.graph_objects",
            "go",
            "datetime",
            "date",
            "timedelta",
        }

        # Dangerous node types (ast.Exec was removed in Python 3)
        self.dangerous_nodes = {
            ast.Import,
            ast.ImportFrom,
            ast.Global,
            ast.Nonlocal,
        }

    def validate_patterns(self, code: str) -> List[str]:
        """Check for dangerous patterns using regex"""
        violations = []
        for pattern in self.dangerous_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                violations.append(f"Dangerous pattern detected: {pattern}")
        return violations

    def validate_ast(self, code: str) -> List[str]:
        """Validate code using AST parsing"""
        violations = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                # Check for dangerous node types
                if type(node) in self.dangerous_nodes:
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        # Check if it's an allowed import
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                if alias.name not in self.allowed_modules:
                                    violations.append(f"Disallowed import: {alias.name}")
                        elif isinstance(node, ast.ImportFrom):
                            if node.module not in self.allowed_modules:
                                violations.append(f"Disallowed import from: {node.module}")
                    else:
                        violations.append(f"Dangerous AST node: {type(node).__name__}")

                # Check for dangerous attribute access
                if isinstance(node, ast.Attribute):
                    if node.attr in ["__class__", "__base__", "__subclasses__", "__globals__"]:
                        violations.append(f"Dangerous attribute access: {node.attr}")

                # Check for dangerous function calls
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ["eval", "exec", "compile", "__import__"]:
                            violations.append(f"Dangerous function call: {node.func.id}")

        except SyntaxError as e:
            violations.append(f"Syntax error: {e}")

        return violations

    def validate(self, code: str) -> Tuple[bool, List[str]]:
        """
        Comprehensive validation of user code
        Returns (is_safe, violations)
        """
        violations = []

        # Pattern-based validation
        violations.extend(self.validate_patterns(code))

        # AST-based validation
        violations.extend(self.validate_ast(code))

        is_safe = len(violations) == 0
        return is_safe, violations


class SecureCodeExecutor:
    """
    Executes user code in a restricted environment with security checks
    """

    def __init__(self):
        self.validator = SecureCodeValidator()
        self.restricted_builtins = RestrictedBuiltins()

    def execute_code(self, code: str, dataframe: pd.DataFrame) -> Tuple[bool, Any, str]:
        """
        Execute user code safely and return the result

        Args:
            code: Python code to execute
            dataframe: DataFrame to make available as 'df'

        Returns:
            (success: bool, result: Any, message: str)
        """
        # Validate code first
        is_safe, violations = self.validator.validate(code)
        if not is_safe:
            error_msg = "Security violation(s) detected:\n" + "\n".join(violations)
            logger.warning(f"Code execution blocked due to security violations: {violations}")
            return False, None, error_msg

        try:
            # Create restricted execution environment
            restricted_globals = {
                "__builtins__": self.restricted_builtins,
                "pd": pd,
                "pandas": pd,
                "px": px,
                "go": go,
                "np": np,
                "numpy": np,
                "datetime": datetime,
                "date": date,
                "timedelta": timedelta,
                "df": dataframe.copy(),  # Provide a copy to prevent modifications
            }

            # Create local scope
            restricted_locals = {}

            # Execute the code
            exec(code, restricted_globals, restricted_locals)

            # Look for a figure in the local namespace
            fig = restricted_locals.get("fig")
            if fig is None:
                return (
                    False,
                    None,
                    "No figure found. Please ensure your code creates a variable named 'fig'.",
                )

            # Validate that it's a Plotly figure
            if not hasattr(fig, "to_dict"):
                return False, None, "The 'fig' variable is not a valid Plotly figure."

            logger.info("Code executed successfully and figure generated")
            return True, fig, "Code executed successfully!"

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.error(f"Code execution failed: {error_msg}")
            return False, None, error_msg


def get_code_examples() -> Dict[str, str]:
    """Get predefined code examples for different plot types"""
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
        "Advanced Processing": """# Data processing with visualization
df_processed = df.groupby('category').agg({
    'x': 'mean',
    'y': ['mean', 'std']
}).round(2)

df_processed.columns = ['x_mean', 'y_mean', 'y_std']
df_processed = df_processed.reset_index()

fig = px.bar(df_processed, x='category', y='y_mean',
             error_y='y_std', title='Processed Data Visualization')""",
    }
