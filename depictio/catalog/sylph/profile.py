"""sylph-tax merged profile -> long sample x rank x taxon composition.

``sylphtax merge`` writes one wide table per database: a MetaPhlAn-style
``clade_name`` lineage column plus one relative-abundance column per sample, named
after the read file. Every clade of every depth is present, so the rank is read off the
lineage prefix (``d__``, ``p__``, ..., ``t__``) and the leaf name is the last segment.

The result binds the canonical stacked-taxonomy schema, which lets one tile switch
between ranks instead of needing one collapsed table per rank.

Output: sample_id, clade_name, taxon, rank, abundance.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="merged",
        glob_pattern="sylph/sylph_*_combined_reports.tsv",
        format="tsv",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "clade_name": pl.Utf8,
    "taxon": pl.Utf8,
    "rank": pl.Utf8,
    "abundance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# MetaPhlAn-style lineage prefixes, root to leaf.
_RANK_BY_PREFIX = {
    "d": "domain",
    "k": "kingdom",
    "p": "phylum",
    "c": "class",
    "o": "order",
    "f": "family",
    "g": "genus",
    "s": "species",
    "t": "strain",
}

_READ_SUFFIXES = (
    ".fastq.gz",
    ".fq.gz",
    ".fastq",
    ".fq",
    "_1.unmapped_other",
    "_1.unmapped",
    "_2.unmapped",
    ".unmapped_other",
    ".unmapped",
    ".merged",
    "_1",
    "_2",
)


def _sample_expr(column: pl.Expr) -> pl.Expr:
    for suffix in _READ_SUFFIXES:
        column = column.str.strip_suffix(suffix)
    return column


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt the merged report and read the rank off each lineage's leaf prefix."""
    wide = sources["merged"]
    if "clade_name" not in wide.columns:
        raise ValueError("sylph profile: no `clade_name` column in the merged report")

    sample_cols = [c for c in wide.columns if c != "clade_name"]
    if not sample_cols:
        raise ValueError("sylph profile: the merged report carries no per-sample columns")

    leaf = pl.col("clade_name").str.split("|").list.last()

    long = (
        wide.with_columns(pl.col(c).cast(pl.Float64, strict=False) for c in sample_cols)
        .unpivot(
            index=["clade_name"],
            on=sample_cols,
            variable_name="sample_id",
            value_name="abundance",
        )
        .drop_nulls("abundance")
        .filter(pl.col("abundance") > 0)
        .with_columns(
            _sample_expr(pl.col("sample_id").cast(pl.Utf8)).alias("sample_id"),
            leaf.str.split_exact("__", 1)
            .struct.field("field_0")
            .replace_strict(_RANK_BY_PREFIX, default="unknown")
            .alias("rank"),
            leaf.str.split_exact("__", 1)
            .struct.field("field_1")
            .fill_null(leaf)
            .str.replace_all("_", " ")
            .alias("taxon"),
        )
    )
    if long.is_empty():
        raise ValueError("sylph profile: the merged report had no positive abundance")

    return long.select("sample_id", "clade_name", "taxon", "rank", "abundance").sort(
        ["sample_id", "rank", "abundance"], descending=[False, False, True]
    )
