"""Editing outcome per guide, one row per protospacer.

Joins the per-library edit summary (``crisprseq_edit_summary``) to the sample
hub's ``guide`` and summarises each guide over its libraries: how many, how
many reads, the median editing, frameshift, in-frame and template-based rates,
the dominant indel size and its share of the guide's indel reads (from
``crisprseq_indel_sizes``), and, when the clonality classifier ran, how the
libraries were classified.

Medians rather than means: a guide's libraries are replicates or cell pools
whose editing can differ by an order of magnitude, and one failed library
should not move the guide's number.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import indel_sizes_per_library, library_guides, rounded

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples"),
    RecipeSource(ref="summary", dc_ref="crisprseq_edit_summary"),
    RecipeSource(ref="indels", dc_ref="crisprseq_indels"),
    RecipeSource(ref="clonality", dc_ref="crisprseq_clonality", optional=True),
]

# Column order is the table's: the guide, its editing level and the key rates
# first.
EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "guide": pl.Utf8,
    "edit_class": pl.Utf8,
    "libraries": pl.Int64,
    "median_edited_pct": pl.Float64,
    "median_frameshift_of_indels_pct": pl.Float64,
    "median_frameshift_pct": pl.Float64,
    "median_inframe_pct": pl.Float64,
    "median_template_based_pct": pl.Float64,
    "min_edited_pct": pl.Float64,
    "max_edited_pct": pl.Float64,
    "dominant_indel_size": pl.Int64,
    "dominant_indel_share_pct": pl.Float64,
    "classification_mix": pl.Utf8,
    "classified_reads": pl.Int64,
}

# Median editing above these (percent of classified reads) labels the guide.
_EDIT_CLASSES = ((50.0, "High editing"), (10.0, "Moderate editing"), (1.0, "Low editing"))


def _edit_class(expr: pl.Expr) -> pl.Expr:
    out = pl.lit("Unedited")
    for bound, label in reversed(_EDIT_CLASSES):
        out = pl.when(expr >= bound).then(pl.lit(label)).otherwise(out)
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    summary = sources["summary"]
    libs = library_guides(sources["samples"], summary)
    per_lib = summary.join(libs.select("sample", "guide"), on="sample", how="inner")
    out = per_lib.group_by("guide").agg(
        pl.col("sample").n_unique().cast(pl.Int64).alias("libraries"),
        pl.col("classified_reads").sum().cast(pl.Int64),
        pl.col("edited_pct").median().alias("median_edited_pct"),
        pl.col("frameshift_pct").median().alias("median_frameshift_pct"),
        pl.col("inframe_pct").median().alias("median_inframe_pct"),
        pl.col("template_based_pct").median().alias("median_template_based_pct"),
        pl.col("frameshift_of_indels_pct").median().alias("median_frameshift_of_indels_pct"),
        pl.col("edited_pct").min().alias("min_edited_pct"),
        pl.col("edited_pct").max().alias("max_edited_pct"),
    )
    sizes = (
        indel_sizes_per_library(sources["indels"])
        .join(libs.select("sample", "guide"), on="sample", how="inner")
        .group_by("guide", "size")
        .agg(pl.col("reads").sum())
        .with_columns(
            (pl.col("reads") * 100.0 / pl.col("reads").sum().over("guide")).alias("_share")
        )
        .sort("reads", "size", descending=[True, False])
        .group_by("guide", maintain_order=True)
        .first()
        .select(
            "guide",
            pl.col("size").cast(pl.Int64).alias("dominant_indel_size"),
            pl.col("_share").cast(pl.Float64).alias("dominant_indel_share_pct"),
        )
    )
    out = out.join(sizes, on="guide", how="left")
    clon = sources.get("clonality")
    if clon is not None and clon.height:
        mix = (
            clon.join(libs.select("sample", "guide"), on="sample", how="inner")
            .group_by("guide", "classification")
            .agg(pl.len().alias("n"))
            .sort("guide", "n", "classification", descending=[False, True, False])
            .group_by("guide", maintain_order=True)
            .agg(pl.format("{} {}", pl.col("classification"), pl.col("n")).str.join(", "))
            .rename({"classification": "classification_mix"})
        )
        out = out.join(mix, on="guide", how="left")
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("classification_mix"))
    rates = [c for c, t in EXPECTED_SCHEMA.items() if t == pl.Float64]
    out = (
        out.with_columns([pl.col(c).cast(pl.Float64) for c in rates])
        .with_columns(_edit_class(pl.col("median_edited_pct")).alias("edit_class"))
        .with_columns(rounded(*rates))
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(
        "median_edited_pct", descending=True, nulls_last=True
    )
