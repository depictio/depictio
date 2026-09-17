"""Top-expressed transcripts of Bambu's transcript-level count matrix.

``bambu`` writes ``counts_transcript.txt`` as a TSV: ``TXNAME``, ``GENEID`` (a
GTF-style attribute string, ``ccds_id ...; gene_biotype ...; ENSG...``) and one
integer count column per sample, a normal, correctly-aligned header, unlike
``counts_gene.txt``.

Output: wide matrix, ``transcript_id`` (Utf8, the heatmap index) +
``gene_id`` (Utf8, extracted from ``GENEID``) + one Float64 column per sample
(``.sorted`` suffix stripped), kept to the ``TOP_N`` transcripts with the
highest total count across samples.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        glob_pattern="**/bambu/counts_transcript.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "transcript_id": pl.Utf8,
    "gene_id": pl.Utf8,
}
# Sample columns are run-dependent, so they sit outside the declared schema
# and go unchecked (see deseq2/vst_top_variable.py for the same contract).

TOP_N = 50
_GENE_RE = r"(ENSG\d+)"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["counts"]
    id_col, gene_col, *sample_generic = df.columns
    sample_names = [strip_stage_suffixes(c) for c in sample_generic]

    df = df.rename(
        {id_col: "transcript_id", **dict(zip(sample_generic, sample_names, strict=True))}
    )
    df = df.with_columns(
        [pl.col(c).cast(pl.Float64, strict=False) for c in sample_names]
        + [pl.col(gene_col).str.extract(_GENE_RE, 1).alias("gene_id")]
    )
    df = df.filter(pl.col("transcript_id").is_not_null())
    df = df.with_columns(pl.sum_horizontal(sample_names).alias("_total"))
    df = df.sort("_total", descending=True).head(TOP_N).drop([gene_col, "_total"])
    return df.select(["transcript_id", "gene_id", *sample_names])
