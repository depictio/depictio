"""Gene by sample ARG hit matrix for a clustered heatmap.

Pivots the hAMRonization combined report into one row per gene symbol with
one numeric column per sample holding the number of hits, plus the gene's
most frequent ``drug_class`` as a categorical row annotation. Genes and
samples are discovered from the report, so the sample columns are dynamic;
only the two leading columns are fixed.

Output columns:
    gene_symbol, drug_class, <one Float64 column per sample>
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


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count hits per (gene, sample) and pivot samples into columns."""
    df = sources["report"].select(
        _sample(pl.col("input_file_name").cast(pl.Utf8)).alias("sample"),
        pl.col("gene_symbol").cast(pl.Utf8),
        pl.col("drug_class").cast(pl.Utf8).fill_null("unclassified"),
    )
    annotation = df.group_by("gene_symbol").agg(pl.col("drug_class").mode().first())
    counts = df.group_by("gene_symbol", "sample").agg(pl.len().cast(pl.Float64).alias("hits"))
    matrix = counts.pivot(on="sample", index="gene_symbol", values="hits").fill_null(0.0)
    sample_cols = sorted(c for c in matrix.columns if c != "gene_symbol")
    return (
        annotation.join(matrix, on="gene_symbol", how="inner")
        .select("gene_symbol", "drug_class", *sample_cols)
        .sort("gene_symbol")
    )
