"""
Safe Polars filter expression validation and execution.

Provides a sandboxed evaluator for Polars filter expressions defined in YAML
component configurations. Expressions are validated against an allowlist of safe
constructs before being evaluated in a restricted namespace.

Two filtering paradigms are supported:

**Row-level filtering** — keep individual rows matching a condition:
    ``"col('read_depth') >= 30"``
    ``"(col('read_depth') >= 30) & (col('contamination') < 0.05)"``
    ``"col('gene').str.contains('HOX')"``
    ``"col('tumor_expr') > col('normal_expr')"``
    ``"col('expression').is_between(1.0, 100.0)"``
    ``"~col('sample_type').is_in(['control', 'blank'])"``

**Group-level filtering** — keep rows belonging to groups that pass an aggregate
condition, using Polars window functions via ``.over()``:
    ``"col('cell_type').count().over('cell_type') >= 100"``
    ``"col('expression').mean().over('gene') > 1.0"``
    ``"col('expression').std().over('gene') < 0.5"``
    ``"col('read_depth').min().over('batch') > 30"``

Allowed constructs:
    - ``col('name')`` with comparison operators: ``>=``, ``<=``, ``>``, ``<``, ``==``, ``!=``
    - Logical operators: ``&``, ``|``, ``~``
    - Parentheses for grouping
    - Literal values: numbers, quoted strings, ``True``, ``False``, ``None``
    - Methods: ``.is_in()``, ``.is_null()``, ``.is_not_null()``
    - String methods: ``.str.contains()``, ``.str.starts_with()``, ``.str.ends_with()``,
      ``.str.to_lowercase()``, ``.str.to_uppercase()``, ``.str.strip()``
    - Range check: ``.is_between(low, high)``
    - Aggregations (for ``.over()``): ``.mean()``, ``.sum()``, ``.min()``, ``.max()``,
      ``.count()``, ``.std()``, ``.median()``
    - Window function: ``.over('group_col')``
    - Date accessors: ``.dt.year()``, ``.dt.month()``, ``.dt.day()``
    - Type casting: ``.cast()``
    - ``lit()`` for explicit literal wrapping
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

# Patterns that indicate dangerous/unsafe code
_BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bimport\b"),
    re.compile(r"\bexec\b"),
    re.compile(r"\beval\b"),
    re.compile(r"\bcompile\b"),
    re.compile(r"\bgetattr\b"),
    re.compile(r"\bsetattr\b"),
    re.compile(r"\bdelattr\b"),
    re.compile(r"\bglobals\b"),
    re.compile(r"\blocals\b"),
    re.compile(r"\bvars\b"),
    re.compile(r"\bdir\b"),
    re.compile(r"__\w+__"),  # dunder attributes
    re.compile(r"\bopen\b"),
    re.compile(r"\bos\b"),
    re.compile(r"\bsys\b"),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bshutil\b"),
    re.compile(r"\bpathlib\b"),
    re.compile(r"\blambda\b"),
    re.compile(r"\bdef\b"),
    re.compile(r"\bclass\b"),
    re.compile(r"\bfor\b"),
    re.compile(r"\bwhile\b"),
    re.compile(r"\bwith\b"),
    re.compile(r"\braise\b"),
    re.compile(r"\byield\b"),
    re.compile(r"\bassert\b"),
    re.compile(r"\bdel\b"),
    re.compile(r"\bglobal\b"),
    re.compile(r"\bnonlocal\b"),
    re.compile(r"\bbreakpoint\b"),
    re.compile(r"\bprint\b"),
    re.compile(r"\binput\b"),
]

# Allowed function/method names that can appear in expressions
_ALLOWED_CALLABLES: set[str] = {
    # Core constructors
    "col",
    "lit",
    # Membership & null checks
    "is_in",
    "is_null",
    "is_not_null",
    # Range check
    "is_between",
    # String namespace & methods
    "str",
    "contains",
    "starts_with",
    "ends_with",
    "to_lowercase",
    "to_uppercase",
    "strip",
    "lstrip",
    "rstrip",
    # Type casting
    "cast",
    # Aggregation methods (used with .over() for group-level filtering)
    "mean",
    "sum",
    "min",
    "max",
    "count",
    "std",
    "median",
    # Window function (group-by broadcasting)
    "over",
    # Date accessors
    "dt",
    "year",
    "month",
    "day",
}


def validate_filter_expr(expr_str: str) -> None:
    """Validate that a Polars filter expression string is safe for evaluation.

    Checks the expression against a blocklist of dangerous patterns and verifies
    that only allowed callables are used.

    Args:
        expr_str: The Polars filter expression string to validate.

    Raises:
        ValueError: If the expression is empty, contains blocked patterns,
            or uses disallowed function calls.
    """
    if not expr_str or not expr_str.strip():
        raise ValueError("filter_expr must be a non-empty string")

    stripped = expr_str.strip()

    # Check for blocked patterns
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(stripped):
            raise ValueError(
                f"filter_expr contains disallowed construct: '{pattern.pattern}'. "
                f"Only col(), lit(), comparison operators, and logical operators are allowed."
            )

    # Extract all function-call names (word followed by '(')
    call_names = re.findall(r"\b([a-zA-Z_]\w*)\s*\(", stripped)
    for name in call_names:
        if name not in _ALLOWED_CALLABLES:
            allowed = ", ".join(sorted(_ALLOWED_CALLABLES))
            raise ValueError(
                f"filter_expr contains disallowed function call '{name}()'. "
                f"Allowed callables: {allowed}"
            )

    # Verify balanced parentheses
    depth = 0
    for ch in stripped:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            raise ValueError("filter_expr has unbalanced parentheses")
    if depth != 0:
        raise ValueError("filter_expr has unbalanced parentheses")


def build_filter_expr(expr_str: str) -> "pl.Expr":
    """Validate and compile a filter expression string into a Polars Expr.

    Useful for callers that want to apply the expression to a ``LazyFrame``
    via ``.filter(expr)`` without materializing a ``DataFrame`` first.

    Args:
        expr_str: A Polars filter expression string.

    Returns:
        A Polars ``Expr`` object.

    Raises:
        ValueError: If the expression is invalid or doesn't evaluate to a
            Polars ``Expr``.
        RuntimeError: If expression evaluation fails.
    """
    import polars as pl

    validate_filter_expr(expr_str)

    safe_namespace: dict[str, object] = {
        "col": pl.col,
        "lit": pl.lit,
        "True": True,
        "False": False,
        "None": None,
        "__builtins__": {},
    }

    try:
        expr = eval(expr_str, safe_namespace)  # noqa: S307
    except Exception as e:
        raise RuntimeError(f"Failed to evaluate filter_expr '{expr_str}': {e}") from e

    if not isinstance(expr, pl.Expr):
        raise ValueError(f"filter_expr must evaluate to a Polars Expr, got {type(expr).__name__}")

    return expr


def apply_filter_expr(df: "pl.DataFrame", expr_str: str) -> "pl.DataFrame":
    """Apply a validated Polars filter expression to a DataFrame.

    The expression is evaluated in a restricted namespace containing only
    ``polars.col`` and ``polars.lit``. The resulting expression is used to
    filter the DataFrame.

    Args:
        df: The Polars DataFrame to filter.
        expr_str: A Polars filter expression string (e.g. ``"col('x') >= 5"``).

    Returns:
        The filtered DataFrame.

    Raises:
        ValueError: If the expression is invalid or unsafe.
        RuntimeError: If expression evaluation fails at runtime.
    """
    expr = build_filter_expr(expr_str)

    try:
        return df.filter(expr)
    except Exception as e:
        raise RuntimeError(f"Failed to apply filter_expr '{expr_str}' to DataFrame: {e}") from e
