"""Time points of a time-course run: hours, order, baseline and phase.

A time course carries its design in one numeric column (hours since the first
sample) and, usually, a label (``30min``, ``2h``). Every panel downstream needs
the same four things out of it, spelled the same way:

* ``time_h``: hours, the x of every trajectory;
* ``time_order``: the rank of the time point, 1 for the earliest;
* ``time_axis``: ``log2(1 + time_h)``, the axis a time course sampled densely
  at the start (minutes) and sparsely at the end (days) reads on, so the early
  points are not crowded into the first few pixels;
* ``phase``: ``Early``, ``Mid`` or ``Late``, the tertile of the time point's
  rank among the points after the baseline, so a response can be described by
  when it peaks without naming hours a run may not have sampled.

The baseline is the earliest time point; every fold change is against it.

The design table is the source of truth (its ``time_col``, hours). A run started
without one still gets a time course when its sample ids end in a duration
(``<anything>_30min``, ``<anything>_2h``, ``_1d``): :func:`parse_hours` reads
that suffix, and only that suffix. A sample with neither is left without a
time and drops out of the trajectories rather than being placed anywhere.
"""

from __future__ import annotations

import math
import re

import polars as pl

#: Trailing duration of a sample id or a time label: ``30min``, ``2h``, ``1.5 hr``,
#: ``3d``, ``45s``. Anchored at the end, after an underscore, dash, dot or
#: nothing, so ``GM_12h`` reads 12 and ``REP12`` reads nothing.
_DURATION_RE = re.compile(
    r"(?:^|[_\-.\s])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>s|sec|secs|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$",
    re.IGNORECASE,
)
_UNIT_HOURS = {"s": 1 / 3600, "m": 1 / 60, "h": 1.0, "d": 24.0}
#: Phase labels, earliest first.
PHASES = ("Early", "Mid", "Late")
#: Phase of the baseline time point itself.
BASELINE_PHASE = "Baseline"


def parse_hours(label: str | None) -> float | None:
    """Hours encoded in the trailing duration of ``label``, else ``None``."""
    if label is None:
        return None
    match = _DURATION_RE.search(str(label).strip())
    if not match:
        return None
    unit = match.group("unit").lower()
    key = "m" if unit.startswith("m") else unit[0]
    return float(match.group("value")) * _UNIT_HOURS[key]


def format_hours(hours: float | None) -> str | None:
    """A compact label for ``hours``: ``30min``, ``2h``, ``1.5h``."""
    if hours is None or math.isnan(hours):
        return None
    if 0 < hours < 1:
        return f"{hours * 60:g}min"
    return f"{hours:g}h"


def time_columns(frame: pl.DataFrame, hours_col: str = "time_h") -> pl.DataFrame:
    """Add ``time_order``, ``time_axis`` and ``phase`` from ``hours_col``.

    ``frame`` holds one row per sample (several samples may share a time
    point). Rows without hours get null in all three.
    """
    hours = pl.col(hours_col)
    points = (
        frame.select(pl.col(hours_col).cast(pl.Float64))
        .drop_nulls()
        .unique()
        .sort(hours_col)
        .get_column(hours_col)
        .to_list()
    )
    order = {h: i + 1 for i, h in enumerate(points)}
    after = points[1:]
    phase: dict[float, str] = {}
    if points:
        phase[points[0]] = BASELINE_PHASE
    for i, h in enumerate(after):
        phase[h] = PHASES[min(len(PHASES) - 1, (i * len(PHASES)) // max(1, len(after)))]
    return frame.with_columns(
        hours.cast(pl.Float64).alias(hours_col),
        hours.cast(pl.Float64)
        .replace_strict(order, default=None, return_dtype=pl.Int64)
        .alias("time_order"),
        (hours.cast(pl.Float64) + 1.0).log(2).alias("time_axis"),
        hours.cast(pl.Float64)
        .replace_strict(phase, default=None, return_dtype=pl.Utf8)
        .alias("phase"),
    )


def sample_times(
    samples: list[str],
    design: pl.DataFrame | None = None,
    time_col: str | None = "time_h",
) -> pl.DataFrame:
    """One row per sample: ``sample, time_point, time_h`` and the derived columns.

    ``design`` is keyed by ``sample``. Its ``time_col`` (hours) wins over the
    duration parsed from the sample id; its ``time_point`` label is kept when it
    has one, else the label is written from the hours.
    """
    ids = sorted({str(s) for s in samples if s is not None})
    base = pl.DataFrame(
        {"sample": ids, "_parsed": [parse_hours(s) for s in ids]},
        schema={"sample": pl.Utf8, "_parsed": pl.Float64},
    )
    design_hours = pl.lit(None, dtype=pl.Float64)
    design_label = pl.lit(None, dtype=pl.Utf8)
    if design is not None and not design.is_empty() and "sample" in design.columns:
        keep = {"sample": "sample"}
        if time_col and time_col != "sample" and time_col in design.columns:
            keep[time_col] = "_design_h"
        if "time_point" in design.columns:
            keep["time_point"] = "_design_label"
        picked = (
            design.select([pl.col(c).alias(a) for c, a in keep.items()])
            .with_columns(pl.col("sample").cast(pl.Utf8).str.strip_chars())
            .unique(subset="sample", keep="first")
        )
        base = base.join(picked, on="sample", how="left")
        if "_design_h" in base.columns:
            design_hours = pl.col("_design_h").cast(pl.Float64, strict=False)
        if "_design_label" in base.columns:
            design_label = pl.col("_design_label").cast(pl.Utf8)
    base = base.with_columns(
        pl.coalesce(design_hours, pl.col("_parsed")).alias("time_h"),
        design_label.alias("_label"),
    )
    labels = [
        label or format_hours(hours) or sample
        for sample, hours, label in zip(base["sample"], base["time_h"], base["_label"], strict=True)
    ]
    out = base.select("sample", "time_h").with_columns(
        pl.Series("time_point", labels, dtype=pl.Utf8)
    )
    return time_columns(out.select("sample", "time_point", "time_h"))


# ---------------------------------------------------------------------------
# Changes over time: one rule for genes and for genomic windows
# ---------------------------------------------------------------------------

#: log2 fold change against the baseline a time point needs to count as changed.
MIN_LOG2FC = 1.0
#: Changed time points (same direction) a feature needs to be called responsive.
#: A time course of nascent transcription is rarely replicated per time point, so
#: one time point alone is not evidence; two in the same direction are.
MIN_CHANGED_POINTS = 2
#: Direction labels.
UP, DOWN, FLAT = "Up", "Down", "Stable"

#: Columns of :func:`time_point_values`, besides the feature key.
TIME_POINT_COLUMNS = ("time_point", "time_h", "time_order", "time_axis", "phase")


def time_point_values(
    long: pl.DataFrame, times: pl.DataFrame, *, key: str, value_col: str
) -> pl.DataFrame:
    """Mean ``value_col`` per feature and time point, with its log2 fold change.

    ``long`` is one row per feature and sample; ``times`` the hub's per-sample
    time columns (``sample, time_point, time_h, time_order, time_axis, phase``).
    Samples without a time drop out. Libraries sharing a time point (replicates)
    are averaged. ``log2fc`` is the value minus the feature's value at the
    baseline (``time_order == 1``), so ``value_col`` must already be on a log2
    scale.
    """
    timed = long.join(times.filter(pl.col("time_order").is_not_null()), on="sample", how="inner")
    if timed.is_empty():
        raise ValueError("time_course: no sample has a time point")
    per_point = timed.group_by([key, *TIME_POINT_COLUMNS]).agg(
        pl.col(value_col).mean().alias("value")
    )
    baseline = per_point.filter(pl.col("time_order") == 1).select(
        key, pl.col("value").alias("baseline")
    )
    return (
        per_point.join(baseline, on=key, how="left")
        .with_columns((pl.col("value") - pl.col("baseline")).alias("log2fc"))
        .sort([key, "time_order"])
    )


def classify_changes(
    points: pl.DataFrame,
    *,
    key: str,
    min_log2fc: float = MIN_LOG2FC,
    min_points: int = MIN_CHANGED_POINTS,
) -> pl.DataFrame:
    """One row per feature: its peak change, when it peaks and its direction.

    ``points`` is :func:`time_point_values`. The peak is the time point after
    the baseline with the largest absolute fold change. ``direction`` is ``Up``
    or ``Down`` when the peak reaches ``min_log2fc`` and at least ``min_points``
    time points change by that much in the peak's direction (all of them on a
    run with fewer later time points), else ``Stable``.

    Columns: ``key, baseline, mean_value, dynamic_range, peak_log2fc,
    abs_peak_log2fc, peak_time_point, peak_time_h, peak_phase, last_log2fc,
    n_changed, direction``.
    """
    after = points.filter(pl.col("time_order") > 1)
    if after.is_empty():
        raise ValueError("time_course: a time course needs a time point after the baseline")
    # A run with fewer later time points than ``min_points`` asks for all of them.
    needed = min(min_points, after.get_column("time_order").n_unique())
    peak = (
        after.sort([key, pl.col("log2fc").abs()], descending=[False, True])
        .group_by(key, maintain_order=True)
        .first()
        .select(
            key,
            pl.col("log2fc").alias("peak_log2fc"),
            pl.col("time_point").alias("peak_time_point"),
            pl.col("time_h").alias("peak_time_h"),
            pl.col("phase").alias("peak_phase"),
        )
    )
    last = (
        after.sort([key, "time_order"])
        .group_by(key, maintain_order=True)
        .last()
        .select(key, pl.col("log2fc").alias("last_log2fc"))
    )
    spread = points.group_by(key).agg(
        pl.col("baseline").first(),
        pl.col("value").mean().alias("mean_value"),
        (pl.col("value").max() - pl.col("value").min()).alias("dynamic_range"),
    )
    joined = peak.join(after.select(key, "log2fc"), on=key).with_columns(
        (
            (pl.col("log2fc") * pl.col("peak_log2fc").sign() >= min_log2fc)
            & (pl.col("peak_log2fc").abs() >= min_log2fc)
        ).alias("_changed")
    )
    changed = joined.group_by(key).agg(pl.col("_changed").sum().cast(pl.Int64).alias("n_changed"))
    return (
        spread.join(peak, on=key)
        .join(last, on=key)
        .join(changed, on=key)
        .with_columns(
            pl.col("peak_log2fc").abs().alias("abs_peak_log2fc"),
            pl.when(pl.col("n_changed") >= needed)
            .then(pl.when(pl.col("peak_log2fc") > 0).then(pl.lit(UP)).otherwise(pl.lit(DOWN)))
            .otherwise(pl.lit(FLAT))
            .alias("direction"),
        )
        .sort(key)
    )


def spread_by_class(points: pl.DataFrame, *, class_col: str) -> pl.DataFrame:
    """Median and quartiles of ``log2fc`` per class and time point.

    The shape a ``profile`` tile draws as one curve per class with its
    interquartile band: ``class_col, time_point, time_h, time_order, time_axis,
    phase, median_log2fc, q1_log2fc, q3_log2fc, n_features``.
    """
    return (
        points.group_by([class_col, *TIME_POINT_COLUMNS])
        .agg(
            pl.col("log2fc").median().alias("median_log2fc"),
            pl.col("log2fc").quantile(0.25, interpolation="linear").alias("q1_log2fc"),
            pl.col("log2fc").quantile(0.75, interpolation="linear").alias("q3_log2fc"),
            pl.len().cast(pl.Int64).alias("n_features"),
        )
        .sort([class_col, "time_order"])
    )
