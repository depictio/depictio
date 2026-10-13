"""Server-computed payloads for the card's numeric / QC secondary layouts.

These layouts answer questions the existing ones cannot:

``histogram``
    The *shape* of a numeric column. ``box_plot`` summarises it as five
    numbers, which is exactly the summary that hides bimodality: two peaks and
    a flat plateau produce the same min/Q1/median/Q3/max. The sparkline is the
    only layout that shows the difference.

``threshold``
    How many rows pass a QC cut-off, and how many fail. This is the question
    every nf-core pipeline asks — MultiQC is in 110 of the 155 pipelines, and
    its general-statistics table exists to be read against thresholds (Q30,
    duplication, mapping rate, ≥10x breadth). A ``box_plot`` shows the spread
    but never answers "are 3 of my 40 samples unusable".

``completeness``
    How much of the column is actually populated. First question asked of any
    clinical / sample metadata table, and the data is already in the
    precomputed specs, so it costs nothing.

``attrition``
    Row-count retention across a sequence of numeric columns — reads in →
    trimmed → mapped → deduplicated. The most-read figure of any nf-core
    report, and the only layout here that spans several columns.

``trend``
    The hero aggregation recomputed per bucket of an ordered column. Where
    ``attrition`` walks a fixed sequence of *columns*, this walks the *values*
    of one — a date, a run index, a batch — so it is the only layout that
    answers "is this number moving".

``uniqueness``
    Distinct versus repeated values. The other half of the data-quality pair:
    ``completeness`` counts what is missing, this counts what is duplicated,
    which is invisible to every other layout because nothing is absent.

All of them are computed server-side, on the same frame the hero value is
computed from, and shared with the builder-preview endpoint so a card's
preview and its saved self cannot disagree.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import polars as pl

# Layouts implemented here, i.e. those needing a payload that is not the
# categorical ``__breakdown__``. Kept next to ``BREAKDOWN_LAYOUTS`` in
# ``card_breakdown`` so the two sets are read together; every gate that asks
# "does this card need server-side work" must consult both.
NUMERIC_LAYOUTS = (
    "histogram",
    "threshold",
    "completeness",
    "attrition",
    "trend",
    "uniqueness",
)

# Secondary layouts whose per-selection-group variant ships in the
# ``__group_compare__`` payload (see ``card_groups.compute_group_compare`` and
# the wiring in ``bulk_compute_cards``). Explicit rather than derived: a layout
# added to NUMERIC_LAYOUTS but forgotten here silently keeps chips-only
# comparison, which is the safe default — the reverse (a layout gated in but
# with no compact client rendering) would ship an empty strip.
GROUP_COMPARABLE_LAYOUTS = (
    "box_plot",
    "threshold",
    "completeness",
    "uniqueness",
    # Shared-scale layouts: the bin grid / x-axis grid is computed once over
    # the whole frame and every partition is reduced against it — self-scaled
    # per-group charts would be incomparable.
    "histogram",
    "trend",
    # Per-group breakdown over the card's own breakdown_col — donut gets a
    # mini-ring per group (client caps visible groups), the other breakdown
    # layouts degrade to one composition meter per group. Rings/meters are
    # read alone, so divergent per-group category sets are acceptable at this
    # scale.
    "donut",
    "composition",
    "top_n",
    "concentration",
    # Client-computable: per-group hero value against the card's authored
    # coverage_max / denominator; no server payload needed.
    "coverage",
    "gauge",
)

# Bin count for the sparkline. Twenty bars is what fits a ~260px card at a
# legible bar width; more turns into noise, fewer hides the second mode the
# layout exists to reveal.
HISTOGRAM_BINS = 20


def compute_box_plot_stats(values: pl.Series, max_outliers: int = 100) -> dict[str, Any] | None:
    """Compound Tukey box-and-whisker payload, computed in one scan.

    Extracted from the ``box_plot_stats`` pseudo-aggregation branch of the card
    endpoint's ``_agg_value`` so the hero path and the per-group comparison
    path reduce identically (same argument as ``compute_breakdown`` vs the
    preview). Returns the 9-field dict the React box-plot renderer reads, or
    ``None`` for an empty/non-numeric series.

    ``max_outliers`` caps the outlier list — beyond that the dots overlap into
    a solid bar at card scale; the count is exposed separately. Per-group
    callers pass a much lower cap than the hero's 100: the payload is repeated
    once per group.
    """
    numeric = values.cast(pl.Float64, strict=False).drop_nulls()
    if numeric.len() == 0:
        return None
    mn = float(numeric.min())  # type: ignore[arg-type]
    mx = float(numeric.max())  # type: ignore[arg-type]
    q1 = float(numeric.quantile(0.25, interpolation="linear"))  # type: ignore[arg-type]
    q3 = float(numeric.quantile(0.75, interpolation="linear"))  # type: ignore[arg-type]
    median = float(numeric.median())  # type: ignore[arg-type]
    mean = float(numeric.mean())  # type: ignore[arg-type]
    iqr = q3 - q1
    fence_lo = q1 - 1.5 * iqr
    fence_hi = q3 + 1.5 * iqr
    # Whisker = most extreme data point that's still within the fence. Falls
    # back to min/max when the fence excludes everything (e.g. constant column
    # → iqr=0 → both fences land on q1=q3=median).
    within = numeric.filter((numeric >= fence_lo) & (numeric <= fence_hi))
    lower_w = float(within.min()) if within.len() else mn  # type: ignore[arg-type]
    upper_w = float(within.max()) if within.len() else mx  # type: ignore[arg-type]
    outliers_series = numeric.filter((numeric < fence_lo) | (numeric > fence_hi))
    outlier_count = int(outliers_series.len())
    outliers = outliers_series.head(max_outliers).to_list() if outlier_count else []
    return {
        "min": mn,
        "max": mx,
        "q1": q1,
        "q3": q3,
        "median": median,
        "mean": mean,
        "lower_whisker": lower_w,
        "upper_whisker": upper_w,
        "outliers": outliers,
        "outlier_count": outlier_count,
    }


# Buckets a trend line is cut into. Beyond this the line is drawn from more
# points than the card has pixels, so the extra detail is invisible and the
# payload is just bigger. Distinct values below the cap are kept as-is: a
# three-year study should show three points, not three interpolated ones.
TREND_MAX_POINTS = 24


def _bucket_expr(value: pl.Expr, lo: float, width: float, n: int) -> pl.Expr:
    """Equal-width bucket index of ``value`` on the fixed grid ``[lo, lo + n*width)``."""
    return ((value - lo) / width).floor().clip(0, n - 1).cast(pl.Int64)


def _axis_num_expr(axis: str, temporal: bool) -> pl.Expr:
    """Numeric form of a trend axis — temporal axes via their integer
    representation, so one bucketing expression covers dates, timestamps and
    plain numbers."""
    return pl.col(axis).cast(pl.Int64) if temporal else pl.col(axis).cast(pl.Float64)


def _classify_axis(dtype: pl.DataType) -> tuple[bool, bool, str]:
    """``(temporal, numeric, axis_kind)`` classification of a trend axis dtype."""
    temporal = dtype in (pl.Date, pl.Datetime) or dtype.base_type() in (pl.Date, pl.Datetime)
    numeric = dtype.is_numeric()
    return temporal, numeric, "temporal" if temporal else "numeric" if numeric else "categorical"


def compute_histogram(
    frame: pl.DataFrame | pl.LazyFrame,
    column: str,
    bins: int = HISTOGRAM_BINS,
    domain: tuple[float, float] | None = None,
) -> dict[str, Any] | None:
    """Binned counts for ``column``, or ``None`` when a histogram is meaningless.

    Returns ``None`` rather than an empty chart for a column with no spread (all
    rows identical, or a single row): every bar would be the same height and the
    reader would infer a uniform distribution from what is really one value.

    Nulls are excluded from the bars — a null has no position on a numeric axis
    — but reported separately so a mostly-empty column cannot masquerade as a
    narrow distribution.

    ``domain`` pins the bin grid to an externally computed ``(lo, hi)`` instead
    of the frame's own extent — required by the per-group comparison, where
    each partition binned on its own extent would produce incomparable bars.
    With a domain, a single-value partition is still meaningful (one tall bar
    on the shared axis), so the no-spread guard applies to the domain instead.
    """
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    stats = lazy.select(
        pl.col(column).min().alias("min"),
        pl.col(column).max().alias("max"),
        pl.col(column).null_count().alias("nulls"),
        pl.len().alias("total"),
        pl.col(column).median().alias("median"),
    ).collect()
    if not stats.height:
        return None
    lo, hi = stats["min"][0], stats["max"][0]
    total = int(stats["total"][0] or 0)
    nulls = int(stats["nulls"][0] or 0)
    if domain is not None:
        d_lo, d_hi = domain
        if d_hi <= d_lo or lo is None or total - nulls < 1:
            return None
        width = (d_hi - d_lo) / bins
        bucket = _bucket_expr(pl.col(column).cast(pl.Float64), d_lo, width, bins)
        grouped = (
            lazy.filter(pl.col(column).is_not_null())
            .group_by(bucket.alias("__bucket__"))
            .agg(pl.len().alias("__count__"))
            .collect()
        )
        by_bucket = dict(zip(grouped["__bucket__"].to_list(), grouped["__count__"].to_list()))
        counts = [int(by_bucket.get(i, 0)) for i in range(bins)]
        breakpoints = [d_lo + width * (i + 1) for i in range(bins)]
    else:
        if lo is None or hi is None or total - nulls <= 1 or lo == hi:
            return None
        hist = (
            lazy.select(pl.col(column).hist(bin_count=bins, include_breakpoint=True).alias("h"))
            .unnest("h")
            .collect()
        )
        counts = [int(c or 0) for c in hist["count"].to_list()]
        breakpoints = [float(b) for b in hist["breakpoint"].to_list()]
    return {
        "bins": counts,
        "breakpoints": breakpoints,
        "min": float(lo),
        "max": float(hi),
        "median": float(stats["median"][0]) if stats["median"][0] is not None else None,
        "total": total,
        "nulls": nulls,
    }


def compute_threshold(
    frame: pl.DataFrame | pl.LazyFrame,
    column: str,
    threshold: float,
    direction: str = "min",
    warn_threshold: float | None = None,
) -> dict[str, Any] | None:
    """Pass / warn / fail counts of ``column`` against a QC cut-off.

    ``direction`` says which side passes: ``min`` means "at least" (coverage,
    Q30, mapping rate — higher is better), ``max`` means "at most" (duplication
    rate, contamination, error rate — lower is better). Getting this backwards
    silently inverts a QC verdict, so it is explicit rather than inferred.

    ``warn_threshold`` is optional and sits between pass and fail: rows on the
    passing side of it but the failing side of ``threshold`` are "warn". It is
    ignored unless it lies strictly between the failing side and ``threshold``,
    because a warn band on the wrong side of the cut-off would label passing
    rows as warnings.

    Nulls count as neither pass nor fail — a missing measurement is not a failed
    one — but are reported so they cannot silently shrink the denominator.
    """
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    col = pl.col(column)
    higher_is_better = direction != "max"

    passes = col >= threshold if higher_is_better else col <= threshold
    warn_valid = warn_threshold is not None and (
        warn_threshold < threshold if higher_is_better else warn_threshold > threshold
    )
    if warn_valid:
        # Warn band: fails the main cut-off but clears the softer one.
        warns = (~passes) & (col >= warn_threshold if higher_is_better else col <= warn_threshold)
    else:
        warns = pl.lit(False)

    stats = lazy.select(
        pl.len().alias("total"),
        col.null_count().alias("nulls"),
        passes.sum().alias("passing"),
        warns.sum().alias("warning"),
        col.min().alias("min"),
        col.max().alias("max"),
        col.median().alias("median"),
    ).collect()
    if not stats.height:
        return None

    total = int(stats["total"][0] or 0)
    nulls = int(stats["nulls"][0] or 0)
    measured = total - nulls
    passing = int(stats["passing"][0] or 0)
    warning = int(stats["warning"][0] or 0) if warn_valid else 0
    failing = max(0, measured - passing - warning)

    return {
        "column": column,
        "threshold": float(threshold),
        "warn_threshold": float(warn_threshold) if warn_valid else None,
        "direction": "min" if higher_is_better else "max",
        "total": total,
        "measured": measured,
        "nulls": nulls,
        "passing": passing,
        "warning": warning,
        "failing": failing,
        "pass_rate": (passing / measured) if measured > 0 else 0.0,
        "min": float(stats["min"][0]) if stats["min"][0] is not None else None,
        "max": float(stats["max"][0]) if stats["max"][0] is not None else None,
        "median": float(stats["median"][0]) if stats["median"][0] is not None else None,
    }


def compute_completeness(
    frame: pl.DataFrame | pl.LazyFrame,
    column: str,
) -> dict[str, Any] | None:
    """How much of ``column`` is populated.

    Deliberately counts nulls only. Empty strings and sentinel values ("NA",
    -1, "unknown") are domain conventions this layer cannot distinguish from
    real data, and guessing at them would report a completeness the user cannot
    reproduce from their own table.
    """
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    stats = lazy.select(
        pl.len().alias("total"),
        pl.col(column).null_count().alias("nulls"),
    ).collect()
    if not stats.height:
        return None
    total = int(stats["total"][0] or 0)
    nulls = int(stats["nulls"][0] or 0)
    filled = max(0, total - nulls)
    return {
        "column": column,
        "total": total,
        "filled": filled,
        "nulls": nulls,
        "fill_rate": (filled / total) if total > 0 else 0.0,
    }


def compute_attrition(
    frame: pl.DataFrame | pl.LazyFrame,
    columns: list[str],
    aggregation: str = "sum",
) -> dict[str, Any] | None:
    """Retention across an ordered sequence of numeric columns.

    ``columns`` is the pipeline's stages in order — ``["raw_reads",
    "trimmed_reads", "mapped_reads", "deduplicated"]``. Each stage is reduced
    with ``aggregation`` (``sum`` totals the cohort, ``average`` describes the
    typical sample) and reported both as a share of the first stage and as the
    step-to-step drop, because a single catastrophic step is invisible in the
    cumulative curve alone.

    The stages are *not* sorted by value: their order is the pipeline's order,
    which is the whole content of the chart. A stage that rises above its
    predecessor is reported as-is rather than clamped, since that means the
    columns were listed in the wrong order and hiding it would strand the user.
    """
    if len(columns) < 2:
        return None
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    reducer = {
        "sum": lambda c: pl.col(c).sum(),
        "average": lambda c: pl.col(c).mean(),
        "mean": lambda c: pl.col(c).mean(),
        "median": lambda c: pl.col(c).median(),
        "min": lambda c: pl.col(c).min(),
        "max": lambda c: pl.col(c).max(),
    }.get((aggregation or "sum").lower(), lambda c: pl.col(c).sum())

    row = lazy.select([reducer(c).alias(c) for c in columns]).collect()
    if not row.height:
        return None

    values: list[float] = []
    for c in columns:
        raw = row[c][0]
        values.append(float(raw) if raw is not None else 0.0)

    first = values[0]
    stages = []
    for idx, (name, value) in enumerate(zip(columns, values)):
        previous = values[idx - 1] if idx else None
        stages.append(
            {
                "name": name,
                "value": value,
                # Share of the *starting* population: the cumulative survival.
                "share": (value / first) if first else 0.0,
                # Share of the immediately preceding stage: isolates which single
                # step did the damage.
                "step_share": (value / previous) if idx and previous else None,
            }
        )

    return {
        "columns": list(columns),
        "aggregation": (aggregation or "sum").lower(),
        "stages": stages,
        "retained": (values[-1] / first) if first else 0.0,
    }


def compute_uniqueness(
    frame: pl.DataFrame | pl.LazyFrame,
    column: str,
) -> dict[str, Any] | None:
    """Distinct versus repeated values in ``column``.

    Nulls are excluded from both sides: a missing value is neither a distinct
    entry nor a duplicate of one, and counting it as either turns a sparsely
    filled column into a false uniqueness verdict. They are reported separately
    so the denominator is never a surprise.

    ``top_repeat`` names the worst offender, because "8 rows repeat" is a
    number and "SRR10070141 appears 3 times" is a lead.
    """
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    stats = lazy.select(
        pl.len().alias("total"),
        pl.col(column).null_count().alias("nulls"),
        # Polars counts null as one of the distinct values, so subtract it back
        # out below rather than reporting a column that is 40% empty as having
        # one more distinct value than it does.
        pl.col(column).n_unique().alias("distinct_raw"),
    ).collect()
    if not stats.height:
        return None

    total = int(stats["total"][0] or 0)
    nulls = int(stats["nulls"][0] or 0)
    measured = max(0, total - nulls)
    distinct = max(0, int(stats["distinct_raw"][0] or 0) - (1 if nulls else 0))
    if measured <= 0:
        return None

    top = (
        lazy.filter(pl.col(column).is_not_null())
        .group_by(column)
        .agg(pl.len().alias("__count__"))
        # Name breaks ties so the same data always names the same offender.
        .sort(["__count__", column], descending=[True, False], nulls_last=True)
        .head(1)
        .collect()
    )
    top_repeat: dict[str, Any] | None = None
    if top.height and int(top["__count__"][0]) > 1:
        top_repeat = {
            "name": str(top[column].cast(pl.Utf8)[0]),
            "count": int(top["__count__"][0]),
        }

    return {
        "column": column,
        "total": total,
        "measured": measured,
        "distinct": distinct,
        "duplicated": max(0, measured - distinct),
        "unique_rate": (distinct / measured) if measured else 0.0,
        "nulls": nulls,
        "top_repeat": top_repeat,
    }


# Aggregations a trend bucket can be reduced with. Deliberately a small set:
# a per-bucket skewness is a statistic nobody reads off a 28px sparkline, and
# offering it would only produce noisy lines.
_TREND_REDUCERS = {
    "count": lambda c: pl.col(c).count(),
    "nunique": lambda c: pl.col(c).n_unique(),
    "unique": lambda c: pl.col(c).n_unique(),
    "sum": lambda c: pl.col(c).sum(),
    "average": lambda c: pl.col(c).mean(),
    "mean": lambda c: pl.col(c).mean(),
    "median": lambda c: pl.col(c).median(),
    "min": lambda c: pl.col(c).min(),
    "max": lambda c: pl.col(c).max(),
}


def _format_axis_label(value: Any) -> str:
    """Bucket label as a reader would write it: a date as a date, an integral
    float as an integer (``2007`` rather than ``2007.0``)."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0, 0) else value.isoformat(" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def compute_trend(
    frame: pl.DataFrame | pl.LazyFrame,
    column: str,
    axis: str,
    aggregation: str = "count",
    max_points: int = TREND_MAX_POINTS,
) -> dict[str, Any] | None:
    """``column`` reduced per bucket of ``axis``, in ``axis`` order.

    ``axis`` is what makes this a trend rather than a breakdown: it must be
    ordered, so a date, a timestamp or any sortable number. A categorical axis
    is accepted and sorted lexically, which is right for the ``run_01``,
    ``run_02`` naming that pipelines produce and wrong for anything else — hence
    ``axis_kind`` in the payload, so the reader knows which they are looking at.

    Above ``max_points`` distinct values a date or numeric axis is cut into
    equal-width buckets, so the line keeps its horizontal *scale*: taking every
    n-th value instead would compress a long quiet stretch and a short busy one
    into the same width. A categorical axis cannot be binned that way, so it
    keeps its last ``max_points`` values instead.

    Returns ``None`` below two buckets, where a line has no shape to show.
    """
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    schema = lazy.collect_schema()
    names = set(schema.names())
    if column not in names or axis not in names:
        return None

    temporal, numeric, axis_kind = _classify_axis(schema[axis])

    reducer = _TREND_REDUCERS.get((aggregation or "count").lower(), _TREND_REDUCERS["count"])
    base = lazy.filter(pl.col(axis).is_not_null())

    distinct = int(base.select(pl.col(axis).n_unique()).collect().item() or 0)
    if distinct < 2:
        return None

    if distinct > max_points and (temporal or numeric):
        axis_num = _axis_num_expr(axis, temporal)
        bounds = base.select(axis_num.min().alias("lo"), axis_num.max().alias("hi")).collect()
        lo = float(bounds["lo"][0])
        hi = float(bounds["hi"][0])
        width = (hi - lo) / max_points
        if width <= 0:
            return None
        bucket = _bucket_expr(axis_num, lo, width, max_points)
        grouped = (
            base.group_by(bucket.alias("__bucket__"))
            .agg(
                reducer(column).alias("__value__"),
                # Label each bucket with its own earliest value rather than the
                # computed edge: a real timestamp from the data is a label the
                # user can find again.
                pl.col(axis).min().alias("__label__"),
            )
            .sort("__bucket__")
            .collect()
        )
        labels = [_format_axis_label(v) for v in grouped["__label__"].to_list()]
    else:
        grouped = base.group_by(axis).agg(reducer(column).alias("__value__")).sort(axis).collect()
        if grouped.height > max_points:
            grouped = grouped.tail(max_points)
        labels = [_format_axis_label(v) for v in grouped[axis].to_list()]

    values = [float(v) if v is not None else 0.0 for v in grouped["__value__"].to_list()]
    if len(values) < 2:
        return None

    first, last = values[0], values[-1]
    return {
        "column": column,
        "axis": axis,
        "axis_kind": axis_kind,
        "aggregation": (aggregation or "count").lower(),
        "points": [{"label": labels[i], "value": values[i]} for i in range(len(values))],
        "first": first,
        "last": last,
        # A percentage change off a zero baseline is undefined, not infinite.
        "change": ((last / first) - 1.0) if first else None,
        "min": min(values),
        "max": max(values),
    }


def trend_axis_grid(
    frame: pl.DataFrame | pl.LazyFrame,
    axis: str,
    max_points: int = TREND_MAX_POINTS,
) -> dict[str, Any] | None:
    """Shared x-grid for multi-series trends, computed over the WHOLE frame.

    Per-group trend series binned on their own extents would put the same
    bucket index at different x positions — the overlay would be a lie. This
    hoists ``compute_trend``'s bucketing decision so every partition is binned
    against one grid: ``{"kind": "binned", lo, hi, n, temporal}`` for a
    numeric/temporal axis, ``{"kind": "labels", labels}`` for a categorical
    one (or a low-cardinality ordered one, where every value is its own
    bucket).
    """
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    schema = lazy.collect_schema()
    if axis not in set(schema.names()):
        return None
    temporal, numeric, axis_kind = _classify_axis(schema[axis])

    base = lazy.filter(pl.col(axis).is_not_null())
    distinct = int(base.select(pl.col(axis).n_unique()).collect().item() or 0)
    if distinct < 2:
        return None

    if distinct > max_points and (temporal or numeric):
        axis_num = _axis_num_expr(axis, temporal)
        bounds = base.select(axis_num.min().alias("lo"), axis_num.max().alias("hi")).collect()
        lo = float(bounds["lo"][0])
        hi = float(bounds["hi"][0])
        if hi <= lo:
            return None
        return {
            "kind": "binned",
            "lo": lo,
            "hi": hi,
            "n": max_points,
            "temporal": temporal,
            "axis_kind": axis_kind,
        }
    labels_df = base.select(pl.col(axis).unique().sort().alias("v")).collect()
    labels = labels_df["v"].to_list()
    if len(labels) > max_points:
        labels = labels[-max_points:]
    return {"kind": "labels", "labels": labels, "axis_kind": axis_kind}


def compute_trend_on_grid(
    frame: pl.DataFrame | pl.LazyFrame,
    column: str,
    axis: str,
    aggregation: str,
    grid: dict[str, Any],
) -> dict[str, Any] | None:
    """One trend series aligned on a shared :func:`trend_axis_grid`.

    Every returned series has exactly one point per grid slot, ``value: None``
    where the partition has no rows in that bucket — which is what lets the
    client overlay N series on one x axis and break the line over gaps rather
    than inventing zeros for aggregations where zero is a claim (a mean of
    nothing is not 0).
    """
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    if column not in set(lazy.collect_schema().names()):
        return None
    reducer = _TREND_REDUCERS.get((aggregation or "count").lower(), _TREND_REDUCERS["count"])
    base = lazy.filter(pl.col(axis).is_not_null())

    if grid["kind"] == "binned":
        lo, hi, n = grid["lo"], grid["hi"], int(grid["n"])
        width = (hi - lo) / n
        bucket = _bucket_expr(_axis_num_expr(axis, bool(grid["temporal"])), lo, width, n)
        grouped = (
            base.group_by(bucket.alias("__bucket__"))
            .agg(reducer(column).alias("__value__"), pl.col(axis).min().alias("__label__"))
            .collect()
        )
        by_bucket = {
            int(b): (v, label)
            for b, v, label in zip(
                grouped["__bucket__"].to_list(),
                grouped["__value__"].to_list(),
                grouped["__label__"].to_list(),
            )
        }
        points = []
        for i in range(n):
            v, label = by_bucket.get(i, (None, None))
            points.append(
                {
                    "label": _format_axis_label(label) if label is not None else str(i),
                    "value": float(v) if v is not None else None,
                }
            )
    else:
        labels = grid["labels"]
        grouped = base.group_by(axis).agg(reducer(column).alias("__value__")).collect()
        by_label = dict(zip(grouped[axis].to_list(), grouped["__value__"].to_list()))
        points = [
            {
                "label": _format_axis_label(lbl),
                "value": float(by_label[lbl]) if by_label.get(lbl) is not None else None,
            }
            for lbl in labels
        ]

    present = [p["value"] for p in points if p["value"] is not None]
    if len(present) < 1:
        return None
    return {
        "axis": axis,
        "axis_kind": grid["axis_kind"],
        "aggregation": (aggregation or "count").lower(),
        "points": points,
        "min": min(present),
        "max": max(present),
    }


def _attrition_columns(card: dict[str, Any], column: str) -> list[str]:
    """Stage list for ``attrition``, from the card's config.

    ``attrition_cols`` holds the ordered stages. The card's own column is
    prepended when the user left it out, because a card titled "raw reads"
    broken into later stages reads as the first stage even if only the
    subsequent ones were listed.
    """
    raw = card.get("attrition_cols") or []
    stages = [str(c) for c in raw if c]
    if column and column not in stages:
        stages = [column, *stages]
    return stages


def numeric_layout_payload(
    frame: pl.DataFrame | pl.LazyFrame,
    card: dict[str, Any],
    column: str,
    layout: str,
) -> dict[str, Any] | None:
    """Dispatch a card's config to the right helper above.

    Shared by ``bulk_compute_cards`` (saved card, filtered frame) and the
    builder-preview endpoint (unfiltered scan) so the two cannot drift — the
    same reason the categorical breakdown is centralised.

    Returns ``None`` when the layout's required config is missing or the data
    cannot support it; callers then render no strip rather than a broken one.
    """
    available = set(
        frame.collect_schema().names() if isinstance(frame, pl.LazyFrame) else frame.columns
    )

    if layout == "histogram":
        if column not in available:
            return None
        return compute_histogram(frame, column)

    if layout == "threshold":
        threshold = card.get("threshold_value")
        if threshold is None or column not in available:
            return None
        return compute_threshold(
            frame,
            column,
            float(threshold),
            direction=str(card.get("threshold_direction") or "min"),
            warn_threshold=(
                float(card["threshold_warn"]) if card.get("threshold_warn") is not None else None
            ),
        )

    if layout == "completeness":
        if column not in available:
            return None
        return compute_completeness(frame, column)

    if layout == "uniqueness":
        if column not in available:
            return None
        return compute_uniqueness(frame, column)

    if layout == "trend":
        axis = card.get("trend_col")
        if not axis or str(axis) not in available or column not in available:
            return None
        return compute_trend(
            frame,
            column,
            str(axis),
            aggregation=str(card.get("aggregation") or "count"),
        )

    if layout == "attrition":
        stages = [c for c in _attrition_columns(card, column) if c in available]
        if len(stages) < 2:
            return None
        return compute_attrition(frame, stages, str(card.get("aggregation") or "sum"))

    return None


def hero_value(frame: pl.DataFrame | pl.LazyFrame, column: str, aggregation: str) -> Any:
    """A card's hero scalar, computed live on ``frame``.

    Exists for the builder preview under active dashboard filters: the static
    precomputed spec (``col.specs[aggregation]``) describes the unfiltered
    collection, so a filtered preview needs the reduction evaluated against the
    filtered frame instead. Reuses the exact expression + coercion pair the
    saved-card pushdown path uses (``_agg_expr`` / ``_coerce_agg_result``), so
    the preview's hero and the saved card's value cannot disagree. Imported at
    call time: that module imports this one at module level.

    Returns ``None`` when the column is missing or the aggregation has no lazy
    expression form (``mode``, ``box_plot_stats`` — the fallback paths need
    materialised values, which a preview shouldn't force).
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _agg_expr,
        _coerce_agg_result,
    )

    available = set(
        frame.collect_schema().names() if isinstance(frame, pl.LazyFrame) else frame.columns
    )
    if column not in available:
        return None
    expr = _agg_expr(column, aggregation)
    if expr is None:
        return None
    lazy = frame if isinstance(frame, pl.LazyFrame) else frame.lazy()
    try:
        raw = lazy.select(expr.alias("__hero__")).collect().row(0)[0]
    except Exception:
        return None
    return _coerce_agg_result(raw, aggregation)
