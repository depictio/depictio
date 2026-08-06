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

Scope and limits: this module answers "may this run?", never "has this
run too long?". An allowlist cannot price a query — a `join` or a
`unique` is spelled the same whether it touches four rows or forty
million. Enforcing a deadline means being able to kill the work, which
means a process, which lives in `sandbox.py`. Call `execute_polars`
directly only for trusted, small inputs (tests, fixtures); model-authored
code against real data goes through `AnalysisSandbox`.
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
#
# This is NOT the same allowlist as the one in
# `depictio/models/components/filter_expr.py`. That one guards a grammar
# whose output is *persisted* on dashboard documents and re-evaluated on
# every render, so widening it is a long-lived commitment. This one guards
# transient analysis code that is executed once and thrown away. The
# asymmetry is deliberate: this list can afford to be much larger. Do not
# copy entries between the two on the assumption that they are peers.

# Methods called on a DataFrame.
ALLOWED_DF_METHODS: frozenset[str] = frozenset(
    {
        "agg",
        "bottom_k",
        "cast",
        "columns",
        "corr",
        "describe",
        "drop",
        "drop_nulls",
        "explode",
        "fill_nan",
        "fill_null",
        "filter",
        "group_by",
        "head",
        "height",
        "join",
        "limit",
        "max",
        "mean",
        "median",
        "min",
        "n_unique",
        "null_count",
        "pivot",
        "quantile",
        "rename",
        "sample",
        "schema",
        "select",
        "shape",
        "slice",
        "sort",
        "std",
        "sum",
        "tail",
        "to_dicts",
        "top_k",
        "unique",
        "unpivot",
        "value_counts",
        "var",
        "width",
        "with_columns",
        "with_row_index",
    }
)

# Methods called on an expression, i.e. anything hanging off pl.col(...).
# Kept separate from the frame methods so that widening `pl.<helper>()`
# no longer silently widens what may be called on a DataFrame: `pl.when`
# and the type casts are reachable only through `pl` now.
ALLOWED_EXPR_METHODS: frozenset[str] = frozenset(
    {
        "abs",
        "alias",
        "bottom_k",
        "cast",
        "ceil",
        "clip",
        "count",
        "cum_count",
        "cum_sum",
        "diff",
        "drop_nulls",
        "exp",
        "explode",
        "fill_nan",
        "fill_null",
        "first",
        "floor",
        "head",
        "is_between",
        "is_in",
        "is_nan",
        "is_not_nan",
        "is_not_null",
        "is_null",
        "last",
        "len",
        "log",
        "max",
        "mean",
        "median",
        "min",
        "mode",
        "n_unique",
        "otherwise",
        "over",
        "pct_change",
        "quantile",
        "rank",
        "round",
        "shift",
        "sort",
        "sort_by",
        "sqrt",
        "std",
        "sum",
        "tail",
        "then",
        "top_k",
        "unique",
        "value_counts",
        "var",
    }
)

# Top-level pl.* helpers.
ALLOWED_PL_FUNCS: frozenset[str] = frozenset(
    {
        "all",
        "any",
        "col",
        "concat_str",
        "corr",
        "count",
        "first",
        "format",
        "last",
        "len",
        "lit",
        "max",
        "mean",
        "median",
        "min",
        "n_unique",
        "std",
        "struct",
        "sum",
        "var",
        "when",
        # type casts
        "Boolean",
        "Date",
        "Datetime",
        "Float32",
        "Float64",
        "Int32",
        "Int64",
        "String",
        "Utf8",
    }
)

# Expression namespaces (`pl.col('x').str.contains(...)`). These need their
# own dispatch: the accessor node itself is harmless, but the terminal
# method name is what gets validated, and `contains` means something
# different under `.str` than under `.list`.
ALLOWED_NS_METHODS: dict[str, frozenset[str]] = {
    "str": frozenset(
        {
            "contains",
            "count_matches",
            "ends_with",
            "extract",
            "head",
            "len_bytes",
            "len_chars",
            "replace",
            "replace_all",
            "slice",
            "split",
            "starts_with",
            "strip_chars",
            "strip_prefix",
            "strip_suffix",
            "tail",
            "to_date",
            "to_datetime",
            "to_lowercase",
            "to_uppercase",
            "zfill",
        }
    ),
    "dt": frozenset(
        {
            "date",
            "day",
            "epoch",
            "hour",
            "minute",
            "month",
            "ordinal_day",
            "round",
            "second",
            "strftime",
            "time",
            "truncate",
            "weekday",
            "year",
        }
    ),
    "list": frozenset(
        {
            "contains",
            "first",
            "get",
            "head",
            "join",
            "last",
            "len",
            "max",
            "mean",
            "min",
            "sort",
            "sum",
            "tail",
            "unique",
        }
    ),
    "name": frozenset({"keep", "prefix", "suffix", "to_lowercase", "to_uppercase"}),
}

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

# `dc` is the mapping of data-collection tag -> DataFrame; `df` is an
# alias for the default collection, kept so single-DC code keeps working.
# `True`/`False`/`None` are deliberately absent: they parse as ast.Constant,
# never ast.Name, so listing them here would be dead weight.
ALLOWED_NAMES: frozenset[str] = frozenset({"df", "pl", "dc"})


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
                raise ValidationError(reason=f"unknown name '{child.id}'", node_lineno=child.lineno)

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
        # Every method name along a chain gets its own _validate_call as
        # ast.walk visits the nested Call nodes, so checking THIS link's
        # name is sufficient here. Three dispatches, in order of
        # specificity: direct pl.<helper>(), a namespaced accessor, then
        # the general frame/expression sets.
        parent = func.value
        if isinstance(parent, ast.Name) and parent.id == "pl":
            if func.attr not in ALLOWED_PL_FUNCS:
                raise ValidationError(
                    reason=f"disallowed pl helper '{func.attr}'",
                    node_lineno=call.lineno,
                )
        elif isinstance(parent, ast.Attribute) and parent.attr in ALLOWED_NS_METHODS:
            if func.attr not in ALLOWED_NS_METHODS[parent.attr]:
                raise ValidationError(
                    reason=f"disallowed .{parent.attr} method '{func.attr}'",
                    node_lineno=call.lineno,
                )
        elif func.attr not in ALLOWED_DF_METHODS and func.attr not in ALLOWED_EXPR_METHODS:
            raise ValidationError(
                reason=f"disallowed method '{func.attr}'",
                node_lineno=call.lineno,
            )

        # Walk to the root of the chain, descending through attribute
        # access, call results (df.group_by(...).agg(...)) and subscripts
        # (df['col'].max()). The chain must originate at `df` or `pl` —
        # the Name allowlist already rejects anything else, but keep the
        # explicit check so the error names the offending root.
        node: ast.expr = func.value
        while True:
            if isinstance(node, ast.Attribute):
                node = node.value
            elif isinstance(node, ast.Call):
                node = node.func
            elif isinstance(node, ast.Subscript):
                node = node.value
            else:
                break
        if not isinstance(node, ast.Name):
            raise ValidationError(
                reason="call chain does not root at df/dc/pl",
                node_lineno=call.lineno,
            )
        if node.id not in ALLOWED_NAMES:
            raise ValidationError(
                reason=f"call on unknown root '{node.id}'",
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


class _Scope(dict):
    """`dc` mapping that explains itself when the model guesses a tag."""

    def __missing__(self, key: object) -> None:
        available = ", ".join(sorted(str(k) for k in self)) or "(none)"
        raise KeyError(f"unknown data collection '{key}'; available: {available}")


def execute_polars(
    code: str,
    df: pl.DataFrame,
    *,
    scope: dict[str, pl.DataFrame] | None = None,
) -> ExecutionStep:
    """Run a single Polars expression against `df` and return an ExecutionStep.

    `code` may be a single expression or a tiny script ending in an
    expression statement; we evaluate the last expression and treat its
    repr as the step output.

    There is no timeout here on purpose. This function used to take a
    `timeout_s` and compare against it *after* the work had finished,
    which interrupted nothing and, worse, discarded the result the caller
    had just paid for. Enforcing a deadline requires being able to kill
    the work, which needs a process: see `sandbox.AnalysisSandbox`.
    """
    code = textwrap.dedent(code).strip()
    rows_in = df.height
    if not code:
        return ExecutionStep(code=code, status="warning", output="empty code", rows_in=rows_in)

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return ExecutionStep(code=code, status="error", output=f"SyntaxError: {e}", rows_in=rows_in)

    try:
        _validate(tree)
    except ValidationError as e:
        return ExecutionStep(
            code=code, status="error", output=f"BlockedByPolicy: {e}", rows_in=rows_in
        )

    # If the last statement is an expression, evaluate it for the result.
    last = tree.body[-1] if tree.body else None
    result_value: Any = None
    safe_globals: dict[str, Any] = {"__builtins__": {}, "pl": pl}
    safe_locals: dict[str, Any] = {"df": df, "dc": _Scope(scope or {})}

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
        return ExecutionStep(
            code=code,
            status="success",
            output=render_output(result_value),
            rows_in=rows_in,
            rows_out=result_value.height if isinstance(result_value, pl.DataFrame) else None,
            seconds=round(time.perf_counter() - t0, 3),
        )
    except Exception as e:  # noqa: BLE001 — we want to surface anything as a step
        return ExecutionStep(
            code=code,
            status="error",
            output=f"{type(e).__name__}: {e}",
            rows_in=rows_in,
            seconds=round(time.perf_counter() - t0, 3),
        )


MAX_OUTPUT_ROWS = 200


def render_output(value: Any) -> str:
    """Render a result for the model, capped by rows first and chars second.

    The char cap alone is not enough: `df.to_dicts()` on a tall frame
    materialises every row before anything gets truncated, so the memory
    is already spent by the time the string is trimmed. Cap the rows
    while the value is still structured, and say so, since a silently
    shortened result reads to the model as the whole answer.
    """
    if isinstance(value, pl.DataFrame) and value.height > MAX_OUTPUT_ROWS:
        head = value.head(MAX_OUTPUT_ROWS)
        note = f"\n… [{value.height - MAX_OUTPUT_ROWS} of {value.height} rows not shown]"
        return _truncate(repr(head)) + note
    if isinstance(value, list) and len(value) > MAX_OUTPUT_ROWS:
        note = f"\n… [{len(value) - MAX_OUTPUT_ROWS} of {len(value)} items not shown]"
        return _truncate(repr(value[:MAX_OUTPUT_ROWS])) + note
    return _truncate(repr(value))


def _truncate(s: str, limit: int = 4000) -> str:
    return s if len(s) <= limit else s[:limit] + f"… [{len(s) - limit} chars truncated]"


def grammar_block(tags: list[str] | None = None) -> str:
    """Render the allowlist as prompt text.

    Generated rather than hand-written: the recital in the analyze prompt
    had drifted from the allowlist in both directions, advertising methods
    that were rejected and omitting ones that were accepted. Deriving it
    here means the prompt cannot go stale, and a test can assert the two
    agree.
    """
    namespaces = "\n".join(
        f"  .{ns} -> {', '.join(sorted(methods))}"
        for ns, methods in sorted(ALLOWED_NS_METHODS.items())
    )
    if tags:
        listed = ", ".join(f'dc["{t}"]' for t in tags)
        sources = (
            f"Data sources: {listed}. `df` is an alias for the first.\n"
            "Pick the collection each step needs; join them with "
            "`dc['a'].join(dc['b'], on='key')` when a question spans two."
        )
    else:
        sources = "The DataFrame is named `df`."
    return f"""When you need to compute something, write a Polars expression.
{sources}
The sandbox is an AST allowlist; only these pass:
- Names: {", ".join(f"`{n}`" for n in sorted(ALLOWED_NAMES))}
- DataFrame methods: {", ".join(sorted(ALLOWED_DF_METHODS))}
- Expression methods (on pl.col(...)): {", ".join(sorted(ALLOWED_EXPR_METHODS))}
- pl helpers: {", ".join(sorted(ALLOWED_PL_FUNCS))}
- Expression namespaces:
{namespaces}

NO imports, NO file I/O, NO lambdas, NO assignments, NO comprehensions,
NO f-strings, NO bare function calls. Write one expression, not a script.
Results are capped at {MAX_OUTPUT_ROWS} rows — aggregate rather than dumping rows."""
