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
from depictio.recipes.lib.lineage import CANONICAL_RANKS, UNCLASSIFIED, asv_table_to_ranks

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="asv_tax",
        path="qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv",
        format="TSV",
        # Read every column as text and cast at the point of use: a sample
        # column whose first few thousand ASVs are all absent looks integer
        # until a relative abundance in scientific notation turns up later.
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
    RecipeSource(
        ref="genus",
        path="qiime2/rel_abundance_tables/rel-table-6.tsv",
        format="TSV",
        read_kwargs={"skip_rows": 1},
        # Fallback for runs without the DADA2 ASV table (QIIME2-only taxonomy).
        # Optional on both counts: level 6 is the Genus only for a 7-rank
        # reference database — under an 8-rank one (sbdi-gtdb) it is the Family,
        # which is why the ASV table above is preferred when present.
        optional=True,
    ),
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
_RANKS_BY_POSITION = list(CANONICAL_RANKS)


def _parse_rank_at(lineage: pl.Expr, position: int) -> pl.Expr:
    """Take the ``position``-th ``;``-separated segment from a QIIME2 lineage
    string. Returns 'Unclassified' for missing / empty segments."""
    seg = lineage.str.split(";").list.get(position, null_on_oob=True).str.strip_chars()
    return pl.when(seg.is_null() | (seg == "")).then(pl.lit(UNCLASSIFIED)).otherwise(seg)


def _from_collapsed_table(wide: pl.DataFrame) -> pl.DataFrame:
    """Fallback: unpivot a collapsed ``rel-table-N`` and split its lineage.

    Positional by necessity — the collapsed tables carry no rank names — so this
    is only correct for a 7-rank reference database, where level 6 is the Genus.
    """
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
    return (
        long.with_columns(rank_exprs)
        .drop(lineage_col)
        .with_columns(
            pl.col("sample_id").cast(pl.Utf8),
            pl.col("abundance").cast(pl.Float64, strict=False),
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Build the per-sample rank hierarchy, then join habitat when available.

    The ASV table is preferred: its ranks are named columns, so the hierarchy is
    correct whatever depth the run's reference database has. The collapsed
    Genus-level table stays as a fallback for runs that ship no DADA2 ASV table.
    """
    asv_tax = sources.get("asv_tax")
    genus = sources.get("genus")

    if asv_tax is not None and not asv_tax.is_empty():
        long = asv_table_to_ranks(asv_tax)
    elif genus is not None and not genus.is_empty():
        long = _from_collapsed_table(genus)
    else:
        raise ValueError(
            "ampliseq sunburst: no taxonomy source found — expected either "
            "qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv or a "
            "collapsed rel-table under the run directory"
        )

    long = long.filter(pl.col("abundance") > 0)

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
