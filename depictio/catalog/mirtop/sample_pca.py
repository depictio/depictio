"""Sample PCA on miRNA expression, one row per sample.

Principal components of the log2(CPM + 1) matrix restricted to the
``TOP_VARIABLE`` most variable miRNAs among those with a mean CPM of at least
``MIN_MEAN_CPM`` (low counts are dominated by sampling noise and would pull
the first components towards depth rather than biology). Centred, not scaled,
so a miRNA weighs by how much it actually varies, which is the usual choice for
log counts.

Each row also carries the sample's miRNA library size and the number of miRNAs
it detects, so a point that sits apart can be checked against depth before it
is read as biology, and the design columns when a design table was given.

Source: the ``mirtop_mirna_counts`` collection (``mirtop/mirna_counts.py``).

Output schema:
    sample : Utf8
    dim_1 : Float64            PC1
    dim_2 : Float64            PC2
    dim_3 : Float64            PC3 (null with fewer than three samples)
    mirna_reads : Int64        reads assigned to miRNAs
    mirnas_detected : Int64    miRNAs with at least one read
    <design columns> : Utf8
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.dimreduction import run_pca

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="counts", dc_ref="mirtop_mirna_counts"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_3": pl.Float64,
    "mirna_reads": pl.Int64,
    "mirnas_detected": pl.Int64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

TOP_VARIABLE = 500
MIN_MEAN_CPM = 10.0

_MEASURES = ("mirna", "reads", "cpm", "log2_cpm", "isomirs", "reference_pct")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """PCA of the top variable, expressed miRNAs."""
    counts = sources["counts"]
    design = [c for c in counts.columns if c not in _MEASURES and c != "sample"]
    stats = counts.group_by("mirna").agg(
        pl.col("cpm").mean().alias("_mean"), pl.col("log2_cpm").var().alias("_var")
    )
    keep = (
        stats.filter((pl.col("_mean") >= MIN_MEAN_CPM) & pl.col("_var").is_not_null())
        .sort(["_var", "mirna"], descending=[True, False])
        .head(TOP_VARIABLE)["mirna"]
        .to_list()
    )
    if len(keep) < 2:
        keep = stats.sort("_mean", descending=True).head(TOP_VARIABLE)["mirna"].to_list()
    wide = (
        counts.filter(pl.col("mirna").is_in(keep))
        .pivot(on="mirna", index="sample", values="log2_cpm")
        .fill_null(0.0)
        .sort("sample")
    )
    coords = run_pca(wide, n_components=min(3, wide.height, wide.width - 1), scale=False)
    coords = coords.rename({"sample_id": "sample"})
    for dim in ("dim_1", "dim_2", "dim_3"):
        if dim not in coords.columns:
            coords = coords.with_columns(pl.lit(None, dtype=pl.Float64).alias(dim))

    per_sample = counts.group_by("sample").agg(
        pl.col("reads").sum().cast(pl.Int64).alias("mirna_reads"),
        (pl.col("reads") > 0).sum().cast(pl.Int64).alias("mirnas_detected"),
    )
    out = coords.join(per_sample, on="sample", how="left").select(list(EXPECTED_SCHEMA))
    if design:
        out = out.join(counts.select("sample", *design).unique(subset="sample"), on="sample")
    return out.sort("sample")
