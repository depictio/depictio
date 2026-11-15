"""Companion columns + codebooks for serverless bundles (RFC §5 + errata #1).

This supersedes the earlier stub from the producer-B workstream; the public
contract (``CompanionResult`` / ``build_companions``) is identical.

The build pushes Polars' value-casting semantics to build time so the browser
never re-implements them (RFC ``docs/design/rfc-serverless-deployment.md``
§12 errata #1):

- **Categorical non-String columns** get a dense ``Int32`` ``__code__<col>``
  companion plus a ``{serialized_value: code}`` codebook. At runtime a
  MultiSelect filter is integer set-membership over the companion: each picked
  option string is looked up in the codebook (miss → matches nothing), so no
  string→dtype casting exists in JS at all. String columns get neither — the
  runtime compares them directly (``is_in`` over the raw column), exactly like
  the server's ``_categorical_predicate`` String branch.
- **Date/Datetime columns** get an ``Int64`` ``__ts__<col>`` epoch-microsecond
  companion derived from the *same* normalisation expression the server's
  DateRangePicker/Timeline branch uses
  (``depictio.models.components.predicates.datetime_column_expr`` — the
  Utf8-coalesce parse with timezone stripping), so an integer range compare in
  JS selects the same rows the server's datetime predicate does. Null
  preserving.

- **Component-static row-level ``filter_expr``** (a card's own row scoping, an
  interactive component's scope) gets a Boolean ``__fe__<sha8>`` companion,
  evaluated with the server's own ``build_filter_expr`` (RFC §5): the browser
  ANDs it into the mask instead of re-implementing the expression grammar. It
  does not depend on the filter state, so evaluating it over the whole frame
  and ANDing is the same as the server's filter-then-``filter(expr)``. A window
  expression (``.over(...)``) does depend on which rows the window spans, so it
  gets no companion (:func:`filter_expr_companionable`); a component carrying
  one is not served live.

Every companion kind is recorded in ``CompanionResult.companions``
(``companion column -> source``; the expression text for ``__fe__``) for the
manifest.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import polars as pl

from depictio.models.components.predicates import datetime_column_expr

FILTER_EXPR_PREFIX = "__fe__"
_FILTER_EXPR_COL_RE = re.compile(r"col\(\s*['\"]([^'\"]+)['\"]\s*\)")
_WINDOW_RE = re.compile(r"\.over\s*\(")


def filter_expr_companion(expr: str) -> str:
    """``__fe__<sha8>``: the companion column name of a filter_expr (RFC §5)."""
    return f"{FILTER_EXPR_PREFIX}{hashlib.sha1(expr.encode('utf-8')).hexdigest()[:8]}"


def filter_expr_companionable(expr: str | None) -> bool:
    """True for a row-level filter_expr (no ``.over()`` window)."""
    return bool(expr and expr.strip()) and not _WINDOW_RE.search(expr or "")


def filter_expr_targets(components: Iterable[dict]) -> list[str]:
    """Every distinct filter_expr the components carry, in first-seen order."""
    out: dict[str, None] = {}
    for comp in components:
        expr = comp.get("filter_expr") or (comp.get("metadata") or {}).get("filter_expr")
        if isinstance(expr, str) and expr.strip():
            out[expr] = None
    return list(out)


@dataclass
class CompanionResult:
    """The frame with companions appended, plus what was added and why."""

    df: pl.DataFrame
    codebooks: dict[str, dict[str, int]] = field(default_factory=dict)
    companions: dict[str, str] = field(default_factory=dict)


def serialize_option(value: object) -> str:
    """Serialize one categorical value the way the API serves MultiSelect options.

    Mirrors the server's option-list path, ``get_unique_values`` in
    ``depictio/api/v1/endpoints/deltatables_endpoints/routes.py`` (the
    ``values_str = sorted({str(v) for v in values})`` line): options are the
    plain ``str()`` rendering of the Python-native values Polars returns from
    ``to_list()``. That is also byte-identical to the value-side serialization
    inside ``_categorical_predicate`` (``str_values = [str(v) for v in
    values]`` in ``depictio/models/components/predicates.py``), and to what
    ``json.dumps(..., default=str)`` (``depictio/catalog/payload.py::_inject``)
    emits for non-JSON-native values (dates, datetimes, times). So for every
    dtype the server converts confidently — numerics, Date, Datetime, Time,
    String — codebook keys are byte-identical to the option strings the
    frontend receives.

    The single deliberate exception is ``bool``: the endpoint would render
    ``str(True) == "True"``, but the server predicate for Boolean columns is
    the Utf8-fallback ``col.cast(Utf8).is_in(...)`` and Polars renders booleans
    as ``"true"``/``"false"`` — so the option string ``"True"`` matches
    *nothing* on the live server. To keep the codebook path equivalent to the
    server predicate (the whole point of this layer), bools serialize to the
    Polars/JSON rendering ``"true"``/``"false"``: a client-sent ``"true"``
    matches on both paths, a client-sent ``"True"`` matches nothing on both.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def serialize_value(value: object) -> str | None:
    """Compatibility shim for the superseded stub's name. Prefer
    :func:`serialize_option`."""
    if value is None:
        return None
    return serialize_option(value)


def _is_stringlike(dtype: pl.DataType) -> bool:
    """String / Categorical-of-string dtypes need no codebook: the runtime does
    direct string membership, matching the server's String branch (bare
    ``is_in``) and Categorical fallback (``cast(Utf8)`` → the category string).
    """
    base = dtype.base_type()
    return dtype == pl.String or base == pl.Categorical or base == pl.Enum


def build_companions(
    df: pl.DataFrame,
    categorical_cols: list[str],
    datetime_cols: list[str],
    filter_exprs: Iterable[str] = (),
) -> CompanionResult:
    """Append companion columns for the given categorical/datetime columns.

    Args:
        df: The (already pruned) frame to extend.
        categorical_cols: Columns filtered by Select/MultiSelect/SegmentedControl
            components. Only non-String columns get a ``__code__`` companion +
            codebook; columns absent from ``df`` are skipped.
        datetime_cols: Columns filtered by DateRangePicker/Timeline components.
            Only Date/Datetime columns get a ``__ts__`` companion (Time and
            Duration have no epoch-µs meaning through the server's datetime
            branch; string-dated columns are the runtime's raw-parse concern).
        filter_exprs: Component-static filter_expr strings. Each row-level one
            whose ``col(...)`` references all exist on ``df`` and that compiles
            and evaluates to one Boolean per row gets a ``__fe__<sha8>``
            companion (null → False, as ``filter`` drops a null predicate).
            The others are skipped: the runtime then has no companion to AND,
            which the producers' tier check reports instead.

    Idempotent: a companion column that already exists on ``df`` is left as-is
    (never duplicated, never recomputed); its codebook/manifest entries are
    still returned.

    Returns:
        A :class:`CompanionResult` with the extended frame, per-column
        codebooks, and the companion → source-column map for the manifest.
    """
    exprs: list[pl.Expr | pl.Series] = []
    codebooks: dict[str, dict[str, int]] = {}
    companions: dict[str, str] = {}
    schema = df.schema

    for col in categorical_cols:
        if col not in schema:
            continue
        dtype = schema[col]
        if _is_stringlike(dtype):
            continue

        # Deterministic codes: unique non-null values, ordered by their
        # serialized form, dense 0..n-1. Two values with the same serialized
        # form (indistinguishable to the frontend) share one code.
        uniques = df.get_column(col).drop_nulls().unique().to_list()
        uniques.sort(key=serialize_option)
        codebook: dict[str, int] = {}
        codes: list[int] = []
        for v in uniques:
            key = serialize_option(v)
            if key not in codebook:
                codebook[key] = len(codebook)
            codes.append(codebook[key])

        companion = f"__code__{col}"
        codebooks[col] = codebook
        companions[companion] = col
        if companion in schema:
            continue  # idempotent: already materialised
        if uniques:
            exprs.append(
                pl.col(col)
                .replace_strict(
                    old=pl.Series(uniques, dtype=dtype),
                    new=pl.Series(codes, dtype=pl.Int32),
                    default=None,  # null source rows stay null
                    return_dtype=pl.Int32,
                )
                .alias(companion)
            )
        else:  # all-null column: companion is all-null too
            exprs.append(pl.lit(None, dtype=pl.Int32).alias(companion))

    for col in datetime_cols:
        if col not in schema:
            continue
        base = schema[col].base_type()
        if base != pl.Date and base != pl.Datetime:
            continue  # not a temporal column we can epoch — nothing to materialise
        companion = f"__ts__{col}"
        companions[companion] = col
        if companion in schema:
            continue  # idempotent
        # Same normalisation expression as the server's datetime branch
        # (Utf8-coalesce parse, tz stripped), then epoch µs. Null-preserving.
        exprs.append(
            datetime_column_expr(col).cast(pl.Datetime("us")).cast(pl.Int64).alias(companion)
        )

    for expr in dict.fromkeys(filter_exprs):
        if not filter_expr_companionable(expr):
            continue
        refs = set(_FILTER_EXPR_COL_RE.findall(expr))
        if not refs or not refs <= set(schema):
            continue
        companion = filter_expr_companion(expr)
        if companion in schema:
            companions[companion] = expr
            continue
        from depictio.models.components.filter_expr import build_filter_expr

        try:
            series = df.select(build_filter_expr(expr).alias(companion)).to_series()
        except Exception:
            continue
        if series.len() != df.height or series.dtype != pl.Boolean:
            continue
        companions[companion] = expr
        exprs.append(series.fill_null(False))

    out = df.with_columns(exprs) if exprs else df
    return CompanionResult(df=out, codebooks=codebooks, companions=companions)
