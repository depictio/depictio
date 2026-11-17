"""Box statistics of the most stable genes of every section of nf-core/stableexpression.

One row per gene for the best-ranked candidates of each expression section
(``top_per_section``, 25 by default, as many as the pipeline's MultiQC report
draws per section): its stability score and ranks, and the Tukey box statistics
of its normalised expression over every sample that measured it (quartiles,
whisker ends at the furthest value within 1.5 IQR, mean, standard deviation,
minimum, maximum), with how many samples that is.

The values come from ``merged_data/all_counts.parquet``, the merged matrix
before imputation, so a box is drawn from measured values only; the pipeline's
own report and Dash app draw the imputed matrix, which fills the samples a
platform never measured. Point the ``counts`` source at
``merged_data/all_counts.imputed.parquet`` to draw those instead.

A cohort holds thousands of samples, so the boxes are computed here rather
than shipped as raw values: 250 rows instead of a million.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import (
    TEXT_READ_KWARGS,
    box_stats,
    candidates_with_parts,
    gene_rows,
)

DEFAULT_TOP_PER_SECTION = 25

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="reporting/all_genes_summary.csv",
        format="csv",
        read_kwargs=TEXT_READ_KWARGS,
        input_schema={
            "gene_id": pl.Utf8,
            "section": pl.Utf8,
            "stability_score": pl.Utf8,
            "rank": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="counts",
        path="merged_data/all_counts.parquet",
        format="parquet",
        input_schema={"gene_id": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "section": pl.Utf8,
    "section_index": pl.Int64,
    "section_rank": pl.Int64,
    "overall_rank": pl.Int64,
    "stability_score": pl.Float64,
    "q1": pl.Float64,
    "median": pl.Float64,
    "q3": pl.Float64,
    "lower": pl.Float64,
    "upper": pl.Float64,
    "mean": pl.Float64,
    "sd": pl.Float64,
    "min": pl.Float64,
    "max": pl.Float64,
    "n_measured": pl.Int64,
    "n_samples": pl.Int64,
    "measured_share": pl.Float64,
    "expression_level": pl.Utf8,
}

_STATS = ("q1", "median", "q3", "lower", "upper", "mean", "sd", "min", "max")


def _top_per_section(params: dict[str, str] | None) -> int:
    try:
        value = int(str((params or {}).get("top_per_section", DEFAULT_TOP_PER_SECTION)))
    except ValueError:
        return DEFAULT_TOP_PER_SECTION
    return max(1, value)


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    n_top = _top_per_section(params)
    genes = candidates_with_parts(sources["summary"]).filter(pl.col("section_rank") <= n_top)
    counts = sources["counts"]
    sample_cols = [c for c in counts.columns if c != "gene_id"]
    rows = gene_rows(counts, genes.get_column("gene_id").to_list())
    if rows.is_empty():
        raise ValueError("none of the candidate genes is in the count matrix")
    matrix = rows.select(pl.col(sample_cols).cast(pl.Float64)).to_numpy()
    records = []
    for gene_id, values in zip(rows.get_column("gene_id").to_list(), matrix, strict=True):
        stats = box_stats(np.asarray(values, dtype=float))
        records.append(
            {"gene_id": gene_id, **{k: stats[k] for k in _STATS}, "n_measured": stats["n"]}
        )
    box = pl.DataFrame(
        records,
        schema={"gene_id": pl.Utf8, **{k: pl.Float64 for k in _STATS}, "n_measured": pl.Int64},
    )
    out = genes.drop("median", "mean", "measured_share").join(box, on="gene_id", how="inner")
    return (
        out.with_columns(
            pl.lit(len(sample_cols), dtype=pl.Int64).alias("n_samples"),
            (pl.col("n_measured") / len(sample_cols)).round(4).alias("measured_share"),
            *[pl.col(k).round(6) for k in _STATS],
        )
        .select(list(OUTPUT_SCHEMA))
        .sort("section_index", "section_rank")
    )
