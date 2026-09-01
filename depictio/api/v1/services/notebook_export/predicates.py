"""Polars *source* for the predicates the server applies.

The render pipeline builds ``pl.Expr`` objects (``deltatables_utils.add_filter``
and ``_categorical_predicate``); a notebook needs the same predicates as text.
Expression objects cannot be printed back as Python, so this module mirrors
``add_filter`` branch for branch and emits source instead. The equivalence
test (``tests/unit/notebook_export/test_predicates.py``) evaluates what is
emitted here against what ``add_filter`` builds, for every branch, so the two
cannot drift silently.

The emitted code assumes the notebook's imports cell:
``import datetime``, ``import polars as pl`` and ``from polars import col, lit``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime as _dt
from typing import Any

import polars as pl

from depictio.api.v1.deltatables_utils import LINK_NO_MATCH, parse_iso_datetime
from depictio.models.components.filter_expr import validate_filter_expr

CATEGORICAL_TYPES: frozenset[str] = frozenset({"Select", "MultiSelect", "SegmentedControl"})
DATE_RANGE_TYPES: frozenset[str] = frozenset({"DateRangePicker", "Timeline"})


@dataclass(frozen=True)
class PredicateSource:
    """Source for one predicate: optional statements, then the expression."""

    expr: str
    prelude: list[str] = field(default_factory=list)
    note: str | None = None

    def as_lines(self, target: str) -> list[str]:
        """``target = target.filter(<expr>)`` with its prelude, ready to indent."""
        return [*self.prelude, f"{target} = {target}.filter({self.expr})"]


def literal(value: Any) -> str:
    """Python source for a filter value.

    ``repr`` is exact for ``str``/``int``/``float``/``bool``/``None`` and for
    ``datetime.*`` objects, whose repr is spelled with the module prefix the
    imports cell provides (``datetime.datetime(2024, 1, 1, 0, 0)``).
    """
    return repr(value)


def literal_list(values: list[Any]) -> str:
    return "[" + ", ".join(literal(v) for v in values) + "]"


def dtype_source(dtype: pl.DataType) -> str:
    """``pl.Int64``, ``pl.Datetime(time_unit='us', time_zone=None)``, ..."""
    return f"pl.{dtype!r}"


def _column(column: str) -> str:
    return f"pl.col({column!r})"


def _categorical(column: str, values: list[Any], dtype: pl.DataType | None) -> PredicateSource:
    """Mirror of ``_categorical_predicate``: cast the values, never the column."""
    str_values = [str(v) for v in values]
    fallback = PredicateSource(
        expr=f"{_column(column)}.cast(pl.Utf8, strict=False).is_in({literal_list(str_values)})"
    )
    if dtype is None:
        return fallback
    if dtype == pl.String:
        return PredicateSource(expr=f"{_column(column)}.is_in({literal_list(str_values)})")

    raw = pl.Series(str_values, dtype=pl.Utf8)
    base = dtype.base_type()
    try:
        if dtype.is_numeric() or dtype == pl.Date:
            converted = raw.cast(dtype, strict=False)
            typed = converted.drop_nulls().to_list()
            if not typed:
                return fallback
            return PredicateSource(expr=f"{_column(column)}.is_in({literal_list(typed)})")
        if base == pl.Datetime:
            converted = raw.str.to_datetime(strict=False).cast(dtype, strict=False)
            if not converted.drop_nulls().to_list():
                return fallback
            return PredicateSource(
                expr=(
                    f"{_column(column)}.is_in("
                    f"pl.Series({literal_list(str_values)}, dtype=pl.Utf8)"
                    f".str.to_datetime(strict=False)"
                    f".cast({dtype_source(dtype)}, strict=False).drop_nulls())"
                )
            )
        if base == pl.Time:
            converted = raw.str.to_time(strict=False)
            if not converted.drop_nulls().to_list():
                return fallback
            return PredicateSource(
                expr=(
                    f"{_column(column)}.is_in("
                    f"pl.Series({literal_list(str_values)}, dtype=pl.Utf8)"
                    f".str.to_time(strict=False).drop_nulls())"
                )
            )
    except Exception:
        return fallback
    return fallback


def _naive(value: object) -> object:
    if isinstance(value, _dt) and value.tzinfo:
        return value.replace(tzinfo=None)
    return value


def _date_range(column: str, value: Any) -> PredicateSource | None:
    if not (value and isinstance(value, list) and len(value) == 2):
        return None
    try:
        start = _naive(parse_iso_datetime(value[0]))
        end = _naive(parse_iso_datetime(value[1]))
    except Exception:
        return None
    if not isinstance(start, (_dt, _date)) or not isinstance(end, (_dt, _date)):
        return None
    col_str = f"{_column(column)}.cast(pl.Utf8, strict=False)"
    prelude = [
        "_d = pl.coalesce(",
        "    [",
        f"        {col_str}.str.to_datetime(strict=False).dt.replace_time_zone(None),",
        f'        {col_str}.str.strptime(pl.Datetime, "%Y-%m-%d", strict=False),',
        "    ]",
        ")",
    ]
    return PredicateSource(
        expr=f"(_d >= pl.lit({literal(start)})) & (_d <= pl.lit({literal(end)}))",
        prelude=prelude,
    )


def emit_predicate(
    interactive_component_type: str | None,
    column: str,
    value: Any,
    dtype: pl.DataType | None = None,
) -> PredicateSource | None:
    """Source for what ``add_filter`` would append, or ``None`` when it appends nothing.

    ``None`` is also what a ``Switch`` gets: the server has no branch for it,
    so a Switch never narrows rows, and the notebook must not pretend it does.
    """
    itype = interactive_component_type or ""
    if itype == LINK_NO_MATCH:
        return PredicateSource(expr="pl.lit(False)")
    if itype in CATEGORICAL_TYPES:
        if not value:
            return None
        values = value if isinstance(value, list) else [value]
        return _categorical(column, values, dtype)
    if itype == "TextInput":
        if not value:
            return None
        return PredicateSource(expr=f"{_column(column)}.str.contains({literal(value)})")
    if itype == "Slider":
        if not value:
            return None
        return PredicateSource(expr=f"{_column(column)} == {literal(value)}")
    if itype == "RangeSlider":
        if not value:
            return None
        lo, hi = value[0], value[1]
        return PredicateSource(
            expr=f"({_column(column)} >= {literal(lo)}) & ({_column(column)} <= {literal(hi)})"
        )
    if itype in DATE_RANGE_TYPES:
        return _date_range(column, value)
    return None


def emit_filter_expr(expr_str: str) -> str:
    """A component's static ``filter_expr`` as source.

    The grammar is already Polars spelled with bare ``col``/``lit``
    (``depictio/models/components/filter_expr.py``), which is exactly what
    the imports cell provides, so the validated text is the source.
    """
    validate_filter_expr(expr_str)
    return expr_str.strip()
