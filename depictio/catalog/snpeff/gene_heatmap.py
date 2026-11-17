"""Gene by callset burden matrix, for a clustered heatmap.

Rows are the genes carrying the most coding variants across the run, columns
are one per callset (sample and caller), cells are that gene's total variant
count. Clustering the columns is the quickest read of whether the callers
differ more from each other than the depths do.

Each column also carries its caller and its sample, serialised into
`_col_annotations_json` (the contract the other heatmap recipes use), so the
heatmap draws them as strips above the columns. They are named `caller` and
`sample_id` on purpose: a dashboard that pins colours on those columns paints
the strips with them, and a caller or a sample keeps its colour across tiles.
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="genes",
        dc_ref="snpeff_genes",
        input_schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "gene_name": pl.Utf8,
            "n_coding": pl.Int64,
            "n_variants": pl.Int64,
        },
    )
]

#: A clustered heatmap stops being readable well before a hundred rows.
TOP_GENES = 40

_ANNOTATIONS_COL = "_col_annotations_json"

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {"gene_name": pl.Utf8}
# One numeric column per callset, known only at ingest.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot the busiest genes into a gene by callset matrix of variant counts."""
    genes = sources["genes"].with_columns(
        pl.concat_str([pl.col("sample"), pl.col("caller")], separator=" / ").alias("callset")
    )
    callsets = genes.select("callset", "sample", "caller").unique(subset=["callset"])
    owner = {r["callset"]: r for r in callsets.iter_rows(named=True)}

    top = (
        genes.group_by("gene_name")
        .agg(pl.col("n_coding").sum().alias("total_coding"))
        .sort(["total_coding", "gene_name"], descending=[True, False])
        .head(TOP_GENES)
        .select("gene_name")
    )

    wide = (
        genes.join(top, on="gene_name", how="inner")
        .group_by(["gene_name", "callset"])
        .agg(pl.col("n_variants").sum().cast(pl.Float64).alias("burden"))
        .pivot(values="burden", index="gene_name", on="callset", aggregate_function="sum")
    )
    # A pivot's column order follows the group_by order, which is not stable
    # between runs; sorted so the Delta schema and the fixture never churn.
    value_cols = sorted(c for c in wide.columns if c != "gene_name")
    result = wide.select(
        "gene_name", *[pl.col(c).fill_null(0.0).cast(pl.Float64) for c in value_cols]
    ).sort("gene_name")
    # Positional against the value columns, as the heatmap reads them.
    strips = {
        name: {"values": [str(owner[c][field]) for c in value_cols], "type": "categorical"}
        for name, field in (("caller", "caller"), ("sample_id", "sample"))
    }
    return result.with_columns(pl.lit(json.dumps(strips)).alias(_ANNOTATIONS_COL))
