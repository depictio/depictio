"""The trajectories of the genes that move most, one curve per gene.

The response classes say what a typical gene of each class does; these are the
genes a reader names next. The ``TOP_N`` responsive genes (direction not
``Stable``) with the largest absolute peak change, among those transcribed at a
usable level at their peak or at the baseline (``MIN_LOG2_CPM``, about 7 counts
per million), so a gene going from 0 to 3 reads does not top the list.

Sources:
    trajectories  ``gene_trajectories``
    dynamics      ``gene_dynamics``

Output schema:
    gene_id, time_point : Utf8
    time_h : Float64, time_order : Int64, time_axis : Float64
    log2_cpm, log2fc : Float64
    response : Utf8
    rank : Int64        rank of the gene among the top genes, 1 the largest change
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="trajectories",
        dc_ref="gene_trajectories",
        input_schema={
            "gene_id": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "log2_cpm": pl.Float64,
            "log2fc": pl.Float64,
            "response": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="dynamics",
        dc_ref="gene_dynamics",
        input_schema={
            "gene_id": pl.Utf8,
            "direction": pl.Utf8,
            "abs_peak_log2fc": pl.Float64,
            "baseline_log2_cpm": pl.Float64,
            "peak_log2fc": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "log2_cpm": pl.Float64,
    "log2fc": pl.Float64,
    "response": pl.Utf8,
    "rank": pl.Int64,
}

#: Genes drawn. Ten curves still read one by one with a legend under the plot.
TOP_N = 10
#: log2(cpm + 1) the gene must reach at its baseline or at its peak.
MIN_LOG2_CPM = 3.0


def top_genes(dynamics: pl.DataFrame, top_n: int = TOP_N) -> pl.DataFrame:
    """``gene_id, rank`` of the ``top_n`` responsive genes by absolute peak change."""
    peak_level = pl.col("baseline_log2_cpm") + pl.col("peak_log2fc")
    return (
        dynamics.filter(
            (pl.col("direction") != "Stable")
            & ((pl.col("baseline_log2_cpm") >= MIN_LOG2_CPM) | (peak_level >= MIN_LOG2_CPM))
        )
        .sort(["abs_peak_log2fc", "gene_id"], descending=[True, False])
        .head(top_n)
        .select("gene_id")
        .with_row_index("rank", offset=1)
        .select("gene_id", pl.col("rank").cast(pl.Int64))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    top = top_genes(sources["dynamics"])
    if top.is_empty():
        raise ValueError("nascent top_gene_trajectories: no responsive gene on this run")
    return (
        sources["trajectories"]
        .join(top, on="gene_id", how="inner")
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["rank", "time_order"])
    )
