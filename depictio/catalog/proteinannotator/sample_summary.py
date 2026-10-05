"""The sample hub: one row per sample of the run, every per-sample number.

Built from the SeqFu statistics (``seqfu/stats``), which the pipeline writes for
every sample before and after its length and duplicate filter, and enriched
with the per-protein annotation summary (``proteinannotator/proteins``) when
it exists. ``sample_id`` is the samplesheet id, the key every other collection
links to.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="stats", dc_ref="seqfu_stats"),
    RecipeSource(ref="proteins", dc_ref="proteinannotator_proteins", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "input_sequences": pl.Int64,
    "kept_sequences": pl.Int64,
    "removed_sequences": pl.Int64,
    "kept_residues": pl.Int64,
    "mean_length": pl.Float64,
    "n50": pl.Int64,
    "min_length": pl.Int64,
    "max_length": pl.Int64,
    "annotated_proteins": pl.Int64,
    "annotated_protein_pct": pl.Float64,
    "domain_hits": pl.Int64,
    "median_annotated_pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Pivot the before / after statistics and add the annotation rates."""
    stats = sources["stats"]
    after = stats.filter(pl.col("stage") != "before").unique(subset="sample", keep="last")
    before = stats.filter(pl.col("stage") == "before").unique(subset="sample", keep="last")
    hub = after.select(
        pl.col("sample").alias("sample_id"),
        pl.col("sequences").alias("kept_sequences"),
        pl.col("total_length").alias("kept_residues"),
        "mean_length",
        "n50",
        "min_length",
        "max_length",
    ).join(
        before.select(
            pl.col("sample").alias("sample_id"), pl.col("sequences").alias("input_sequences")
        ),
        on="sample_id",
        how="left",
    )
    hub = hub.with_columns(
        pl.coalesce(pl.col("input_sequences"), pl.col("kept_sequences")).alias("input_sequences")
    ).with_columns(
        (pl.col("input_sequences") - pl.col("kept_sequences")).alias("removed_sequences")
    )

    proteins = sources.get("proteins")
    if proteins is not None and not proteins.is_empty():
        rates = proteins.group_by("sample").agg(
            (pl.col("domain_hits") > 0).sum().cast(pl.Int64).alias("annotated_proteins"),
            ((pl.col("domain_hits") > 0).mean() * 100.0).alias("annotated_protein_pct"),
            pl.col("domain_hits").sum().cast(pl.Int64).alias("domain_hits"),
            pl.col("annotated_pct").median().alias("median_annotated_pct"),
        )
        hub = hub.join(rates, left_on="sample_id", right_on="sample", how="left")
    else:
        hub = hub.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("annotated_proteins"),
            pl.lit(None, dtype=pl.Float64).alias("annotated_protein_pct"),
            pl.lit(None, dtype=pl.Int64).alias("domain_hits"),
            pl.lit(None, dtype=pl.Float64).alias("median_annotated_pct"),
        )
    return hub.select(list(EXPECTED_SCHEMA)).sort("sample_id")
