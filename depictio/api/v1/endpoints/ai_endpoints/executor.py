"""AST-allowlisted Polars executor.

Replaces the LangChain pandas REPL from `dev/litellm-prototype`. The LLM is
prompted to write a single expression operating on a `df: pl.DataFrame`
already in scope, and we only let through:

* Names: `df`, `pl`, plus literal numbers/strings
* Attribute access on `df` and `pl`, but NOT walking up to dunders
* Calls to a curated set of Polars / DataFrame methods
* Comparisons, boolean ops, arithmetic, subscript

Nothing else passes — no `import`, no lambdas, no `__getattribute__`, no
file I/O, no walrus, no comprehensions. Failures are surfaced as
`ExecutionStep(status='error')` rather than raised so the trace is always
renderable end-to-end.

This is v1: trusted users + per-request resource limits live above this
function. Move to a subprocess sandbox if/when we go multi-tenant.
"""

from __future__ import annotations

import ast
import logging
import textwrap
import time
from dataclasses import dataclass
from typing import Any

import polars as pl

from depictio.api.v1.endpoints.ai_endpoints.schemas import ExecutionStep

logger = logging.getLogger(__name__)


# ---------- Allowlist ----------

ALLOWED_DF_METHODS: frozenset[str] = frozenset(
    {
        "filter",
        "select",
        "with_columns",
        "group_by",
        "agg",
        "sort",
        "head",
        "tail",
        "limit",
        "drop_nulls",
        "unique",
        "join",
        "describe",
        "schema",
        "columns",
        "shape",
        "height",
        "width",
        "to_dicts",
        "to_pandas",
        "rename",
        "n_unique",
        "null_count",
        "min",
        "max",
        "mean",
        "median",
        "sum",
        "std",
        "var",
        "count",
        "value_counts",
        "is_in",
        "alias",
        "cast",
    }
)

# Top-level pl.* helpers.
ALLOWED_PL_FUNCS: frozenset[str] = frozenset(
    {
        "col",
        "lit",
        "sum",
        "mean",
        "median",
        "min",
        "max",
        "count",
        "len",
        "all",
        "any",
        "when",
        "Int64",
        "Int32",
        "Float64",
        "Utf8",
        "String",
        "Boolean",
        "Date",
    }
)

ALLOWED_NODE_TYPES: tuple[type, ...] = (
    ast.Module,
    ast.Expression,
    ast.Expr,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.Call,
    ast.keyword,
    ast.Subscript,
    ast.Slice,
    ast.Tuple,
    ast.List,
    ast.Dict,
    ast.Set,
    ast.Compare,
    ast.BoolOp,
    ast.UnaryOp,
    ast.BinOp,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Invert,
    ast.Starred,
)

ALLOWED_NAMES: frozenset[str] = frozenset({"df", "pl", "True", "False", "None"})


# ---------- Validation ----------


@dataclass
class ValidationError(Exception):
    reason: str
    node_lineno: int = 0

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"line {self.node_lineno}: {self.reason}"


def _validate(node: ast.AST) -> None:
    """Walk the AST; raise ValidationError on first disallowed node."""
    for child in ast.walk(node):
        if not isinstance(child, ALLOWED_NODE_TYPES):
            raise ValidationError(
                reason=f"disallowed syntax: {type(child).__name__}",
                node_lineno=getattr(child, "lineno", 0),
            )

        # Names: only df, pl, True/False/None
        if isinstance(child, ast.Name):
            if child.id not in ALLOWED_NAMES:
                raise ValidationError(
                    reason=f"unknown name '{child.id}'", node_lineno=child.lineno
                )

        # Attribute: block dunder access at all depths
        if isinstance(child, ast.Attribute):
            if child.attr.startswith("_"):
                raise ValidationError(
                    reason=f"disallowed attribute '{child.attr}'",
                    node_lineno=child.lineno,
                )

        # Calls: gate the callable shape
        if isinstance(child, ast.Call):
            _validate_call(child)


def _validate_call(call: ast.Call) -> None:
    func = call.func
    # df.method(...) or chain ending in .method()
    if isinstance(func, ast.Attribute):
        # Walk to the root of the attribute chain to check origin
        root = func
        while isinstance(root.value, ast.Attribute):
            root = root.value
        if isinstance(root.value, ast.Name):
            origin = root.value.id
            if origin == "pl":
                # pl.<func>(...) — must be a known helper at the top
                # If the chain goes deeper (pl.col("x").mean()) the inner
                # call's func.attr will be checked below as a method.
                if not isinstance(func.value, ast.Name):
                    # e.g. pl.col("x").alias("y") — alias must be allowed
                    if func.attr not in ALLOWED_DF_METHODS and func.attr not in ALLOWED_PL_FUNCS:
                        raise ValidationError(
                            reason=f"disallowed method '{func.attr}' on pl chain",
                            node_lineno=call.lineno,
                        )
                else:
                    if func.attr not in ALLOWED_PL_FUNCS:
                        raise ValidationError(
                            reason=f"disallowed pl helper '{func.attr}'",
                            node_lineno=call.lineno,
                        )
            elif origin == "df":
                if func.attr not in ALLOWED_DF_METHODS:
                    raise ValidationError(
                        reason=f"disallowed DataFrame method '{func.attr}'",
                        node_lineno=call.lineno,
                    )
            else:
                raise ValidationError(
                    reason=f"call on unknown root '{origin}'",
                    node_lineno=call.lineno,
                )
        else:
            raise ValidationError(
                reason="call on non-name root",
                node_lineno=call.lineno,
            )
    elif isinstance(func, ast.Name):
        # Bare function call — none allowed (no len(), no print(), etc.)
        raise ValidationError(
            reason=f"bare function call '{func.id}' not allowed",
            node_lineno=call.lineno,
        )
    else:
        raise ValidationError(
            reason=f"unsupported callable: {type(func).__name__}",
            node_lineno=call.lineno,
        )


# ---------- Execution ----------


def execute_polars(code: str, df: pl.DataFrame, *, timeout_s: float = 5.0) -> ExecutionStep:
    """Run a single Polars expression against `df` and return an ExecutionStep.

    `code` may be a single expression or a tiny script ending in an
    expression statement; we evaluate the last expression and treat its
    repr as the step output.
    """
    code = textwrap.dedent(code).strip()
    if not code:
        return ExecutionStep(code=code, status="warning", output="empty code")

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return ExecutionStep(code=code, status="error", output=f"SyntaxError: {e}")

    try:
        _validate(tree)
    except ValidationError as e:
        return ExecutionStep(code=code, status="error", output=f"BlockedByPolicy: {e}")

    # If the last statement is an expression, evaluate it for the result.
    last = tree.body[-1] if tree.body else None
    result_value: Any = None
    safe_globals: dict[str, Any] = {"__builtins__": {}, "pl": pl}
    safe_locals: dict[str, Any] = {"df": df}

    t0 = time.perf_counter()
    try:
        if isinstance(last, ast.Expr):
            preceding = ast.Module(body=tree.body[:-1], type_ignores=[])
            if preceding.body:
                exec(compile(preceding, "<ai>", "exec"), safe_globals, safe_locals)
            result_value = eval(
                compile(ast.Expression(body=last.value), "<ai>", "eval"),
                safe_globals,
                safe_locals,
            )
        else:
            exec(compile(tree, "<ai>", "exec"), safe_globals, safe_locals)
        elapsed = time.perf_counter() - t0
        if elapsed > timeout_s:
            return ExecutionStep(
                code=code,
                status="warning",
                output=f"completed in {elapsed:.1f}s (over {timeout_s}s budget)",
            )
        return ExecutionStep(
            code=code,
            status="success",
            output=_truncate(repr(result_value)),
        )
    except Exception as e:  # noqa: BLE001 — we want to surface anything as a step
        return ExecutionStep(
            code=code,
            status="error",
            output=f"{type(e).__name__}: {e}",
        )


def _truncate(s: str, limit: int = 4000) -> str:
    return s if len(s) <= limit else s[:limit] + f"… [{len(s) - limit} chars truncated]"
