"""nf-core/rnavar Genome tab navigator: PASS variants in 1 Mb windows, one lane per design group.

The Genome tab's locus section is driven by one ``genome_view`` navigator that
emits a region filter; the call track and the genome browser follow it. A
navigator receives its whole collection sampled to about 10,000 rows
(TEMPLATE_BOTTLENECKS 20), so it reads a summary rather than the calls: one row
per 1 Mb window and design group (a cell line, a condition) holding at least one
PASS call, about 2,500 windows a group on a human transcriptome, never sampled.
RNA calls pile up on expressed genes, so the windows light up where the
transcriptome is dense (chr19, chr17, chr1p) and stay dark over gene deserts.

One row per group, not per sample: the navigator stacks one lane per group
(``facet_by_sample`` on the group column), so the replicates of a line are
counted together and the lanes tell the groups apart, which the browser below
then shows sample by sample. Without a design table the group is the hub's
constant column, and the navigator draws a single lane.

The coordinates are named ``chrom`` / ``pos`` / ``end`` like the call track's,
because a follower only zooms on a region the navigator names in its own column
names (TEMPLATE_BOTTLENECKS 19). Only the primary contigs are kept, since the
assembly-aware view throws on an alt or unplaced contig (TEMPLATE_BOTTLENECKS 21).

The windows are the 0-based, 1 Mb aligned ones ``depictio.recipes.lib.genomic_bins``
draws. The per-sample, ideogram-shaped density (chrom, start, end, value,
sample) is the catalog output ``vcf/variant_density``, built on that helper;
this one is the navigator's.

Sources:
    variants  ``vcf_variants`` (this template's ``variants.py``)
    hub       ``samples`` (this template's ``samples.py``): the design group of each sample

Parameters:
    group_col   the design column the lanes are split by (the template's ``GROUP_COL``);
                the hub's constant ``__no_group__`` column when the run has no design

Output schema (the group column is named by ``group_col``):
    chrom : Utf8          primary contig
    pos : Int64           window start, 0-based
    end : Int64           window end, exclusive
    <group> : Utf8        the design group (a lane of the navigator)
    variants : Int64      distinct PASS variants of the group in the window
    calls : Int64         PASS calls in the window (a variant called in 3 samples counts 3)
    samples : Int64       samples of the group with at least one PASS call in the window
    snv_pct : Float64     share of the window's distinct variants that are SNVs, percent
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
            "variant_type": pl.Utf8,
            "is_pass": pl.Boolean,
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
    "variants": pl.Int64,
    "calls": pl.Int64,
    "samples": pl.Int64,
    "snv_pct": pl.Float64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

BIN_SIZE = 1_000_000
PRIMARY_CONTIG_RE = r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2]|X|Y|M|MT)$"
#: Column the group falls back to when the run has no design table.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All samples"


def group_of_samples(hub: pl.DataFrame | None, group_col: str | None) -> tuple[str, pl.DataFrame]:
    """The group column's name and a ``sample`` -> group frame, from the sample hub.

    A run with no design table (or a ``group_col`` the hub does not carry) has one
    constant group, under the hub's own ``__no_group__`` name.
    """
    if (
        hub is not None
        and group_col
        and group_col in hub.columns
        and "sample" in hub.columns
        and group_col != "sample"
    ):
        return group_col, hub.select(
            pl.col("sample").cast(pl.Utf8), pl.col(group_col).cast(pl.Utf8).alias(group_col)
        ).unique(subset="sample", keep="first")
    samples = hub["sample"].cast(pl.Utf8).unique().to_list() if hub is not None else []
    return NO_GROUP_COL, pl.DataFrame(
        {"sample": samples, NO_GROUP_COL: [NO_GROUP_VALUE] * len(samples)},
        schema={"sample": pl.Utf8, NO_GROUP_COL: pl.Utf8},
    )


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Sum the PASS calls of each design group into 1 Mb windows over the primary contigs."""
    group, groups = group_of_samples(sources.get("hub"), (params or {}).get("group_col"))
    calls = (
        sources["variants"]
        .filter(
            pl.col("is_pass").fill_null(False)
            & pl.col("chrom").str.contains(PRIMARY_CONTIG_RE)
            & pl.col("pos").is_not_null()
        )
        .join(groups, on="sample", how="left")
        .with_columns(pl.col(group).fill_null(NO_GROUP_VALUE))
    )
    schema = {**OUTPUT_SCHEMA, group: pl.Utf8}
    order = ["chrom", "pos", "end", group, "variants", "calls", "samples", "snv_pct"]
    if calls.is_empty():
        return pl.DataFrame(schema=schema).select(order)
    windowed = calls.with_columns(((pl.col("pos") - 1) // BIN_SIZE * BIN_SIZE).alias("_start"))
    per_window = windowed.group_by(["chrom", "_start", group]).agg(
        pl.col("variant_key").n_unique().cast(pl.Int64).alias("variants"),
        pl.len().cast(pl.Int64).alias("calls"),
        pl.col("sample").n_unique().cast(pl.Int64).alias("samples"),
        pl.col("variant_key")
        .filter(pl.col("variant_type") == "SNP")
        .n_unique()
        .cast(pl.Int64)
        .alias("_snvs"),
    )
    return (
        per_window.with_columns(
            pl.col("_start").cast(pl.Int64).alias("pos"),
            (pl.col("_start") + BIN_SIZE).cast(pl.Int64).alias("end"),
            pl.when(pl.col("variants") > 0)
            .then(pl.col("_snvs") * 100.0 / pl.col("variants"))
            .otherwise(None)
            .round(2)
            .alias("snv_pct"),
        )
        .select([pl.col(c).cast(t) for c, t in {**schema}.items()])
        .select(order)
        .sort(["chrom", "pos", group])
    )
