"""One row per CUT&RUN sample, from the samplesheet the pipeline validated.

nf-core/cutandrun writes `pipeline_info/samplesheet.valid.csv` with one row per
sequencing LIBRARY (`id` carries a `_T<n>` technical-replicate suffix) and it
never spells out the sample name the rest of the run uses. Every downstream file
is named `<group>_R<replicate>`, so that is what this recipe builds: the hub the
sample filter and every project link key on.

The IgG control rows stay in the table. A CUT&RUN experiment is only
interpretable next to its control - it is what SEACR thresholds against and what
MACS2 uses as its background - so hiding the controls would hide the comparison
the assay is built on. `role` separates them without dropping them.

Output schema:
    sample_id : Utf8        `<group>_R<replicate>`, the name every output file uses
    target : Utf8           the samplesheet group (the antibody / mark, or the control)
    replicate : Int64       replicate number inside the group
    role : Utf8             "target" or "IgG control"
    is_control : Boolean    true for the IgG control samples
    control_target : Utf8   group of the control this sample was called against
    n_libraries : Int64     sequencing libraries merged into the sample
    library_ids : Utf8      those libraries' samplesheet ids, comma separated
    single_end : Boolean    true when the libraries are single-end
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "target": pl.Utf8,
    "replicate": pl.Int64,
    "role": pl.Utf8,
    "is_control": pl.Boolean,
    "control_target": pl.Utf8,
    "n_libraries": pl.Int64,
    "library_ids": pl.Utf8,
    "single_end": pl.Boolean,
}

_REQUIRED = ["id", "group", "replicate"]


def _truthy(column: str) -> pl.Expr:
    """A 0/1/true/false samplesheet flag as a Boolean."""
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["1", "true", "yes", "y"])
        .fill_null(False)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse the library rows to samples and label targets against controls."""
    df = sources["samplesheet"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"cutandrun samples: samplesheet lacks columns {missing}")

    is_control = _truthy("is_control") if "is_control" in df.columns else pl.lit(False)
    single_end = _truthy("single_end") if "single_end" in df.columns else pl.lit(False)
    control = pl.col("control").cast(pl.Utf8) if "control" in df.columns else pl.lit(None, pl.Utf8)

    df = df.with_columns(
        pl.col("group").cast(pl.Utf8).alias("target"),
        pl.col("replicate").cast(pl.Int64, strict=False).alias("replicate"),
        pl.col("id").cast(pl.Utf8).alias("library_id"),
        is_control.alias("is_control"),
        single_end.alias("single_end"),
        control.replace("", None).alias("control_target"),
    )
    df = df.with_columns(
        pl.concat_str([pl.col("target"), pl.lit("_R"), pl.col("replicate").cast(pl.Utf8)]).alias(
            "sample_id"
        )
    )

    samples = df.group_by("sample_id").agg(
        pl.col("target").first(),
        pl.col("replicate").first(),
        pl.col("is_control").first(),
        pl.col("control_target").first(),
        pl.len().cast(pl.Int64).alias("n_libraries"),
        pl.col("library_id").sort().str.join(",").alias("library_ids"),
        pl.col("single_end").first(),
    )
    samples = samples.with_columns(
        pl.when(pl.col("is_control"))
        .then(pl.lit("IgG control"))
        .otherwise(pl.lit("target"))
        .alias("role")
    )
    return samples.select(list(EXPECTED_SCHEMA)).sort(["is_control", "target", "replicate"])
