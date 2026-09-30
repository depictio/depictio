"""Per-feature differential test between two groups of observations.

The shape this serves is the one ``complex_heatmap`` already reads: a wide
frame whose rows are observations (a cell, a sample) named by ``index_col``
and whose other numeric columns are features (genes, taxa, metabolites). What
the ``group_compare`` visualisation adds is a comparison *between two subsets
of those rows*, picked in the dashboard rather than baked into the data:
either two saved selection groups (lasso on an embedding, ticked table rows)
or two values of a label column.

Kept out of ``celery_tasks.py`` on purpose. Everything below is a pure
function over a Polars frame, so the statistics can be unit-tested without a
broker, a Delta table or a Mongo connection; the Celery task is the thin
loader around it.

Directions are always "A relative to B": a positive ``log2fc`` means the
feature is higher in group A.
"""

from __future__ import annotations

import math
import time
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import polars as pl

# Added to both means before the ratio so a feature absent from one group
# yields a large but finite fold change instead of an infinity the volcano
# cannot place. Small against normalised counts, which is the scale this
# visualisation reads.
LOG2FC_PSEUDOCOUNT = 1.0

# Hard ceiling on what a single job may test, independent of the component's
# own ``max_features``. A wide frame with tens of thousands of columns would
# otherwise turn one click into a minutes-long worker task.
ABSOLUTE_MAX_FEATURES = 20_000

_TESTS = ("wilcoxon", "t_test")

#: How a boolean travels as text: Python's ``str(True)``, Polars' ``cast(Utf8)``
#: and a JSON ``1`` / ``0`` all have to land on the same flag.
_BOOL_WORDS = {"true": True, "1": True, "false": False, "0": False}


class GroupCompareError(ValueError):
    """A comparison that cannot be run, with a message meant for the reader."""


def selector_mask(df: pl.DataFrame, selector: Mapping[str, Any]) -> pl.Series:
    """Boolean mask of the rows a group selector picks out.

    A selector is ``{"label", "column", "values"}``: the column a saved
    selection group captured its values on, or the config's ``group_col`` with
    a single value. Matching is on the string form of the column, because the
    values a group captured travelled through JSON and localStorage and came
    back as strings whatever the frame's dtype is. A numeric or boolean column
    is matched on its own dtype as well: Polars spells ``1.0`` and ``true``
    where Python spells ``1`` and ``True``, so the string form alone misses
    every group captured on a Float64 or Boolean column.
    """
    column = str(selector.get("column") or "")
    if not column:
        raise GroupCompareError("group selector has no column")
    if column not in df.columns:
        raise GroupCompareError(f"column '{column}' is not in this data collection")
    values = [str(v) for v in (selector.get("values") or []) if v is not None]
    if not values:
        raise GroupCompareError(f"group '{selector.get('label') or column}' captured no values")
    col = pl.col(column)
    match = col.cast(pl.Utf8).is_in(values)
    dtype = df.schema[column]
    if dtype.is_numeric():
        numeric = pl.Series(values, dtype=pl.Utf8).cast(pl.Float64, strict=False).drop_nulls()
        if numeric.len():
            match = match | col.cast(pl.Float64, strict=False).is_in(numeric.to_list())
    elif dtype == pl.Boolean:
        flags = [_BOOL_WORDS[v.lower()] for v in values if v.lower() in _BOOL_WORDS]
        if flags:
            match = match | col.is_in(flags)
    return df.select(match).to_series().fill_null(False)


def resolve_feature_columns(
    df: pl.DataFrame,
    index_col: str,
    exclude: Iterable[str] = (),
) -> list[str]:
    """Numeric columns that are features, in frame order.

    Inferred rather than declared, exactly as ``complex_heatmap`` infers its
    matrix: naming 2000 gene columns in a dashboard YAML is not a thing anyone
    would maintain. Everything the comparison itself uses (the row id, the
    label column, the columns the two groups were selected on) is excluded, so
    a numeric grouping column can never be tested against itself.
    """
    skip = {index_col, *(c for c in exclude if c)}
    return [
        name
        for name, dtype in zip(df.columns, df.dtypes)
        if name not in skip and dtype.is_numeric()
    ]


def top_features_by_variance(df: pl.DataFrame, features: Sequence[str], cap: int) -> list[str]:
    """The ``cap`` most variable features, in frame order.

    Variance rather than mean: the point of the cap is to keep the features a
    comparison could possibly separate, and a column that never moves cannot
    separate anything. Ties and all-null columns fall to the end.
    """
    if cap <= 0 or len(features) <= cap:
        return list(features)
    variances = df.select([pl.col(c).cast(pl.Float64).var().alias(c) for c in features]).row(0)
    ranked = sorted(
        range(len(features)),
        key=lambda i: (-(variances[i] if variances[i] is not None else -1.0), i),
    )
    keep = {features[i] for i in ranked[:cap]}
    return [c for c in features if c in keep]


def benjamini_hochberg(p_values: Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values, monotone and clipped to 1."""
    p = np.asarray(p_values, dtype=float)
    if p.size == 0:
        return p
    p = np.where(np.isfinite(p), p, 1.0)
    n = p.size
    order = np.argsort(p, kind="stable")
    scaled = p[order] * n / (np.arange(n) + 1.0)
    # Enforce monotonicity from the largest p downwards, which is what stops a
    # mid-list feature from being reported as more significant than a smaller
    # raw p-value above it.
    scaled = np.minimum.accumulate(scaled[::-1])[::-1]
    out = np.empty(n, dtype=float)
    out[order] = np.clip(scaled, 0.0, 1.0)
    return out


def _feature_block(frame: pl.DataFrame, features: Sequence[str]) -> np.ndarray:
    """One group's observation-by-feature block, nulls read as zero.

    A null in a wide matrix of counts is an absence, not an unknown: the cell
    never expressed the gene, the sample never carried the taxon. Reading it as
    zero is what keeps a feature's two group means comparable.
    """
    return (
        frame.select([pl.col(c).cast(pl.Float64).fill_null(0.0) for c in features])
        .to_numpy()
        .astype(float)
    )


def _p_values(a: np.ndarray, b: np.ndarray, test: str) -> np.ndarray:
    """Column-wise p-values for two observation-by-feature blocks."""
    # Features with no spread anywhere carry no signal and make both tests
    # return NaN (Wilcoxon) or divide by zero (Welch). Scored as p = 1 rather
    # than dropped, so the feature list the reader sees still matches the
    # matrix they bound.
    constant = np.ptp(np.vstack([a, b]), axis=0) == 0

    if test == "t_test":
        from scipy.stats import ttest_ind

        result = ttest_ind(a, b, axis=0, equal_var=False)
    else:
        from scipy.stats import mannwhitneyu

        with np.errstate(invalid="ignore"):
            result = mannwhitneyu(a, b, axis=0, alternative="two-sided")

    p = np.atleast_1d(np.asarray(result.pvalue, dtype=float))
    p = np.where(np.isfinite(p), p, 1.0)
    p[constant] = 1.0
    return np.clip(p, 0.0, 1.0)


def group_compare_from_frame(
    df: pl.DataFrame,
    *,
    index_col: str,
    group_a: Mapping[str, Any],
    group_b: Mapping[str, Any],
    test: str = "wilcoxon",
    log_transform: bool = True,
    max_features: int = 2000,
    min_observations: int = 3,
    fdr_threshold: float = 0.05,
    log2fc_threshold: float = 1.0,
    top_n_labels: int = 20,
) -> dict[str, Any]:
    """Compare two row groups feature by feature.

    ``log_transform`` applies ``log1p`` before the test. It is a no-op for the
    Wilcoxon rank-sum test, which is rank-based and therefore invariant under
    any monotone transform; it is left available because it is what makes the
    Welch t-test usable on raw counts. The means and the fold change are always
    reported on the frame's own scale, so the table reads in the data's units
    whatever the test did.
    """
    started = time.monotonic()
    if test not in _TESTS:
        raise GroupCompareError(f"unknown test '{test}' (expected one of {', '.join(_TESTS)})")
    if index_col not in df.columns:
        raise GroupCompareError(f"index column '{index_col}' is not in this data collection")

    mask_a = selector_mask(df, group_a)
    mask_b = selector_mask(df, group_b)
    # An observation claimed by both selectors belongs to neither comparison
    # arm: keeping it would put the same rows on both sides of the test and
    # shrink every difference towards nothing, silently.
    in_both = mask_a & mask_b
    overlap = int(in_both.sum())
    if overlap:
        mask_a = mask_a & ~in_both
        mask_b = mask_b & ~in_both

    frame_a = df.filter(mask_a)
    frame_b = df.filter(mask_b)
    label_a = str(group_a.get("label") or "Group A")
    label_b = str(group_b.get("label") or "Group B")
    # The model's floor (``ge=2``), re-applied here because the endpoint takes
    # a plain dict: below two observations an arm has no spread to test, and a
    # ``min_observations: 0`` with an empty arm would otherwise return a result
    # full of nulls instead of the readable refusal below.
    min_observations = max(2, int(min_observations))
    if frame_a.height < min_observations or frame_b.height < min_observations:
        raise GroupCompareError(
            f"each group needs at least {min_observations} observations "
            f"({label_a}: {frame_a.height}, {label_b}: {frame_b.height})"
        )

    exclude = [str(group_a.get("column") or ""), str(group_b.get("column") or "")]
    features = resolve_feature_columns(df, index_col, exclude)
    if not features:
        raise GroupCompareError(
            "no numeric feature columns left after excluding the row id and the grouping columns"
        )
    total_features = len(features)
    cap = max(1, min(int(max_features), ABSOLUTE_MAX_FEATURES))
    selected = df.filter(mask_a | mask_b)
    features = top_features_by_variance(selected, features, cap)

    a = _feature_block(frame_a, features)
    b = _feature_block(frame_b, features)

    mean_a = a.mean(axis=0)
    mean_b = b.mean(axis=0)
    log2fc = np.log2((mean_a + LOG2FC_PSEUDOCOUNT) / (mean_b + LOG2FC_PSEUDOCOUNT))

    tested_a, tested_b = (
        (np.log1p(np.clip(a, 0, None)), np.log1p(np.clip(b, 0, None))) if log_transform else (a, b)
    )
    p = _p_values(tested_a, tested_b, test)
    fdr = benjamini_hochberg(p)

    significant = (fdr <= fdr_threshold) & (np.abs(log2fc) >= log2fc_threshold)
    order = np.lexsort((np.arange(len(features)), p))

    rows = [
        {
            "feature": features[i],
            "mean_a": _finite(mean_a[i]),
            "mean_b": _finite(mean_b[i]),
            "log2fc": _finite(log2fc[i]),
            "p_value": _finite(p[i]),
            "fdr": _finite(fdr[i]),
            "significant": bool(significant[i]),
            "direction": ("up" if log2fc[i] > 0 else "down") if significant[i] else "ns",
        }
        for i in order
    ]

    return {
        "rows": rows,
        "group_a": {"label": label_a, "n": int(frame_a.height)},
        "group_b": {"label": label_b, "n": int(frame_b.height)},
        "overlap_dropped": overlap,
        "feature_count": total_features,
        "tested_features": len(features),
        "significant_count": int(significant.sum()),
        "test": test,
        "log_transform": bool(log_transform),
        "fdr_threshold": float(fdr_threshold),
        "log2fc_threshold": float(log2fc_threshold),
        "top_n_labels": int(top_n_labels),
        "row_count": int(df.height),
        "compute_ms": int((time.monotonic() - started) * 1000),
    }


def _finite(value: Any) -> float | None:
    """JSON-safe float: NaN and infinities become null rather than invalid JSON."""
    out = float(value)
    return out if math.isfinite(out) else None
