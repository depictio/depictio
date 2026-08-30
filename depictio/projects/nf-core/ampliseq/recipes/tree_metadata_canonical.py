"""Tip metadata for the ampliseq phylogenetic tree.

Builds a joinable tip-metadata table whose ``taxon`` matches the ASV-hash tip
labels in tree.nwk, with the taxonomy split into per-rank columns the
phylogenetic renderer can use for tip colouring / labelling.

Reads whichever taxonomy artefact the run actually produced. ampliseq emits
different ones depending on the classifier and whether taxonomy was supplied as
input rather than assigned, and a recipe bound to only one of them leaves the
Phylogeny tab empty on every other route:

* ``rel-table-ASV_with-DADA2-tax.tsv`` — preferred. Ranks are already split into
  columns, confidence is a column, and the per-sample abundances sit in the same
  frame, so the dominant-group call needs no second source.
* ``qiime2/taxonomy/taxonomy.tsv`` — the classifier's own table, a ``Taxon``
  lineage string to parse. Both dialects are handled: Greengenes-style
  ``k__Bacteria; p__…`` prefixes, and prefix-less SILVA-style ``Bacteria;…``.
  ``Confidence`` may be a column, a trailing field of the lineage string, or
  absent entirely.

A run can carry far more ASVs than a tree is readable at: this one has
127,845 tips against the reference dataset's 2,683. Where the abundances are
available the table is capped to the ``MAX_TIPS`` most abundant ASVs, and
``prune_newick.py`` cuts tree.nwk to the same set at ingestion so tips and
metadata stay in step.

Output schema:
    taxon : Utf8 — ASV hash (matches tree.nwk tip names)
    Kingdom … Species : Utf8
    confidence : Float64
    label : Utf8 — short display label (Phylum if known, else taxon[:8])
    dominant_habitat : Utf8 — group carrying most of the ASV's abundance
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="asv_tax",
        path="qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv",
        format="TSV",
        # Read every column as text and cast at the point of use. A sample
        # column whose first few thousand ASVs are all absent looks like an
        # integer column until a relative abundance in scientific notation
        # turns up 40,000 rows later, and schema inference over a 90 MB table
        # never sees it. Nothing here needs an inferred numeric type: the ranks
        # are strings, and every numeric read below casts explicitly.
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
    RecipeSource(
        ref="taxonomy",
        path="qiime2/taxonomy/taxonomy.tsv",
        format="TSV",
        optional=True,
    ),
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

# Cap on the number of tips carried into the tree metadata. Ranking is by
# summed cohort abundance, so what survives is the community the run actually
# measured rather than an arbitrary slice. 3000 sits just above the reference
# dataset (2,683 tips), which therefore passes through untouched, and holds
# ~93% of the summed abundance on a 127k-ASV run. None disables the cap.
MAX_TIPS: int | None = 3000

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


# Columns of the ASV table that are not per-sample abundances.
_ASV_META_COLS = (
    "ID",
    "Kingdom",
    "Phylum",
    "Class",
    "Order",
    "Family",
    "Genus",
    "Species",
    "confidence",
    "sequence",
)

_RANKS = ("Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species")


def _blank_to_null(col: str) -> pl.Expr:
    """ampliseq writes unassigned ranks as empty strings, not nulls."""
    return pl.when(pl.col(col).str.strip_chars() == "").then(None).otherwise(pl.col(col)).alias(col)


def top_taxa(asv_tax: pl.DataFrame, max_tips: int) -> list[str]:
    """The `max_tips` ASV ids carrying the most abundance across the cohort.

    Shared with ``scripts/prune_newick.py``, which prunes tree.nwk to exactly
    this set. Two implementations of the same rule would drift, and a tree
    holding tips the metadata has dropped renders them unannotated.

    Ties break on the ASV id so the selection is reproducible across runs.
    """
    sample_cols = [c for c in asv_tax.columns if c not in _ASV_META_COLS]
    if not sample_cols:
        return asv_tax["ID"].to_list()
    ranked = (
        asv_tax.select(
            pl.col("ID"),
            pl.sum_horizontal(
                [pl.col(c).cast(pl.Float64, strict=False) for c in sample_cols]
            ).alias("total_abundance"),
        )
        .sort(["total_abundance", "ID"], descending=[True, False])
        .head(max_tips)
    )
    return ranked["ID"].to_list()


def _from_asv_table(asv: pl.DataFrame) -> pl.DataFrame:
    """Ranks are already columns here — only naming and blanks need work."""
    df = asv.rename({"ID": "taxon"})
    present = [r for r in _RANKS if r in df.columns]
    df = df.with_columns([_blank_to_null(r) for r in present])
    if "confidence" in df.columns:
        df = df.with_columns(pl.col("confidence").cast(pl.Float64, strict=False))
    return df.select(["taxon", *present, *(["confidence"] if "confidence" in df.columns else [])])


def _from_taxonomy_table(tax: pl.DataFrame) -> pl.DataFrame:
    """Parse a lineage string, in either dialect, into per-rank columns."""
    id_col = next((c for c in ("Feature ID", "feature_id", "taxon") if c in tax.columns), None)
    tax_col = next((c for c in ("Taxon", "taxon_string", "Taxonomy") if c in tax.columns), None)
    if id_col is None or tax_col is None:
        raise ValueError(f"taxonomy table needs an id and a lineage column; got {tax.columns}")
    df = tax.rename({id_col: "taxon", tax_col: "taxonomy_string"})

    prefixed = bool(df.select(pl.col("taxonomy_string").str.contains("k__").any()).item())
    if prefixed:
        rank_exprs = [
            pl.col("taxonomy_string")
            .str.extract(rf"{prefix}([^;]+)", 1)
            .str.strip_chars()
            .alias(rank)
            for rank, prefix in zip(
                _RANKS, ("k__", "p__", "c__", "o__", "f__", "g__", "s__"), strict=True
            )
        ]
    else:
        # Prefix-less: ranks are positional, semicolon-separated.
        parts = pl.col("taxonomy_string").str.split(";")
        rank_exprs = [
            parts.list.get(i, null_on_oob=True).str.strip_chars().alias(rank)
            for i, rank in enumerate(_RANKS)
        ]
    df = df.with_columns(rank_exprs).with_columns([_blank_to_null(r) for r in _RANKS])

    if "Confidence" in df.columns:
        conf = pl.col("Confidence").cast(pl.Float64, strict=False)
    else:
        # Some exports append confidence as a trailing field of the lineage
        # ("Bacteria;…;;1"). Non-numeric trailing fields cast to null, which is
        # the same answer as "no confidence recorded".
        conf = (
            pl.col("taxonomy_string")
            .str.split(";")
            .list.last()
            .str.strip_chars()
            .cast(pl.Float64, strict=False)
        )
    return df.with_columns(conf.alias("confidence")).select(["taxon", *_RANKS, "confidence"])


def _group_column(metadata: pl.DataFrame) -> str | None:
    """The metadata column samples are grouped by.

    `habitat` when the run has one, else the template's own convention: the
    first column is the sample id and the second is the grouping factor. Reading
    it positionally is what lets this work on a run whose factor is `locality`,
    `site` or anything else, instead of only on the reference dataset.
    """
    if "habitat" in metadata.columns:
        return "habitat"
    candidates = [c for c in metadata.columns if not c.startswith("depictio_")]
    return candidates[1] if len(candidates) > 1 else None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Build tip metadata from whichever taxonomy artefact the run produced."""
    asv_tax = sources.get("asv_tax")
    taxonomy = sources.get("taxonomy")

    if asv_tax is not None:
        df = _from_asv_table(asv_tax)
    elif taxonomy is not None:
        df = _from_taxonomy_table(taxonomy)
    else:
        raise ValueError(
            "no taxonomy source found: expected either "
            "qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv or "
            "qiime2/taxonomy/taxonomy.tsv under the run directory"
        )

    df = df.with_columns(
        pl.when(pl.col("Phylum").is_not_null() & (pl.col("Phylum") != ""))
        .then(pl.col("Phylum"))
        .otherwise(pl.col("taxon").str.slice(0, 8))
        .alias("label")
    )

    # The ASV table carries its own per-sample abundances; the classifier table
    # does not, so dominance is only available on the first route.
    asv_abundance = None
    if asv_tax is not None:
        sample_cols = [c for c in asv_tax.columns if c not in _ASV_META_COLS]
        if sample_cols:
            asv_abundance = asv_tax.select(["ID", *sample_cols])

    # Dominant-habitat derivation. When ASV abundance + sample metadata are
    # both available, compute per-ASV summed abundance by habitat and assign:
    #   - 'Rare'  → ASV total < _RARE_TOTAL_ABUNDANCE × cohort total
    #   - 'Mixed' → no single habitat ≥ _DOMINANCE_THRESHOLD of ASV total
    #   - <Habitat name> → the habitat carrying the largest share
    # ASVs that don't appear in the abundance table at all get
    # 'No abundance' (~75 % of the metadata DC for this run — they're
    # taxonomy-classified rep-seqs that dropped out before the OTU table).
    metadata = sources.get("metadata")
    group_col = _group_column(metadata) if metadata is not None else None
    if asv_abundance is not None and metadata is not None and group_col is not None:
        sample_col = next(
            (c for c in (_METADATA_ID_COL, "ID", "sample_id") if c in metadata.columns),
            metadata.columns[0] if metadata.columns else None,
        )
        if sample_col is not None and sample_col != group_col:
            sample_to_habitat = (
                metadata.select(sample_col, group_col)
                .unique(subset=[sample_col])
                .rename({sample_col: "sample_id", group_col: "habitat"})
            )

            # Unpivot the ASV × sample wide table to long form, then join the
            # habitat mapping. The lineage column is whatever name the source
            # CSV used (typically '#OTU ID' from the QIIME2 biom export).
            lineage_col = asv_abundance.columns[0]  # "ID"
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

    # Cap last, so the dominance call still sees the whole cohort: an ASV's
    # share of its habitat is a property of all the abundance recorded, not of
    # the subset that survives the cut.
    if asv_tax is not None and MAX_TIPS is not None and df.height > MAX_TIPS:
        df = df.filter(pl.col("taxon").is_in(top_taxa(asv_tax, MAX_TIPS)))

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
