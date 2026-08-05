"""Shared Polars predicate semantics for Depictio's interactive filters.

This module is the single home of the *pure* expression-building logic behind
categorical (Select / MultiSelect / SegmentedControl) and datetime
(DateRangePicker / Timeline) filters. It was extracted verbatim from
``depictio/api/v1/deltatables_utils.py`` so that both the FastAPI server and
the serverless producer (``depictio/serverless``) build their filter
expressions from the same code — making build/server drift structurally
impossible.

Import constraints: this lives in ``depictio.models`` and therefore must stay
importable without FastAPI, Dash, or any server-side dependency. Only polars,
the stdlib, and the models-package logger are allowed here. I/O, caching and
orchestration stay in ``deltatables_utils``.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _dt

import polars as pl

from depictio.models.logging import logger

# Synthetic ``interactive_component_type`` for "a cross-DC link resolved to no
# target values". Not a user-facing component: it exists so an empty resolution
# can be carried through the ordinary filter payload and still mean "no rows",
# which an empty value list cannot express (see ``add_filter`` in
# ``deltatables_utils``).
LINK_NO_MATCH = "__link_no_match__"


def _categorical_predicate(column_name: str, values: list, dtype: pl.DataType | None) -> pl.Expr:
    """Build the ``is_in`` predicate for Select/MultiSelect/SegmentedControl.

    The values arrive stringified: ``unique_values`` stringifies for the React
    MultiSelect, and scatter/table selections round-trip through the same path.
    So an ``int64`` column compared against ``["1", "2"]`` must still match.

    The obvious way to get that — ``pl.col(c).cast(pl.Utf8).is_in([...])`` — is
    a performance trap. Wrapping the *column* in a cast makes the predicate
    opaque to Polars' parquet reader: row-group min/max statistics can no
    longer be used to skip, and dictionary pushdown is lost, so every filtered
    read fully decodes the filter column across the whole table. Measured on
    the 1 GB benchmark tier that turned a 100-row filtered table page into an
    18-second load.

    So we cast the *values* to the column's dtype instead, which leaves
    ``pl.col(c)`` bare and keeps the predicate pushable. ``dtype`` comes from
    the cached Delta schema; when it is unknown (no schema available) or of a
    kind we don't convert confidently, we fall back to the original
    column-cast form — correctness first, speed only when it is free.

    How a value is converted depends on the dtype, and getting this wrong is
    how a filter silently empties a component:

    - numerics and ``Date`` — ``cast`` parses their string form directly.
    - ``Datetime`` and ``Time`` — ``cast`` from string is a *numeric* parse and
      returns null without raising, so casting is not merely slow, it drops
      every row. They need the real parsers (``str.to_datetime`` /
      ``str.to_time``), which also accept every rendering a client sends:
      ``str()`` (``"2024-01-01 12:30:45"``), ``isoformat()`` (with ``T``), and
      Polars' own ``cast(Utf8)`` (with microseconds). Note the column-cast form
      matched *none* of those — it renders microseconds while clients send
      seconds — so temporal categorical filters never matched anything before;
      routing them through a parser fixes that as well as making them pushable.
    - ``Duration`` — no parser, and its string form isn't castable at all, so
      it keeps the fallback (which raises on contact; pre-existing).
    - everything else (Boolean, Categorical, nested) keeps the fallback: the
      conversion rules aren't obvious enough to risk a silent behaviour change.

    A value that cannot be converted is dropped rather than matched: an int
    column genuinely has no row equal to ``"abc"``, which is what the
    column-cast form returned too. But if *nothing* converts we fall back
    instead of returning "matches nothing" — an all-null conversion is far more
    likely to mean "this dtype doesn't parse from text" than "the user picked
    values this column cannot hold", and guessing wrong empties the component.
    """
    str_values = [str(v) for v in values]
    fallback = pl.col(column_name).cast(pl.Utf8, strict=False).is_in(str_values)

    if dtype is None:
        return fallback

    # Already text: no conversion needed on either side, and the bare column
    # is directly pushable. The common case for categorical filters.
    if dtype == pl.String:  # pl.Utf8 is the same dtype under an older name
        return pl.col(column_name).is_in(str_values)

    raw = pl.Series(str_values, dtype=pl.Utf8)
    base = dtype.base_type()
    try:
        if dtype.is_numeric() or dtype == pl.Date:
            converted = raw.cast(dtype, strict=False)
        elif base == pl.Datetime:
            # Parse naive, then cast to the column's own unit/zone. Verified to
            # round-trip for naive, UTC and offset zones.
            converted = raw.str.to_datetime(strict=False).cast(dtype, strict=False)
        elif base == pl.Time:
            converted = raw.str.to_time(strict=False)
        else:
            return fallback
    except Exception as e:
        logger.debug(
            f"_categorical_predicate: cannot convert values to {dtype} for column "
            f"{column_name!r} ({e}); using the string-cast predicate"
        )
        return fallback

    typed_values = converted.drop_nulls().to_list()
    if not typed_values:
        logger.debug(
            f"_categorical_predicate: no value converted to {dtype} for column "
            f"{column_name!r}; using the string-cast predicate"
        )
        return fallback
    return pl.col(column_name).is_in(typed_values)


# Public alias for consumers outside the API layer (the serverless producer).
categorical_predicate = _categorical_predicate


def parse_datetime_boundary(raw: object) -> object:
    """Parse a React-supplied ISO string (or pass through if already a
    date/datetime) into a Python ``datetime`` object.

    Timeline accepts richer ISO formats (yyyy-mm-ddTHH:MM:SS) so a list of
    formats is tried; DateRangePicker historically used day-precision strings.
    Extracted verbatim from the ``_parse_iso`` closure in ``add_filter``.
    """
    if isinstance(raw, (_dt, _date)):
        return raw
    if not isinstance(raw, str):
        return raw
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return _dt.strptime(raw, fmt)
        except ValueError:
            continue
    # Fall back to ISO 8601 parser (handles trailing 'Z' etc).
    return _dt.fromisoformat(raw.rstrip("Z"))


def strip_timezone(value: object) -> object:
    """Strip tz from a boundary literal in case some caller hands us tz-aware
    datetimes (DateRangePicker historically sent date-only strings, but
    Timeline now emits ISO with ``Z``)."""
    if isinstance(value, _dt) and value.tzinfo:
        return value.replace(tzinfo=None)
    return value


def datetime_column_expr(column_name: str) -> pl.Expr:
    """Robust datetime column expression: works for Date, Datetime, AND
    Utf8 columns.

    ``cast(pl.Datetime)`` alone fails at evaluation when the column is stored
    as a string (which ampliseq's ``sampling_date`` is). Casting to Utf8 first
    then coalesce-parsing across formats covers all three dtypes plus full ISO
    timestamps (``2026-05-05T16:10:27Z``, which the React Timeline emits and
    earlier code rejected because it only tried the date-only ``%Y-%m-%d``
    format).

    Any inferred timezone is stripped so naive comparison literals match.
    Polars treats ``datetime[μs, UTC]`` and ``datetime[μs]`` as incompatible
    for ``>=`` even when the wall-clock values are identical — strings like
    ``2026-05-05T16:10:27Z`` parse with tz, plain ``2026-05-05`` parses
    without. Coalescing requires both branches to share a dtype, so we
    normalize.
    """
    col_str = pl.col(column_name).cast(pl.Utf8, strict=False)
    parsed_iso = col_str.str.to_datetime(strict=False).dt.replace_time_zone(None)
    parsed_date = col_str.str.strptime(pl.Datetime, "%Y-%m-%d", strict=False)
    return pl.coalesce([parsed_iso, parsed_date])


def datetime_range_predicate(column_name: str, start_value: object, end_value: object) -> pl.Expr:
    """Build the inclusive-range predicate for DateRangePicker / Timeline.

    Pure expression construction: boundary parsing, tz normalisation on both
    the column and the literals, and the ``>= / <=`` conjunction. Validation
    of the incoming value shape and error logging stay with the caller
    (``add_filter`` in ``deltatables_utils``).
    """
    start_naive = strip_timezone(parse_datetime_boundary(start_value))
    end_naive = strip_timezone(parse_datetime_boundary(end_value))
    date_col = datetime_column_expr(column_name)
    return (date_col >= pl.lit(start_naive)) & (date_col <= pl.lit(end_naive))
