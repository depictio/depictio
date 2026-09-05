"""Melon genome-copy estimates, one row per full seven-rank lineage.

Melon writes one TSV per sample under ``melon/<database>/<sample>_<database>/``, with
the seven NCBI ranks already split into their own columns (``<taxid>|<name>``), the
estimated genome ``copy`` number, the derived ``abundance`` and a per-read ``identity``
string. Because the tool is a long-read profiler run on prokaryotic marker genes, the
copy number is a genome-count estimate rather than a read count, which is what makes it
worth its own tile next to the read-count profilers.

The recipe strips the taxid prefix off each rank, sums the copies of identical lineages
and normalises the abundance, producing the wide per-rank shape a sunburst binds
directly.

Caveat: the sample identifier lives only in the file path, which the recipe framework
does not surface, so the rows are pooled across the melon samples. Per-sample melon
composition therefore is not available here; the taxpasta collection carries the
per-sample view for every profiler that taxpasta standardises.

Output: superkingdom, phylum, class, order, family, genus, species,
copy_number, abundance, identity_mean, lineages.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profiles", glob_pattern="melon/*/*/*.tsv", format="tsv"),
]

_RANKS = ["superkingdom", "phylum", "class", "order", "family", "genus", "species"]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    **{rank: pl.Utf8 for rank in _RANKS},
    "copy_number": pl.Float64,
    "abundance": pl.Float64,
    "identity_mean": pl.Float64,
    "lineages": pl.Int64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_UNCLASSIFIED = "unclassified"


def _clean(rank: str) -> pl.Expr:
    """`<taxid>|<name>` -> `<name>`, with a placeholder for the empty levels."""
    return (
        pl.col(rank)
        .cast(pl.Utf8)
        .str.split_exact("|", 1)
        .struct.field("field_1")
        .fill_null(pl.col(rank).cast(pl.Utf8))
        .str.strip_chars()
        .replace("", None)
        .fill_null(_UNCLASSIFIED)
        .alias(rank)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split the rank labels, pool identical lineages and renormalise."""
    df = sources["profiles"]
    missing = [rank for rank in _RANKS if rank not in df.columns]
    if missing:
        raise ValueError(f"melon ranks: the profiles are missing rank column(s) {missing}")
    if "abundance" not in df.columns:
        raise ValueError("melon ranks: the profiles carry no `abundance` column")

    identity = (
        # `identity` is "<mapped>/<aligned>"; the first number is the mean identity.
        pl.col("identity")
        .cast(pl.Utf8)
        .str.split_exact("/", 1)
        .struct.field("field_0")
        .cast(pl.Float64, strict=False)
        if "identity" in df.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    copies = (
        pl.col("copy").cast(pl.Float64, strict=False)
        if "copy" in df.columns
        else pl.lit(0.0, dtype=pl.Float64)
    )

    pooled = (
        df.with_columns(
            *[_clean(rank) for rank in _RANKS],
            copies.alias("copy_number"),
            pl.col("abundance").cast(pl.Float64, strict=False).alias("abundance"),
            identity.alias("identity_value"),
        )
        .group_by(_RANKS)
        .agg(
            pl.col("copy_number").sum().alias("copy_number"),
            pl.col("abundance").sum().alias("abundance"),
            pl.col("identity_value").mean().alias("identity_mean"),
            pl.len().cast(pl.Int64).alias("lineages"),
        )
    )
    if pooled.is_empty():
        raise ValueError("melon ranks: no lineage survived the pooling")

    total = pooled["abundance"].sum()
    return (
        pooled.with_columns(
            (pl.col("abundance") / total if total else pl.col("abundance"))
            .cast(pl.Float64)
            .alias("abundance"),
            pl.col("identity_mean").cast(pl.Float64),
        )
        .select(*_RANKS, "copy_number", "abundance", "identity_mean", "lineages")
        .sort("abundance", descending=True)
    )
