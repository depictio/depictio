"""The nf-core/smrnaseq sample hub: one row per sample, every per-sample number.

Every tab of the template filters through this table, so it has to exist on
every run, with or without a design table. It is built from what the pipeline
always writes (the mirtop miRNA counts) and enriched with what it may write:
the miRTrace composition (absent when MultiQC was skipped) and the miRDeep2
predictions (absent with ``--skip_mirdeep``). A missing source leaves its
columns null rather than failing the collection.

The design columns come from the counts collection, which joined the design
table when the run declared one, so the hub carries the run's factors under
their own names and the dashboard's ``{GROUP_COL}`` resolves against them.

Sources:
    counts       ``mirtop_mirna_counts`` (catalog ``mirtop/mirna_counts.py``)
    composition  ``mirtrace_composition`` (catalog ``multiqc/mirtrace_composition.py``), optional
    predictions  ``mirdeep2_predictions`` (catalog ``mirdeep2/predictions.py``), optional

Output schema:
    sample : Utf8
    mirna_reads : Int64          reads assigned to miRNAs by mirtop
    mirnas_detected : Int64      miRNAs with at least one read
    mirnas_10cpm : Int64         miRNAs at 10 CPM or more
    reference_isoform_pct : Float64  miRNA reads matching the reference sequence exactly, %
    mirna_pct : Float64          miRTrace: reads classified as miRNA, %
    rrna_pct : Float64           miRTrace: rRNA, %
    trna_pct : Float64           miRTrace: tRNA, %
    artifact_pct : Float64       miRTrace: artifact, %
    unknown_pct : Float64        miRTrace: unknown, %
    top_clade : Utf8             miRTrace: clade holding most detected miRNAs
    top_clade_pct : Float64      its share of the detected miRNAs, %
    novel_candidates : Int64     miRDeep2 novel precursor calls
    known_recovered : Int64      miRBase precursors miRDeep2 re-discovered
    <design columns> : Utf8
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="counts", dc_ref="mirtop_mirna_counts"),
    RecipeSource(ref="composition", dc_ref="mirtrace_composition", optional=True),
    RecipeSource(ref="predictions", dc_ref="mirdeep2_predictions", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "mirna_reads": pl.Int64,
    "mirnas_detected": pl.Int64,
    "mirnas_10cpm": pl.Int64,
    "reference_isoform_pct": pl.Float64,
    "mirna_pct": pl.Float64,
    "rrna_pct": pl.Float64,
    "trna_pct": pl.Float64,
    "artifact_pct": pl.Float64,
    "unknown_pct": pl.Float64,
    "top_clade": pl.Utf8,
    "top_clade_pct": pl.Float64,
    "novel_candidates": pl.Int64,
    "known_recovered": pl.Int64,
}
# Design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_MEASURES = ("mirna", "reads", "cpm", "log2_cpm", "isomirs", "reference_pct")
_RNA_TYPES = {
    "miRNA": "mirna_pct",
    "rRNA": "rrna_pct",
    "tRNA": "trna_pct",
    "Artifact": "artifact_pct",
    "Unknown": "unknown_pct",
}


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per sample of the counts, enriched when the optional sources exist."""
    counts = sources["counts"]
    design = [c for c in counts.columns if c not in _MEASURES and c != "sample"]
    ref_reads = pl.col("reference_pct").fill_null(0.0) * pl.col("reads") / 100.0
    hub = counts.group_by("sample").agg(
        pl.col("reads").sum().cast(pl.Int64).alias("mirna_reads"),
        (pl.col("reads") > 0).sum().cast(pl.Int64).alias("mirnas_detected"),
        (pl.col("cpm") >= 10.0).sum().cast(pl.Int64).alias("mirnas_10cpm"),
        ref_reads.sum().alias("_ref"),
    )
    hub = hub.with_columns(
        pl.when(pl.col("mirna_reads") > 0)
        .then(pl.col("_ref") * 100.0 / pl.col("mirna_reads"))
        .otherwise(None)
        .alias("reference_isoform_pct")
    ).drop("_ref")

    composition = sources.get("composition")
    if composition is not None and not composition.is_empty():
        types = (
            composition.filter(
                (pl.col("rank") == "RNA type") & pl.col("taxon").is_in(list(_RNA_TYPES))
            )
            .with_columns(pl.col("taxon").replace_strict(_RNA_TYPES).alias("_col"))
            .pivot(on="_col", index="sample", values="percent")
        )
        hub = hub.join(types, on="sample", how="left")
        clades = (
            composition.filter(pl.col("rank") == "Clade")
            .sort("abundance", descending=True)
            .group_by("sample", maintain_order=True)
            .first()
            .select(
                "sample",
                pl.col("taxon").alias("top_clade"),
                pl.col("percent").alias("top_clade_pct"),
            )
        )
        hub = hub.join(clades, on="sample", how="left")

    predictions = sources.get("predictions")
    if predictions is not None and not predictions.is_empty():
        calls = predictions.group_by("sample").agg(
            (pl.col("category") == "novel").sum().cast(pl.Int64).alias("novel_candidates"),
            (pl.col("category") == "known").sum().cast(pl.Int64).alias("known_recovered"),
        )
        hub = hub.join(calls, on="sample", how="left")

    hub = hub.with_columns(
        [pl.lit(None, dtype=t).alias(c) for c, t in EXPECTED_SCHEMA.items() if c not in hub.columns]
    ).with_columns([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()])
    out = hub.select(list(EXPECTED_SCHEMA))
    if design:
        out = out.join(
            counts.select("sample", *design).unique(subset="sample"), on="sample", how="left"
        )
    return out.sort("sample")
