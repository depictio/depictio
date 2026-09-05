"""Contig by tool membership matrix for an UpSet plot of ARG tool concordance.

Each row is a contig with at least one ARG hit; each tool column is 1 when
that screening tool reported a hit on the contig and 0 otherwise. Hits are
matched on the contig rather than on the gene symbol because every tool has
its own gene vocabulary (``ErmB`` / ``erm(B)`` / ``ERMB``), while the contig
id is shared. Prodigal-style ORF suffixes (``_<n>``) are stripped so
protein-level and contig-level reporters land on the same contig.

Output columns:
    contig, sample, <one 0/1 Int64 column per tool>
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
    "contig": pl.Utf8,
    "sample": pl.Utf8,
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
    """Pivot (contig, tool) presence into a binary matrix."""
    df = (
        sources["report"]
        .select(
            _sample(pl.col("input_file_name").cast(pl.Utf8)).alias("sample"),
            pl.col("input_sequence_id").cast(pl.Utf8).str.replace(r"_\d+$", "").alias("contig"),
            pl.col("analysis_software_name").cast(pl.Utf8).str.to_lowercase().alias("tool"),
        )
        .drop_nulls(["contig", "tool"])
    )
    presence = df.group_by("contig", "sample", "tool").agg(pl.lit(1, dtype=pl.Int64).alias("v"))
    matrix = presence.pivot(on="tool", index=["contig", "sample"], values="v").fill_null(0)
    tool_cols = sorted(c for c in matrix.columns if c not in ("contig", "sample"))
    return matrix.select("contig", "sample", *[pl.col(c).cast(pl.Int64) for c in tool_cols]).sort(
        "sample", "contig"
    )
