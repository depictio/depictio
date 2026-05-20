"""Canonical-schema sunburst DC for ampliseq.

Pulls from the QIIME2 Genus-level rel-abundance table (rel-table-6.tsv) and
joins the sample → habitat metadata so the sunburst can include Habitat as
an inner ring. Output columns expose the full Habitat + 6-rank lineage so
the dashboard can configure ``rank_cols`` to any subset.

Schema for ``sunburst`` is permissive — only ``abundance`` is role-validated;
the rank columns are specified per-tile via ``rank_cols`` in SunburstConfig.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="genus", dc_ref="rel_abundance_genus"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
    "abundance": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "Habitat": pl.Utf8,
    "Class": pl.Utf8,
    "Order": pl.Utf8,
    "Family": pl.Utf8,
    "Genus": pl.Utf8,
    "sample_id": pl.Utf8,
}

_METADATA_ID_COL = "sample"
_RANKS_BY_POSITION = ["Kingdom", "Phylum", "Class", "Order", "Family", "Genus"]


def _parse_rank_at(lineage: pl.Expr, position: int) -> pl.Expr:
    """Take the ``position``-th ``;``-separated segment from a QIIME2 lineage
    string. Returns 'Unclassified' for missing / empty segments."""
    seg = lineage.str.split(";").list.get(position, null_on_oob=True).str.strip_chars()
    return (
        pl.when(seg.is_null() | (seg == ""))
        .then(pl.lit("Unclassified"))
        .otherwise(seg)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot the Genus-level wide table + parse lineage + optional habitat join."""
    wide = sources["genus"]
    if wide is None or wide.is_empty():
        raise ValueError("ampliseq sunburst: rel-table-6 (Genus) source required")

    lineage_col = wide.columns[0]
    sample_cols = [c for c in wide.columns if c != lineage_col]

    long = wide.unpivot(
        on=sample_cols,
        index=[lineage_col],
        variable_name="sample_id",
        value_name="abundance",
    )
    rank_exprs = [
        _parse_rank_at(pl.col(lineage_col), i).alias(name)
        for i, name in enumerate(_RANKS_BY_POSITION)
    ]
    long = (
        long.with_columns(rank_exprs)
        .drop(lineage_col)
        .with_columns(
            pl.col("sample_id").cast(pl.Utf8),
            pl.col("abundance").cast(pl.Float64, strict=False),
        )
        .filter(pl.col("abundance") > 0)
    )

    metadata = sources.get("metadata")
    if metadata is not None and "habitat" in metadata.columns:
        sample_col = next(
            (c for c in (_METADATA_ID_COL, "ID", "sample_id") if c in metadata.columns), None
        )
        if sample_col is not None:
            sample_to_habitat = (
                metadata.select(sample_col, "habitat")
                .unique(subset=[sample_col])
                .rename({sample_col: "sample_id", "habitat": "Habitat"})
                .with_columns(pl.col("Habitat").cast(pl.Utf8))
            )
            long = long.join(sample_to_habitat, on="sample_id", how="left")

    keep = [
        c
        for c in (
            "sample_id",
            "Habitat",
            "Kingdom",
            "Phylum",
            "Class",
            "Order",
            "Family",
            "Genus",
            "abundance",
        )
        if c in long.columns
    ]
    return long.select(keep)
