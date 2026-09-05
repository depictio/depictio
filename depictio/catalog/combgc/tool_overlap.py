"""Contig by tool membership matrix for an UpSet plot of BGC caller agreement.

One row per contig carrying at least one predicted biosynthetic gene cluster;
one 0/1 column per prediction tool comBGC merged (antiSMASH, DeepBGC, GECCO).
Agreement is scored on the contig rather than on the region coordinates: the
callers disagree on region boundaries by design, so a coordinate join would
report no overlap at all where the biology is the same cluster.

The tool columns are discovered from the report, so only the two leading
columns are fixed.

Output columns:
    contig, sample, <one 0/1 Int64 column per prediction tool>
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="reports/combgc/combgc_complete_summary.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""], "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contig": pl.Utf8,
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot (contig, tool) presence into a binary matrix."""
    df = (
        sources["summary"]
        .select(
            pl.col("sample_id").cast(pl.Utf8).alias("sample"),
            pl.col("contig_id").cast(pl.Utf8).alias("contig"),
            pl.col("Prediction_tool").cast(pl.Utf8).alias("tool"),
        )
        .drop_nulls(["contig", "tool"])
    )
    presence = df.group_by("contig", "sample", "tool").agg(pl.lit(1, dtype=pl.Int64).alias("v"))
    matrix = presence.pivot(on="tool", index=["contig", "sample"], values="v").fill_null(0)
    tool_cols = sorted(c for c in matrix.columns if c not in ("contig", "sample"))
    return matrix.select("contig", "sample", *[pl.col(c).cast(pl.Int64) for c in tool_cols]).sort(
        "sample", "contig"
    )
