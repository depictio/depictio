"""Bambu's transcript count matrix, melted to one row per sample and transcript.

Same reshape as ``counts_gene_long.py`` one level down: ``counts_transcript.txt``
is wide (``TXNAME``, ``GENEID``, one column per sample) and therefore carries no
``sample`` column for a hub filter to reach. Melting it gives the isoform side
of the dashboard the same sample scope the gene side gets.

Unlike the gene file this one has a well-formed header and a row-unique id, so
there is nothing to stitch and nothing to sum: ``TXNAME`` is already the
transcript. The gene id and the biotype are extracted out of the ``GENEID``
attribute string, which is where Bambu hides them.

CPM is computed against the full library before the ``MIN_TOTAL_COUNT``
filter; ``log_cpm`` is ``log2(cpm + 1)``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bambu import (
    condition_of,
    gene_biotype_expr,
    gene_id_expr,
    melt_counts,
)
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
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "transcript_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_biotype": pl.Utf8,
    "count": pl.Float64,
    "cpm": pl.Float64,
    "log_cpm": pl.Float64,
}

#: Transcripts under this total read count across the run are dropped.
MIN_TOTAL_COUNT = 1.0


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Wide transcript matrix -> long (sample, transcript) rows with CPM."""
    frame = sources["counts"]
    id_col, gene_col, *generic = frame.columns
    samples = [strip_stage_suffixes(c) for c in generic]

    wide = (
        frame.rename({id_col: "transcript_id", **dict(zip(generic, samples, strict=True))})
        .with_columns(
            [pl.col(c).cast(pl.Float64, strict=False) for c in samples]
            + [
                gene_id_expr(gene_col).alias("gene_id"),
                gene_biotype_expr(gene_col).fill_null("unannotated").alias("gene_biotype"),
            ]
        )
        .filter(pl.col("transcript_id").is_not_null())
        .select(["transcript_id", "gene_id", "gene_biotype", *samples])
    )

    long = melt_counts(
        wide,
        id_columns=["transcript_id", "gene_id", "gene_biotype"],
        samples=samples,
        min_total=MIN_TOTAL_COUNT,
    )
    conditions = {name: condition_of(name) for name in samples}
    return (
        long.with_columns(
            pl.col("sample")
            .replace_strict(conditions, default=None, return_dtype=pl.Utf8)
            .alias("condition")
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "transcript_id"])
    )
