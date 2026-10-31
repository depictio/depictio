"""The most dynamic genes as a gene x time point matrix, for a heatmap.

The ``TOP_N`` responsive genes with the largest absolute peak change (the same
ranking and expression floor as ``top_gene_trajectories``, over more genes), one
row each, one column per time point in time order, holding the gene's mean
``log2(cpm + 1)`` there. The tile z-scores each row, so a row reads as when the
gene is high and low rather than how high it is; ``response`` rides along as the
row annotation, and the columns keep their time order (the tile does not
cluster them).

Columns are named by the time point labels (``0h``, ``30min`` ...), the axis a
reader reads, rather than by library: libraries sharing a time point are
averaged.

Sources:
    trajectories  ``gene_trajectories``
    dynamics      ``gene_dynamics``

Output schema:
    gene_id : Utf8
    response : Utf8
    <time_point> : Float64   one column per time point, in time order
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
            "time_order": pl.Int64,
            "log2_cpm": pl.Float64,
        },
    ),
    RecipeSource(
        ref="dynamics",
        dc_ref="gene_dynamics",
        input_schema={
            "gene_id": pl.Utf8,
            "direction": pl.Utf8,
            "response": pl.Utf8,
            "abs_peak_log2fc": pl.Float64,
            "baseline_log2_cpm": pl.Float64,
            "peak_log2fc": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it. The time
# point columns are the run's own.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "response": pl.Utf8,
}

#: Rows of the heatmap. Forty gene names still read on the row axis.
TOP_N = 40
#: log2(cpm + 1) the gene must reach at its baseline or at its peak.
MIN_LOG2_CPM = 3.0


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    dynamics = sources["dynamics"]
    peak_level = pl.col("baseline_log2_cpm") + pl.col("peak_log2fc")
    top = (
        dynamics.filter(
            (pl.col("direction") != "Stable")
            & ((pl.col("baseline_log2_cpm") >= MIN_LOG2_CPM) | (peak_level >= MIN_LOG2_CPM))
        )
        .sort(["abs_peak_log2fc", "gene_id"], descending=[True, False])
        .head(TOP_N)
        .select("gene_id", "response")
    )
    if top.is_empty():
        raise ValueError("nascent top_gene_heatmap: no responsive gene on this run")
    long = sources["trajectories"].join(top.select("gene_id"), on="gene_id", how="inner")
    order = (
        long.select("time_point", "time_order")
        .unique()
        .sort("time_order")
        .get_column("time_point")
        .to_list()
    )
    wide = long.pivot(
        on="time_point", index="gene_id", values="log2_cpm", aggregate_function="first"
    )
    return top.join(wide, on="gene_id", how="left").select(
        "gene_id", "response", *[pl.col(t).cast(pl.Float64) for t in order]
    )
