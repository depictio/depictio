"""SILVA + PR2 merged taxonomy of the ASVs, with the SILVA run's abundances.

For a project that ran nf-core/ampliseq twice on the same reads, once against
SILVA (the ingested run, ``DATA_ROOT``) and once against PR2 (``PR2_RESULTS``):
each ASV takes PR2's lineage when PR2 calls it Eukaryota, else SILVA's. The
rule, the rank mapping and its PR2 rank shift are in
``depictio/recipes/lib/dual_taxonomy.py``.

The output is the SILVA run's ``rel-table-ASV_with-DADA2-tax.tsv`` with merged
rank columns, without the sequences, plus ``taxonomy_source``. The taxonomy
recipes of the template (tip metadata, sunburst, sankey, Phylum relative
abundance, stacked taxonomy) read it when it exists in place of the SILVA
tables, so every taxonomy view of the project shows the merged names, and the
views built on those (heatmaps, UpSet, PCoA, Bray-Curtis) follow.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.dual_taxonomy import (
    DEFAULT_EUK_PHYLUM_RANK,
    PR2_RANKS,
    SLOTS,
    SOURCE_COLUMN,
    merge_pr2,
)
from depictio.recipes.lib.lineage import asv_sample_columns, with_kingdom

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="asv_tax",
        path="qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv",
        format="TSV",
        input_schema={"ID": pl.Utf8},
        # Text only, cast at the point of use (see tree_metadata_canonical.py).
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="pr2_tax",
        # The PR2 run's table of the same name; the template points this at
        # {PR2_RESULTS}/qiime2/rel_abundance_tables/. Only its taxonomy is read.
        path="pr2/qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv",
        format="TSV",
        input_schema={"ID": pl.Utf8, "Domain": pl.Utf8},
        read_kwargs={"infer_schema_length": 0, "columns": ["ID", *PR2_RANKS, "confidence"]},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "ID": pl.Utf8,
    SOURCE_COLUMN: pl.Utf8,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
}
# One Float64 column per sample follows the ranks; samples are run-specific.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "Class": pl.Utf8,
    "Order": pl.Utf8,
    "Family": pl.Utf8,
    "Genus": pl.Utf8,
    "Species": pl.Utf8,
    "confidence": pl.Float64,
}


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Merge the two runs' taxonomies over the SILVA run's ASV table."""
    # ampliseq >= 3.0 may name SILVA's top rank Domain: read it as the Kingdom.
    asv = with_kingdom(sources["asv_tax"])
    euk_rank = (params or {}).get("euk_phylum_rank") or DEFAULT_EUK_PHYLUM_RANK
    merged = merge_pr2(asv, sources["pr2_tax"], euk_rank)
    if merged.height != asv.height:  # pragma: no cover - a left join on unique ids
        raise ValueError("the PR2 join changed the ASV count")
    samples = asv_sample_columns(merged)
    return merged.select(
        "ID",
        SOURCE_COLUMN,
        *SLOTS,
        "confidence",
        *[pl.col(s).cast(pl.Float64, strict=False) for s in samples],
    )
