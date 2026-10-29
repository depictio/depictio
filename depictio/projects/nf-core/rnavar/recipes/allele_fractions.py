"""nf-core/rnavar allele-fraction distribution: each sample's PASS calls over the allele fraction.

A germline call in a diploid sample has an allele fraction (the share of reads that
carry the ALT allele) near 0.5 when heterozygous and near 1 when homozygous-alternate.
The shape of that distribution per sample says more about a callset than the fraction
of any one call: a heterozygous peak that sits off 0.5, or a broad shoulder of low
fractions, points at contamination, allelic imbalance (in RNA-seq, allele-specific
expression) or artefacts.

This counts, per sample, variant type and depth class, the PASS calls in 20 bins of
0.05 over 0 to 1, among the calls read at least 10 times (an allele
fraction taken from a handful of reads is too coarse to tell a heterozygous call from a
homozygous one, and puts peaks in by construction). The depth class (10 to 19, 20 to 49, 50 to 99, 100 and
more reads) and the variant type are columns, not axes, so the dashboard narrows the
distribution to the depth or type it wants with a filter and the figure sums what is
left. Empty bins have no row.

A sample with no call at that depth has no rows.

Sources:
    variants  ``vcf_variants`` (this template's ``variants.py``)
    hub       ``samples`` (this template's ``samples.py``): the design group of each sample

Parameters:
    group_col   the design column the samples are coloured by (the template's ``GROUP_COL``);
                the hub's constant ``__no_group__`` column when the run has no design

Output schema (the group column is named by ``group_col``):
    sample : Utf8         the sample
    <group> : Utf8        the sample's design group
    variant_type : Utf8   SNP, INDEL, MNP or SV
    depth_class : Utf8    read depth at the call: 10-19, 20-49, 50-99 or 100+
    vaf_bin : Float64     lower edge of the bin (0.0, 0.05 ... 0.95)
    vaf : Float64         middle of the bin
    calls : Int64         PASS calls of that sample, type and depth class in the bin
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
            "variant_type": pl.Utf8,
            "dp": pl.Int64,
            "vaf": pl.Float64,
            "is_pass": pl.Boolean,
        },
    ),
    # No input_schema beyond the key: the design columns are the user's factors.
    RecipeSource(ref="hub", dc_ref="samples", optional=True, input_schema={"sample": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "variant_type": pl.Utf8,
    "depth_class": pl.Utf8,
    "vaf_bin": pl.Float64,
    "vaf": pl.Float64,
    "calls": pl.Int64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Column the group falls back to when the run has no design table.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All samples"
N_BINS = 20
MIN_DEPTH = 10


def _groups(hub: pl.DataFrame | None, group_col: str | None, called: list[str]):
    """The group column's name and a ``sample`` -> group frame over the called samples."""
    if (
        hub is not None
        and group_col
        and group_col in hub.columns
        and group_col != "sample"
        and "sample" in hub.columns
    ):
        frame = hub.select(
            pl.col("sample").cast(pl.Utf8), pl.col(group_col).cast(pl.Utf8).alias(group_col)
        ).unique(subset="sample", keep="first")
        return group_col, frame.filter(pl.col("sample").is_in(called))
    return NO_GROUP_COL, pl.DataFrame(
        {"sample": called, NO_GROUP_COL: [NO_GROUP_VALUE] * len(called)},
        schema={"sample": pl.Utf8, NO_GROUP_COL: pl.Utf8},
    )


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Bin each sample's deep PASS calls by allele fraction, per variant type and depth class."""
    params = params or {}
    calls = sources["variants"].filter(
        pl.col("is_pass").fill_null(False)
        & pl.col("vaf").is_not_null()
        & (pl.col("dp").fill_null(0) >= MIN_DEPTH)
    )
    called = calls["sample"].drop_nulls().unique().sort().to_list()
    group, groups = _groups(sources.get("hub"), params.get("group_col"), called)
    order = ["sample", group, "variant_type", "depth_class", "vaf_bin", "vaf", "calls"]
    schema = {
        "sample": pl.Utf8,
        group: pl.Utf8,
        **{k: v for k, v in OUTPUT_SCHEMA.items() if k != "sample"},
    }
    if not called:
        return pl.DataFrame(schema=schema).select(order)

    dp = pl.col("dp")
    return (
        calls.join(groups, on="sample", how="left")
        .with_columns(
            pl.col(group).fill_null(NO_GROUP_VALUE),
            pl.col("variant_type").fill_null("other"),
            pl.when(dp < 20)
            .then(pl.lit("10-19"))
            .when(dp < 50)
            .then(pl.lit("20-49"))
            .when(dp < 100)
            .then(pl.lit("50-99"))
            .otherwise(pl.lit("100+"))
            .alias("depth_class"),
            (pl.col("vaf").clip(0.0, 1.0) * N_BINS)
            .floor()
            .clip(0, N_BINS - 1)
            .cast(pl.Int64)
            .alias("_bin"),
        )
        .group_by(["sample", group, "variant_type", "depth_class", "_bin"])
        .agg(pl.len().cast(pl.Int64).alias("calls"))
        .with_columns(
            (pl.col("_bin") / N_BINS).round(4).alias("vaf_bin"),
            ((pl.col("_bin") + 0.5) / N_BINS).round(4).alias("vaf"),
        )
        .select([pl.col(c).cast(schema[c]) for c in order])
        .sort(["sample", "variant_type", "depth_class", "vaf_bin"])
    )
