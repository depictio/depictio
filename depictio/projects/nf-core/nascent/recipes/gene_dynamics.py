"""Per gene: how far its nascent transcription moves over the time course, and when.

nf-core/nascent counts reads over every gene body (``featureCounts``, catalog
``subread/gene_counts.py``). A run-on library measures transcription while it
happens, so a gene's count at a time point is its transcription rate then, not
an accumulated mRNA level: a time course of it shows a response within minutes.

For every gene detected (10 reads) in at least half of the libraries, on
``log2(cpm + 1)``, averaged over the libraries of each time point
(``depictio/recipes/lib/time_course.py``):

* ``log2fc`` at each time point against the baseline (the earliest);
* the peak: the time point after the baseline with the largest absolute change;
* ``direction``: ``Induced`` or ``Repressed`` when the peak reaches a log2 fold
  change of 1 and at least two time points change that much the same way,
  else ``Stable``. Two time points, because a time course is rarely replicated
  and one time point alone is not evidence;
* ``response``: the direction and the phase of the peak (``Induced early``,
  ``Repressed late``...), or ``Stable``. The phase is the tertile of the peak's
  rank among the later time points, so the classes hold for any sampling.

Sources:
    counts   ``subread_gene_counts`` (catalog ``subread/gene_counts.py``)
    samples  ``samples`` (the sample hub), for each library's time point

Output schema:
    gene_id, chromosome : Utf8, start, end, length : Int64, strand : Utf8
    baseline_log2_cpm, mean_log2_cpm, dynamic_range : Float64
    peak_log2fc, abs_peak_log2fc, last_log2fc : Float64
    peak_time_point : Utf8, peak_time_h : Float64, peak_phase : Utf8
    n_changed : Int64           time points changed by a log2 fold change of 1 in the peak's direction
    direction, response : Utf8
    rank : Int64                rank of the gene by absolute peak change, 1 the largest
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import time_course as tc
from depictio.recipes.lib.count_matrix import MIN_COUNTS

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        dc_ref="subread_gene_counts",
        input_schema={
            "gene_id": pl.Utf8,
            "chromosome": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "strand": pl.Utf8,
            "length": pl.Int64,
            "sample": pl.Utf8,
            "counts": pl.Int64,
            "log2_cpm": pl.Float64,
        },
    ),
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={
            "sample": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "phase": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "length": pl.Int64,
    "baseline_log2_cpm": pl.Float64,
    "mean_log2_cpm": pl.Float64,
    "dynamic_range": pl.Float64,
    "peak_log2fc": pl.Float64,
    "abs_peak_log2fc": pl.Float64,
    "last_log2fc": pl.Float64,
    "peak_time_point": pl.Utf8,
    "peak_time_h": pl.Float64,
    "peak_phase": pl.Utf8,
    "n_changed": pl.Int64,
    "direction": pl.Utf8,
    "response": pl.Utf8,
    "rank": pl.Int64,
}

#: Direction labels of a gene, by the sign of its peak change.
DIRECTION_LABELS = {tc.UP: "Induced", tc.DOWN: "Repressed", tc.FLAT: "Stable"}


def expressed_genes(counts: pl.DataFrame) -> pl.DataFrame:
    """Genes with ``MIN_COUNTS`` reads in at least half of the libraries."""
    n_libraries = counts.get_column("sample").n_unique()
    needed = max(1, -(-n_libraries // 2))
    return (
        counts.group_by("gene_id")
        .agg((pl.col("counts") >= MIN_COUNTS).sum().alias("_detected"))
        .filter(pl.col("_detected") >= needed)
        .select("gene_id")
    )


def gene_points(counts: pl.DataFrame, samples: pl.DataFrame) -> pl.DataFrame:
    """Per expressed gene and time point: mean log2 CPM and its log2 fold change."""
    kept = counts.join(expressed_genes(counts), on="gene_id")
    if kept.is_empty():
        raise ValueError("nascent gene_dynamics: no gene is detected in half of the libraries")
    times = samples.select("sample", *tc.TIME_POINT_COLUMNS)
    return tc.time_point_values(
        kept.select("gene_id", "sample", "log2_cpm"), times, key="gene_id", value_col="log2_cpm"
    )


def response_label(direction: pl.Expr, phase: pl.Expr) -> pl.Expr:
    """``Induced early`` ... ``Repressed late``, or ``Stable``."""
    return (
        pl.when(direction == "Stable")
        .then(pl.lit("Stable"))
        .otherwise(pl.concat_str([direction, pl.lit(" "), phase.str.to_lowercase()]))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    counts = sources["counts"]
    points = gene_points(counts, sources["samples"])
    calls = tc.classify_changes(points, key="gene_id")
    loci = counts.select("gene_id", "chromosome", "start", "end", "strand", "length").unique(
        subset="gene_id", keep="first"
    )
    direction = pl.col("direction").replace_strict(DIRECTION_LABELS, return_dtype=pl.Utf8)
    return (
        calls.join(loci, on="gene_id", how="left")
        .with_columns(direction.alias("direction"))
        .with_columns(
            response_label(pl.col("direction"), pl.col("peak_phase")).alias("response"),
            pl.col("baseline").alias("baseline_log2_cpm"),
            pl.col("mean_value").alias("mean_log2_cpm"),
            pl.col("abs_peak_log2fc")
            .rank(method="ordinal", descending=True)
            .cast(pl.Int64)
            .alias("rank"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort("rank")
    )
