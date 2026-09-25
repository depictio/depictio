"""The library hub: one row per demultiplexed library, the key every tab filters on.

Joins, per library, what the demultiplexer counted (reads, yield, base
quality, index purity, summed over the lanes it was sequenced on), what fastp
measured on its reads after demultiplexing, and the design columns of an
optional sample metadata file. It is the collection the sample sheet section,
the library filters, the design grouping and the library record card read.

``pct_of_expected`` is the balance number a facility acts on: the library's
reads as a percent of an even split of the run's assigned reads between its
libraries (100 is exactly its share; 10 means it got a tenth of it).
``pct_of_run`` is the same reads over every read of the run, Undetermined
included.

The metadata file (``METADATA_FILE``) is matched on its FIRST column, the same
column the template's ``METADATA_ID_COL`` auto-detection picks. Every other
column is passed through as text (so a numeric design factor such as an input
amount groups and filters like a label); a column whose name collides with a
hub column gets a ``meta_`` prefix. Without metadata the hub carries a
constant ``__no_group__`` column: that is the value ``GROUP_COL`` falls back
to when no metadata is given, so the tiles grouped by ``{GROUP_COL}`` still
resolve and show a single group.

Output schema (plus the metadata columns):
    sample : Utf8                 library name
    flowcell : Utf8               flowcell (first one when a library spans several)
    lanes : Utf8                  lanes the library was read on, comma separated
    n_lanes : Int64               how many
    index : Utf8                  index sequence(s), i7+i5
    fastq_id : Utf8               FASTQ stem of its first lane, the MultiQC name of its fastp and Falco rows
    reads : Int64                 read clusters assigned, all lanes
    pct_of_run : Float64          reads over every read of the run, percent
    pct_of_expected : Float64     reads over an even share of the assigned reads, percent
    yield_mb : Float64            bases passing filter, megabases
    pct_q30 : Float64             bases at Q30 or above, percent
    mean_quality : Float64        mean Phred score
    pct_perfect_index : Float64   reads whose index matched with no mismatch, percent
    reads_after_filter : Int64    reads fastp kept (both mates)
    pct_passed : Float64          reads fastp kept, percent
    pct_duplication : Float64     fastp duplication rate, percent
    pct_adapter_trimmed : Float64 reads with adapter trimmed, percent
    gc_pct : Float64              GC content after filtering, percent
    pct_q30_after : Float64       bases at Q30 or above after filtering, percent
    insert_size_peak : Int64      most frequent insert size, bp
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="demux", dc_ref="demux_stats"),
    RecipeSource(ref="qc", dc_ref="fastp_library_qc", optional=True),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "flowcell": pl.Utf8,
    "lanes": pl.Utf8,
    "n_lanes": pl.Int64,
    "index": pl.Utf8,
    "fastq_id": pl.Utf8,
    "reads": pl.Int64,
    "pct_of_run": pl.Float64,
    "pct_of_expected": pl.Float64,
    "yield_mb": pl.Float64,
    "pct_q30": pl.Float64,
    "mean_quality": pl.Float64,
    "pct_perfect_index": pl.Float64,
    "reads_after_filter": pl.Int64,
    "pct_passed": pl.Float64,
    "pct_duplication": pl.Float64,
    "pct_adapter_trimmed": pl.Float64,
    "gc_pct": pl.Float64,
    "pct_q30_after": pl.Float64,
    "insert_size_peak": pl.Int64,
}

#: Column ``GROUP_COL`` resolves to when the run gives no metadata file.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All libraries"

_QC_COLS: dict[str, type[pl.DataType]] = {
    "reads_after_filter": pl.Int64,
    "pct_passed": pl.Float64,
    "pct_duplication": pl.Float64,
    "pct_adapter_trimmed": pl.Float64,
    "gc_pct": pl.Float64,
    "pct_q30_after": pl.Float64,
    "insert_size_peak": pl.Int64,
}


def _weighted(col: str, weight: str) -> pl.Expr:
    """Mean of ``col`` weighted by ``weight``, ignoring rows where ``col`` is null."""
    w = pl.when(pl.col(col).is_not_null()).then(pl.col(weight)).otherwise(0)
    return (pl.col(col).fill_null(0) * w).sum() / w.sum()


def _qc_per_library(qc: pl.DataFrame | None) -> pl.DataFrame | None:
    if qc is None or qc.is_empty():
        return None
    return (
        qc.sort(["sample", "lane"], nulls_last=True)
        .group_by("sample", maintain_order=True)
        .agg(
            pl.col("fastq_id").first(),
            pl.col("reads_after").sum().alias("reads_after_filter"),
            pl.col("reads_before").sum().alias("_before"),
            *[
                _weighted(c, "reads_before").alias(c)
                for c in ("pct_passed", "pct_duplication", "pct_adapter_trimmed", "gc_pct")
            ],
            _weighted("pct_q30_after", "reads_after").alias("pct_q30_after"),
            pl.col("insert_size_peak").median().round(0).cast(pl.Int64).alias("insert_size_peak"),
        )
        .drop("_before")
    )


def _metadata(meta: pl.DataFrame | None, taken: set[str]) -> pl.DataFrame | None:
    if meta is None or meta.is_empty() or meta.width < 2:
        return None
    id_col = meta.columns[0]
    renames = {c: (f"meta_{c}" if c in taken else c) for c in meta.columns[1:]}
    return (
        meta.select(
            pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("sample"),
            *[pl.col(c).cast(pl.Utf8).alias(renames[c]) for c in meta.columns[1:]],
        )
        .filter(pl.col("sample").is_not_null())
        .unique(subset="sample", keep="first", maintain_order=True)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library, Undetermined excluded."""
    demux = sources["demux"]
    if demux is None or demux.is_empty():
        raise ValueError("libraries: the demux_stats collection is empty")
    run_total = float(demux["reads"].sum() or 0)
    libs = demux.filter(~pl.col("is_undetermined"))
    if libs.is_empty():
        raise ValueError("libraries: no library in demux_stats, only Undetermined reads")
    hub = (
        libs.with_columns(
            (pl.col("yield_mb") * pl.col("pct_q30")).alias("_q30w"),
            (pl.col("yield_mb") * pl.col("mean_quality")).alias("_qw"),
        )
        .sort(["sample", "flowcell", "lane"])
        .group_by("sample", maintain_order=True)
        .agg(
            pl.col("flowcell").first(),
            pl.col("lane").unique(maintain_order=True).cast(pl.Utf8).str.join(", ").alias("lanes"),
            pl.col("lane").n_unique().cast(pl.Int64).alias("n_lanes"),
            pl.col("index").first(),
            pl.col("reads").sum(),
            pl.col("yield_mb").sum(),
            _weighted("pct_q30", "yield_mb").alias("pct_q30"),
            _weighted("mean_quality", "yield_mb").alias("mean_quality"),
            _weighted("pct_perfect_index", "reads").alias("pct_perfect_index"),
        )
    )
    assigned = float(hub["reads"].sum() or 0)
    even_share = assigned / hub.height if hub.height else 0.0
    hub = hub.with_columns(
        (100.0 * pl.col("reads") / run_total if run_total else pl.lit(None)).alias("pct_of_run"),
        (100.0 * pl.col("reads") / even_share if even_share else pl.lit(None)).alias(
            "pct_of_expected"
        ),
    )
    qc = _qc_per_library(sources.get("qc"))
    if qc is not None:
        hub = hub.join(qc, on="sample", how="left")
    else:
        hub = hub.with_columns(pl.lit(None, dtype=pl.Utf8).alias("fastq_id"))
        hub = hub.with_columns(pl.lit(None, dtype=t).alias(c) for c, t in _QC_COLS.items())
    hub = hub.select([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()])
    meta = _metadata(sources.get("metadata"), set(EXPECTED_SCHEMA))
    if meta is not None:
        hub = hub.join(meta, on="sample", how="left")
    else:
        hub = hub.with_columns(pl.lit(NO_GROUP_VALUE).alias(NO_GROUP_COL))
    return hub.sort("sample")
