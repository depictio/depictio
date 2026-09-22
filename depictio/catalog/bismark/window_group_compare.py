"""Window-by-window methylation comparison between the run's two groups.

nf-core/methylseq ships no differential-methylation caller at any version, so a
cohort that was sequenced to compare two conditions arrives with no answer to
the question it was run for. This recipe is the honest screen that the published
files do support: every window of ``bismark_binned_methylation`` tested between
the two levels of the run's design factor, corrected for multiplicity, and
handed to a volcano and a Manhattan.

What it is, precisely, so nobody reads more into it than it holds:

* the unit is a ``BIN_SIZE`` window, not a CpG and not a called DMR. A window
  that comes out significant is a region worth looking at, not a region a caller
  has delimited;
* the test is a pooled two-sample t-test on the **arcsine square-root
  transform** of the window's methylation proportion. Methylation is a
  proportion bounded at 0 and 1 whose variance collapses at both ends; the
  arcsine transform is the classical variance-stabilising map for exactly that,
  and it is what keeps a window at 97 % from being called significant just for
  being near the ceiling. The effect size reported back is the untransformed
  difference in percentage points, because that is the quantity a reader can
  judge;
* the weights are absent. Without per-CpG coverage counts (Bismark writes them
  to ``methylation_coverage/*.cov.gz``, which this megatest does not publish) a
  beta-binomial model has nothing to be binomial about, so each window
  contributes its mean and the test is on library-level replication alone. With
  three versus four libraries that is a low-powered screen, and it is labelled
  as one;
* multiplicity is handled with Benjamini-Hochberg over all tested windows.

The t distribution's tail is evaluated here rather than through SciPy: the
degrees of freedom are the same for every window, so the two-sided p-value is
one regularised incomplete beta with scalar parameters, and a recipe that
imports SciPy would fail in the slim CLI environment, which ships numpy and
polars only.

Output schema:
    window_id : Utf8            ``chr1:10000-20000``
    chromosome : Utf8           contig, the Manhattan's x grouping
    position : Int64            window centre, the Manhattan's x
    start : Int64               window start
    end : Int64                 window end
    group_a : Utf8              level whose methylation is the reference
    group_b : Utf8              the other level
    mean_a : Float64            mean % methylation of group_a's libraries
    mean_b : Float64            mean % methylation of group_b's libraries
    delta_methylation : Float64 mean_a - mean_b, in percentage points
    t_statistic : Float64       pooled t on the arcsine-transformed proportions
    p_value : Float64           two-sided p
    padj : Float64              Benjamini-Hochberg adjusted p
    neg_log10_padj : Float64    -log10(padj), the Manhattan's y
    direction : Utf8            Hypermethylated / Hypomethylated / Not significant
    n_cpg_min : Int64           CpGs behind the thinnest library's window mean
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.genomic_bins import window_id_expr

MATRIX_DC_TAG = "bismark_binned_methylation"
SAMPLES_DC_TAG = "samples"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="windows", dc_ref=MATRIX_DC_TAG),
    RecipeSource(ref="samples", dc_ref=SAMPLES_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "window_id": pl.Utf8,
    "chromosome": pl.Utf8,
    "position": pl.Int64,
    "start": pl.Int64,
    "end": pl.Int64,
    "group_a": pl.Utf8,
    "group_b": pl.Utf8,
    "mean_a": pl.Float64,
    "mean_b": pl.Float64,
    "delta_methylation": pl.Float64,
    "t_statistic": pl.Float64,
    "p_value": pl.Float64,
    "padj": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "direction": pl.Utf8,
    "n_cpg_min": pl.Int64,
}

#: Sample-hub columns that may carry the design, most explicit first. The first
#: one with exactly two levels across the run's libraries is the factor tested:
#: a two-group comparison needs a two-level factor, and `group` exists so a
#: template can say which factor that is instead of leaving it to be guessed.
GROUP_COLUMN_CANDIDATES = ("group", "cell_line", "treatment", "condition")

#: Adjusted-p cut-off used to label `direction`. The volcano's own threshold is
#: a display control; this is the label the cards and the donut count.
PADJ_THRESHOLD = 0.05
#: Difference in percentage points a window must also clear to be labelled. A
#: statistically clean 2-point shift is not a methylation difference anyone acts
#: on, and calling it one is how a screen turns into noise.
MIN_DELTA_PCT = 10.0
#: Floor on the adjusted p before the -log10, so a window that underflows to
#: zero plots at the top of the Manhattan instead of at infinity.
MIN_PADJ = 1e-300


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _beta_continued_fraction(
    a: float, b: float, x: np.ndarray, iterations: int = 300, eps: float = 3e-14
) -> np.ndarray:
    """Lentz evaluation of the continued fraction for the incomplete beta.

    Vectorised over ``x`` (one entry per window); ``a`` and ``b`` are scalars,
    which is what lets a single fraction serve every window.
    """
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = np.ones_like(x)
    d = 1.0 - qab * x / qap
    d = np.where(np.abs(d) < tiny, tiny, d)
    d = 1.0 / d
    h = d.copy()
    for m in range(1, iterations + 1):
        m2 = 2 * m
        for numerator in (
            m * (b - m) * x / ((qam + m2) * (a + m2)),
            -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2)),
        ):
            d = 1.0 + numerator * d
            d = np.where(np.abs(d) < tiny, tiny, d)
            d = 1.0 / d
            c = 1.0 + numerator / c
            c = np.where(np.abs(c) < tiny, tiny, c)
            delta = d * c
            h = h * delta
        if np.all(np.abs(delta - 1.0) < eps):
            break
    return h


def _regularised_incomplete_beta(a: float, b: float, x: np.ndarray) -> np.ndarray:
    """``I_x(a, b)`` for scalar ``a``, ``b`` and an array of ``x`` in [0, 1]."""
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    interior = (x > 0.0) & (x < 1.0)
    out = np.where(x <= 0.0, 0.0, 1.0)
    if not np.any(interior):
        return out

    xi = x[interior]
    front = np.exp(a * np.log(xi) + b * np.log1p(-xi) - _log_beta(a, b))
    take_direct = xi < (a + 1.0) / (a + b + 2.0)
    values = np.empty_like(xi)
    if np.any(take_direct):
        values[take_direct] = (
            front[take_direct] * _beta_continued_fraction(a, b, xi[take_direct]) / a
        )
    flipped = ~take_direct
    if np.any(flipped):
        values[flipped] = (
            1.0 - front[flipped] * _beta_continued_fraction(b, a, 1.0 - xi[flipped]) / b
        )
    out[interior] = np.clip(values, 0.0, 1.0)
    return out


def two_sided_t_p_value(t: np.ndarray, df: int) -> np.ndarray:
    """Two-sided p of Student's t with ``df`` degrees of freedom."""
    t = np.asarray(t, dtype=np.float64)
    finite = np.isfinite(t)
    x = np.ones_like(t)
    np.divide(df, df + np.square(t), out=x, where=finite)
    p = _regularised_incomplete_beta(df / 2.0, 0.5, x)
    return np.where(finite, p, 1.0)


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """BH-adjusted p-values, in the input order."""
    p_values = np.asarray(p_values, dtype=np.float64)
    n = p_values.size
    order = np.argsort(p_values)
    ranked = p_values[order] * n / np.arange(1, n + 1)
    monotone = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(n, dtype=np.float64)
    adjusted[order] = np.clip(monotone, 0.0, 1.0)
    return adjusted


def _group_assignment(samples: pl.DataFrame, libraries: list[str]) -> tuple[str, dict[str, str]]:
    """The design column with exactly two levels, and each library's level."""
    if samples is None or samples.is_empty() or "sample_id" not in samples.columns:
        raise ValueError(
            "bismark_window_group_compare: the 'samples' hub is missing or has no "
            "'sample_id' column, so the run has no design to compare along"
        )
    present = samples.filter(pl.col("sample_id").is_in(libraries))
    for column in GROUP_COLUMN_CANDIDATES:
        if column not in present.columns:
            continue
        levels = present.get_column(column).drop_nulls().unique().sort().to_list()
        if len(levels) == 2:
            mapping = dict(
                zip(
                    present.get_column("sample_id").to_list(),
                    present.get_column(column).to_list(),
                    strict=True,
                )
            )
            return column, {k: v for k, v in mapping.items() if v is not None}
    raise ValueError(
        "bismark_window_group_compare: none of the sample-hub columns "
        f"{list(GROUP_COLUMN_CANDIDATES)} has exactly two levels across the run's "
        "libraries, so there is no two-group comparison to run"
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Test every window between the design's two levels, BH-correct, label."""
    windows = sources["windows"]
    required = {"sample", "chromosome", "start", "end", "methylation_pct", "n_cpg"}
    missing = required - set(windows.columns)
    if missing:
        raise ValueError(
            f"bismark_window_group_compare: '{MATRIX_DC_TAG}' lacks {sorted(missing)}, "
            f"got {windows.columns}"
        )

    libraries = windows.get_column("sample").unique().sort().to_list()
    _, assignment = _group_assignment(sources["samples"], libraries)
    levels = sorted({level for library, level in assignment.items() if library in libraries})
    if len(levels) != 2:
        raise ValueError(
            f"bismark_window_group_compare: the design factor covers {levels} among the "
            "libraries that reached the window matrix; two levels are needed"
        )
    group_a, group_b = levels
    members_a = [s for s in libraries if assignment.get(s) == group_a]
    members_b = [s for s in libraries if assignment.get(s) == group_b]
    if len(members_a) < 2 or len(members_b) < 2:
        raise ValueError(
            f"bismark_window_group_compare: '{group_a}' has {len(members_a)} libraries and "
            f"'{group_b}' has {len(members_b)}; a t-test needs at least two on each side"
        )

    labelled = windows.with_columns(window_id_expr())
    coordinates = (
        labelled.group_by("window_id")
        .agg(
            pl.col("chromosome").first(),
            pl.col("start").first(),
            pl.col("end").first(),
            pl.col("n_cpg").min().alias("n_cpg_min"),
        )
        .sort("window_id")
    )
    wide = (
        labelled.pivot(on="sample", index="window_id", values="methylation_pct")
        .sort("window_id")
        .join(coordinates, on="window_id", how="inner")
        .sort("window_id")
    )

    percent_a = wide.select(members_a).to_numpy().astype(np.float64)
    percent_b = wide.select(members_b).to_numpy().astype(np.float64)
    # Arcsine square-root of the proportion: the variance-stabilising transform
    # for a bounded proportion, applied before the test and nowhere else, so the
    # effect size the reader sees stays in percentage points.
    transformed_a = np.arcsin(np.sqrt(np.clip(percent_a / 100.0, 0.0, 1.0)))
    transformed_b = np.arcsin(np.sqrt(np.clip(percent_b / 100.0, 0.0, 1.0)))

    n_a, n_b = len(members_a), len(members_b)
    df = n_a + n_b - 2
    variance_pooled = (
        (n_a - 1) * transformed_a.var(axis=1, ddof=1)
        + (n_b - 1) * transformed_b.var(axis=1, ddof=1)
    ) / df
    standard_error = np.sqrt(variance_pooled * (1.0 / n_a + 1.0 / n_b))
    difference = transformed_a.mean(axis=1) - transformed_b.mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        t_statistic = np.where(standard_error > 0.0, difference / standard_error, 0.0)
    t_statistic = np.nan_to_num(t_statistic, nan=0.0, posinf=0.0, neginf=0.0)

    p_value = two_sided_t_p_value(t_statistic, df)
    padj = benjamini_hochberg(p_value)
    mean_a = percent_a.mean(axis=1)
    mean_b = percent_b.mean(axis=1)
    delta = mean_a - mean_b

    return (
        wide.select("window_id", "chromosome", "start", "end", "n_cpg_min")
        .with_columns(
            pl.lit(group_a, pl.Utf8).alias("group_a"),
            pl.lit(group_b, pl.Utf8).alias("group_b"),
            pl.Series("mean_a", mean_a, pl.Float64),
            pl.Series("mean_b", mean_b, pl.Float64),
            pl.Series("delta_methylation", delta, pl.Float64),
            pl.Series("t_statistic", t_statistic, pl.Float64),
            pl.Series("p_value", p_value, pl.Float64),
            pl.Series("padj", padj, pl.Float64),
        )
        .with_columns(
            ((pl.col("start") + pl.col("end")) // 2).cast(pl.Int64).alias("position"),
            (-pl.col("padj").clip(MIN_PADJ, 1.0).log10()).cast(pl.Float64).alias("neg_log10_padj"),
            pl.when(
                (pl.col("padj") >= PADJ_THRESHOLD)
                | (pl.col("delta_methylation").abs() < MIN_DELTA_PCT)
            )
            .then(pl.lit("Not significant"))
            .when(pl.col("delta_methylation") > 0)
            .then(pl.lit("Hypermethylated"))
            .otherwise(pl.lit("Hypomethylated"))
            .cast(pl.Utf8)
            .alias("direction"),
        )
        .select(list(EXPECTED_SCHEMA))
        # Ties on padj are common (BH assigns one value to a run of p-values),
        # so the genomic position keeps the order stable between runs.
        .sort(["padj", "chromosome", "start"])
    )
