"""SNV substitution spectrum per callset, folded onto the six pyrimidine classes.

Every PASS single-nucleotide call is folded onto its pyrimidine reference (a G>A
call reads as C to T, its reverse complement) and counted in one of the six
classes, two transitions (C to T, T to C) and four transversions. Each count is
also given as a share of the callset's PASS SNVs, so callsets of different
sizes compare on shape rather than on yield.

On RNA the spectrum carries a signature DNA does not: A-to-I editing by ADAR is
read by the sequencer as A to G on the transcript, which folds onto T to C here,
so an RNA callset shows a T to C share above the C to T one where a DNA
callset of the same individual shows the reverse.

Same shape as sarek's bcftools-based spectrum (``substitution_class``,
``mutation_class``, ``count``, ``fraction``), read from the VCF rows instead,
for a pipeline that runs no bcftools stats.

Output schema:
    sample, caller : Utf8
    callset : Utf8             sample and caller together, the series label
    substitution_class : Utf8  C to A, C to G, C to T, T to A, T to C, T to G
    mutation_class : Utf8      transition or transversion
    count : Int64              PASS SNVs of the class
    fraction : Float64         count over the callset's PASS SNVs
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        dc_ref="vcf_variants",
        input_schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "ref": pl.Utf8,
            "alt": pl.Utf8,
            "variant_type": pl.Utf8,
            "is_pass": pl.Boolean,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "callset": pl.Utf8,
    "substitution_class": pl.Utf8,
    "mutation_class": pl.Utf8,
    "count": pl.Int64,
    "fraction": pl.Float64,
}

_COMPLEMENT = {"A": "T", "C": "G", "G": "C", "T": "A"}
#: Every directed substitution -> its pyrimidine-folded class.
FOLD: dict[str, str] = {}
for _ref in "ACGT":
    for _alt in "ACGT":
        if _ref == _alt:
            continue
        if _ref in "CT":
            FOLD[_ref + _alt] = f"{_ref} to {_alt}"
        else:
            FOLD[_ref + _alt] = f"{_COMPLEMENT[_ref]} to {_COMPLEMENT[_alt]}"
CLASSES = ["C to A", "C to G", "C to T", "T to A", "T to C", "T to G"]
TRANSITION_CLASSES = {"C to T", "T to C"}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Fold, count and normalise the PASS SNVs of every callset."""
    v = sources["variants"]
    snvs = (
        v.filter(pl.col("is_pass").fill_null(False) & (pl.col("variant_type") == "SNP"))
        .with_columns(
            pl.concat_str(
                [
                    pl.col("ref").str.to_uppercase(),
                    pl.col("alt").str.split(",").list.get(0, null_on_oob=True).str.to_uppercase(),
                ]
            )
            .replace_strict(FOLD, default=None, return_dtype=pl.Utf8)
            .alias("substitution_class")
        )
        .filter(pl.col("substitution_class").is_not_null())
    )
    callsets = v.select("sample", "caller").unique()
    grid = callsets.join(
        pl.DataFrame({"substitution_class": CLASSES}), how="cross"
    )  # every class on every callset, 0 when absent
    counts = snvs.group_by(["sample", "caller", "substitution_class"]).agg(
        pl.len().cast(pl.Int64).alias("count")
    )
    total = pl.col("count").sum().over(["sample", "caller"])
    return (
        grid.join(counts, on=["sample", "caller", "substitution_class"], how="left")
        .with_columns(pl.col("count").fill_null(0))
        .with_columns(
            pl.concat_str([pl.col("sample"), pl.col("caller")], separator=" · ").alias("callset"),
            pl.when(pl.col("substitution_class").is_in(list(TRANSITION_CLASSES)))
            .then(pl.lit("transition"))
            .otherwise(pl.lit("transversion"))
            .alias("mutation_class"),
            pl.when(total > 0)
            .then(pl.col("count") / total)
            .otherwise(None)
            .round(5)
            .alias("fraction"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "caller", "substitution_class"])
    )
