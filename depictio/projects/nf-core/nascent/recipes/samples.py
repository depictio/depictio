"""The nf-core/nascent sample hub: one row per library, its time point and its QC.

Every tab filters through this table, so it must exist on every run. It is
built from the libraries the gene counts name (``subread_library_summary``),
joined with the strand-coverage totals (``bedtools_strand_summary``, absent on a
run fetched without its bedGraphs) and with the optional design table.

Time. The design table's ``time_col`` (``TIME_COL``, hours, default
``time_h``) and its ``time_point`` label are the source of truth; without a
design, a library id ending in a duration (``<name>_30min``, ``<name>_2h``)
gives both, through ``depictio/recipes/lib/time_course.py``. ``time_order``,
``time_axis`` (log2 of one plus the hours) and ``phase`` (Baseline, then the
tertiles of the later time points: Early, Mid, Late) follow from the hours.

Design columns are joined under their own names right after ``sample``, so the
dashboard's ``{GROUP_COL}`` resolves against them. The design's id column is
its ``sample`` column, or its first one. Without a design table the hub carries
a ``__no_group__`` column instead, the value ``GROUP_COL`` falls back to, holding
each library's phase: the group filter, the colours and the splits by
``{GROUP_COL}`` then read the phases of the time course rather than one group.

Sources:
    library    ``subread_library_summary`` (catalog ``subread/library_summary.py``)
    signal     ``bedtools_strand_summary`` (catalog ``bedtools/strand_summary.py``), optional
    metadata   ``metadata`` (the design table), optional

Output schema (the design columns inserted after ``sample``):
    sample, time_point : Utf8
    time_h : Float64, time_order : Int64, time_axis : Float64, phase : Utf8
    assigned_reads, genes_detected : Int64
    genes_detected_pct, top100_share_pct : Float64
    total_read_bases, plus_share_pct, mito_pct, off_main_pct, hotspot_share_pct : Float64
    strand_skew_pct : Float64   points the plus-strand share sits from an even split, |plus - 50|
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.time_course import sample_times

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="library",
        dc_ref="subread_library_summary",
        input_schema={
            "sample": pl.Utf8,
            "assigned_reads": pl.Int64,
            "genes_detected": pl.Int64,
            "genes_detected_pct": pl.Float64,
            "top100_share_pct": pl.Float64,
        },
    ),
    RecipeSource(
        ref="signal",
        dc_ref="bedtools_strand_summary",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "total_read_bases": pl.Float64,
            "plus_share_pct": pl.Float64,
            "mito_pct": pl.Float64,
            "off_main_pct": pl.Float64,
            "hotspot_share_pct": pl.Float64,
        },
    ),
    # No input_schema: the design's id is its `sample` column or its first one,
    # and every other column is a data-named factor.
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "phase": pl.Utf8,
    "assigned_reads": pl.Int64,
    "genes_detected": pl.Int64,
    "genes_detected_pct": pl.Float64,
    "top100_share_pct": pl.Float64,
    "total_read_bases": pl.Float64,
    "plus_share_pct": pl.Float64,
    "mito_pct": pl.Float64,
    "off_main_pct": pl.Float64,
    "hotspot_share_pct": pl.Float64,
    "strand_skew_pct": pl.Float64,
}
# Design columns are run-dependent and pass through unvalidated.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: The column ``GROUP_COL`` resolves to on a run without a design table.
NO_GROUP_COL = "__no_group__"

SIGNAL_COLUMNS = (
    "total_read_bases",
    "plus_share_pct",
    "mito_pct",
    "off_main_pct",
    "hotspot_share_pct",
)


def _present(df: pl.DataFrame | None) -> bool:
    return df is not None and not df.is_empty()


def design_table(metadata: pl.DataFrame | None) -> pl.DataFrame | None:
    """The design keyed by ``sample``, every other column kept as is."""
    if not _present(metadata):
        return None
    id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    return (
        metadata.rename({id_col: "sample"})
        .with_columns(pl.col("sample").cast(pl.Utf8).str.strip_chars())
        .unique(subset="sample", keep="first")
    )


def transform(sources: dict[str, pl.DataFrame | None], params: dict | None = None) -> pl.DataFrame:
    params = params or {}
    time_col = params.get("time_col") or "time_h"
    library = sources["library"]
    signal = sources.get("signal")
    design = design_table(sources.get("metadata"))

    ids = library.get_column("sample").to_list()
    if _present(signal):
        ids += signal.get_column("sample").to_list()
    hub = sample_times(ids, design, time_col).join(
        library.select(
            "sample", "assigned_reads", "genes_detected", "genes_detected_pct", "top100_share_pct"
        ),
        on="sample",
        how="left",
    )
    if _present(signal):
        hub = hub.join(signal.select("sample", *SIGNAL_COLUMNS), on="sample", how="left")
    hub = hub.with_columns(
        # How far a library sits from an even split between the strands, the number a
        # cut-off can read (a share of 62% and one of 38% are the same departure).
        (pl.col("plus_share_pct") - 50.0).abs().alias("strand_skew_pct")
        if "plus_share_pct" in hub.columns
        else pl.lit(None, dtype=pl.Float64).alias("strand_skew_pct")
    )
    hub = hub.with_columns(
        [pl.lit(None, dtype=t).alias(c) for c, t in OUTPUT_SCHEMA.items() if c not in hub.columns]
    ).select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])

    if design is not None:
        factors = [
            c for c in design.columns if c != "sample" and c not in OUTPUT_SCHEMA and c != time_col
        ]
        hub = hub.join(design.select("sample", *factors), on="sample", how="left").select(
            "sample", *factors, *list(OUTPUT_SCHEMA)[1:]
        )
    else:
        hub = hub.with_columns(pl.col("phase").alias(NO_GROUP_COL)).select(
            "sample", NO_GROUP_COL, *list(OUTPUT_SCHEMA)[1:]
        )
    return hub.sort(["time_order", "sample"], nulls_last=True)
