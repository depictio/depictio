"""Code-mode prologue transpiler (RFC §7, phase 6).

Turns the *data-preparation prefix* of a code-mode figure into the closed JSON
IR defined in :mod:`depictio.models.models.serverless` (``PrologueOp`` /
``Pred``), so the browser runtime can re-run the reshape on filtered data
without shipping a Python interpreter.

What this is not
----------------
It does **not** translate the ``px.*`` call or the ``fig.update_*`` chain. Under
bind-and-refill (RFC §4) the real Python runs once at build time to produce the
scaffold; only the prologue has to be replayable. So the grammar below covers
exactly the five reshape ops the IR has — filter / unpivot / group_by / sort /
rename — and nothing else.

Design stance: **never guess.**
------------------------------
A wrong IR silently renders wrong data; ``None`` merely freezes the figure with
reason ``code_mode``, which is a correct (if duller) render. Every construct
outside the allowlist — an unlisted method, a computed column
(``with_columns``), a lambda, subscripting, arithmetic between columns, an
unrecognised kwarg, a Python ``and``/``or`` where Polars needs ``&``/``|`` —
returns ``None``.

Deliberately rejected even though they *look* mappable:

``pandas`` reshaping (``.groupby``, ``.sort_values``, ``.agg``)
    ``DataFrame.groupby`` defaults to ``dropna=True`` (drops null-key groups)
    and ``sort=True`` (sorts by key), while the IR's ``group_by`` pins
    ``maintain_order=True`` and keeps null keys. ``sort_values`` defaults to
    ``na_position="last"`` while Polars' ``sort`` puts nulls first ascending.
    Same-looking calls, different rows/order — so they freeze.
    ``.to_pandas()`` / ``.to_dicts()`` themselves are pure format conversions
    and are treated as identity.

bare ``pl.count()`` / ``pl.len()`` / ``pl.col(c).len()``
    These are *group size*; the IR's ``count`` is the NON-NULL count of a named
    column (pinned repo-wide by ``_agg_value``). The two differ exactly when the
    counted column has nulls, and group size has no column to attach to, so the
    IR cannot express it. ``pl.col(c).count()`` **is** the non-null count and is
    accepted.

Splitting
---------
``services.figure.code_mode.analyze_constrained_code`` is a line/paren splitter
returning raw source; it is used here only to *validate* that the code has the
constrained ``fig = px.…`` shape. The prefix/suffix split itself is done on the
``ast`` (first statement assigning ``fig``), because the line splitter drops
plain ``df = df.filter(...)`` reassignments entirely (it only tracks names
starting with ``df_``).

Public API
----------
``transpile(code) -> list[PrologueOp] | None``
``classify(code) -> "free" | "prologue" | "frozen"``
"""

from __future__ import annotations

import ast
from typing import Any, Literal

from depictio.api.v1.services.figure.code_mode import analyze_constrained_code
from depictio.models.models.serverless import (
    AggFn,
    AggSpec,
    AndPred,
    CmpArgs,
    CmpOperator,
    CmpPred,
    ColRef,
    FilterOp,
    GroupByOp,
    IsInArgs,
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

__all__ = ["Classification", "classify", "transpile"]

Classification = Literal["free", "prologue", "frozen"]

#: The frame the component's data collection is bound to.
_ROOT = "df"

#: Format conversions that change no rows and no column names — dropped.
_IDENTITY_METHODS = frozenset({"to_pandas", "to_dicts", "lazy", "collect"})

#: ``pl.col("x").<name>()`` reducers -> IR ``fn``. ``len`` is *not* here: see the
#: module docstring (group size != non-null count).
_AGG_METHODS: dict[str, AggFn] = {
    "sum": AggFn.SUM,
    "mean": AggFn.MEAN,
    "median": AggFn.MEDIAN,
    "min": AggFn.MIN,
    "max": AggFn.MAX,
    "count": AggFn.COUNT,
    "n_unique": AggFn.NUNIQUE,
    "std": AggFn.STD,
    "var": AggFn.VAR,
    "first": AggFn.FIRST,
    "last": AggFn.LAST,
}

#: ``pl.<name>("x")`` shorthands for the same reducers.
_AGG_SHORTHANDS = dict(_AGG_METHODS)

_CMP_OPS: dict[type[ast.cmpop], CmpOperator] = {
    ast.Lt: CmpOperator.LT,
    ast.LtE: CmpOperator.LE,
    ast.Gt: CmpOperator.GT,
    ast.GtE: CmpOperator.GE,
    ast.Eq: CmpOperator.EQ,
    ast.NotEq: CmpOperator.NE,
}

#: Mirror image of ``_CMP_OPS`` for ``literal < pl.col("x")``.
_FLIPPED: dict[CmpOperator, CmpOperator] = {
    CmpOperator.LT: CmpOperator.GT,
    CmpOperator.GT: CmpOperator.LT,
    CmpOperator.LE: CmpOperator.GE,
    CmpOperator.GE: CmpOperator.LE,
    CmpOperator.EQ: CmpOperator.EQ,
    CmpOperator.NE: CmpOperator.NE,
}


class _Reject(Exception):
    """Raised anywhere in the walk; the whole prologue then freezes.

    The message is a short human reason, surfaced by
    ``depictio/serverless/scripts/measure_prologue.py``.
    """


# ---------------------------------------------------------------------------
# small ast helpers
# ---------------------------------------------------------------------------


def _reject(node: ast.AST, why: str) -> _Reject:
    return _Reject(f"{why} (line {getattr(node, 'lineno', '?')})")


def _is_pl(node: ast.AST) -> bool:
    """``pl`` — the only module name the grammar knows."""
    return isinstance(node, ast.Name) and node.id == "pl"


def _literal(node: ast.expr) -> Any:
    """A JSON scalar literal (``-1`` included), or reject."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _literal(node.operand)
        if not isinstance(inner, (int, float)) or isinstance(inner, bool):
            raise _reject(node, "unary sign on a non-numeric literal")
        return -inner if isinstance(node.op, ast.USub) else inner
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bool, int, float)):
        return node.value
    raise _reject(node, "expected a scalar literal")


def _string(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise _reject(node, "expected a string literal")


def _string_list(node: ast.expr) -> list[str]:
    """``"a"`` -> ``["a"]``; ``["a", "b"]`` / ``("a", "b")`` -> ``["a", "b"]``."""
    if isinstance(node, ast.Constant):
        return [_string(node)]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_string(el) for el in node.elts]
    raise _reject(node, "expected a string or list of strings")


def _bool_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    raise _reject(node, "expected a bool literal")


def _bool_list(node: ast.expr, width: int) -> list[bool]:
    """A scalar bool broadcasts across ``width`` keys; a list must match exactly."""
    if isinstance(node, (ast.List, ast.Tuple)):
        flags = [_bool_literal(el) for el in node.elts]
        if len(flags) != width:
            raise _reject(node, "descending list length does not match the sort keys")
        return flags
    return [_bool_literal(node)] * width


def _kwargs(call: ast.Call, allowed: set[str]) -> dict[str, ast.expr]:
    """Keyword arguments, rejecting ``**kwargs`` and anything unlisted."""
    out: dict[str, ast.expr] = {}
    for kw in call.keywords:
        if kw.arg is None:
            raise _reject(call, "** unpacking is not allowed")
        if kw.arg not in allowed:
            raise _reject(call, f"unsupported keyword '{kw.arg}'")
        out[kw.arg] = kw.value
    return out


def _col_of(node: ast.expr) -> str:
    """``pl.col("x")`` -> ``"x"``."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "col"
        and _is_pl(node.func.value)
        and not node.keywords
        and len(node.args) == 1
    ):
        return _string(node.args[0])
    raise _reject(node, "expected pl.col('name')")


# ---------------------------------------------------------------------------
# predicates
# ---------------------------------------------------------------------------


def _flatten(node: Pred, kind: type[AndPred] | type[OrPred]) -> list[Pred]:
    """``(a & b) & c`` -> ``[a, b, c]``: associativity makes the nesting noise."""
    if isinstance(node, kind):
        inner = node.and_ if isinstance(node, AndPred) else node.or_
        return list(inner)
    return [node]


def _predicate(node: ast.expr) -> Pred:
    """Compile one Polars boolean expression into a :data:`Pred` node."""
    if isinstance(node, ast.BoolOp):
        raise _reject(
            node,
            "Python 'and'/'or' on Polars expressions is a bug — use '&'/'|'",
        )

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
        return NotPred(not_=_predicate(node.operand))

    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitAnd, ast.BitOr)):
        left = _predicate(node.left)
        right = _predicate(node.right)
        if isinstance(node.op, ast.BitAnd):
            return AndPred(and_=_flatten(left, AndPred) + _flatten(right, AndPred))
        return OrPred(or_=_flatten(left, OrPred) + _flatten(right, OrPred))

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise _reject(node, "chained comparisons are not supported")
        op = _CMP_OPS.get(type(node.ops[0]))
        if op is None:
            raise _reject(node, "unsupported comparison operator")
        left, right = node.left, node.comparators[0]
        try:
            col = _col_of(left)
        except _Reject:
            # ``0.05 > pl.col("q_val")`` — same predicate, mirrored.
            col = _col_of(right)
            op = _FLIPPED[op]
            right = left
        value = _literal(right)
        return CmpPred(cmp=CmpArgs(col=col, op=op, value=value))

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        method = node.func.attr
        if method in ("is_null", "is_not_null"):
            if node.args or node.keywords:
                raise _reject(node, f"{method}() takes no arguments")
            ref = ColRef(col=_col_of(node.func.value))
            return (
                IsNullPred(is_null=ref) if method == "is_null" else IsNotNullPred(is_not_null=ref)
            )
        if method == "is_in":
            if len(node.args) != 1 or node.keywords:
                raise _reject(node, "is_in() takes exactly one literal collection")
            col = _col_of(node.func.value)
            seq = node.args[0]
            if not isinstance(seq, (ast.List, ast.Tuple, ast.Set)):
                raise _reject(seq, "is_in() needs a literal list/tuple/set")
            return IsInPred(is_in=IsInArgs(col=col, values=[_literal(el) for el in seq.elts]))
        raise _reject(node, f"unsupported predicate method '.{method}()'")

    raise _reject(node, "unsupported predicate expression")


# ---------------------------------------------------------------------------
# aggregations
# ---------------------------------------------------------------------------


def _agg_spec(node: ast.expr) -> AggSpec:
    """``pl.col("x").mean().alias("y")`` / ``pl.mean("x")`` -> one :class:`AggSpec`."""
    alias: str | None = None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "alias"
    ):
        if len(node.args) != 1 or node.keywords:
            raise _reject(node, "alias() takes exactly one string")
        alias = _string(node.args[0])
        node = node.func.value

    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        raise _reject(node, "expected an aggregation call")

    name = node.func.attr

    # ``pl.mean("x")`` shorthand.
    if _is_pl(node.func.value):
        if name in ("len",) or (name == "count" and not node.args):
            # ``pl.count()`` / ``pl.len()`` are the GROUP SIZE. The IR's `count`
            # is the non-null count of a named column, which differs on every
            # group whose column has nulls, and there is no column to name here.
            # Expressing this needs a new `fn` in the pinned allowlist.
            raise _reject(
                node,
                f"pl.{name}() is the group size, not a column's non-null count — "
                "not expressible in the IR",
            )
        fn = _AGG_SHORTHANDS.get(name)
        if fn is None:
            raise _reject(node, f"unsupported aggregation 'pl.{name}()'")
        if len(node.args) != 1 or node.keywords:
            raise _reject(node, f"pl.{name}() must take exactly one column name")
        col = _string(node.args[0])
        return AggSpec(col=col, fn=fn, alias=alias or col)

    # ``pl.col("x").mean()``.
    fn = _AGG_METHODS.get(name)
    if fn is None:
        if name == "len":
            raise _reject(
                node,
                "len() is the group size, not a non-null count — not expressible in the IR",
            )
        raise _reject(node, f"unsupported aggregation '.{name}()'")
    if node.args or node.keywords:
        raise _reject(node, f".{name}() must take no arguments")
    col = _col_of(node.func.value)
    return AggSpec(col=col, fn=fn, alias=alias or col)


# ---------------------------------------------------------------------------
# methods on the frame
# ---------------------------------------------------------------------------


def _filter_op(call: ast.Call) -> FilterOp:
    if call.keywords:
        # ``filter(col=value)`` constraint form: expressible, but the kwarg name
        # is not necessarily a column and the coercion rules differ — freeze.
        raise _reject(call, "filter() keyword constraints are not supported")
    if not call.args:
        raise _reject(call, "filter() needs at least one predicate")
    preds = [_predicate(arg) for arg in call.args]
    if len(preds) == 1:
        return FilterOp(pred=preds[0])
    flat: list[Pred] = []
    for p in preds:
        flat.extend(_flatten(p, AndPred))
    return FilterOp(pred=AndPred(and_=flat))


def _group_by_keys(call: ast.Call) -> list[str]:
    """Keys of ``group_by(...)``; ``maintain_order`` is accepted and ignored."""
    kw = _kwargs(call, {"by", "maintain_order"})
    if "maintain_order" in kw:
        _bool_literal(kw["maintain_order"])  # must be a literal, value is irrelevant
    keys: list[str] = []
    for arg in call.args:
        keys.extend(_string_list(arg))
    if "by" in kw:
        if keys:
            raise _reject(call, "group_by() got both positional and by= keys")
        keys = _string_list(kw["by"])
    if not keys:
        raise _reject(call, "group_by() needs at least one key column")
    return keys


def _agg_op(group_call: ast.Call, agg_call: ast.Call) -> GroupByOp:
    if agg_call.keywords:
        raise _reject(agg_call, "agg() keyword aggregations are not supported")
    if not agg_call.args:
        raise _reject(agg_call, "agg() needs at least one aggregation")
    specs: list[AggSpec] = []
    for arg in agg_call.args:
        if isinstance(arg, (ast.List, ast.Tuple)):
            specs.extend(_agg_spec(el) for el in arg.elts)
        else:
            specs.append(_agg_spec(arg))
    return GroupByOp(by=_group_by_keys(group_call), agg=specs)


def _sort_op(call: ast.Call) -> SortOp:
    kw = _kwargs(call, {"by", "descending"})
    keys: list[str] = []
    for arg in call.args:
        keys.extend(_string_list(arg))
    if "by" in kw:
        if keys:
            raise _reject(call, "sort() got both positional and by= keys")
        keys = _string_list(kw["by"])
    if not keys:
        raise _reject(call, "sort() needs at least one key column")
    desc = _bool_list(kw["descending"], len(keys)) if "descending" in kw else [False] * len(keys)
    return SortOp(by=keys, desc=desc)


def _rename_op(call: ast.Call) -> RenameOp:
    _kwargs(call, set())
    if len(call.args) != 1 or not isinstance(call.args[0], ast.Dict):
        raise _reject(call, "rename() needs exactly one dict literal")
    mapping_node = call.args[0]
    mapping: dict[str, str] = {}
    for key, value in zip(mapping_node.keys, mapping_node.values):
        if key is None:
            raise _reject(call, "rename() dict cannot use ** unpacking")
        mapping[_string(key)] = _string(value)
    if not mapping:
        raise _reject(call, "rename() with an empty mapping")
    return RenameOp(map=mapping)


def _unpivot_op(call: ast.Call) -> UnpivotOp:
    kw = _kwargs(call, {"on", "index", "variable_name", "value_name"})
    args = list(call.args)
    on_node = args.pop(0) if args else kw.get("on")
    index_node = args.pop(0) if args else kw.get("index")
    if args:
        raise _reject(call, "unpivot() got too many positional arguments")
    if on_node is None:
        raise _reject(call, "unpivot() without on= melts every remaining column — unresolvable")
    return UnpivotOp(
        on=_string_list(on_node),
        index=_string_list(index_node) if index_node is not None else [],
        variable=_string(kw["variable_name"]) if "variable_name" in kw else "variable",
        value=_string(kw["value_name"]) if "value_name" in kw else "value",
    )


def _melt_op(call: ast.Call) -> UnpivotOp:
    """Legacy spelling of :func:`_unpivot_op` (``id_vars`` / ``value_vars``)."""
    kw = _kwargs(call, {"id_vars", "value_vars", "variable_name", "value_name"})
    args = list(call.args)
    index_node = args.pop(0) if args else kw.get("id_vars")
    on_node = args.pop(0) if args else kw.get("value_vars")
    if args:
        raise _reject(call, "melt() got too many positional arguments")
    if on_node is None:
        raise _reject(call, "melt() without value_vars melts every remaining column")
    return UnpivotOp(
        on=_string_list(on_node),
        index=_string_list(index_node) if index_node is not None else [],
        variable=_string(kw["variable_name"]) if "variable_name" in kw else "variable",
        value=_string(kw["value_name"]) if "value_name" in kw else "value",
    )


# ---------------------------------------------------------------------------
# chain walking
# ---------------------------------------------------------------------------


def _chain(node: ast.expr, env: dict[str, list[PrologueOp]]) -> list[PrologueOp]:
    """Compile a method chain rooted at a known frame variable into ops.

    ``env`` maps already-assigned prologue variables to the ops that produce
    them, so ``df_b = df_a.sort("x")`` accumulates onto ``df_a``'s ops.
    """
    if isinstance(node, ast.Name):
        if node.id in env:
            return list(env[node.id])
        raise _reject(node, f"unknown frame variable '{node.id}'")

    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        raise _reject(node, "expected a method call on the dataframe")

    method = node.func.attr
    receiver = node.func.value

    # ``group_by(...).agg(...)`` is one op, so the receiver of ``.agg`` is the
    # group_by call and must be skipped over.
    if method == "agg":
        if (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Attribute)
            and receiver.func.attr in ("group_by", "groupby")
        ):
            if receiver.func.attr == "groupby":
                raise _reject(receiver, "pandas .groupby() differs on null keys and ordering")
            base = _chain(receiver.func.value, env)
            return base + [_agg_op(receiver, node)]
        raise _reject(node, ".agg() outside of a group_by() is not supported")

    base = _chain(receiver, env)

    if method in _IDENTITY_METHODS:
        if node.args or node.keywords:
            raise _reject(node, f".{method}() must take no arguments")
        return base
    if method == "filter":
        return base + [_filter_op(node)]
    if method == "sort":
        return base + [_sort_op(node)]
    if method == "rename":
        return base + [_rename_op(node)]
    if method == "unpivot":
        return base + [_unpivot_op(node)]
    if method == "melt":
        return base + [_melt_op(node)]
    if method in ("group_by", "groupby"):
        raise _reject(node, f".{method}() must be immediately followed by .agg(...)")
    raise _reject(node, f"unsupported method '.{method}()'")


def _split(code: str) -> tuple[list[ast.Assign], str | None]:
    """``(prologue statements, name of the frame the fig line consumes)``.

    Everything before the first ``fig = …`` is the prologue; the suffix is the
    caller's problem (bind-and-refill already handles it).
    """
    try:
        module = ast.parse(code)
    except SyntaxError as exc:
        raise _Reject(f"syntax error: {exc.msg}") from exc

    fig_index: int | None = None
    for i, stmt in enumerate(module.body):
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "fig" for t in stmt.targets
        ):
            fig_index = i
            break
    if fig_index is None:
        raise _Reject("no 'fig = ...' assignment")

    prologue: list[ast.Assign] = []
    for stmt in module.body[:fig_index]:
        if isinstance(stmt, ast.Import) or isinstance(stmt, ast.ImportFrom):
            continue
        if not isinstance(stmt, ast.Assign):
            raise _reject(stmt, "prologue statements must be simple assignments")
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            raise _reject(stmt, "prologue assignment must bind exactly one plain name")
        prologue.append(stmt)

    # Which frame does the fig call actually consume? It must be the last one the
    # prologue produced, otherwise ops we compiled are not the ops that fed the
    # scaffold.
    fig_stmt = module.body[fig_index]
    used = {n.id for n in ast.walk(fig_stmt) if isinstance(n, ast.Name)}
    return prologue, _terminal(prologue, used)


def _terminal(prologue: list[ast.Assign], used_in_fig: set[str]) -> str | None:
    """Name of the frame the figure consumes, validated against the prologue."""
    if not prologue:
        return _ROOT if _ROOT in used_in_fig else None
    target = prologue[-1].targets[0]
    assert isinstance(target, ast.Name)
    last = target.id
    if last not in used_in_fig:
        raise _Reject(f"fig line does not use the final prologue frame '{last}'")
    # An earlier intermediate showing up too means the figure mixes frames.
    others = {
        t.id
        for stmt in prologue[:-1]
        for t in stmt.targets
        if isinstance(t, ast.Name) and t.id != last
    }
    if others & used_in_fig:
        raise _Reject("fig line mixes several prologue frames")
    return last


def _transpile_or_raise(code: str) -> list[PrologueOp]:
    prologue, terminal = _split(code)
    if not prologue:
        return []
    env: dict[str, list[PrologueOp]] = {_ROOT: []}
    for stmt in prologue:
        target = stmt.targets[0]
        assert isinstance(target, ast.Name)
        env[target.id] = _chain(stmt.value, env)
    assert terminal is not None
    return env[terminal]


def transpile(code: str) -> list[PrologueOp] | None:
    """Compile a code-mode figure's data prologue to IR.

    Returns the (possibly empty) op list when **every** prep statement is
    recognised, and ``None`` otherwise — the caller then freezes the component
    with reason ``code_mode``.
    """
    return transpile_with_reason(code)[0]


def transpile_with_reason(code: str) -> tuple[list[PrologueOp] | None, str | None]:
    """Like :func:`transpile`, plus a one-line reason when it refuses."""
    if not code or not code.strip():
        return None, "empty code"
    analysis = analyze_constrained_code(code)
    if not analysis.get("is_valid"):
        return None, str(analysis.get("error_message") or "not constrained-code shaped")
    try:
        return _transpile_or_raise(code), None
    except _Reject as exc:
        return None, str(exc)
    except RecursionError:
        return None, "expression nested too deeply"


def classify(code: str) -> Classification:
    """``free`` (no reshape), ``prologue`` (fully transpiled) or ``frozen``."""
    ops, _ = transpile_with_reason(code)
    if ops is None:
        return "frozen"
    return "free" if not ops else "prologue"
