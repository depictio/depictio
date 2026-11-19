"""References computed from the data on show: one statistic, one name.

RULES.md §17 allows a reference that is defined by the data only when it is
called that: a line at the median of a table is a reading aid, not a threshold
of the tool, and must say so. Every place that draws one (the advanced-viz data
route, the export builders, the UI-mode figure builder and the catalog preview)
computes it here and names it with :func:`reference_label`, so the value and the
words can never disagree between the dashboard and its preview.

The statistic is taken on the filtered rows *before* any sampling: a client
fetch may be a uniform sample, and the Manhattan / genome view keep one tail
whole, either of which would bias a quantile taken in the browser.

Pure polars, no FastAPI: ``depictio/catalog/payload.py`` imports it lazily on
the CLI-only install.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

#: Every statistic a ``*_stat`` field may name (``ReferenceStat`` in
#: ``depictio/models/components/advanced_viz/configs.py``).
REFERENCE_STATS: tuple[str, ...] = ("median", "mean", "p75", "p90", "p95", "p99")

#: How each statistic is named on the plot; " of this table" is appended.
#: Mirrored in ``packages/depictio-react-core/src/components/advanced_viz/referenceStats.ts``.
REFERENCE_STAT_NAMES: dict[str, str] = {
    "median": "median",
    "mean": "mean",
    "p75": "75th percentile",
    "p90": "90th percentile",
    "p95": "95th percentile",
    "p99": "99th percentile",
}

_QUANTILES: dict[str, float] = {"p75": 0.75, "p90": 0.90, "p95": 0.95, "p99": 0.99}


def reference_label(stat: str) -> str:
    """The words a computed reference is drawn with: ``median of this table``."""
    return f"{REFERENCE_STAT_NAMES.get(stat, stat)} of this table"


def stat_expr(column: str, stat: str) -> pl.Expr:
    """A polars expression computing ``stat`` over ``column``.

    Nulls and non-finite values (NaN, +-inf) are left out: a NaN poisons a mean
    and an infinity drags a p99 off the axis. Strings that parse as numbers are
    cast; anything else becomes null and is ignored.
    """
    if stat not in REFERENCE_STATS:
        raise ValueError(f"unknown reference stat {stat!r}; expected one of {REFERENCE_STATS}")
    col = pl.col(column).cast(pl.Float64, strict=False)
    col = col.filter(col.is_finite())
    if stat == "median":
        return col.median()
    if stat == "mean":
        return col.mean()
    return col.quantile(_QUANTILES[stat], interpolation="linear")


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def compute_stat(series: pl.Series | list[Any], stat: str) -> float | None:
    """``stat`` over ``series``, or None when no finite value is left."""
    if not isinstance(series, pl.Series):
        series = pl.Series("v", list(series), strict=False)
    frame = pl.DataFrame({"v": series})
    return _finite(frame.select(stat_expr("v", stat)).item())


def parse_requests(raw: Any) -> dict[str, tuple[str, str]]:
    """``{field: (column, stat)}`` from a request's ``reference_stats``.

    The wire shape is ``{field: {"column": str, "stat": str}}``. Malformed
    entries are dropped rather than raised on: a reference is a reading aid,
    and a bad one must not cost the reader the plot.
    """
    out: dict[str, tuple[str, str]] = {}
    if not isinstance(raw, dict):
        return out
    for field, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        column, stat = spec.get("column"), spec.get("stat")
        if isinstance(column, str) and column and stat in REFERENCE_STATS:
            out[str(field)] = (column, str(stat))
    return out


def compute_requests(
    frame: pl.DataFrame | pl.LazyFrame, requests: dict[str, tuple[str, str]]
) -> dict[str, float | None]:
    """Every requested statistic over ``frame`` in one pass.

    A column the frame does not hold answers None, like a column with no
    finite value: the renderer then draws no line, never a wrong one.
    """
    if not requests:
        return {}
    names = set(
        frame.collect_schema().names() if isinstance(frame, pl.LazyFrame) else frame.columns
    )
    exprs = [
        stat_expr(column, stat).alias(f"__ref_{i}")
        for i, (column, stat) in enumerate(requests.values())
        if column in names
    ]
    values: dict[str, Any] = {}
    if exprs:
        result = frame.select(exprs)
        if isinstance(result, pl.LazyFrame):
            result = result.collect()
        values = result.row(0, named=True)
    out: dict[str, float | None] = {}
    for i, (field, (column, _stat)) in enumerate(requests.items()):
        out[field] = _finite(values.get(f"__ref_{i}")) if column in names else None
    return out


def config_reference_requests(
    viz_kind: str | None, config: dict[str, Any]
) -> dict[str, tuple[str, str]]:
    """The statistics an advanced-viz config asks for, as ``{field: (column, stat)}``.

    The field is the config key the value stands in for, which is also the key
    the data route answers under in ``reference_stats``. An explicit value on
    that key wins, so nothing is requested for it. Twin of ``referenceRequests``
    in ``packages/depictio-react-core/src/components/advanced_viz/referenceStats.ts``.
    """
    out: dict[str, tuple[str, str]] = {}
    if viz_kind == "scatter_xy":
        stat, line = config.get("reference_stat"), config.get("reference_line")
        column = config.get("y_col") if line == "horizontal" else config.get("x_col")
        if stat and line in ("horizontal", "vertical") and config.get("reference_value") is None:
            if column:
                out["reference_value"] = (str(column), str(stat))
    elif viz_kind == "profile":
        stat, column = config.get("reference_y_stat"), config.get("y_col")
        if stat and column and config.get("reference_y") is None:
            out["reference_y"] = (str(column), str(stat))
    elif viz_kind in ("manhattan", "genome_view"):
        stat, column = config.get("score_threshold_stat"), config.get("score_col")
        if stat and column and config.get("score_threshold") is None:
            out["score_threshold"] = (str(column), str(stat))
    return {f: (c, s) for f, (c, s) in out.items() if s in REFERENCE_STATS}
