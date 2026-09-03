"""Transform QIIME2 barplot CSV (wide) to long-format taxonomy composition table."""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.lineage import kingdom_phylum

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="barplot_csv",
        path="qiime2/barplot/level-2.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "taxonomy": pl.Utf8,
    "count": pl.Float64,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
}
# Metadata columns (e.g. habitat) are user-defined and passed through dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt wide barplot CSV to long format with taxonomy and counts.

    The barplot CSV embeds metadata columns (index, habitat, etc.) alongside
    taxonomy count columns.  Taxonomy columns are detected by QIIME2 convention:
    their column names contain semicolons (e.g. ``Bacteria;Proteobacteria``).
    Everything else (except ``index``) is treated as metadata and passed through.
    """
    df = sources["barplot_csv"]

    # Detect taxonomy columns by QIIME2 convention: column NAMES contain ";"
    # (lineage format like Bacteria;Proteobacteria). Cell values are numeric counts.
    taxonomy_cols: list[str] = []
    metadata_cols: list[str] = []
    for col in df.columns:
        if col == "index":
            continue
        if ";" in col:
            taxonomy_cols.append(col)
        else:
            metadata_cols.append(col)

    if not taxonomy_cols:
        raise ValueError(
            "No taxonomy columns found in barplot CSV (expected QIIME2 lineage format with ';')"
        )

    # Preserve metadata columns alongside index before melting
    keep_cols = ["index"] + metadata_cols

    # Melt to long format
    df = df.unpivot(on=taxonomy_cols, index=keep_cols, variable_name="taxonomy", value_name="count")
    df = df.rename({"index": "sample"})
    df = df.with_columns(pl.col("count").cast(pl.Float64))

    # Filter out zero/null counts
    df = df.filter(pl.col("count").is_not_null() & (pl.col("count") > 0))

    # Split the lineage back into ranks. The barplot export carries the whole
    # lineage in the column *name*, so the ranks only exist once it is melted —
    # and a taxon-count chart is read by rank, not by lineage string. Mirrors
    # nf-core/ampliseq/taxonomy_rel_abundance.py, which splits the same strings.
    #
    # Read from the tail, not by absolute position: the template points this
    # recipe at whichever barplot level *is* Phylum for the run's reference
    # database (level 2 for a 7-rank database, level 3 for an 8-rank one such as
    # sbdi-gtdb), and the leaf of that lineage is the Phylum either way.
    df = df.with_columns(kingdom_phylum(pl.col("taxonomy")))

    # Core columns first, then any metadata columns appended
    core = ["sample", "taxonomy", "count", "Kingdom", "Phylum"]
    return df.select(core + metadata_cols)
