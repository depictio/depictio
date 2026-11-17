"""nf-core/rnavar shared variants: the PASS sites of each design group and how many replicates call them.

The Genome tab asks one question: are the PASS variants shared between the replicates of a
cell line, and do the reads support them? This is the table the genome browser opens from.
One row per design group (a cell line, a condition) and PASS site, where a site is a contig,
a position and alleles (``variant_key``), whatever the genotype. Per row:

* ``n_calling`` of the group's ``samples`` call the site, and ``sharing`` words it: in every
  replicate, in some of them, in one replicate only, or a group of a single sample (nothing to
  share with);
* ``min_dp`` is the read depth at the call in the replicate that read it least, the read
  support of the weakest call, and ``median_vaf`` the allele fraction of the calls;
* ``support_score`` ranks the rows the browser steps through: sites every replicate calls
  first, then sites some replicates call, then the rest; the deeper the weakest call (capped
  at 200 reads, past which more reads add no confidence), then the higher the best QUAL, the
  higher inside a tier. The browser opens on the best row.

Only the primary contigs are kept, since the assembly-aware view throws on an alt or unplaced
contig. A site the replicates disagree on is not an error: RNA calls follow expression, so a
variant sits in one replicate when the other never reached the depth to call it.

Sources:
    variants  ``vcf_variants`` (this template's ``variants.py``)
    hub       ``samples`` (this template's ``samples.py``): the design group of each sample

Parameters:
    group_col   the design column the replicates are grouped by (the template's ``GROUP_COL``);
                the hub's constant ``__no_group__`` column when the run has no design, which
                makes the whole cohort one group

Output schema (the group column is named by ``group_col``):
    chrom : Utf8         primary contig
    pos : Int64          position, 1-based
    end : Int64          last base of the reference allele
    <group> : Utf8       the design group
    variant_key : Utf8   contig, position and alleles joined
    ref, alt : Utf8      alleles
    variant_type : Utf8  SNP, MNP, INDEL or SV
    sharing : Utf8       In every replicate / In some replicates / In one replicate / Single sample
    n_calling : Int64    samples of the group calling the site PASS
    samples : Int64      samples of the group that have a callset
    min_dp : Int64       lowest read depth among the calls
    median_vaf : Float64 median allele fraction of the calls
    best_qual : Float64  highest QUAL among the calls
    carriers : Utf8      the calling samples, comma separated
    support_score : Float64  ranking the browser opens by (higher first)
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
            "chrom": pl.Utf8,
            "pos": pl.Int64,
            "variant_key": pl.Utf8,
            "ref": pl.Utf8,
            "alt": pl.Utf8,
            "variant_type": pl.Utf8,
            "qual": pl.Float64,
            "is_pass": pl.Boolean,
            "dp": pl.Int64,
            "vaf": pl.Float64,
        },
    ),
    # No input_schema beyond the key: the design columns are the user's factors.
    RecipeSource(ref="hub", dc_ref="samples", optional=True, input_schema={"sample": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "end": pl.Int64,
    "variant_key": pl.Utf8,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "sharing": pl.Utf8,
    "n_calling": pl.Int64,
    "samples": pl.Int64,
    "min_dp": pl.Int64,
    "median_vaf": pl.Float64,
    "best_qual": pl.Float64,
    "carriers": pl.Utf8,
    "support_score": pl.Float64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

PRIMARY_CONTIG_RE = r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2]|X|Y|M|MT)$"
#: Column the group falls back to when the run has no design table.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All samples"
#: Past this depth more reads add no confidence to a call; the rank stops counting them.
DEPTH_CAP = 200
QUAL_CAP = 999.0

EVERY = "In every replicate"
SOME = "In some replicates"
ONE = "In one replicate"
SINGLE = "Single sample"


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
            pl.col("sample").cast(pl.Utf8),
            pl.col(group_col).cast(pl.Utf8).fill_null(NO_GROUP_VALUE).alias(group_col),
        ).unique(subset="sample", keep="first")
        return group_col, frame.filter(pl.col("sample").is_in(called))
    return NO_GROUP_COL, pl.DataFrame(
        {"sample": called, NO_GROUP_COL: [NO_GROUP_VALUE] * len(called)},
        schema={"sample": pl.Utf8, NO_GROUP_COL: pl.Utf8},
    )


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """One row per design group and PASS site, with how many replicates call it and how deep."""
    variants = sources["variants"]
    called = variants["sample"].drop_nulls().unique().sort().to_list()
    group, groups = _groups(sources.get("hub"), (params or {}).get("group_col"), called)
    schema = {group: pl.Utf8, **OUTPUT_SCHEMA}
    keys = list(OUTPUT_SCHEMA)
    order = [*keys[:3], group, *keys[3:]]
    if groups.is_empty():
        return pl.DataFrame(schema=schema).select(order)

    size = groups.group_by(group).agg(pl.col("sample").n_unique().cast(pl.Int64).alias("samples"))
    calls = variants.filter(
        pl.col("is_pass").fill_null(False)
        & pl.col("variant_key").is_not_null()
        & pl.col("pos").is_not_null()
        & pl.col("chrom").str.contains(PRIMARY_CONTIG_RE)
    ).join(groups, on="sample", how="inner")
    if calls.is_empty():
        return pl.DataFrame(schema=schema).select(order)

    sites = (
        calls.group_by([group, "variant_key"])
        .agg(
            pl.col("chrom").first(),
            pl.col("pos").first(),
            pl.col("ref").first(),
            pl.col("alt").first(),
            pl.col("variant_type").first(),
            pl.col("sample").n_unique().cast(pl.Int64).alias("n_calling"),
            pl.col("dp").min().cast(pl.Int64).alias("min_dp"),
            pl.col("vaf").median().round(3).alias("median_vaf"),
            pl.col("qual").max().alias("best_qual"),
            pl.col("sample").unique().sort().str.join(", ").alias("carriers"),
        )
        .join(size, on=group, how="left")
        .with_columns(
            (pl.col("pos") + pl.col("ref").str.len_chars().fill_null(1) - 1)
            .cast(pl.Int64)
            .alias("end"),
            pl.when(pl.col("samples") <= 1)
            .then(pl.lit(SINGLE))
            .when(pl.col("n_calling") >= pl.col("samples"))
            .then(pl.lit(EVERY))
            .when(pl.col("n_calling") > 1)
            .then(pl.lit(SOME))
            .otherwise(pl.lit(ONE))
            .alias("sharing"),
        )
        .with_columns(
            (
                pl.when(pl.col("sharing") == EVERY)
                .then(3.0)
                .when(pl.col("sharing") == SOME)
                .then(2.0)
                .otherwise(1.0)
                * 1_000_000.0
                + pl.col("min_dp").fill_null(0).clip(0, DEPTH_CAP).cast(pl.Float64) * 1000.0
                + pl.col("best_qual").fill_null(0.0).clip(0.0, QUAL_CAP)
            ).alias("support_score")
        )
    )
    return (
        sites.select([pl.col(c).cast(t) for c, t in schema.items()])
        .select(order)
        .sort(["support_score", "chrom", "pos"], descending=[True, False, False])
    )
