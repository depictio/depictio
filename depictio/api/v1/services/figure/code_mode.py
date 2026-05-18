"""Code-mode parsing and validation helpers (Dash-free).

Extracted from ``depictio.dash.modules.figure_component.code_mode`` so that
backend callers (Celery tasks, FastAPI routes) can analyze and parse
user-submitted Python code for figure creation without depending on the
Dash UI layer. Only the parsing/validation helpers live here; the UI
construction code remains in the Dash module.
"""

import re
from typing import Any, Dict

import polars as pl

from depictio.api.v1.configs.logging_init import logger


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
    post_figure_lines: list[str] = []
    uses_modified_df = False

    # Track multi-line statements
    in_figure_statement = False
    in_preprocessing_statement = False
    in_post_figure_statement = False
    figure_parts = []
    preprocessing_parts = []
    post_figure_parts = []
    figure_open_parens = 0
    preprocessing_open_parens = 0
    post_figure_open_parens = 0

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
        elif figure_line is not None and line.startswith("fig."):
            # Post-figure customization (fig.update_*, fig.add_*, fig.for_each_*, etc.)
            in_post_figure_statement = True
            post_figure_parts = [line]
            post_figure_open_parens = line.count("(") - line.count(")")

            if post_figure_open_parens == 0:
                post_figure_lines.append(line)
                in_post_figure_statement = False
        elif in_post_figure_statement:
            # Continue collecting post-figure statement
            post_figure_parts.append(line)
            post_figure_open_parens += line.count("(") - line.count(")")

            if post_figure_open_parens == 0:
                post_figure_lines.append("\n".join(post_figure_parts))
                in_post_figure_statement = False
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

    # Combine figure creation with post-figure customization (fig.update_*, fig.add_*, etc.)
    if figure_line and post_figure_lines:
        full_figure_code = figure_line + "\n" + "\n".join(post_figure_lines)
        logger.debug(f"Including {len(post_figure_lines)} post-figure customization line(s)")
    else:
        full_figure_code = figure_line

    # Validation
    if not figure_line:
        return {
            "has_preprocessing": len(preprocessing_lines) > 0,
            "preprocessing_code": "\n".join(preprocessing_lines) if preprocessing_lines else None,
            "figure_code": full_figure_code,
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
                "figure_code": full_figure_code,
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
            "figure_code": full_figure_code,
            "uses_modified_df": uses_modified_df,
            "is_valid": False,
            "error_message": "df_modified is used but not defined. Add: df_modified = df.some_processing()",
        }

    return {
        "has_preprocessing": len(preprocessing_lines) > 0,
        "preprocessing_code": "\n".join(preprocessing_lines) if preprocessing_lines else None,
        "figure_code": full_figure_code,
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
