"""Per patient of a tumour/normal pair: distinct germline variants and distinct somatic ones.

The question a pair's design asks first is how many calls are inherited and how many are
the tumour's own. Two numbers per patient, each a count of *distinct variants* (contig,
position and alleles) kept by a caller (FILTER PASS), so a variant five callers agree on
counts once:

* ``Germline (normal)``: the PASS calls of the pair's normal sample, called on its own;
* ``Somatic (pair)``: the PASS calls of the pair, whatever the caller.

Only patients with a pair are listed; a run without one has no such table and the
comparison tab is skipped. The normal's calls are ``vcf_variants`` (germline units only),
the pair's are ``somatic_calls``.

Output schema:
    patient : Utf8       the patient
    call_class : Utf8    "Germline (normal)" or "Somatic (pair)"
    variants : Int64     distinct PASS variants of that class
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

GERMLINE_CLASS = "Germline (normal)"
SOMATIC_CLASS = "Somatic (pair)"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="somatic",
        dc_ref="somatic_calls",
        input_schema={
            "unit": pl.Utf8,
            "unit_type": pl.Utf8,
            "variant_key": pl.Utf8,
            "is_pass": pl.Boolean,
        },
    ),
    RecipeSource(
        ref="germline",
        dc_ref="vcf_variants",
        input_schema={"sample": pl.Utf8, "variant_key": pl.Utf8, "is_pass": pl.Boolean},
    ),
    RecipeSource(
        ref="pairs",
        dc_ref="pairs",
        input_schema={"pair_id": pl.Utf8, "patient": pl.Utf8, "tumour": pl.Utf8, "normal": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "patient": pl.Utf8,
    "call_class": pl.Utf8,
    "variants": pl.Int64,
}


def _distinct(calls: pl.DataFrame, by: str, pairs: pl.DataFrame, label: str) -> pl.DataFrame:
    """Distinct PASS variants per patient, the calls joined to the pairs on column ``by``."""
    return (
        calls.filter(pl.col("is_pass"))
        .join(pairs, left_on=by, right_on=pairs.columns[0], how="inner")
        .group_by("patient")
        .agg(pl.col("variant_key").n_unique().cast(pl.Int64).alias("variants"))
        .with_columns(pl.lit(label).alias("call_class"))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count the distinct PASS variants of each pair's normal and of the pair itself."""
    pairs = sources["pairs"]
    if pairs.is_empty():
        raise ValueError("sarek patient_call_counts: the run has no tumour/normal pair")
    germline_pairs = pairs.select("normal", "patient").unique()
    somatic_pairs = pairs.select(pl.col("pair_id").alias("unit"), "patient")
    germline = _distinct(
        sources["germline"].rename({"sample": "normal"}), "normal", germline_pairs, GERMLINE_CLASS
    )
    somatic = _distinct(
        sources["somatic"].filter(pl.col("unit_type") == "paired"),
        "unit",
        somatic_pairs,
        SOMATIC_CLASS,
    )
    # A patient with a pair is listed under both classes, 0 when a class has no call.
    grid = (
        pairs.select("patient")
        .unique()
        .join(pl.DataFrame({"call_class": [GERMLINE_CLASS, SOMATIC_CLASS]}), how="cross")
    )
    counted = pl.concat([germline, somatic], how="diagonal_relaxed")
    return (
        grid.join(counted, on=["patient", "call_class"], how="left")
        .with_columns(pl.col("variants").fill_null(0).cast(pl.Int64))
        .select(list(OUTPUT_SCHEMA))
        .sort(["patient", "call_class"])
    )
