"""Gene by sample ARG hit matrix for a clustered heatmap.

Pivots the hAMRonization combined report into one row per gene symbol with
one numeric column per sample holding the number of hits, plus the gene's
most frequent ``drug_class`` and a short form of it as categorical row
annotations. Genes and samples are discovered from the report, so the sample
columns are dynamic; only the three leading columns are fixed.

Output columns:
    gene_symbol, drug_class, drug_class_primary, <one Float64 column per sample>
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="report",
        path="reports/hamronization_summarize/hamronization_combined_report.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_symbol": pl.Utf8,
    "drug_class": pl.Utf8,
    "drug_class_primary": pl.Utf8,
}

_TOOL_SUFFIX = r"(abricate|amrfinderplus|deeparg|fargene|rgi|resfinder|srax|staramr|kmerresistance|groot|ariba|csstar|tbprofiler|mykrobe|pointfinder|amrplusplus)"
_SAMPLE_STRIP_PATTERNS = [
    r"_retrieved-genes-.+-hmmsearched\.out(\.fargene)?$",
    r"\.mapping(\.potential)?\.ARG(\.deeparg)?$",
    r"\.(tsv|txt|csv|out|json|tab)\." + _TOOL_SUFFIX + r"$",
    r"\." + _TOOL_SUFFIX + r"$",
    r"\.(tsv|txt|csv|out|json|tab)$",
]


def _sample(col: pl.Expr) -> pl.Expr:
    for pattern in _SAMPLE_STRIP_PATTERNS:
        col = col.str.replace(pattern, "")
    return col


def _primary_class(col: pl.Expr) -> pl.Expr:
    """The leading drug class, short enough to label a heatmap annotation strip.

    hAMRonization passes each tool's own vocabulary through untouched, so the
    field arrives either semicolon separated and lower case from CARD
    ("macrolide antibiotic; lincosamide antibiotic; streptogramin antibiotic;
    ...", up to 126 characters) or slash separated and upper case from
    AMRFinderPlus ("LINCOSAMIDE/OXAZOLIDINONE/PHENICOL/..."). Plotly sizes an
    annotation strip's margin from its longest label, so binding the raw field
    makes the margin exceed the tile and the heatmap draws into a negative
    width. Taking the leading class and folding the two spellings together
    brings this run from 42 labels of up to 126 characters down to 29 of up to
    35, and keeps the full field on the row for the table to show.
    """
    return (
        col.str.split_exact(";", 1)
        .struct.field("field_0")
        .str.split_exact("/", 1)
        .struct.field("field_0")
        .str.strip_chars()
        .str.replace(r"(?i)\s+antibiotic$", "")
        .str.to_uppercase()
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count hits per (gene, sample) and pivot samples into columns."""
    df = sources["report"].select(
        _sample(pl.col("input_file_name").cast(pl.Utf8)).alias("sample"),
        pl.col("gene_symbol").cast(pl.Utf8),
        pl.col("drug_class").cast(pl.Utf8).fill_null("unclassified"),
    )
    annotation = df.group_by("gene_symbol").agg(pl.col("drug_class").mode().first())
    annotation = annotation.with_columns(
        _primary_class(pl.col("drug_class")).alias("drug_class_primary")
    )
    counts = df.group_by("gene_symbol", "sample").agg(pl.len().cast(pl.Float64).alias("hits"))
    matrix = counts.pivot(on="sample", index="gene_symbol", values="hits").fill_null(0.0)
    sample_cols = sorted(c for c in matrix.columns if c != "gene_symbol")
    return (
        annotation.join(matrix, on="gene_symbol", how="inner")
        .select("gene_symbol", "drug_class", "drug_class_primary", *sample_cols)
        .sort("gene_symbol")
    )
