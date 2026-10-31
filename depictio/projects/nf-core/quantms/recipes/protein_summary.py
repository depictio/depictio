"""One row per protein group: how many runs detected it, how strongly and with how many peptides.

Reduces the long protein table to the questions a reader asks of the whole experiment:
in how many of the runs a group was quantified, its mean abundance and the spread of its
intensity across the runs that saw it, how many distinct peptides back it, and where it
ranks by abundance. One 0/1 column per run (named after the run) records which runs
quantified the group, the matrix an UpSet plot reads.

Output schema (the run columns, named after the runs, follow the fixed ones):
    protein_group : Utf8
    protein_name : Utf8
    genes : Utf8
    description : Utf8
    peptides : Int64              distinct peptide sequences over all runs
    peptide_support : Utf8        1 peptide, 2 to 3 peptides or 4 or more peptides
    runs_detected : Int64
    runs_total : Int64
    detected_pct : Float64        share of the runs that quantified the group, percent
    detection : Utf8              All runs, Some runs or One run
    mean_log2_intensity : Float64 mean of the runs that quantified the group
    cv_pct : Float64              coefficient of variation of the intensity over those runs
    abundance_rank : Int64        1 is the most abundant group
    <run id> : Int64              1 when the run quantified the group, else 0
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PROTEINS_DC_TAG = "quantms_proteins"
PRECURSORS_DC_TAG = "quantms_precursors"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="proteins",
        dc_ref=PROTEINS_DC_TAG,
        input_schema={
            "run_id": pl.Utf8,
            "protein_group": pl.Utf8,
            "protein_name": pl.Utf8,
            "genes": pl.Utf8,
            "intensity": pl.Float64,
            "log2_intensity": pl.Float64,
        },
    ),
    RecipeSource(
        ref="precursors",
        dc_ref=PRECURSORS_DC_TAG,
        optional=True,
        input_schema={"protein_group": pl.Utf8, "peptide": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "protein_group": pl.Utf8,
    "protein_name": pl.Utf8,
    "genes": pl.Utf8,
    "description": pl.Utf8,
    "peptides": pl.Int64,
    "peptide_support": pl.Utf8,
    "runs_detected": pl.Int64,
    "runs_total": pl.Int64,
    "detected_pct": pl.Float64,
    "detection": pl.Utf8,
    "mean_log2_intensity": pl.Float64,
    "cv_pct": pl.Float64,
    "abundance_rank": pl.Int64,
}
# One 0/1 column per run: named after the runs, so they pass through unvalidated.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    proteins = sources["proteins"]
    runs = sorted(proteins["run_id"].unique().to_list())
    description = (
        pl.col("description").drop_nulls().first()
        if "description" in proteins.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    base = proteins.group_by("protein_group").agg(
        pl.col("protein_name").first(),
        pl.col("genes").first(),
        description.alias("description"),
        pl.col("run_id").n_unique().cast(pl.Int64).alias("runs_detected"),
        pl.col("log2_intensity").mean().round(4).alias("mean_log2_intensity"),
        pl.when(pl.col("intensity").len() > 1)
        .then(pl.col("intensity").std() / pl.col("intensity").mean() * 100.0)
        .otherwise(None)
        .round(2)
        .alias("cv_pct"),
    )
    precursors = sources.get("precursors")
    if precursors is not None and not precursors.is_empty():
        peptides = precursors.group_by("protein_group").agg(
            pl.col("peptide").n_unique().cast(pl.Int64).alias("peptides")
        )
        base = base.join(peptides, on="protein_group", how="left")
    else:
        base = base.with_columns(pl.lit(None, dtype=pl.Int64).alias("peptides"))
    base = base.with_columns(
        pl.lit(len(runs)).cast(pl.Int64).alias("runs_total"),
        pl.when(pl.col("peptides").is_null())
        .then(None)
        .when(pl.col("peptides") <= 1)
        .then(pl.lit("1 peptide"))
        .when(pl.col("peptides") <= 3)
        .then(pl.lit("2 to 3 peptides"))
        .otherwise(pl.lit("4 or more peptides"))
        .alias("peptide_support"),
    ).with_columns(
        (pl.col("runs_detected") / pl.col("runs_total") * 100.0).round(2).alias("detected_pct"),
        pl.when(pl.col("runs_detected") >= pl.col("runs_total"))
        .then(pl.lit("All runs"))
        .when(pl.col("runs_detected") <= 1)
        .then(pl.lit("One run"))
        .otherwise(pl.lit("Some runs"))
        .alias("detection"),
        pl.col("mean_log2_intensity")
        .rank(method="ordinal", descending=True)
        .cast(pl.Int64)
        .alias("abundance_rank"),
    )
    # The membership matrix: one 0/1 column per run.
    member = (
        proteins.select("protein_group", "run_id")
        .unique()
        .with_columns(pl.lit(1, dtype=pl.Int64).alias("seen"))
        .pivot(on="run_id", index="protein_group", values="seen")
        .fill_null(0)
    )
    for run in runs:
        if run not in member.columns:
            member = member.with_columns(pl.lit(0, dtype=pl.Int64).alias(run))
    member = member.select("protein_group", *[pl.col(r).cast(pl.Int64) for r in runs])
    out = base.join(member, on="protein_group", how="left")
    return out.select([*OUTPUT_SCHEMA, *runs]).sort("abundance_rank")
