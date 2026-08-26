"""Canonical-schema UpSet DC for ampliseq.

Derives a group × taxon presence-absence matrix from the long-format
``taxonomy_rel_abundance`` DC. Each row is one taxon; each column (one per
value of the grouping column — the dashboard's ``GROUP_COL``, e.g.
``habitat`` / ``treatment1``) is a binary indicator (1 = present above
``presence_threshold`` in any sample of that group). When metadata is absent
it falls back to a per-sample presence matrix.

Schema for ``upset_plot`` is permissive — the renderer picks up binary set
columns at compute time (``set_columns`` config field can override).
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="rel_abundance", dc_ref="taxonomy_rel_abundance"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "taxon": pl.Utf8,
}
# Habitat columns are dynamic (one per habitat value) — validated via OPTIONAL_SCHEMA = {}.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_METADATA_ID_COL = "ID"
_PRESENCE_THRESHOLD = 0.001  # 0.1% relative abundance — filter noise/sequencing artefacts


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot to taxon × habitat binary presence matrix."""
    df = sources["rel_abundance"].rename(
        {
            k: v
            for k, v in {"taxonomy": "taxon", "sample": "sample_id"}.items()
            if k in sources["rel_abundance"].columns
        }
    )

    metadata = sources.get("metadata")
    # Normalise the metadata id column: nf-core ampliseq uses `ID`, test fixtures use `sample`.
    if (
        metadata is not None
        and _METADATA_ID_COL not in metadata.columns
        and "sample" in metadata.columns
    ):
        metadata = metadata.rename({"sample": _METADATA_ID_COL})
    # GROUP_COL = first annotation column (first non-ID column), matching the CLI's
    # _auto_detect_metadata_columns convention; keep its real name as set labels.
    group_col = (
        next((c for c in metadata.columns if c != _METADATA_ID_COL), None)
        if metadata is not None
        else None
    )
    if metadata is None or group_col is None:
        # Fall back to per-sample presence/absence when metadata is unavailable.
        wide = df.filter(pl.col("rel_abundance") > _PRESENCE_THRESHOLD).pivot(
            values="rel_abundance",
            index="taxon",
            on="sample_id",
            aggregate_function="max",
        )
        set_cols = [c for c in wide.columns if c != "taxon"]
        wide = wide.with_columns(
            [pl.col(c).fill_null(0).cast(pl.Int8) for c in set_cols]
        ).with_columns([(pl.col(c) > 0).cast(pl.Int8) for c in set_cols])
        return _attach_taxon_annotations(wide, df)

    sample_to_group = metadata.rename({_METADATA_ID_COL: "sample_id"}).select(
        "sample_id", group_col
    )
    df = df.join(sample_to_group, on="sample_id", how="left")

    presence = (
        df.filter(pl.col("rel_abundance") > _PRESENCE_THRESHOLD)
        .group_by(["taxon", group_col])
        .agg(pl.lit(1, dtype=pl.Int8).alias("present"))
    )

    wide = presence.pivot(values="present", index="taxon", on=group_col, aggregate_function="max")
    set_cols = [c for c in wide.columns if c != "taxon"]
    wide = wide.with_columns([pl.col(c).fill_null(0).cast(pl.Int8) for c in set_cols])
    return _attach_taxon_annotations(wide, df, exclude=(group_col,))


def _attach_taxon_annotations(
    wide: pl.DataFrame, source: pl.DataFrame, exclude: tuple[str, ...] = ()
) -> pl.DataFrame:
    """Carry the source DC's per-taxon attributes onto the presence matrix.

    Without this the matrix is `taxon` + one binary column per group, and a
    dashboard filter on a taxonomic rank (`Kingdom`, `Phylum`) has nothing to
    bite on: the rank columns live on the source DC, so the filter is skipped
    and the UpSet quietly ignores it. Carrying them across makes the same
    filter narrow the matrix rows, and makes each rank available as an
    annotation track.

    Which columns come across is derived, not listed: a taxon attribute is a
    column that is CONSTANT within every taxon. Per-sample columns (the sample
    id, abundances) and the sample metadata joined in upstream (locality,
    season …) vary across the rows of a taxon and drop out on their own, which
    is what keeps this generic across pipelines and metadata schemas.
    """
    taxon_col = "taxon" if "taxon" in source.columns else None
    if taxon_col is None:
        return wide
    candidates = [
        c
        for c in source.columns
        if c not in exclude
        and c != taxon_col
        and c not in wide.columns
        and source.schema[c] == pl.Utf8
    ]
    if not candidates:
        return wide
    per_taxon = source.group_by(taxon_col).agg([pl.col(c).n_unique().alias(c) for c in candidates])
    constant = [c for c in candidates if per_taxon.get_column(c).max() == 1]
    if not constant:
        return wide
    annotations = source.select([taxon_col, *constant]).unique(subset=[taxon_col])
    return wide.join(annotations, on="taxon", how="left")
