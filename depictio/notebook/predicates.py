"""Polars *source* for the predicates the server applies.

The render pipeline builds ``pl.Expr`` objects (``deltatables_utils.add_filter``
and ``_categorical_predicate``); a notebook needs the same predicates as text.
Expression objects cannot be printed back as Python, so this module mirrors
``add_filter`` branch for branch and emits source instead. The equivalence
test (``tests/unit/notebook_export/test_predicates.py``) evaluates what is
emitted here against what ``add_filter`` builds, for every branch, so the two
cannot drift silently.

It lives with the notebook client, not the server, because the document uses
it too: the funnel stages are computed from ``depictio_state`` when the
document runs (``depictio.notebook.funnel``), from the very source the export
would have written. So it imports nothing from the server: the few server
helpers it mirrors (the text-pattern compiler, the ISO date parser, the
slider modes) are copied below and pinned to the originals by
``tests/unit/notebook/test_funnel.py``.

The emitted code assumes the notebook's imports cell:
``import datetime``, ``import polars as pl`` and ``from polars import col, lit``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime as _dt
from functools import lru_cache
from typing import Any

import polars as pl

from depictio.models.components.constants import TEXT_MATCH_MODES
from depictio.models.components.filter_expr import validate_filter_expr

# --- Mirrors of deltatables_utils (pinned by test_funnel.py) ----------------

LINK_NO_MATCH = "__link_no_match__"
SLIDER_MODES: dict[str, str] = {
    "gte": ">=",
    "gt": ">",
    "lte": "<=",
    "lt": "<",
    "eq": "==",
    "ne": "!=",
}
DEFAULT_SLIDER_MODE = "gte"
DEFAULT_TEXT_MATCH_MODE = "regex"
MAX_TEXT_PATTERN_LENGTH = 512
_REGEX_META = frozenset("\\.+*?()|[]{}^$#&-~")


def escape_regex(text: str) -> str:
    return "".join(f"\\{ch}" if ch in _REGEX_META else ch for ch in text)


def normalize_text_filter_options(
    case_sensitive: object = None, match_mode: object = None
) -> tuple[bool, str]:
    mode = str(match_mode).lower() if match_mode else DEFAULT_TEXT_MATCH_MODE
    if mode not in TEXT_MATCH_MODES:
        mode = DEFAULT_TEXT_MATCH_MODE
    return bool(case_sensitive), mode


@lru_cache(maxsize=512)
def _is_valid_regex(pattern: str) -> bool:
    try:
        pl.Series([""]).str.contains(pattern)
    except Exception:
        return False
    return True


def text_filter_pattern(
    value: object, case_sensitive: object = None, match_mode: object = None
) -> tuple[str, bool] | None:
    """``deltatables_utils.text_filter_pattern``: ``(pattern, literal)`` or no filter."""
    if value is None or isinstance(value, list | tuple | dict):
        return None
    text = str(value).strip()
    if not text or len(text) > MAX_TEXT_PATTERN_LENGTH:
        return None
    sensitive, mode = normalize_text_filter_options(case_sensitive, match_mode)
    literal = mode == "contains"
    if literal and sensitive:
        return text, True
    if literal:
        text = escape_regex(text)
    pattern = text if sensitive else f"(?i){text}"
    if not _is_valid_regex(pattern):
        return None
    return pattern, False


def parse_iso_datetime(raw: object) -> object:
    """``deltatables_utils.parse_iso_datetime``."""
    if isinstance(raw, (_dt, _date)):
        return raw
    if not isinstance(raw, str):
        return raw
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return _dt.strptime(raw, fmt)
        except ValueError:
            continue
    return _dt.fromisoformat(raw.rstrip("Z"))


# --- The emitter ------------------------------------------------------------

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
    *,
    slider_mode: str | None = None,
    case_sensitive: object = None,
    match_mode: object = None,
) -> PredicateSource | None:
    """Source for what ``add_filter`` would append, or ``None`` when it appends nothing.

    ``slider_mode``, ``case_sensitive`` and ``match_mode`` are ``add_filter``'s
    own options, read off the same filter entry, and resolved by the same
    helpers: a Slider is a ``>=`` threshold unless its mode says otherwise, a
    TextInput a case-insensitive regex unless its options say otherwise.

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
        compiled = text_filter_pattern(value, case_sensitive, match_mode)
        if compiled is None:
            return None
        pattern, is_literal = compiled
        target = _column(column)
        if dtype != pl.String:
            target += ".cast(pl.Utf8, strict=False)"
        flag = ", literal=True" if is_literal else ""
        return PredicateSource(expr=f"{target}.str.contains({literal(pattern)}{flag})")
    if itype == "Slider":
        # `is not None`, not truthiness: 0 is a real threshold.
        if value is None or value == "" or isinstance(value, list):
            return None
        mode = (slider_mode or DEFAULT_SLIDER_MODE).lower()
        op = SLIDER_MODES.get(mode, SLIDER_MODES[DEFAULT_SLIDER_MODE])
        return PredicateSource(expr=f"{_column(column)} {op} {literal(value)}")
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
