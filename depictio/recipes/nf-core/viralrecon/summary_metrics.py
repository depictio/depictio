"""Parse viralrecon summary_variants_metrics_mqc.csv into a clean per-sample metrics table."""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary_raw",
        path="multiqc/summary_variants_metrics_mqc.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "num_reads_mapped": pl.Float64,
    "pct_reads_mapped": pl.Float64,
    "coverage_median": pl.Float64,
    "pct_genome_covered_1x": pl.Float64,
    "pct_genome_covered_10x": pl.Float64,
    "num_variants_snp": pl.Float64,
    "num_variants_indel": pl.Float64,
    "num_variants_total": pl.Float64,
    "lineage": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Normalize summary metrics CSV: rename columns, cast types."""
    df = sources["summary_raw"]

    # The summary CSV uses 'Sample' as the identifier column
    if "Sample" in df.columns:
        df = df.rename({"Sample": "sample"})

    # Build a rename mapping for common column patterns in the summary CSV
    rename_map = {}
    for col_name in df.columns:
        col_lower = col_name.lower().replace(" ", "_").replace("%", "pct")
        # Map known columns
        if "mapped_reads" in col_lower or "reads_mapped" in col_lower:
            if "%" in col_name or "pct" in col_lower:
                rename_map[col_name] = "pct_reads_mapped"
            elif col_name not in rename_map.values():
                rename_map[col_name] = "num_reads_mapped"
        elif "median" in col_lower and "coverage" in col_lower:
            rename_map[col_name] = "coverage_median"
        elif ("1x" in col_lower or "1X" in col_name) and "coverage" in col_lower:
            rename_map[col_name] = "pct_genome_covered_1x"
        elif ("10x" in col_lower or "10X" in col_name) and "coverage" in col_lower:
            rename_map[col_name] = "pct_genome_covered_10x"
        elif "snp" in col_lower and ("num" in col_lower or "count" in col_lower or "#" in col_name):
            rename_map[col_name] = "num_variants_snp"
        elif "indel" in col_lower and (
            "num" in col_lower or "count" in col_lower or "#" in col_name
        ):
            rename_map[col_name] = "num_variants_indel"
        elif "lineage" in col_lower:
            rename_map[col_name] = "lineage"

    if rename_map:
        df = df.rename(rename_map)

    # Cast numeric columns
    num_cols = [
        "num_reads_mapped",
        "pct_reads_mapped",
        "coverage_median",
        "pct_genome_covered_1x",
        "pct_genome_covered_10x",
        "num_variants_snp",
        "num_variants_indel",
    ]
    for col_name in num_cols:
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).cast(pl.Float64, strict=False))

    # Compute total variants if not present
    if "num_variants_total" not in df.columns:
        if "num_variants_snp" in df.columns and "num_variants_indel" in df.columns:
            df = df.with_columns(
                (
                    pl.col("num_variants_snp").fill_null(0)
                    + pl.col("num_variants_indel").fill_null(0)
                )
                .cast(pl.Float64)
                .alias("num_variants_total")
            )

    # Fill null lineage
    if "lineage" in df.columns:
        df = df.with_columns(pl.col("lineage").fill_null("Unassigned"))

    # Select available columns
    keep_cols = [
        "sample",
        "num_reads_mapped",
        "pct_reads_mapped",
        "coverage_median",
        "pct_genome_covered_1x",
        "pct_genome_covered_10x",
        "num_variants_snp",
        "num_variants_indel",
        "num_variants_total",
        "lineage",
    ]
    available = [c for c in keep_cols if c in df.columns]
    return df.select(available)
