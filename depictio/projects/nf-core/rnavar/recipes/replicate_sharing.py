"""nf-core/rnavar replicate agreement: the PASS sites of a design group that every replicate calls.

A cell line sequenced twice should give the same variants twice. This counts, per
design group (a cell line, a condition), the distinct PASS sites called in at
least one of its samples and the ones called in every one of them; the share is
the Overview's reproducibility measure. Sites, not calls: a variant is its
contig, position and alleles (``variant_key``), whatever the genotype.

A site the replicates disagree on is not an error to fix: RNA calls follow
expression, so a variant sits in one replicate when the other never reached the
depth to call it. A low share therefore points at coverage, a high one at a
callset that does not depend on it.

A group of a single sample has no replicate to agree with: its share is null,
never 100, so it does not lift a median.

Sources:
    variants  ``vcf_variants`` (this template's ``variants.py``)
    hub       ``samples`` (this template's ``samples.py``): the design group of each sample

Parameters:
    group_col   the design column the replicates are grouped by (the template's
                ``GROUP_COL``); the hub's constant ``__no_group__`` column when the
                run has no design, which makes the whole cohort one group

Output schema (the group column is named by ``group_col``):
    <group> : Utf8        the design group
    samples : Int64       samples of the group that have a callset
    sites : Int64         distinct PASS sites called in at least one of them
    shared_sites : Int64  distinct PASS sites called in every one of them
    shared_pct : Float64  shared_sites over sites, percent; null for a group of one sample
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        dc_ref="vcf_variants",
        input_schema={"sample": pl.Utf8, "variant_key": pl.Utf8, "is_pass": pl.Boolean},
    ),
    # No input_schema beyond the key: the design columns are the user's factors.
    RecipeSource(ref="hub", dc_ref="samples", optional=True, input_schema={"sample": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "samples": pl.Int64,
    "sites": pl.Int64,
    "shared_sites": pl.Int64,
    "shared_pct": pl.Float64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Column the group falls back to when the run has no design table.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All samples"


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
    """Count each group's PASS sites, and the ones every sample of the group calls."""
    variants = sources["variants"]
    called = variants["sample"].drop_nulls().unique().sort().to_list()
    group, groups = _groups(sources.get("hub"), (params or {}).get("group_col"), called)
    schema = {group: pl.Utf8, **OUTPUT_SCHEMA}
    if groups.is_empty():
        return pl.DataFrame(schema=schema)

    size = groups.group_by(group).agg(pl.col("sample").n_unique().cast(pl.Int64).alias("samples"))
    sites = (
        variants.filter(pl.col("is_pass").fill_null(False) & pl.col("variant_key").is_not_null())
        .join(groups, on="sample", how="inner")
        .group_by([group, "variant_key"])
        .agg(pl.col("sample").n_unique().alias("_n"))
        .join(size, on=group, how="left")
        .group_by(group)
        .agg(
            pl.len().cast(pl.Int64).alias("sites"),
            (pl.col("_n") == pl.col("samples")).sum().cast(pl.Int64).alias("shared_sites"),
        )
    )
    out = (
        size.join(sites, on=group, how="left")
        .with_columns(pl.col("sites").fill_null(0), pl.col("shared_sites").fill_null(0))
        .with_columns(
            pl.when((pl.col("samples") > 1) & (pl.col("sites") > 0))
            .then(pl.col("shared_sites") * 100.0 / pl.col("sites"))
            .otherwise(None)
            .round(2)
            .alias("shared_pct")
        )
    )
    return out.select([pl.col(c).cast(t) for c, t in schema.items()]).sort(group)
