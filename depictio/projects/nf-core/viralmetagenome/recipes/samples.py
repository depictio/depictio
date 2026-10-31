"""Sample hub for nf-core/viralmetagenome: one row per sample, its reads and its assembly.

The measures come from the pipeline's samples overview table, through the
catalog collection ``vmg_samples_overview`` (``viralmetagenome/samples_overview``):
the read pairs before trimming, after trimming and after host removal, the
host share, fastp's Q30 and duplication, the de novo assembly length and N50,
the contig clusters kept and removed, and the de novo consensus count.

The design. viralmetagenome takes a sample metadata table through
``--metadata`` and merges it into the overview, but does not publish the table
itself. When the template is given it (``METADATA_FILE``: sample id in the
column named ``sample`` or in the first column, every other column a factor),
its columns are joined under their own names, right after ``sample``, so
``{GROUP_COL}`` resolves against the hub. Without it the hub carries:

* the factor columns of the overview's metadata block (``Sample metadata.
  <column>``) under their names, so ``--var GROUP_COL=<column>`` still finds
  one. A factor is a column that groups the samples: at least two values and
  fewer values than samples, which leaves the accessions and the constants out;
* a constant ``__no_group__`` column, the value ``GROUP_COL`` falls back to
  when no metadata is given, so the group filter and the group breakdowns
  resolve and show one group.

Sources:
    overview   ``vmg_samples_overview`` (catalog ``viralmetagenome/samples_overview``)
    metadata   ``metadata``, the design table, optional

Output schema: the catalog collection's measures (``OUTPUT_SCHEMA``), with the
design columns after ``sample``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import (
    NO_GROUP_COL,
    NO_GROUP_VALUE,
    design_columns,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="overview",
        dc_ref="vmg_samples_overview",
        input_schema={
            "sample": pl.Utf8,
            "raw_read_pairs": pl.Int64,
            "host_filtered_read_pairs": pl.Int64,
        },
    ),
    # No input_schema on the design table: its columns are the user's factors, and the
    # sample id sits in the column named `sample` or, failing that, the first one.
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "raw_read_pairs": pl.Int64,
    "raw_gc_pct": pl.Float64,
    "raw_dup_pct": pl.Float64,
    "trimmed_reads": pl.Int64,
    "q30_pct": pl.Float64,
    "fastp_dup_pct": pl.Float64,
    "adapter_pct": pl.Float64,
    "trimmed_read_pairs": pl.Int64,
    "host_pct": pl.Float64,
    "host_filtered_read_pairs": pl.Int64,
    "retained_pct": pl.Float64,
    "assembly_length": pl.Int64,
    "assembly_n50": pl.Int64,
    "clusters": pl.Int64,
    "removed_clusters": pl.Int64,
    "mean_cluster_size": pl.Float64,
    "singletons": pl.Int64,
    "denovo_consensus": pl.Int64,
}

META_PREFIX = "meta_"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    overview = sources["overview"]
    if overview.is_empty():
        raise ValueError("viralmetagenome samples: the samples overview is empty")
    for col, dtype in OUTPUT_SCHEMA.items():
        if col not in overview.columns:
            overview = overview.with_columns(pl.lit(None, dtype=dtype).alias(col))
    measures = overview.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
    reserved = set(OUTPUT_SCHEMA)

    design = design_columns(sources.get("metadata"), reserved)
    if design is not None:
        # The factors right after the sample, so the sample sheet opens on who
        # the sample is before what it yielded.
        return (
            measures.join(design, on="sample", how="left")
            .select("sample", *design.columns[1:], *list(OUTPUT_SCHEMA)[1:])
            .sort("sample")
        )

    n_samples = overview["sample"].n_unique()
    meta = {
        c: c[len(META_PREFIX) :]
        for c in overview.columns
        if c.startswith(META_PREFIX)
        and c[len(META_PREFIX) :] not in reserved
        and 2 <= overview[c].drop_nulls().n_unique() < n_samples
    }
    out = measures.join(
        overview.select("sample", *meta).rename(meta), on="sample", how="left"
    ).with_columns(pl.lit(NO_GROUP_VALUE).alias(NO_GROUP_COL))
    return out.select("sample", NO_GROUP_COL, *meta.values(), *list(OUTPUT_SCHEMA)[1:]).sort(
        "sample"
    )
