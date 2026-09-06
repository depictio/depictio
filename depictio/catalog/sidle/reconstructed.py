"""Melt the SIDLE cross-region reconstructed feature table to long per-sample taxonomy.

SIDLE reconstructs one feature table from per-region ASVs.
``reconstructed_merged.tsv`` carries one row per reconstructed feature with its
taxonomy and one count column per sample (ID, Taxon, <sample columns...>).
Melting it to the canonical sample / taxonomy / count long shape lets a
dashboard render the multi-region composition with the same components it uses
for a single-region barplot.

Output schema:
    feature_id : Utf8   reconstructed feature the count belongs to
    sample : Utf8       sample the count came from
    count : Float64     reconstructed count, zeros dropped
    taxonomy : Utf8     the full Greengenes-style lineage string
    Kingdom : Utf8      rank column, ``Unclassified`` when unresolved
    Phylum : Utf8       rank column, ``Unclassified`` when unresolved
    Class : Utf8        rank column, ``Unclassified`` when unresolved
    Genus : Utf8        rank column, ``Unclassified`` when unresolved
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reconstructed",
        path="sidle/reconstructed/reconstructed_merged.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "sample": pl.Utf8,
    "count": pl.Float64,
    "taxonomy": pl.Utf8,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
    "Class": pl.Utf8,
    "Genus": pl.Utf8,
}

# Greengenes-style rank prefixes; lower ranks are repeat-filled when unresolved, so a
# rank is only "real" when a token actually carries its prefix (regex-extracted below).
_RANKS: dict[str, str] = {"Kingdom": "k__", "Phylum": "p__", "Class": "c__", "Genus": "g__"}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot per-sample count columns and split taxonomy into rank columns."""
    df = sources["reconstructed"].rename({"ID": "feature_id", "Taxon": "taxonomy"})

    sample_cols = [c for c in df.columns if c not in ("feature_id", "taxonomy")]
    df = df.with_columns(pl.col(sample_cols).cast(pl.Float64, strict=False))
    df = df.unpivot(
        on=sample_cols,
        index=["feature_id", "taxonomy"],
        variable_name="sample",
        value_name="count",
    )
    df = df.filter(pl.col("count").is_not_null() & (pl.col("count") > 0))
    df = df.with_columns(
        pl.col("taxonomy")
        .str.extract(rf"{prefix}([^;]+)")
        .str.strip_chars()
        .replace("", None)
        .fill_null("Unclassified")
        .alias(rank)
        for rank, prefix in _RANKS.items()
    )
    return df.select(list(EXPECTED_SCHEMA.keys()))
