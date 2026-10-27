"""Peptides of nf-core/epitopeprediction, one row per sample and peptide.

Every peptide of ``predictions/<sample>.tsv`` with its best prediction over all
alleles and tools: the allele and tool with the lowest IC50, how many alleles
scored it and how many a tool called it a binder for, and its source: for
variant input the gene, transcript, consequence, protein change, genomic anchor
and UniProt accession pVACseq gave it, for protein input the protein records it
was cut from, for peptide input its id. ``call`` is ``Binder`` when at least one
tool calls the peptide a binder of at least one allele, ``Unsupported`` when no
tool could score it (allele or length not supported) and ``Non-binder``
otherwise.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.epitope_predictions import (
    LINE_COLUMN,
    LINE_READ_KWARGS,
    VARIANT_COLUMNS,
    affinity_class,
    load,
    scored,
    with_wildtype,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
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
    "peptide_key": pl.Utf8,
    "sample": pl.Utf8,
    "sequence": pl.Utf8,
    "peptide_id": pl.Utf8,
    "length": pl.Int64,
    "length_class": pl.Utf8,
    "origin": pl.Utf8,
    "call": pl.Utf8,
    "binder": pl.Int64,
    "alleles_scored": pl.Int64,
    "binding_alleles": pl.Int64,
    "binder_calls": pl.Int64,
    "predictors": pl.Utf8,
    "best_allele": pl.Utf8,
    "best_predictor": pl.Utf8,
    "best_ic50_nm": pl.Float64,
    "best_affinity_class": pl.Utf8,
    "binding_allele_list": pl.Utf8,
    "gene": pl.Utf8,
    "transcript": pl.Utf8,
    "consequence": pl.Utf8,
    "HGVSp": pl.Utf8,
    "genomic_anchor": pl.Utf8,
    "uniprot": pl.Utf8,
    "protein_ids": pl.Utf8,
    "source_records": pl.Int64,
    "wildtype": pl.Utf8,
    "wt_best_ic50_nm": pl.Float64,
    "agretopicity": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_KEY = ["sample", "sequence"]
#: How many binding alleles the list column names before it stops.
_ALLELE_LIST_MAX = 10


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = load(sources)
    info_cols = ["id", "length", "length_class", "origin", *VARIANT_COLUMNS]
    info_cols += ["protein_ids", "counts", "wildtype"]
    peptides = df.group_by(_KEY, maintain_order=True).agg(
        [pl.col(c).drop_nulls().first().alias(c) for c in info_cols]
    )

    hits = with_wildtype(scored(df))
    per_allele = hits.group_by([*_KEY, "allele"]).agg(
        pl.col("binder").fill_null(False).any().alias("_binds"),
        pl.col("binder").fill_null(False).sum().alias("_calls"),
    )
    counts = per_allele.group_by(_KEY).agg(
        pl.len().cast(pl.Int64).alias("alleles_scored"),
        pl.col("_binds").sum().cast(pl.Int64).alias("binding_alleles"),
        pl.col("_calls").sum().cast(pl.Int64).alias("binder_calls"),
        pl.col("allele")
        .filter(pl.col("_binds"))
        .sort()
        .head(_ALLELE_LIST_MAX)
        .str.join(", ")
        .alias("binding_allele_list"),
    )
    tools = hits.group_by(_KEY).agg(
        pl.col("predictor").unique().sort().str.join(", ").alias("predictors")
    )
    # Best = lowest IC50; a tool without an IC50 (MixMHCpred) falls back to its rank.
    best = (
        hits.sort(["ic50_nm", "rank"], nulls_last=True)
        .group_by(_KEY, maintain_order=True)
        .first()
        .select(
            *_KEY,
            pl.col("allele").alias("best_allele"),
            pl.col("predictor").alias("best_predictor"),
            pl.col("ic50_nm").alias("best_ic50_nm"),
            pl.col("wt_ic50_nm").alias("wt_best_ic50_nm"),
            pl.col("agretopicity"),
        )
    )
    out = (
        peptides.join(counts, on=_KEY, how="left")
        .join(tools, on=_KEY, how="left")
        .join(best, on=_KEY, how="left")
        .with_columns(
            pl.col("alleles_scored").fill_null(0),
            pl.col("binding_alleles").fill_null(0),
            pl.col("binder_calls").fill_null(0),
        )
    )
    return (
        out.with_columns(
            (pl.col("sample") + "|" + pl.col("sequence")).alias("peptide_key"),
            pl.col("id").alias("peptide_id"),
            pl.when(pl.col("alleles_scored") == 0)
            .then(pl.lit("Unsupported"))
            .when(pl.col("binding_alleles") > 0)
            .then(pl.lit("Binder"))
            .otherwise(pl.lit("Non-binder"))
            .alias("call"),
            (pl.col("binding_alleles") > 0).cast(pl.Int64).alias("binder"),
            affinity_class(pl.col("best_ic50_nm")).alias("best_affinity_class"),
            pl.col("counts").cast(pl.Int64, strict=False).alias("source_records"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(_KEY)
    )
