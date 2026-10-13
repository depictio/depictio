"""Code-mode parsing and validation helpers (Dash-free).

Extracted from ``depictio.dash.modules.figure_component.code_mode`` so that
backend callers (Celery tasks, FastAPI routes) can analyze and parse
user-submitted Python code for figure creation without depending on the
Dash UI layer. Only the parsing/validation helpers live here; the UI
construction code remains in the Dash module.
"""

import ast
import re
from typing import Any

from depictio.api.v1.configs.logging_init import logger


def _assigns_fig(node: ast.AST) -> bool:
    """Whether *node* (or anything inside it) assigns the name ``fig``."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            targets = sub.targets
        elif isinstance(sub, (ast.AnnAssign, ast.AugAssign)):
            targets = [sub.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "fig" for t in targets):
            return True
    return False


def _kept_lines(lines: list[str]) -> list[str]:
    """Drop blank and comment lines, keep each line's own indentation."""
    return [line.rstrip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _split_by_ast(code: str) -> tuple[list[str], str | None, str | None] | None:
    """Split *code* at the first top-level statement that assigns ``fig``.

    The statement is taken whole, so a ``fig = px.scatter(...)`` written
    inside an ``if`` / ``else`` (one branch per shape of the data) stays in its
    block instead of being lifted out of it. The line scanner below took the
    first line that started with ``fig =`` wherever it stood, re-emitted it at
    column 0 and appended the rest verbatim, so the still-indented lines of
    that branch came back as "unexpected indent". Returns ``None`` when the
    code does not parse, so the scanner can name the problem as it did before.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    src_lines = code.split("\n")
    for stmt in tree.body:
        if not _assigns_fig(stmt):
            continue
        start, end = stmt.lineno - 1, stmt.end_lineno or stmt.lineno
        preprocessing_lines = _kept_lines(src_lines[:start])
        figure_line = "\n".join(src_lines[start:end])
        post_figure_lines = _kept_lines(src_lines[end:])
        full_figure_code = (
            figure_line + "\n" + "\n".join(post_figure_lines) if post_figure_lines else figure_line
        )
        return preprocessing_lines, figure_line, full_figure_code
    return [], None, None


def _split_by_scan(code: str) -> tuple[list[str], str | None, str | None]:
    """Line scanner fallback for code that does not parse."""
    # Split into lines, preserving structure for multi-line statements
    all_lines = code.split("\n")

    # Drop comments and blank lines, but keep each line's own indentation.
    # Indentation is the only thing carrying block structure, and stripping it
    # made the body of a `for` indistinguishable from a statement standing on
    # its own — which is how a loop could be taken apart line by line.
    lines: list[tuple[str, str]] = []
    for line in all_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append((line.rstrip(), stripped))

    preprocessing_lines = []
    figure_line = None
    post_figure_lines: list[str] = []

    # Track multi-line statements
    in_figure_statement = False
    in_preprocessing_statement = False
    figure_parts = []
    preprocessing_parts = []
    figure_open_parens = 0
    preprocessing_open_parens = 0

    for idx, (raw, line) in enumerate(lines):
        # Check if this line starts a figure assignment
        if line.startswith("fig =") or line.startswith("fig="):
            in_figure_statement = True
            figure_parts = [line]
            figure_open_parens = line.count("(") - line.count(")")

            # Check if it's a complete single-line statement
            if figure_open_parens == 0:
                figure_line = line
                in_figure_statement = False
                post_figure_lines = [r for r, _ in lines[idx + 1 :]]
                break
        elif in_figure_statement:
            # Continue collecting figure statement lines
            figure_parts.append(line)
            figure_open_parens += line.count("(") - line.count(")")

            # Check if statement is complete
            if figure_open_parens == 0:
                # Join with newlines to preserve Python syntax for multi-line statements
                figure_line = "\n".join(figure_parts)
                in_figure_statement = False
                logger.debug(
                    f"Found multi-line figure: {figure_line[:80]}... ({len(figure_parts)} lines)"
                )
                post_figure_lines = [r for r, _ in lines[idx + 1 :]]
                break
        elif in_preprocessing_statement:
            # Continue collecting a multi-line preprocessing statement. Checked
            # BEFORE the generic case below, which would otherwise swallow the
            # continuation lines as if each were a statement of its own.
            preprocessing_parts.append(raw)
            preprocessing_open_parens += line.count("(") - line.count(")")
            preprocessing_open_parens += line.count("[") - line.count("]")

            if preprocessing_open_parens == 0:
                preprocessing_lines.append("\n".join(preprocessing_parts))
                in_preprocessing_statement = False
        elif figure_line is None:
            # Everything before the figure statement is preprocessing.
            #
            # This used to require the line to mention `df_modified` or start
            # with `df_`, and silently DROPPED anything else — a helper list, a
            # threshold, an intermediate frame under any other name. The code
            # then ran without those lines and failed on the first name it could
            # no longer resolve ("name 'gain' is not defined"), pointing at the
            # figure line, which is not where the problem was. Naming a variable
            # is not a signal about what the code is for.
            in_preprocessing_statement = True
            preprocessing_parts = [raw]
            preprocessing_open_parens = line.count("(") - line.count(")")
            # Brackets too: `agg([` spans lines just as `agg(` does, and
            # counting only parentheses closed the statement one line early.
            preprocessing_open_parens += line.count("[") - line.count("]")

            if preprocessing_open_parens == 0:
                preprocessing_lines.append(raw)
                in_preprocessing_statement = False

    # Everything after the figure statement runs as written, verbatim.
    #
    # It used to be filtered down to the lines starting with `fig.`, on the
    # assumption that customisation is only ever a chain of `fig.update_*`
    # calls. Anything else — a loop, a condition, a helper assignment — was
    # dropped without a word, and the surviving `fig.` lines were re-emitted at
    # column 0, so a `fig.add_scatter(...)` written inside a `for` came back
    # referring to loop variables that no longer existed. The failure surfaced
    # as "name 'sub' is not defined" pointing at the figure code, which is not
    # where the user's mistake was, because there wasn't one.
    if figure_line and post_figure_lines:
        full_figure_code = figure_line + "\n" + "\n".join(post_figure_lines)
        logger.debug(f"Keeping {len(post_figure_lines)} post-figure line(s) verbatim")
    else:
        full_figure_code = figure_line
    return preprocessing_lines, figure_line, full_figure_code


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

    split = _split_by_ast(code)
    if split is None:
        split = _split_by_scan(code)
    preprocessing_lines, figure_line, full_figure_code = split
    uses_modified_df = bool(figure_line and "df_modified" in figure_line)

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

        # Does the figure use anything the preprocessing produced?
        #
        # The check used to look for a `df`-shaped name in the figure line, so
        # preprocessing that ended in a variable called anything else was
        # rejected as unused even though the figure was built from it. Read the
        # names the preprocessing actually assigns and look for those instead —
        # `df` itself still counts, since a figure may use the frame directly
        # alongside a helper.
        assigned_names = set()
        for prep_line in preprocessing_lines:
            match = re.match(r"\s*([A-Za-z_]\w*)\s*=(?!=)", prep_line)
            if match:
                assigned_names.add(match.group(1))
        df_pattern = r"\bdf[\.\(,\)]|df_\w+"
        uses_any_df_var = bool(re.search(df_pattern, figure_line)) or any(
            re.search(rf"\b{re.escape(name)}\b", figure_line) for name in assigned_names
        )

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

        # Otherwise allow it - user can use df_modified or other intermediate vars.
        # Nudge toward df_modified as a best practice, but at debug level: this runs
        # on every figure validation, so warning-level would flood the logs (and the
        # admin monitoring pane) with noise for a purely cosmetic naming preference.
        if "df_modified" not in "\n".join(preprocessing_lines):
            logger.debug(
                "Preprocessing doesn't create 'df_modified' variable. Consider using df_modified as final variable name for clarity."
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
