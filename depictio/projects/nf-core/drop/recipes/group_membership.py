"""nf-core/drop analysis groups, one row per sample and group it belongs to.

``DROP_GROUP`` lists the analysis groups of a sample, comma-separated: the same
sample can feed an expression group and a splicing group, and a sample taken from
another study (external counts) joins the groups that borrow its counts. The sample
hub keeps one group per sample for the filters; this long table counts a sample
once per group, which is what the group sizes of the cohort tab need.

Sources:
    sheet   the run's sample sheet (the template repoints it at ``{SAMPLESHEET}``)

Output schema:
    sample : Utf8         RNA_ID, links to the sample hub
    drop_group : Utf8     one group of the sample's DROP_GROUP list
    count_source : Utf8   Alignment or External counts
    has_dna : Utf8        Genotyped or RNA only
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sheet",
        path="input/samplesheet.tsv",
        format="tsv",
        input_schema={"RNA_ID": pl.Utf8, "DROP_GROUP": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "drop_group": pl.Utf8,
    "count_source": pl.Utf8,
    "has_dna": pl.Utf8,
}


def _has(sheet: pl.DataFrame, column: str) -> pl.Expr:
    """Whether the sheet's cell of ``column`` holds a value (absent column: never)."""
    if column not in sheet.columns:
        return pl.lit(False)
    text = pl.col(column).cast(pl.Utf8).str.strip_chars()
    return text.is_not_null() & ~text.is_in(["", "NA"])


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Explode the DROP_GROUP list: one row per sample and group."""
    sheet = sources["sheet"]
    long = (
        sheet.select(
            pl.col("RNA_ID").cast(pl.Utf8).str.strip_chars().alias("sample"),
            pl.col("DROP_GROUP").cast(pl.Utf8).str.split(",").alias("drop_group"),
            pl.when(_has(sheet, "RNA_BAM_FILE"))
            .then(pl.lit("Alignment"))
            .otherwise(pl.lit("External counts"))
            .alias("count_source"),
            pl.when(_has(sheet, "DNA_VCF_FILE"))
            .then(pl.lit("Genotyped"))
            .otherwise(pl.lit("RNA only"))
            .alias("has_dna"),
        )
        .explode("drop_group")
        .with_columns(pl.col("drop_group").str.strip_chars())
        .filter(pl.col("sample").is_not_null() & (pl.col("drop_group") != ""))
        .unique(subset=["sample", "drop_group"], keep="first", maintain_order=True)
    )
    return long.select(list(OUTPUT_SCHEMA)).sort(["drop_group", "sample"])
