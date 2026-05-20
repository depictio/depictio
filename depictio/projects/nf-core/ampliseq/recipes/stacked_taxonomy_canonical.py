"""Canonical-schema stacked-taxonomy DC for ampliseq.

Consumes QIIME2 ``rel_abundance_tables/rel-table-{2..6}.tsv`` — one per
taxonomic level (Phylum=2 … Genus=6) — and emits one long-format row per
(sample, rank, taxon, abundance). The stacked-taxonomy renderer's
``default_rank`` dropdown can then switch between Kingdom (aggregated),
Phylum, Class, Order, Family and Genus without reloading.

Canonical schema (see depictio/models/components/advanced_viz/schemas.py):
    sample_id : Utf8
    taxon : Utf8
    rank : Utf8
    abundance : Float64

Optional roles:
    lineage : Utf8 — full ``Kingdom;Phylum;…`` lineage string
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="phylum", dc_ref="rel_abundance_phylum"),
    RecipeSource(ref="class_", dc_ref="rel_abundance_class"),
    RecipeSource(ref="order", dc_ref="rel_abundance_order"),
    RecipeSource(ref="family", dc_ref="rel_abundance_family"),
    RecipeSource(ref="genus", dc_ref="rel_abundance_genus"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

_METADATA_ID_COL = "sample"  # `Metadata_full.tsv` calls the sample col "sample"

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "taxon": pl.Utf8,
    "rank": pl.Utf8,
    "abundance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "lineage": pl.Utf8,
    "habitat": pl.Utf8,
}

# QIIME2 collapse level → human-readable rank. Level 1 (Kingdom) is added
# server-side by aggregating Phylum rows; QIIME2 emits rel-table-2 (Phylum)
# through rel-table-6 (Genus) by default in ampliseq runs.
_LEVEL_TO_RANK = {
    2: "Phylum",
    3: "Class",
    4: "Order",
    5: "Family",
    6: "Genus",
}


def _unpivot_level(wide: pl.DataFrame, rank: str) -> pl.DataFrame:
    """Convert a QIIME2 rel-table-X (wide, taxa × samples) to long format.

    The TSV has a header comment line ``# Constructed from biom file`` which
    the generator strips before calling this. The first column is
    ``#OTU ID`` (the full Kingdom;…;<rank> lineage); the remaining columns
    are per-sample relative abundances.
    """
    lineage_col = wide.columns[0]
    sample_cols = [c for c in wide.columns if c != lineage_col]
    long = wide.unpivot(
        on=sample_cols,
        index=[lineage_col],
        variable_name="sample_id",
        value_name="abundance",
    )
    # taxon = leaf segment of the lineage string (e.g. "Gammaproteobacteria"
    # from "Bacteria;Proteobacteria;Gammaproteobacteria"). Drops empty leaves
    # (lineages ending in ";") to keep "Unclassified;" rows usable downstream
    # without bleeding into the visible bars at every level.
    return long.with_columns(
        pl.col(lineage_col).str.split(";").list.last().str.strip_chars().alias("taxon"),
        pl.col(lineage_col).alias("lineage"),
        pl.lit(rank).alias("rank"),
        pl.col("sample_id").cast(pl.Utf8),
        pl.col("abundance").cast(pl.Float64, strict=False),
    ).select("sample_id", "taxon", "rank", "abundance", "lineage")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Combine 5 rank-level rel-tables + a derived Kingdom level."""
    pieces: list[pl.DataFrame] = []

    # Map source ref → (rank, level). We tolerate missing levels (e.g. if the
    # pipeline didn't emit a deeper collapse) by skipping them rather than
    # failing the whole recipe.
    level_specs = (
        ("phylum", "Phylum"),
        ("class_", "Class"),
        ("order", "Order"),
        ("family", "Family"),
        ("genus", "Genus"),
    )

    for ref, rank in level_specs:
        wide = sources.get(ref)
        if wide is None or wide.is_empty():
            continue
        pieces.append(_unpivot_level(wide, rank))

    if not pieces:
        raise ValueError(
            "ampliseq stacked_taxonomy: no rel-table inputs found "
            f"(expected one of {[s[0] for s in level_specs]})"
        )

    long = pl.concat(pieces, how="vertical")

    # Derive Kingdom by summing Phylum-level rows per (sample, kingdom).
    # Kingdom is the first ";"-separated lineage segment.
    if "Phylum" in long["rank"].unique().to_list():
        phylum_rows = long.filter(pl.col("rank") == "Phylum")
        kingdom = (
            phylum_rows.with_columns(
                pl.col("lineage").str.split(";").list.first().str.strip_chars().alias("taxon")
            )
            .group_by(["sample_id", "taxon"])
            .agg(pl.col("abundance").sum())
            .with_columns(
                pl.lit("Kingdom").alias("rank"),
                pl.col("taxon").alias("lineage"),
            )
            .select("sample_id", "taxon", "rank", "abundance", "lineage")
        )
        long = pl.concat([kingdom, long], how="vertical")

    long = long.with_columns(pl.col("taxon").cast(pl.Utf8))

    # Optional habitat join + sort. The StackedTaxonomy renderer's default
    # ``sample sort`` mode is ``input`` (preserves the row order it reads
    # from the DC), so sorting the recipe output by (habitat, sample_id)
    # makes the rendered bars group adjacently per habitat — easier to read
    # cross-habitat composition shifts than alphabetical sample IDs.
    metadata = sources.get("metadata")
    if metadata is not None and "habitat" in metadata.columns:
        sample_col = next(
            (c for c in (_METADATA_ID_COL, "ID", "sample_id") if c in metadata.columns), None
        )
        if sample_col is not None:
            sample_to_habitat = (
                metadata.select(sample_col, "habitat")
                .unique(subset=[sample_col])
                .rename({sample_col: "sample_id"})
                .with_columns(pl.col("habitat").cast(pl.Utf8))
            )
            long = long.join(sample_to_habitat, on="sample_id", how="left").sort(
                ["habitat", "sample_id", "rank"]
            )

    return long
