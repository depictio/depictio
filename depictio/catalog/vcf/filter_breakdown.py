"""How each caller's own FILTER column partitions its calls, per callset.

GATK VariantFiltration (and every caller that filters its own output) writes
the names of the hard filters a call failed into FILTER, semicolon-joined, and
PASS on the kept ones. Counting the FILTER values verbatim gives an exact
partition of the callset: one row per callset and FILTER value, PASS among
them, with its share of the callset. ``failed_filters`` counts how many
filters a call failed at once, so a value like ``FS;QD`` reads as two.

Built from the per-variant rows of ``vcf/variants``, the same input as the
callset summary; vcftools' ``FILTER.summary`` is the equivalent for a pipeline
that runs vcftools.

Output schema:
    sample, caller : Utf8
    filter_label : Utf8      FILTER value, verbatim; PASS for the kept calls
    is_pass : Boolean        True on the PASS row
    failed_filters : Int64   filters named in the value (0 on PASS)
    calls : Int64            calls carrying the value
    calls_pct : Float64      their share of the callset, percent
    snvs : Int64             of which SNVs
    indels : Int64           of which indels
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
            "variant_type": pl.Utf8,
            "filter_status": pl.Utf8,
            "is_pass": pl.Boolean,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "filter_label": pl.Utf8,
    "is_pass": pl.Boolean,
    "failed_filters": pl.Int64,
    "calls": pl.Int64,
    "calls_pct": pl.Float64,
    "snvs": pl.Int64,
    "indels": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count every FILTER value of every callset."""
    v = sources["variants"].with_columns(
        pl.when(pl.col("is_pass").fill_null(False))
        .then(pl.lit("PASS"))
        .otherwise(pl.col("filter_status").fill_null("."))
        .alias("filter_label")
    )
    out = v.group_by(["sample", "caller", "filter_label"]).agg(
        pl.col("is_pass").fill_null(False).any().alias("is_pass"),
        pl.len().cast(pl.Int64).alias("calls"),
        (pl.col("variant_type") == "SNP").sum().cast(pl.Int64).alias("snvs"),
        (pl.col("variant_type") == "INDEL").sum().cast(pl.Int64).alias("indels"),
    )
    total = pl.col("calls").sum().over(["sample", "caller"])
    return (
        out.with_columns(
            pl.when(pl.col("is_pass"))
            .then(pl.lit(0, dtype=pl.Int64))
            .otherwise(pl.col("filter_label").str.split(";").list.len().cast(pl.Int64))
            .alias("failed_filters"),
            (pl.col("calls") * 100.0 / total).round(3).alias("calls_pct"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "caller", "calls"], descending=[False, False, True])
    )
