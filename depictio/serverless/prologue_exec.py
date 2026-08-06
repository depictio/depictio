"""Build-side execution of the code-mode prologue IR (RFC §7, phase 6).

Two halves, both used by the producers when they turn a code-mode figure into a
*live* component:

``execute_ops(ops, df)``
    Runs the IR with real Polars, so the producer can build the binding table
    against the frame the user's code actually handed to plotly-express — the
    same frame the browser re-derives at every filter state via
    ``packages/depictio-static-core/src/prologue.ts``. It mirrors the
    *source grammar* of :mod:`depictio.serverless.prologue` term for term
    (``maintain_order=True`` group_by *and* sort, Polars-default null
    placement, the ``len`` vs ``count`` split), and it is pinned against the
    cross-language
    fixture by ``depictio/tests/unit/serverless/test_prologue_exec.py``: the
    transpiler, this executor and the TypeScript interpreter all answer to the
    same arbiter (``fixtures/prologue-expected.json``).

``terminal_px_call(code)``
    Reads ``fig = px.<name>(<terminal frame>, **kwargs)`` off the AST and hands
    back ``(visu_type, dict_kwargs)`` — what
    :func:`depictio.serverless.binding.build_binding` needs to form its
    column hypothesis for a figure nobody declared kwargs for. The frame is not
    an argument the binder can see, so it is *validated* here instead: the call
    must consume the terminal prologue frame (the one whose ops were compiled),
    otherwise the binding would be built against a frame the ops never
    produced.

Same stance as the transpiler: **never guess.** A kwarg that is not a plain
literal, a call that is not ``px.<name>``, a frame that is not the terminal one
— all return ``None``, and the caller freezes the figure. Statements *after*
the ``fig =`` line (``fig.update_layout(...)`` & co.) are deliberately ignored:
the real code runs once at build time and bakes them into the scaffold.
"""

from __future__ import annotations

import ast
from typing import Any

import polars as pl

from depictio.models.models.serverless import (
    AggFn,
    AggSpec,
    AndPred,
    CmpOperator,
    CmpPred,
    FilterOp,
    GroupByOp,
    IsInPred,
    IsNotNullPred,
    IsNullPred,
    NotPred,
    OrPred,
    Pred,
    PrologueOp,
    RenameOp,
    SortOp,
    UnpivotOp,
)
from depictio.serverless.prologue import _Reject, _split

__all__ = ["execute_ops", "terminal_px_call"]


# ---------------------------------------------------------------------------
# IR execution (Polars is the semantics)
# ---------------------------------------------------------------------------

#: ``AggFn`` -> the Polars expression method it stands for. ``len`` is the group
#: SIZE (every row, nulls included) while ``count`` is the non-null count of the
#: source column — the distinction the IR exists to preserve.
_AGG_EXPR = {
    AggFn.SUM: lambda e: e.sum(),
    AggFn.MEAN: lambda e: e.mean(),
    AggFn.MEDIAN: lambda e: e.median(),
    AggFn.MIN: lambda e: e.min(),
    AggFn.MAX: lambda e: e.max(),
    AggFn.COUNT: lambda e: e.count(),
    AggFn.LEN: lambda e: e.len(),
    AggFn.NUNIQUE: lambda e: e.n_unique(),
    AggFn.STD: lambda e: e.std(),
    AggFn.VAR: lambda e: e.var(),
    AggFn.FIRST: lambda e: e.first(),
    AggFn.LAST: lambda e: e.last(),
}

_CMP_EXPR = {
    CmpOperator.LT: lambda col, value: col < value,
    CmpOperator.LE: lambda col, value: col <= value,
    CmpOperator.GT: lambda col, value: col > value,
    CmpOperator.GE: lambda col, value: col >= value,
    CmpOperator.EQ: lambda col, value: col == value,
    CmpOperator.NE: lambda col, value: col != value,
}


def _pred_expr(pred: Pred) -> pl.Expr:
    """One predicate node -> the Polars boolean expression it stands for.

    ``&``/``|``/``~`` are used (not Python's ``and``/``or``/``not``) so null
    propagation matches Polars exactly: a null comparison is not a match.
    """
    if isinstance(pred, AndPred):
        out = _pred_expr(pred.and_[0])
        for sub in pred.and_[1:]:
            out = out & _pred_expr(sub)
        return out
    if isinstance(pred, OrPred):
        out = _pred_expr(pred.or_[0])
        for sub in pred.or_[1:]:
            out = out | _pred_expr(sub)
        return out
    if isinstance(pred, NotPred):
        return ~_pred_expr(pred.not_)
    if isinstance(pred, IsNullPred):
        return pl.col(pred.is_null.col).is_null()
    if isinstance(pred, IsNotNullPred):
        return pl.col(pred.is_not_null.col).is_not_null()
    if isinstance(pred, IsInPred):
        return pl.col(pred.is_in.col).is_in(pred.is_in.values)
    if isinstance(pred, CmpPred):
        return _CMP_EXPR[pred.cmp.op](pl.col(pred.cmp.col), pred.cmp.value)
    raise TypeError(f"unknown predicate node {type(pred).__name__}")


def _agg_expr(spec: AggSpec) -> pl.Expr:
    """One ``AggSpec`` -> its aliased Polars expression.

    ``col`` is null only for a bare ``len`` (``pl.len()`` / ``pl.count()``),
    which reads no column at all; ``pl.col(c).len()`` keeps ``c`` — the group
    size again, but named after ``c`` and still raising when ``c`` is missing.
    """
    if spec.fn is AggFn.LEN and spec.col is None:
        return pl.len().alias(spec.alias)
    assert spec.col is not None  # guaranteed by AggSpec's validator
    return _AGG_EXPR[spec.fn](pl.col(spec.col)).alias(spec.alias)


def execute_ops(ops: list[PrologueOp], df: pl.DataFrame) -> pl.DataFrame:
    """Run a prologue IR program over ``df``, returning the derived frame.

    Raises whatever Polars raises (missing column, incompatible dtype) — the
    producers treat any failure as "this figure does not bind" and freeze it.
    """
    for op in ops:
        if isinstance(op, FilterOp):
            df = df.filter(_pred_expr(op.pred))
        elif isinstance(op, UnpivotOp):
            df = df.unpivot(
                on=op.on,
                index=op.index,
                variable_name=op.variable,
                value_name=op.value,
            )
        elif isinstance(op, GroupByOp):
            df = df.group_by(op.by, maintain_order=True).agg([_agg_expr(spec) for spec in op.agg])
        elif isinstance(op, SortOp):
            # maintain_order=True is NOT the Polars default: without it ties come
            # out in whatever order the parallel sort produced, so replaying the
            # same IR over the same frame twice can give two different row
            # orders. The IR is replayed on both sides of the bundle (here at
            # build time, prologue.ts at every filter state), and the TypeScript
            # interpreter's sort is stable, so "stable" is the pinned semantics.
            df = df.sort(op.by, descending=op.desc, maintain_order=True)
        elif isinstance(op, RenameOp):
            df = df.rename(op.map)
        else:
            raise TypeError(f"unknown prologue op {type(op).__name__}")
    return df


# ---------------------------------------------------------------------------
# the terminal ``fig = px.<name>(...)`` call
# ---------------------------------------------------------------------------

#: Frame conversions accepted between the terminal prologue frame and the ``px``
#: call. ``to_pandas()`` changes neither the rows nor the column names (the
#: transpiler already treats it as identity), so the binding built on the Polars
#: frame describes the pandas one too. Nothing else is accepted: ``to_dicts()``
#: & co. would hand px a shape whose column semantics we would be guessing at.
_FRAME_CONVERSIONS = frozenset({"to_pandas"})


class _NotLiteral(Exception):
    """A kwarg value that is not a plain literal — the call is not analyzable."""


def _literal(node: ast.expr) -> Any:
    """A JSON-ish literal (scalars, lists, string-keyed dicts), or reject."""
    if isinstance(node, ast.Constant):
        if node.value is None or isinstance(node.value, (str, bool, int, float)):
            return node.value
        raise _NotLiteral(f"unsupported constant {node.value!r}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _literal(node.operand)
        if isinstance(inner, bool) or not isinstance(inner, (int, float)):
            raise _NotLiteral("unary sign on a non-numeric literal")
        return -inner if isinstance(node.op, ast.USub) else inner
    if isinstance(node, ast.List):
        return [_literal(el) for el in node.elts]
    if isinstance(node, ast.Dict):
        out: dict[str, Any] = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                raise _NotLiteral("** unpacking inside a dict literal")
            name = _literal(key)
            if not isinstance(name, str):
                raise _NotLiteral("dict literal with a non-string key")
            out[name] = _literal(value)
        return out
    raise _NotLiteral("expected a literal")


def _consumed_frame(node: ast.expr) -> str | None:
    """The frame variable a ``px`` data argument reads, or ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _FRAME_CONVERSIONS
        and not node.args
        and not node.keywords
        and isinstance(node.func.value, ast.Name)
    ):
        return node.func.value.id
    return None


def _fig_call(code: str) -> ast.Call | None:
    """The ``px.…`` call assigned to ``fig``, as a bare ``ast.Call``."""
    module = ast.parse(code)
    for stmt in module.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "fig" for t in stmt.targets
        ):
            return stmt.value if isinstance(stmt.value, ast.Call) else None
    return None


def terminal_px_call(code: str) -> tuple[str, dict[str, Any]] | None:
    """``(visu_type, dict_kwargs)`` of the figure's ``px`` call, or ``None``.

    Accepted shape — and nothing else::

        fig = px.<name>(<terminal frame>[.to_pandas()], **literal_kwargs)

    where ``<terminal frame>`` is the frame the prologue ends on (``df`` when
    there is no prologue). ``None`` means "not analyzable": an unknown callable,
    a data argument that is not the terminal frame, extra positional arguments,
    ``*``/``**`` unpacking, or any kwarg value that is not a literal. The caller
    then freezes the figure rather than binding it against guessed kwargs.
    """
    if not code or not code.strip():
        return None
    try:
        _, terminal = _split(code)
        call = _fig_call(code)
    except (_Reject, SyntaxError, ValueError):
        return None
    if terminal is None or call is None:
        return None

    # ``px.<name>`` and nothing else — not ``go.Figure``, not a helper of ours.
    func = call.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    if func.value.id != "px" or not func.attr:
        return None

    args = list(call.args)
    if any(isinstance(arg, ast.Starred) for arg in args):
        return None

    kwargs: dict[str, Any] = {}
    frame_node: ast.expr | None = args.pop(0) if args else None
    if args:
        return None  # px's second positional is already a kwarg in our grammar
    try:
        for kw in call.keywords:
            if kw.arg is None:
                return None  # ** unpacking
            if kw.arg == "data_frame":
                if frame_node is not None:
                    return None  # frame given twice
                frame_node = kw.value
                continue
            kwargs[kw.arg] = _literal(kw.value)
    except _NotLiteral:
        return None

    if frame_node is None or _consumed_frame(frame_node) != terminal:
        return None
    return func.attr, kwargs
