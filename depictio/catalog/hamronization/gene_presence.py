"""Per sample and gene ARG presence: how many hits, how many tools agree.

Collapses the hAMRonization combined report to one row per (sample, gene
symbol). ``hits`` counts the reported hits, ``n_tools`` the distinct
screening tools that flagged the gene in that sample and ``tool_frac`` divides
it by the number of tools present in the whole report, so a dot plot's size
channel reads as cross-tool concordance. Mean identity / coverage are taken
over the hits that carry them (HMM-based tools such as fARGene report none).

Output columns:
    sample, gene_symbol, drug_class, hits, n_tools, tool_frac, mean_identity,
    mean_coverage
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
    "sample": pl.Utf8,
    "gene_symbol": pl.Utf8,
    "drug_class": pl.Utf8,
    "hits": pl.Float64,
    "n_tools": pl.Int64,
    "tool_frac": pl.Float64,
    "mean_identity": pl.Float64,
    "mean_coverage": pl.Float64,
}

# Same per-tool prefix stripping as hamronization/report.py (recipes do not
# import each other): nf-core hamronization modules name the input file after
# the sample plus a tool-specific tail.
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
    """Aggregate hits per (sample, gene) and score cross-tool support."""
    df = sources["report"]
    n_tools_total = df["analysis_software_name"].drop_nulls().str.to_lowercase().n_unique()

    base = df.select(
        _sample(pl.col("input_file_name").cast(pl.Utf8)).alias("sample"),
        pl.col("gene_symbol").cast(pl.Utf8),
        pl.col("drug_class").cast(pl.Utf8).fill_null("unclassified"),
        pl.col("analysis_software_name").cast(pl.Utf8).str.to_lowercase().alias("tool"),
        pl.col("sequence_identity").cast(pl.Float64, strict=False).alias("identity"),
        pl.col("coverage_percentage").cast(pl.Float64, strict=False).alias("coverage"),
    )
    return (
        base.group_by("sample", "gene_symbol")
        .agg(
            # The most frequent class label a gene carries across its hits.
            pl.col("drug_class").mode().first().alias("drug_class"),
            pl.len().cast(pl.Float64).alias("hits"),
            pl.col("tool").n_unique().cast(pl.Int64).alias("n_tools"),
            pl.col("identity").mean().alias("mean_identity"),
            pl.col("coverage").mean().alias("mean_coverage"),
        )
        .with_columns((pl.col("n_tools") / max(n_tools_total, 1)).alias("tool_frac"))
        .sort("sample", "gene_symbol")
        .select(list(EXPECTED_SCHEMA))
    )
