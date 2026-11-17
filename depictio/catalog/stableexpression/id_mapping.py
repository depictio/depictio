"""Where the gene ids of every nf-core/stableexpression dataset went (long form).

stableexpression maps each dataset's ids (probe sets, Ensembl ids of another
release, symbols) to Ensembl gene ids with g:Profiler, then drops the genes
seen in too few datasets (``--min_occurrence_freq``,
``--min_occurrence_quantile``) and keeps one row per gene where several ids map
to it. One row per dataset and fate, the four of which add up to the ids the
dataset came with: ``Kept`` (a gene of the merged matrix), ``Collapsed`` (one
of several ids mapped to the same gene), ``Rare gene`` and ``Unmapped``.
A run with ``--skip_id_mapping`` writes no mapping statistics and this table
is empty.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import dataset_sources, dataset_table

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = dataset_sources()

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "fate_key": pl.Utf8,
    "dataset": pl.Utf8,
    "accession": pl.Utf8,
    "platform": pl.Utf8,
    "outcome": pl.Utf8,
    "fate": pl.Utf8,
    "fate_order": pl.Int64,
    "gene_ids": pl.Int64,
    "share": pl.Float64,
}

#: Each fate and the ``dataset_table`` column counting its ids.
FATES: tuple[tuple[str, str], ...] = (
    ("Kept", "genes_kept"),
    ("Collapsed", "ids_collapsed"),
    ("Rare gene", "genes_rare"),
    ("Unmapped", "ids_unmapped"),
)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    datasets = dataset_table(sources).filter(pl.col("gene_ids_in").is_not_null())
    if datasets.is_empty():
        raise ValueError("no ID mapping statistics (statistics/id_mapping_stats.csv)")
    rows = pl.concat(
        [
            datasets.select(
                "dataset",
                "accession",
                "platform",
                "outcome",
                pl.lit(label).alias("fate"),
                pl.lit(order, dtype=pl.Int64).alias("fate_order"),
                pl.col(column).fill_null(0).cast(pl.Int64).alias("gene_ids"),
                pl.col("gene_ids_in"),
            )
            for order, (label, column) in enumerate(FATES, start=1)
        ]
    )
    return (
        rows.with_columns(
            (pl.col("dataset") + "|" + pl.col("fate")).alias("fate_key"),
            pl.when(pl.col("gene_ids_in") > 0)
            .then((pl.col("gene_ids") / pl.col("gene_ids_in")).round(4))
            .otherwise(None)
            .alias("share"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort("dataset", "fate_order")
    )
