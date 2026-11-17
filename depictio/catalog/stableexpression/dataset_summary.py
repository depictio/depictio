"""One row per dataset nf-core/stableexpression downloaded, and what became of it.

Each public dataset (an Expression Atlas experiment, split by array design for
microarrays) with its accession, platform and normalisation state (the two
directory levels above it under ``datasets/``), the samples and conditions it
came with, its gene ID mapping (ids kept as genes, merged into another id, rare
genes dropped, unmapped, the mapped share and the failure reason when nothing
mapped), the samples each filter rejected and the samples kept in the merged
matrix, the median zero share, missing share and skewness of its samples, and
its outcome: ``Merged``, ``No gene mapped``, ``Only rare genes`` or
``All samples filtered out``. ``design`` is the array design, or the platform
for RNA-seq: what fixes the share of the genes a dataset can measure.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import dataset_sources, dataset_table

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = dataset_sources()

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "dataset": pl.Utf8,
    "accession": pl.Utf8,
    "platform": pl.Utf8,
    "normalisation": pl.Utf8,
    "array_design": pl.Utf8,
    "design": pl.Utf8,
    "outcome": pl.Utf8,
    "conditions": pl.Int64,
    "samples_downloaded": pl.Int64,
    "samples_id_mapped": pl.Int64,
    "samples_after_zero_filter": pl.Int64,
    "samples_kept": pl.Int64,
    "samples_rejected_zeros": pl.Int64,
    "samples_rejected_missing": pl.Int64,
    "kept_share": pl.Float64,
    "gene_ids_in": pl.Int64,
    "genes_kept": pl.Int64,
    "ids_collapsed": pl.Int64,
    "genes_rare": pl.Int64,
    "ids_unmapped": pl.Int64,
    "mapped_share": pl.Float64,
    "zero_share": pl.Float64,
    "missing_share": pl.Float64,
    "skewness": pl.Float64,
    "downloaded": pl.Int64,
    "id_mapped": pl.Int64,
    "merged": pl.Int64,
    "failure_reason": pl.Utf8,
    "mapping_note": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    # What fixes the genes a dataset can measure: its array design, or RNA-seq.
    design = pl.coalesce("array_design", pl.col("platform"))
    return dataset_table(sources).with_columns(design.alias("design")).select(list(OUTPUT_SCHEMA))
