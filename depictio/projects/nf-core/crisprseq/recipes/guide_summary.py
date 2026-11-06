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

``edit_quartile`` ranks the guides of the run by their median edited share. No
tool or paper publishes a cut-off between high and low editing, so the classes
are the quartiles of the guides in this run: a reference the data defines, not
a threshold. The first and third quartile of a guide's own libraries
(``q1_edited_pct``, ``q3_edited_pct``) and their difference are kept beside the
median, which is how far a guide's libraries agree.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import (
    SAMPLES_INPUT_SCHEMA,
    SUMMARY_INPUT_SCHEMA,
    indel_sizes_per_library,
    library_guides,
    rounded,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples", input_schema=SAMPLES_INPUT_SCHEMA),
    RecipeSource(
        ref="summary",
        dc_ref="crisprseq_edit_summary",
        input_schema={
            **SUMMARY_INPUT_SCHEMA,
            "edited_pct": pl.Float64,
            "frameshift_pct": pl.Float64,
            "inframe_pct": pl.Float64,
            "template_based_pct": pl.Float64,
            "frameshift_of_indels_pct": pl.Float64,
        },
    ),
    RecipeSource(
        ref="indels",
        dc_ref="crisprseq_indels",
        input_schema={
            "sample": pl.Utf8,
            "size": pl.Int64,
            "reads": pl.Int64,
            "pct_reads": pl.Float64,
            "pct_indel_reads": pl.Float64,
        },
    ),
    RecipeSource(
        ref="clonality",
        dc_ref="crisprseq_clonality",
        optional=True,
        input_schema={"sample": pl.Utf8, "classification": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it. Column order is the
# table's: the guide, its editing level and the key rates first.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "guide": pl.Utf8,
    "edit_quartile": pl.Utf8,
    "libraries": pl.Int64,
    "median_edited_pct": pl.Float64,
    "q1_edited_pct": pl.Float64,
    "q3_edited_pct": pl.Float64,
    "iqr_edited_pct": pl.Float64,
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

# Quartiles of the guides' median edited share, highest first. A run with fewer
# than MIN_GUIDES guides (or a guide whose libraries classified nothing) is not ranked:
# a quartile of three values says nothing.
QUARTILE_LABELS = (
    "Highest quartile",
    "Upper-middle quartile",
    "Lower-middle quartile",
    "Lowest quartile",
)
NOT_RANKED = "Not ranked"
MIN_GUIDES = 4


def _edit_quartile(medians: pl.Series) -> pl.Series:
    """Quartile class of each guide's median edited share among the guides of the run."""
    known = medians.drop_nulls()
    if known.len() < MIN_GUIDES:
        return pl.Series("edit_quartile", [NOT_RANKED] * medians.len(), dtype=pl.Utf8)
    q1, q2, q3 = (known.quantile(q, interpolation="linear") for q in (0.25, 0.5, 0.75))
    if q1 == q3:
        # No spread (every guide unedited, say): a quartile of ties ranks nothing.
        return pl.Series("edit_quartile", [NOT_RANKED] * medians.len(), dtype=pl.Utf8)
    high, upper, lower, low = QUARTILE_LABELS
    m = pl.col("m")
    return (
        medians.to_frame("m")
        .select(
            pl.when(m.is_null())
            .then(pl.lit(NOT_RANKED))
            .when(m >= q3)
            .then(pl.lit(high))
            .when(m >= q2)
            .then(pl.lit(upper))
            .when(m >= q1)
            .then(pl.lit(lower))
            .otherwise(pl.lit(low))
            .alias("edit_quartile")
        )
        .to_series()
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    summary = sources["summary"]
    libs = library_guides(sources["samples"], summary)
    per_lib = summary.join(libs.select("sample", "guide"), on="sample", how="inner")
    out = per_lib.group_by("guide").agg(
        pl.col("sample").n_unique().cast(pl.Int64).alias("libraries"),
        pl.col("classified_reads").sum().cast(pl.Int64),
        pl.col("edited_pct").median().alias("median_edited_pct"),
        pl.col("edited_pct").quantile(0.25, interpolation="linear").alias("q1_edited_pct"),
        pl.col("edited_pct").quantile(0.75, interpolation="linear").alias("q3_edited_pct"),
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
    rates = [c for c, t in OUTPUT_SCHEMA.items() if t == pl.Float64]
    out = (
        out.with_columns([pl.col(c).cast(pl.Float64) for c in rates if c != "iqr_edited_pct"])
        .with_columns(
            (pl.col("q3_edited_pct") - pl.col("q1_edited_pct")).alias("iqr_edited_pct"),
        )
        .with_columns(_edit_quartile(out["median_edited_pct"]).alias("edit_quartile"))
        .with_columns(rounded(*rates))
    )
    return out.select(list(OUTPUT_SCHEMA)).sort(
        "median_edited_pct", descending=True, nulls_last=True
    )
