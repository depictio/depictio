"""Peptides shared between conditions, one row per peptide sequence.

Joins the identified peptides (``mhcquant_peptides``) to the sample sheet
(``samples``) on the sample id and records, for every distinct sequence, in
which of the samplesheet's conditions it was identified: one 0/1 column per
condition, named after the condition, plus the number of samples and of
conditions it was seen in and a ``sharing`` label (all, several or one
condition). The two counts can be all-ones on a small run, so an UpSet binding
this table names its sets with a pattern that excludes them. An UpSet plot of the condition columns shows the
presented peptides common to every condition and the ones private to one.

The condition comes from the samplesheet's ``Condition`` column, which the
mhcquant input schema requires; a peptide from a sample missing from the sheet
is counted under ``unassigned``.
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="peptides", dc_ref="mhcquant_peptides"),
    RecipeSource(ref="samples", dc_ref="samples"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sequence": pl.Utf8,
    "length": pl.Int64,
    "length_class": pl.Utf8,
    "samples_detected": pl.Int64,
    "conditions_detected": pl.Int64,
    "sharing": pl.Utf8,
    "conditions": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_RESERVED = set(EXPECTED_SCHEMA)


def _set_name(value: str) -> str:
    name = re.sub(r"[^0-9A-Za-z]+", "_", str(value)).strip("_") or "condition"
    return f"{name}_condition" if name in _RESERVED else name


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    samples = (
        sources["samples"]
        .select(pl.col("sample_id").alias("sample"), pl.col("Condition").cast(pl.Utf8))
        .unique(subset=["sample"])
    )
    pep = (
        sources["peptides"]
        .select("sample", "sequence", "length", "length_class")
        .unique()
        .join(samples, on="sample", how="left")
        .with_columns(pl.col("Condition").fill_null("unassigned"))
        .with_columns(
            pl.col("Condition").map_elements(_set_name, return_dtype=pl.Utf8).alias("_set")
        )
    )
    sets = sorted(pep["_set"].unique().to_list())
    wide = pep.with_columns(pl.lit(1, dtype=pl.Int64).alias("_one")).pivot(
        on="_set", index="sequence", values="_one", aggregate_function="max"
    )
    wide = wide.with_columns([pl.col(s).fill_null(0).cast(pl.Int64) for s in sets])
    per_seq = pep.group_by("sequence").agg(
        pl.col("length").first(),
        pl.col("length_class").first(),
        pl.col("sample").n_unique().cast(pl.Int64).alias("samples_detected"),
        pl.col("Condition").n_unique().cast(pl.Int64).alias("conditions_detected"),
        pl.col("Condition").unique().sort().str.join(", ").alias("conditions"),
    )
    out = per_seq.join(wide, on="sequence").with_columns(
        pl.when(pl.col("conditions_detected") == len(sets))
        .then(pl.lit("All conditions"))
        .when(pl.col("conditions_detected") == 1)
        .then(pl.lit("One condition"))
        .otherwise(pl.lit("Several conditions"))
        .alias("sharing")
    )
    return out.select([*EXPECTED_SCHEMA, *sets]).sort(
        ["conditions_detected", "samples_detected", "sequence"], descending=[True, True, False]
    )
