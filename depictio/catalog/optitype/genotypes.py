"""OptiType HLA class I genotypes, one row per sample, locus and haplotype.

OptiType's ``<sample>_result.tsv`` is wide (``A1`` ... ``C2``); this melts the
optimal solution of each sample long, the shape the ``allele_grid`` kind and
any allele filter want: two rows per locus, one per haplotype, a homozygous
locus repeating its allele. The allele is normalised to ``HLA-A*02:01`` exactly
as the epitopeprediction recipes write theirs, so an allele picked here selects
the same string in a binding-prediction table. ``reads`` and ``objective`` are
the solution's, repeated on each of its rows.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.optitype import best_calls, read_calls, with_call_annotations

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="results",
        input_schema={"source_path": pl.Utf8, "Reads": pl.Utf8, "Objective": pl.Utf8},
        glob_pattern="optitype/*/*_result.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "call_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "locus": pl.Utf8,
    "haplotype": pl.Int64,
    "allele": pl.Utf8,
    "allele_group": pl.Utf8,
    "hla_class": pl.Utf8,
    "zygosity": pl.Utf8,
    "reads": pl.Int64,
    "objective": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    calls = best_calls(read_calls(sources["results"]))
    if calls.is_empty():
        raise ValueError("OptiType results: no sample has a typed locus")
    out = with_call_annotations(calls).with_columns(
        (
            pl.col("sample_id") + "|" + pl.col("locus") + "|" + pl.col("haplotype").cast(pl.Utf8)
        ).alias("call_id")
    )
    return out.select(list(OUTPUT_SCHEMA)).sort(["sample_id", "locus", "haplotype"])
