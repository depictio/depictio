"""Transform QIIME2 relative abundance table to long-format per-sample taxonomy table.

When a metadata DC is present (--var METADATA_FILE=... provided to depictio-cli),
all metadata columns are joined generically. Without metadata, only the core
abundance + taxonomy columns are returned.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rel_table",
        path="qiime2/rel_abundance_tables/rel-table-2.tsv",
        format="TSV",
        read_kwargs={"skip_rows": 1},
    ),
    RecipeSource(
        ref="metadata",
        dc_ref="metadata",  # Reference the metadata DC (optional)
        optional=True,  # Absent when no --var METADATA_FILE was provided
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "taxonomy": pl.Utf8,
    "rel_abundance": pl.Float64,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
}
# Metadata columns are user-defined; validated dynamically via OPTIONAL_SCHEMA = {}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot wide abundance table and optionally join with all metadata columns."""
    df = sources["rel_table"]
    df = df.rename({"#OTU ID": "taxonomy"})

    sample_cols = [c for c in df.columns if c != "taxonomy"]
    df = df.with_columns(pl.col(sample_cols).cast(pl.Float64))
    df = df.unpivot(
        on=sample_cols, index="taxonomy", variable_name="sample", value_name="rel_abundance"
    )
    df = df.filter(pl.col("rel_abundance").is_not_null() & (pl.col("rel_abundance") > 0))
    df = df.with_columns(
        pl.col("taxonomy").str.split(";").list.get(0).alias("Kingdom"),
        pl.col("taxonomy").str.split(";").list.get(1).fill_null("Unclassified").alias("Phylum"),
    )

    # Join ALL metadata columns generically when metadata is available
    metadata = sources.get("metadata")
    if metadata is not None:
        metadata = metadata.rename({"ID": "sample"})
        df = df.join(metadata, on="sample", how="left")

    # Core columns first, then any metadata columns appended
    core = ["sample", "taxonomy", "rel_abundance", "Kingdom", "Phylum"]
    extra = [c for c in df.columns if c not in core]
    return df.select(core + extra)
