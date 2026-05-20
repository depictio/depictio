"""Canonical-schema Sankey DC for ampliseq.

Builds a true hierarchical Kingdom → Phylum → Class → Order → Family → Genus
flow from the QIIME2 ``rel_abundance_tables/rel-table-{2..6}.tsv`` outputs.
Previously this DC was sourced from ``taxonomy_rel_abundance``, which only
carries Phylum-level granularity — making the third Sankey step a literal
``"Kingdom;Phylum"`` concatenation that added no information beyond the
second step.

The deepest available table is ``rel-table-6`` (Genus). Each row in that
table is a full ``k__X;p__Y;c__Z;o__A;f__B;g__C`` lineage with a per-sample
relative-abundance vector. We unpivot, parse the lineage, and emit one
record per (sample, Genus) with the full ancestry filled in. The dashboard
tile's ``step_cols`` field then picks which ranks to wire as Sankey steps.

Output schema:
    sample_id : Utf8
    Kingdom : Utf8
    Phylum : Utf8
    Class : Utf8
    Order : Utf8
    Family : Utf8
    Genus : Utf8
    abundance : Float64
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="genus", dc_ref="rel_abundance_genus"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
    "abundance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "Class": pl.Utf8,
    "Order": pl.Utf8,
    "Family": pl.Utf8,
    "Genus": pl.Utf8,
    "Habitat": pl.Utf8,
}

_METADATA_ID_COL = "sample"

# QIIME2 ``rel_abundance_tables/rel-table-N.tsv`` lineage strings use the
# bare ``Bacteria;Proteobacteria;Gammaproteobacteria;...`` form (no
# ``k__/p__/...`` prefixes — those are stripped when biom→TSV happens in
# the ampliseq pipeline). Split positionally instead.
_RANKS_BY_POSITION = ["Kingdom", "Phylum", "Class", "Order", "Family", "Genus"]


def _parse_rank_at(lineage: pl.Expr, position: int) -> pl.Expr:
    """Take the ``position``-th ``;``-separated segment from a lineage string.

    Returns ``"Unclassified"`` when the segment is missing or empty (the
    source encodes unknown ranks as adjacent ``;`` characters — e.g.
    ``Bacteria;Proteobacteria;;;;`` for a Class-level-unknown row).
    """
    seg = lineage.str.split(";").list.get(position, null_on_oob=True).str.strip_chars()
    return pl.when(seg.is_null() | (seg == "")).then(pl.lit("Unclassified")).otherwise(seg)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot the QIIME2 rel-table-6 wide table into a long Sankey-ready DF."""
    wide = sources["genus"]
    if wide is None or wide.is_empty():
        # Defensive fallback to Phylum-only data if the deeper rel-tables
        # weren't bundled for this project.
        raise ValueError("ampliseq sankey: rel-table-6 (Genus) source required but missing")

    lineage_col = wide.columns[0]
    sample_cols = [c for c in wide.columns if c != lineage_col]

    long = wide.unpivot(
        on=sample_cols,
        index=[lineage_col],
        variable_name="sample_id",
        value_name="abundance",
    )

    # Parse the lineage string into per-rank columns by positional split.
    # Missing intermediate ranks (adjacent ``;``) cleanly resolve to
    # 'Unclassified'.
    rank_exprs = [
        _parse_rank_at(pl.col(lineage_col), i).alias(name)
        for i, name in enumerate(_RANKS_BY_POSITION)
    ]
    long = long.with_columns(rank_exprs).drop(lineage_col)

    long = long.with_columns(
        pl.col("sample_id").cast(pl.Utf8),
        pl.col("abundance").cast(pl.Float64, strict=False),
    )

    # Per-sample relative abundance sums to ~1.0 per sample. The Sankey
    # renderer (compute_sankey) sums weights across all matching rows when
    # grouping by step columns — so with N samples the cumulative flow into
    # the root would be ~N (e.g. 12.0 ≈ 1200%). Pre-divide by sample count
    # so the renderer's sum yields the mean-per-sample abundance, restoring
    # the natural 0-1 (0-100%) reading at the root.
    #
    # CAVEATS — this normalisation is RENDERER-COUPLED:
    #  1. Output is meaningful only under sum-aggregation viz (Sankey). Other
    #     consumers (table view, future bar/violin plots) will see abundance
    #     values that are mean-per-sample, not relative-per-sample.
    #  2. The divisor is computed at recipe time on the FULL sample set. A
    #     cross-DC sample filter (e.g. one habitat → 3 of 12 samples) does
    #     NOT recompute it — the renderer's sum then reads ~3/12 at the root
    #     instead of ~1.0. Acceptable today because all dashboards using
    #     this DC show the full sample universe; revisit if per-sample
    #     filtering becomes common.
    # Proper fix is moving the divisor into compute_sankey via a new
    # `normalise_by_col` payload field — left as follow-up.
    n_samples = long.select(pl.col("sample_id").n_unique()).item()
    if n_samples > 1:
        long = long.with_columns(pl.col("abundance") / n_samples)

    # Drop zero-abundance rows so the Sankey doesn't include hair-thin links
    # that visually clutter the diagram (and contribute nothing to flow).
    long = long.filter(pl.col("abundance") > 0)

    # Optional habitat join. The Sankey renderer's depth slider can then
    # include "Habitat" as one of the step columns, exposing how each
    # habitat partitions its abundance across the taxonomic tree — a view
    # the taxon-only Sankey can't show.
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
