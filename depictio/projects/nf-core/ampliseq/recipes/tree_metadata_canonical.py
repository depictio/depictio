"""Tip metadata for the ampliseq phylogenetic tree.

Parses the QIIME2 taxonomy.tsv (Feature ID / Taxon / Confidence) into a
joinable tip-metadata table where ``taxon`` matches the ASV-hash tip labels
in tree.nwk and the taxonomy string is split into per-rank columns the
phylogenetic renderer can use for tip colouring / labelling.

Output schema:
    taxon : Utf8 — ASV hash (matches tree.nwk tip names)
    Kingdom : Utf8
    Phylum : Utf8
    Class : Utf8
    Order : Utf8
    Family : Utf8
    Genus : Utf8
    Species : Utf8
    confidence : Float64
    label : Utf8 — short display label (Phylum if known, else taxon[:8])
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="taxonomy", dc_ref="qiime2_taxonomy"),
    RecipeSource(ref="asv_abundance", dc_ref="rel_abundance_asv", optional=True),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "taxon": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
    "Class": pl.Utf8,
    "Order": pl.Utf8,
    "Family": pl.Utf8,
    "Genus": pl.Utf8,
    "Species": pl.Utf8,
    "confidence": pl.Float64,
    "label": pl.Utf8,
    "dominant_habitat": pl.Utf8,
}

# Dominance threshold — if no single habitat accounts for at least this
# fraction of the ASV's total summed abundance, the ASV is labelled "Mixed"
# rather than getting an arbitrary winner. 0.6 matches the convention in the
# QIIME2 community for "habitat-specific" calls.
_DOMINANCE_THRESHOLD = 0.6
# ASVs with total abundance below this fraction of the cohort total are
# labelled "Rare" — they're statistically unstable for any habitat call.
_RARE_TOTAL_ABUNDANCE = 0.0001  # = 0.01% of the cohort-wide summed abundance

_METADATA_ID_COL = "sample"

_RANK_PREFIXES = (
    ("Kingdom", "k__"),
    ("Phylum", "p__"),
    ("Class", "c__"),
    ("Order", "o__"),
    ("Family", "f__"),
    ("Genus", "g__"),
    ("Species", "s__"),
)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse QIIME2 'k__X; p__Y; ...' Taxon string into per-rank columns."""
    df = sources["taxonomy"].rename({"Feature ID": "taxon", "Taxon": "taxonomy_string"})

    rank_exprs = [
        pl.col("taxonomy_string")
        .str.extract(rf"{prefix}([^;]+)", 1)
        .str.strip_chars()
        .alias(rank_name)
        for rank_name, prefix in _RANK_PREFIXES
    ]

    df = df.with_columns(rank_exprs).drop("taxonomy_string")

    df = df.with_columns(
        pl.col("Confidence").cast(pl.Float64, strict=False).alias("confidence"),
        pl.when(pl.col("Phylum").is_not_null() & (pl.col("Phylum") != ""))
        .then(pl.col("Phylum"))
        .otherwise(pl.col("taxon").str.slice(0, 8))
        .alias("label"),
    ).drop("Confidence")

    # Dominant-habitat derivation. When ASV abundance + sample metadata are
    # both available, compute per-ASV summed abundance by habitat and assign:
    #   - 'Rare'  → ASV total < _RARE_TOTAL_ABUNDANCE × cohort total
    #   - 'Mixed' → no single habitat ≥ _DOMINANCE_THRESHOLD of ASV total
    #   - <Habitat name> → the habitat carrying the largest share
    # ASVs that don't appear in the abundance table at all get
    # 'No abundance' (~75 % of the metadata DC for this run — they're
    # taxonomy-classified rep-seqs that dropped out before the OTU table).
    asv_abundance = sources.get("asv_abundance")
    metadata = sources.get("metadata")
    if asv_abundance is not None and metadata is not None and "habitat" in metadata.columns:
        sample_col = next(
            (c for c in (_METADATA_ID_COL, "ID", "sample_id") if c in metadata.columns),
            None,
        )
        if sample_col is not None:
            sample_to_habitat = (
                metadata.select(sample_col, "habitat")
                .unique(subset=[sample_col])
                .rename({sample_col: "sample_id"})
            )

            # Unpivot the ASV × sample wide table to long form, then join the
            # habitat mapping. The lineage column is whatever name the source
            # CSV used (typically '#OTU ID' from the QIIME2 biom export).
            lineage_col = asv_abundance.columns[0]
            value_cols = [c for c in asv_abundance.columns if c != lineage_col]
            long_abund = (
                asv_abundance.unpivot(
                    on=value_cols,
                    index=[lineage_col],
                    variable_name="sample_id",
                    value_name="abundance",
                )
                .rename({lineage_col: "taxon"})
                .with_columns(pl.col("abundance").cast(pl.Float64, strict=False))
                .filter(pl.col("abundance") > 0)
                .join(sample_to_habitat, on="sample_id", how="left")
            )

            # Per-ASV totals + per (ASV, habitat) sums.
            per_asv_total = long_abund.group_by("taxon").agg(
                pl.col("abundance").sum().alias("total_abundance")
            )
            cohort_total = float(per_asv_total["total_abundance"].sum() or 1.0)

            per_habitat = (
                long_abund.group_by(["taxon", "habitat"])
                .agg(pl.col("abundance").sum().alias("habitat_abundance"))
                .join(per_asv_total, on="taxon")
                .with_columns(
                    (pl.col("habitat_abundance") / pl.col("total_abundance")).alias("share")
                )
            )

            # Pick the top habitat per ASV; ties broken by alphabetical habitat
            # name (stable, deterministic).
            top_habitat = (
                per_habitat.sort(["share", "habitat"], descending=[True, False])
                .group_by("taxon", maintain_order=True)
                .agg(
                    pl.col("habitat").first().alias("top_habitat"),
                    pl.col("share").first().alias("top_share"),
                    pl.col("total_abundance").first().alias("total_abundance"),
                )
                .with_columns(
                    pl.when(pl.col("total_abundance") < _RARE_TOTAL_ABUNDANCE * cohort_total)
                    .then(pl.lit("Rare"))
                    .when(pl.col("top_share") < _DOMINANCE_THRESHOLD)
                    .then(pl.lit("Mixed"))
                    .otherwise(pl.col("top_habitat"))
                    .alias("dominant_habitat")
                )
                .select("taxon", "dominant_habitat")
            )

            df = df.join(top_habitat, on="taxon", how="left").with_columns(
                pl.col("dominant_habitat").fill_null("No abundance")
            )

    keep = [
        "taxon",
        "Kingdom",
        "Phylum",
        "Class",
        "Order",
        "Family",
        "Genus",
        "Species",
        "confidence",
        "label",
        "dominant_habitat",
    ]
    return df.select([c for c in keep if c in df.columns])
