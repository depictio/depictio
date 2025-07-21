"""
Secure code executor for Plotly code execution with comprehensive security checks
"""

import ast
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, date, timedelta


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
            # Type checking
            "type": type,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "hasattr": hasattr,
            # String operations
            "chr": chr,
            "ord": ord,
            "repr": repr,
            "ascii": ascii,
            "format": format,
            # Math operations
            "any": any,
            "all": all,
            # Safe I/O (limited)
            "print": print,
            # Exceptions (for proper error handling)
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "AttributeError": AttributeError,
            "RuntimeError": RuntimeError,
            "ZeroDivisionError": ZeroDivisionError,
        }

    def __getitem__(self, name):
        if name in self.safe_builtins:
            return self.safe_builtins[name]
        raise SecurityError(f"Access to builtin '{name}' is not allowed")

    def __contains__(self, name):
        return name in self.safe_builtins

    def get(self, name, default=None):
        return self.safe_builtins.get(name, default)


class SecureCodeValidator:
    """
    Validates Python code for security issues before execution
    """

    # Allowed module imports
    ALLOWED_MODULES = {
        "pandas": {
            "pd": [
                "DataFrame",
                "Series",
                "concat",
                "merge",
                "pivot_table",
                "crosstab",
                "cut",
                "qcut",
                "to_datetime",
                "to_numeric",
                "get_dummies",
                "melt",
                "groupby",
                "agg",
                "transform",
                "apply",
                "map",
                "replace",
                "fillna",
                "dropna",
                "drop_duplicates",
                "sort_values",
                "reset_index",
                "set_index",
            ]
        },
        "plotly.express": {
            "px": [
                "scatter",
                "line",
                "bar",
                "histogram",
                "box",
                "violin",
                "pie",
                "area",
                "density_heatmap",
                "density_contour",
                "scatter_3d",
                "line_3d",
                "bar_polar",
                "line_polar",
                "scatter_polar",
                "choropleth",
                "scatter_mapbox",
                "line_mapbox",
                "density_mapbox",
                "choropleth_mapbox",
                "sunburst",
                "treemap",
                "icicle",
                "funnel",
                "funnel_area",
                "strip",
                "ecdf",
                "scatter_matrix",
                "parallel_coordinates",
                "parallel_categories",
                "imshow",
                "timeline",
                "colors",
            ]
        },
        "plotly.graph_objects": {
            "go": [
                "Figure",
                "Scatter",
                "Bar",
                "Line",
                "Histogram",
                "Box",
                "Violin",
                "Pie",
                "Heatmap",
                "Contour",
                "Surface",
                "Mesh3d",
                "Scatter3d",
                "Layout",
                "Annotation",
                "Scatterpolar",
                "Barpolar",
                "Scattermapbox",
                "Choroplethmapbox",
                "Densitymapbox",
                "Sunburst",
                "Treemap",
                "Icicle",
                "Funnel",
                "Funnelarea",
                "Indicator",
                "Table",
            ]
        },
        "numpy": {
            "np": [
                "array",
                "arange",
                "linspace",
                "zeros",
                "ones",
                "empty",
                "full",
                "eye",
                "random",
                "mean",
                "std",
                "var",
                "min",
                "max",
                "sum",
                "prod",
                "median",
                "percentile",
                "quantile",
                "sort",
                "argsort",
                "argmin",
                "argmax",
                "unique",
                "where",
                "select",
                "concatenate",
                "stack",
                "hstack",
                "vstack",
                "split",
                "reshape",
                "transpose",
                "flatten",
                "squeeze",
                "expand_dims",
                "sin",
                "cos",
                "tan",
                "exp",
                "log",
                "log10",
                "sqrt",
                "power",
                "absolute",
                "sign",
                "round",
                "floor",
                "ceil",
                "pi",
                "e",
                "inf",
                "nan",
                "isnan",
                "isinf",
                "isfinite",
            ]
        },
        "datetime": {"datetime": ["datetime", "date", "time", "timedelta", "timezone"]},
        "math": {
            "math": [
                "sqrt",
                "pow",
                "exp",
                "log",
                "log10",
                "sin",
                "cos",
                "tan",
                "asin",
                "acos",
                "atan",
                "atan2",
                "sinh",
                "cosh",
                "tanh",
                "degrees",
                "radians",
                "pi",
                "e",
                "inf",
                "nan",
                "isnan",
                "isinf",
                "isfinite",
                "floor",
                "ceil",
                "trunc",
                "fabs",
                "factorial",
                "gcd",
                "lcm",
                "modf",
                "frexp",
                "ldexp",
            ]
        },
    }

    # Patterns that are definitely dangerous
    DANGEROUS_PATTERNS = [
        # System operations
        r"import\s+os\b",
        r"import\s+sys\b",
        r"import\s+subprocess\b",
        r"import\s+shutil\b",
        r"import\s+pathlib\b",
        r"import\s+glob\b",
        r"import\s+tempfile\b",
        # Network operations
        r"import\s+requests\b",
        r"import\s+urllib\b",
        r"import\s+http\b",
        r"import\s+socket\b",
        r"import\s+ssl\b",
        r"import\s+ftplib\b",
        r"import\s+smtplib\b",
        r"import\s+httpx\b",
        r"import\s+aiohttp\b",
        r"import\s+websockets\b",
        r"import\s+paramiko\b",
        r"import\s+telnetlib\b",
        r"import\s+asyncio\b",
        r"import\s+concurrent\b",
        r"import\s+threading\b",
        r"import\s+multiprocessing\b",
        # Package installation and management
        r"import\s+pip\b",
        r"import\s+setuptools\b",
        r"import\s+distutils\b",
        r"import\s+pkg_resources\b",
        r"import\s+conda\b",
        r"import\s+easy_install\b",
        r"pip\s+install",
        r"pip\.main",
        r"pip\.install",
        r"pip\.download",
        r"conda\s+install",
        r"easy_install",
        # Dynamic package loading
        r"importlib\.import_module",
        r"importlib\.reload",
        r"importlib\.invalidate_caches",
        r"__import__\s*\(",
        # Database connections
        r"import\s+sqlite3\b",
        r"import\s+psycopg2\b",
        r"import\s+pymongo\b",
        r"import\s+redis\b",
        r"import\s+mysql\b",
        r"import\s+sqlalchemy\b",
        # Code execution
        r"import\s+pickle\b",
        r"import\s+marshal\b",
        r"import\s+importlib\b",
        r"import\s+runpy\b",
        r"import\s+code\b",
        r"import\s+codeop\b",
        # Dangerous functions
        r"__import__",
        r"eval\s*\(",
        r"exec\s*\(",
        r"compile\s*\(",
        r"getattr\s*\(",
        r"setattr\s*\(",
        r"delattr\s*\(",
        r"hasattr\s*\(",  # Could be used for attribute discovery
        r"globals\s*\(",
        r"locals\s*\(",
        r"vars\s*\(",
        r"dir\s*\(",
        # File operations
        r"open\s*\(",
        r"file\s*\(",
        r"input\s*\(",
        r"raw_input\s*\(",
        # Process operations
        r"\.system\s*\(",
        r"\.popen\s*\(",
        r"\.call\s*\(",
        r"\.run\s*\(",
        r"\.Popen\s*\(",
        r"\.spawn\s*\(",
        r"\.install\s*\(",
        r"\.check_call\s*\(",
        r"\.check_output\s*\(",
        # Network function calls
        r"\.get\s*\(",  # HTTP GET
        r"\.post\s*\(",  # HTTP POST
        r"\.put\s*\(",  # HTTP PUT
        r"\.delete\s*\(",  # HTTP DELETE
        r"\.request\s*\(",  # Generic HTTP request
        r"\.urlopen\s*\(",  # URL opening
        r"\.urlretrieve\s*\(",  # URL retrieval
        r"\.connect\s*\(",  # Socket connections
        r"\.send\s*\(",  # Socket send
        r"\.recv\s*\(",  # Socket receive
        r"\.download\s*\(",  # Download operations
        # Dangerous attributes
        r"__globals__",
        r"__locals__",
        r"__builtins__",
        r"__code__",
        r"__closure__",
        r"__defaults__",
        r"__dict__",
        r"__class__",
        r"__bases__",
        r"__mro__",
        r"__subclasses__",
        r"func_globals",
        r"func_code",
        r"func_closure",
        r"func_defaults",
        # Module introspection
        r"\.modules\b",
        r"\.path\b",
        r"\.meta_path\b",
        r"\.path_hooks\b",
        # Dangerous keywords
        r"\byield\s+from\b",  # Could be used to bypass restrictions
        r"\bnonlocal\b",  # Could access outer scope
        r"\bglobal\b",  # Could modify global scope
    ]

    # AST node types that are forbidden
    FORBIDDEN_AST_NODES = {
        ast.Global,  # global statements
        ast.Nonlocal,  # nonlocal statements
        ast.AsyncFunctionDef,  # async functions
        ast.AsyncWith,  # async with statements
        ast.AsyncFor,  # async for loops
        ast.Await,  # await expressions
        ast.Yield,  # yield expressions
        ast.YieldFrom,  # yield from expressions
    }

    def __init__(self):
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.DANGEROUS_PATTERNS
        ]

    def validate_code(self, code: str) -> Tuple[bool, str]:
        """
        Comprehensive code validation
        Returns (is_valid, error_message)
        """
        # Check for dangerous patterns
        for pattern in self.compiled_patterns:
            if pattern.search(code):
                return False, f"Dangerous pattern detected: {pattern.pattern}"

        # Parse and validate AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Syntax error: {str(e)}"

        # Walk the AST and check for forbidden constructs
        for node in ast.walk(tree):
            # Check for forbidden node types
            if any(isinstance(node, forbidden_type) for forbidden_type in self.FORBIDDEN_AST_NODES):
                return False, f"Forbidden construct: {type(node).__name__}"

            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in self.ALLOWED_MODULES:
                        return False, f"Import '{alias.name}' not allowed"

            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    return False, "Relative imports not allowed"

                module_parts = node.module.split(".")
                main_module = module_parts[0]

                if main_module not in self.ALLOWED_MODULES:
                    return False, f"Import from '{node.module}' not allowed"

                # Check specific imported names
                if node.names[0].name != "*":  # Not a wildcard import
                    allowed_names = set()
                    for alias_name, names in self.ALLOWED_MODULES[main_module].items():
                        allowed_names.update(names)

                    for alias in node.names:
                        if alias.name not in allowed_names:
                            return False, f"Import '{alias.name}' from '{node.module}' not allowed"

            # Check function calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    dangerous_funcs = [
                        "eval",
                        "exec",
                        "compile",
                        "__import__",
                        "getattr",
                        "setattr",
                        "delattr",
                    ]
                    if node.func.id in dangerous_funcs:
                        return False, f"Function '{node.func.id}' not allowed"

                elif isinstance(node.func, ast.Attribute):
                    # Check for dangerous method calls
                    if node.func.attr in ["system", "popen", "call", "run", "Popen", "spawn"]:
                        return False, f"Method '{node.func.attr}' not allowed"

            # Check attribute access
            elif isinstance(node, ast.Attribute):
                dangerous_attrs = [
                    "__globals__",
                    "__locals__",
                    "__builtins__",
                    "__code__",
                    "__closure__",
                    "__defaults__",
                    "__dict__",
                    "__class__",
                    "__bases__",
                    "__mro__",
                    "__subclasses__",
                    "func_globals",
                    "func_code",
                    "func_closure",
                    "func_defaults",
                ]
                if node.attr in dangerous_attrs:
                    return False, f"Attribute '{node.attr}' not allowed"

            # Check for dangerous names
            elif isinstance(node, ast.Name):
                dangerous_names = [
                    "__import__",
                    "eval",
                    "exec",
                    "compile",
                    "globals",
                    "locals",
                    "vars",
                    "dir",
                ]
                if node.id in dangerous_names:
                    return False, f"Name '{node.id}' not allowed"

        return True, ""


class SecureCodeExecutor:
    """
    Secure code executor for Plotly code with comprehensive security
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()  # Make a copy to avoid modifications
        self.validator = SecureCodeValidator()
        self.restricted_builtins = RestrictedBuiltins()

        # Create safe global environment
        self.safe_globals = {
            "df": self.df,
            "pd": pd,
            "px": px,
            "go": go,
            "np": np,
            "datetime": datetime,
            "date": date,
            "timedelta": timedelta,
            "__builtins__": self.restricted_builtins,
            "__name__": "__main__",
            "__doc__": None,
        }

    def execute_code(self, code: str) -> Tuple[bool, Any, str]:
        """
        Execute code safely with comprehensive security checks
        Returns (success, result, error_message)
        """
        # Validate code first
        is_valid, error_msg = self.validator.validate_code(code)
        if not is_valid:
            return False, None, f"Security violation: {error_msg}"

        # Create isolated execution environment
        local_vars = {}

        try:
            # Execute code in restricted environment
            exec(code, self.safe_globals, local_vars)

            # Look for a figure object in the local variables
            fig = None
            for var_name, var_value in local_vars.items():
                if isinstance(var_value, go.Figure):
                    fig = var_value
                    break
                elif hasattr(var_value, "_figure"):  # Plotly Express figures
                    fig = var_value
                    break

            if fig is None:
                return (
                    False,
                    None,
                    "No Plotly figure found in code. Make sure to create a figure object (e.g., fig = px.scatter(...))",
                )

            return True, fig, ""

        except SecurityError as e:
            return False, None, f"Security error: {str(e)}"
        except Exception as e:
            return False, None, f"Execution error: {str(e)}"

    def get_safe_environment_info(self) -> Dict[str, Any]:
        """
        Get information about the safe execution environment
        """
        return {
            "available_modules": list(self.validator.ALLOWED_MODULES.keys()),
            "dataframe_shape": self.df.shape,
            "dataframe_columns": list(self.df.columns),
            "dataframe_dtypes": self.df.dtypes.to_dict(),
            "sample_data": self.df.head().to_dict(),
            "restricted_builtins": list(self.restricted_builtins.safe_builtins.keys()),
        }
