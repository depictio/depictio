"""Binding predictions of nf-core/epitopeprediction, one row per prediction.

``predictions/<sample>.tsv`` holds every peptide of a sample with the score of
every tool against every allele. This recipe returns one row per sample,
peptide, allele and tool that the tool scored: the 0-1 affinity score the
pipeline writes (``BA``), the IC50 in nM it is derived from, the percentile rank
and the pipeline's own binder call, with the peptide's length, origin (mutant,
wild type or input sequence) and, for variant input, its gene and consequence.
Both output shapes of the pipeline are read (long, the default, and
``--wide_format_output``); see ``depictio.recipes.lib.epitope_predictions`` for
why the files are read as raw lines.

Alleles are normalised to ``HLA-A*02:01`` (two fields, ``HLA-`` prefix) so they
join on alleles typed elsewhere. ``wt_ic50_nm`` and ``agretopicity`` (mutant
IC50 over wild-type IC50) are set on mutant rows whose wild-type peptide was
predicted too (``--wild_type``).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.epitope_predictions import (
    LINE_COLUMN,
    LINE_READ_KWARGS,
    load,
    scored,
    with_wildtype,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # Raw lines: the wide shape is split file by file in the recipe, never
    # concatenated column-wise (see the library docstring).
    RecipeSource(
        ref="predictions",
        input_schema={"source_path": pl.Utf8, LINE_COLUMN: pl.Utf8},
        glob_pattern="predictions/*.tsv",
        format="csv",
        read_kwargs=LINE_READ_KWARGS,
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "row_id": pl.Utf8,
    "sample": pl.Utf8,
    "sequence": pl.Utf8,
    "length": pl.Int64,
    "length_class": pl.Utf8,
    "origin": pl.Utf8,
    "predictor": pl.Utf8,
    "mhc_class": pl.Utf8,
    "allele": pl.Utf8,
    "hla_locus": pl.Utf8,
    "affinity_score": pl.Float64,
    "ic50_nm": pl.Float64,
    "log10_ic50": pl.Float64,
    "percentile_rank": pl.Float64,
    "binder": pl.Int64,
    "call": pl.Utf8,
    "affinity_class": pl.Utf8,
    "peptide_id": pl.Utf8,
    "gene": pl.Utf8,
    "consequence": pl.Utf8,
    "HGVSp": pl.Utf8,
    "genomic_anchor": pl.Utf8,
    "wildtype": pl.Utf8,
    "wt_ic50_nm": pl.Float64,
    "agretopicity": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = with_wildtype(scored(load(sources)))
    out = df.with_columns(
        (
            pl.col("sample")
            + "|"
            + pl.col("sequence")
            + "|"
            + pl.col("allele")
            + "|"
            + pl.col("predictor")
        ).alias("row_id"),
        pl.col("BA").round(4).alias("affinity_score"),
        pl.col("rank").alias("percentile_rank"),
        pl.col("binder").fill_null(False).cast(pl.Int64).alias("binder"),
        pl.when(pl.col("binder"))
        .then(pl.lit("Binder"))
        .otherwise(pl.lit("Non-binder"))
        .alias("call"),
        pl.col("id").alias("peptide_id"),
    )
    return (
        out.unique(subset=["row_id"], keep="first", maintain_order=True)
        .select(list(OUTPUT_SCHEMA))
        .sort(["sample", "allele", "predictor", "sequence"])
    )
