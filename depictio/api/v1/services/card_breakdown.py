"""The ``__breakdown__`` payload behind the card's categorical strips.

``top_n``, ``concentration``, ``composition`` and ``donut`` all draw the same
thing — the top-N values of a column and their share of the total — and differ
only in how the renderer presents it. That shared shape is computed here so the
two callers cannot disagree about it:

* :func:`depictio.api.v1.endpoints.dashboards_endpoints.routes.bulk_compute_cards`
  computes it for a *saved* card, against the interactively filtered frame;
* the ``/deltatables/breakdown`` endpoint computes it for the *builder preview*,
  against the unfiltered Delta table.

Before this module existed the preview had no server call at all: it synthesised
``Bucket 1 / Bucket 2 / Bucket 3`` with a uniform 33/33/34 split from the
precomputed ``nunique``. The names were fake, the distribution was fake, and the
saved card then looked nothing like its own preview. Sharing the real
computation is what makes the preview honest.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

# Secondary layouts that need this payload. Every gate on "does this card need a
# breakdown" reads this one constant — the specs fast path, the pushdown
# short-circuit, the compute block and the builder's required-field logic. A new
# layout added to the renderer but missed in one of those gates renders an empty
# strip, which is exactly how ``composition`` nearly shipped broken.
BREAKDOWN_LAYOUTS = ("top_n", "concentration", "composition", "donut")

# Bound on ``top_n_count``. Past five segments the strip is illegible at a 2x2
# card's width; the builder's NumberInput and the model's ``le=5`` agree.
MAX_TOP_N = 5


def evenness(counts: list[int], total: int) -> float | None:
    """Pielou's evenness of a category distribution, in ``[0, 1]``.

    Shannon entropy over the *whole* distribution divided by ``log(k)``, its
    maximum for ``k`` categories. ``1.0`` means every value occurs equally
    often, values near ``0`` mean one category dominates — the question none of
    the ranking-style layouts answer.

    Computed from the counts the breakdown already grouped, so it costs no extra
    scan. Returns ``None`` below two categories, where the measure is degenerate:
    a single category would score ``0``, which the meter would render as
    "dominated" when the honest answer is "not applicable".
    """
    # Only categories that actually occur count toward ``k``. An empty group can
    # survive a filter, and letting it into the denominator would drag a
    # perfectly balanced distribution below 1.0.
    present = [c for c in counts if c > 0]
    if total <= 0 or len(present) < 2:
        return None
    entropy = 0.0
    for count in present:
        p = count / total
        entropy -= p * math.log(p)
    # log(k) is only zero for k == 1, already excluded above.
    return max(0.0, min(1.0, entropy / math.log(len(present))))


# Per-group reductions for the non-additive heroes: the strip then answers "which
# groups reach the highest max / average", in the card's own unit, instead of
# counting rows under a card that is not about rows. Only ``count`` and ``sum``
# groups are parts of a whole; the renderer shows every other kind (these, and
# ``nunique``, whose per-group distinct counts do not add up to the hero)
# without a percentage.
_VALUE_REDUCTIONS: dict[str, Any] = {
    "average": lambda c: pl.col(c).mean(),
    "mean": lambda c: pl.col(c).mean(),
    "median": lambda c: pl.col(c).median(),
    "min": lambda c: pl.col(c).min(),
    "max": lambda c: pl.col(c).max(),
    "range": lambda c: pl.col(c).max() - pl.col(c).min(),
    "variance": lambda c: pl.col(c).var(),
    "std_dev": lambda c: pl.col(c).std(),
    "std": lambda c: pl.col(c).std(),
}


def group_expr(column: str, breakdown_col: str, aggregation: str) -> pl.Expr:
    """Per-group aggregation expression mirroring the card's hero metric.

    The strip's "Top N cover X%" has to read against the same denominator as the
    hero value, so a ``nunique POS`` card grouped by ``GENE`` must count
    *distinct POS per gene*, not rows per gene. A ``max`` / ``average`` / ...
    card reduces each group with its own aggregation (max reads per group, mean
    reads per group) rather than counting rows under a card that is not about
    rows.

    One special case: when the breakdown column *is* the hero column (an
    ``Unique Lineages`` card broken down by ``lineage``), ``n_unique`` per group
    is trivially 1 and the strip degenerates into N equal bars. Row count is the
    natural reading there: "Alpha: 14 rows, Delta: 9 rows".
    """
    hero = (aggregation or "count").lower()
    if column == breakdown_col:
        return pl.len().alias("__count__")
    if hero in ("nunique", "unique"):
        return pl.col(column).n_unique().alias("__count__")
    if hero == "sum":
        return pl.col(column).sum().alias("__count__")
    if hero in _VALUE_REDUCTIONS:
        return _VALUE_REDUCTIONS[hero](column).alias("__count__")
    # ``count`` and anything else (percentile, mode, ...) -> rows per group.
    return pl.len().alias("__count__")


def _is_value_breakdown(column: str, breakdown_col: str, aggregation: str) -> bool:
    """True when each group carries a value in the hero's unit (max, mean, ...)
    rather than a count or a sum: no share of a total applies."""
    hero = (aggregation or "count").lower()
    return column != breakdown_col and hero in _VALUE_REDUCTIONS


def _plain_number(v: Any) -> float | int | None:
    if v is None:
        return None
    f = float(v)
    if math.isnan(f) or math.isinf(f):
        return None
    return int(f) if f.is_integer() else f


def compute_breakdown(
    frame: pl.DataFrame | pl.LazyFrame,
    column: str,
    breakdown_col: str,
    aggregation: str,
    top_n_count: int = 3,
) -> dict[str, Any]:
    """Group ``frame`` by ``breakdown_col`` and return the renderer's payload.

    ``column`` is the card's hero column and ``aggregation`` its hero metric;
    together they pick the per-group reduction (see :func:`group_expr`).

    The returned dict is the ``__breakdown__`` contract the ``SecondaryMetrics``
    renderer reads: ``top`` carries the N largest groups with their share, while
    ``total``, ``unique_values`` and ``evenness`` describe the *whole*
    distribution, so the tail the strip cannot draw is still accounted for.
    """
    top_n_count = max(1, min(int(top_n_count or 3), MAX_TOP_N))
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    if _is_value_breakdown(column, breakdown_col, aggregation):
        return _value_breakdown(lazy, column, breakdown_col, aggregation, top_n_count)

    grouped = (
        lazy.group_by(breakdown_col)
        .agg(group_expr(column, breakdown_col, aggregation))
        # Name is the tie-break, and it is not cosmetic: ``group_by`` does not
        # promise an order, so on tied counts the preview and the saved card
        # would rank the same data differently — the two callers must agree.
        .sort(["__count__", breakdown_col], descending=[True, False], nulls_last=True)
        .collect()
    )
    total_raw = grouped["__count__"].sum()
    total = int(total_raw or 0) if total_raw is not None else 0
    top_rows = grouped.head(top_n_count)
    # Nulls are a real category — a column that is 40% unfilled is exactly what
    # the composition bar should show. ``cast(Utf8)`` maps them to None, so they
    # get a visible label rather than an empty segment.
    names = [
        ("(null)" if n is None else n) for n in top_rows[breakdown_col].cast(pl.Utf8).to_list()
    ]
    counts = [int(c) for c in top_rows["__count__"].to_list()]
    top_share = (sum(counts) / total) if total > 0 else 0.0

    return {
        "column": breakdown_col,
        "total": total,
        "top": [
            {
                "name": names[i],
                "count": counts[i],
                "percent": (counts[i] / total) if total > 0 else 0.0,
            }
            for i in range(len(names))
        ],
        "top_share": top_share,
        "unique_values": int(grouped.height),
        "breakdown_kind": (aggregation or "count").lower(),
        "evenness": evenness([int(c) for c in grouped["__count__"].to_list()], total),
    }


def _value_breakdown(
    lazy: pl.LazyFrame,
    column: str,
    breakdown_col: str,
    aggregation: str,
    top_n_count: int,
) -> dict[str, Any]:
    """Breakdown for a non-additive hero (max, average, median, ...).

    Each group's ``count`` is the hero aggregation over that group, in the
    column's unit (kept as a float, not truncated). ``percent``, ``top_share``
    and ``evenness`` are ``None``: a group's max is not a share of anything.
    Groups rank by value, descending, except under ``min`` where the lowest
    groups are the interesting ones. ``total`` is the number of rows, so the
    tooltip can still say how much data the strip summarises.
    """
    hero = (aggregation or "count").lower()
    ascending = hero == "min"
    grouped = (
        lazy.group_by(breakdown_col)
        .agg(group_expr(column, breakdown_col, aggregation), pl.len().alias("__rows__"))
        .sort(
            ["__count__", breakdown_col],
            descending=[not ascending, False],
            nulls_last=True,
        )
        .collect()
    )
    top_rows = grouped.head(top_n_count)
    names = [
        ("(null)" if n is None else n) for n in top_rows[breakdown_col].cast(pl.Utf8).to_list()
    ]
    values = [_plain_number(v) for v in top_rows["__count__"].to_list()]
    return {
        "column": breakdown_col,
        "total": int(grouped["__rows__"].sum() or 0),
        "top": [{"name": names[i], "count": values[i], "percent": None} for i in range(len(names))],
        "top_share": None,
        "unique_values": int(grouped.height),
        "breakdown_kind": hero,
        "evenness": None,
    }
