"""Tidy ampliseq's ``overall_summary.tsv`` into per-sample read counts and the share kept.

ampliseq writes one row per sample tracking reads through every step it ran:
cutadapt (``cutadapt_total_processed``, ``cutadapt_passing_filters``), DADA2
(``DADA2_input`` ... ``nonchim``) and the optional filters that follow (decontam
``isContaminant_output``, barrnap ``ssufilter_output``, length ``lenfilter_output``,
taxa ``filtered_tax_filter``). Which of those columns exist depends on the route:
a PacBio, IonTorrent or single-end run stops at ``nonchim``, a multiregion run
writes NA for the taxa filter.

The pipeline's own ``retained_percent`` is the share kept by the taxa filter
alone, not by the whole run, and only some routes write it. The recipe derives
the run-level share instead: ``final_reads`` is the last step's output each row
has a value for, and ``kept_percent`` is that over the reads that entered.

Counts arrive as text with thousands separators (``99,321``), so every column is
read as a string and cleaned before the cast.

Output columns:
    sample, input_reads, trimmed_reads, denoised_reads, final_reads, kept_percent
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# Step outputs after DADA2's chimera removal, in pipeline order. The last one a
# row has a value for is what the run kept.
_FILTER_OUTPUTS = (
    "isContaminant_output",
    "ssufilter_output",
    "lenfilter_output",
    "filtered_tax_filter",
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="overall_summary.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", ""]},
        input_schema={"sample": pl.Utf8, "nonchim": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "input_reads": pl.Int64,
    "denoised_reads": pl.Int64,
    "final_reads": pl.Int64,
    "kept_percent": pl.Float64,
}
# Absent when the run skipped cutadapt (--skip_cutadapt).
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "trimmed_reads": pl.Int64,
}


def _count(column: str) -> pl.Expr:
    """``"99,321"`` -> ``99321``; a value that is not a count becomes null."""
    return pl.col(column).str.replace_all(",", "").cast(pl.Int64, strict=False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Per-sample input, trimmed, denoised and final read counts plus the share kept."""
    df = sources["summary"]
    cols = set(df.columns)

    input_col = "cutadapt_total_processed" if "cutadapt_total_processed" in cols else "DADA2_input"
    outputs = [c for c in _FILTER_OUTPUTS if c in cols]
    # Latest step first, so the coalesce lands on the last one with a value.
    final = pl.coalesce([_count(c) for c in reversed(outputs)] + [_count("nonchim")])

    columns = [
        pl.col("sample"),
        _count(input_col).alias("input_reads"),
        _count("nonchim").alias("denoised_reads"),
        final.alias("final_reads"),
    ]
    if "cutadapt_passing_filters" in cols:
        columns.insert(2, _count("cutadapt_passing_filters").alias("trimmed_reads"))

    out = df.select(columns)
    return out.with_columns(
        pl.when(pl.col("input_reads") > 0)
        .then(pl.col("final_reads") / pl.col("input_reads") * 100)
        .otherwise(None)
        .cast(pl.Float64)
        .alias("kept_percent")
    )
