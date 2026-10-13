"""Fixed-window binning of a per-coordinate signal, without materialising it.

A pipeline that calls a value at every covered base or every covered site
publishes a file that is far too long to read into memory and far too fine to
draw: Bismark's per-CpG bedGraph is 8 to 120 million rows per sample, mosdepth's
per-base BED the same order, a bedGraph of read depth likewise. What a dashboard
wants out of them is the same three columns binned into windows: which window,
what the average value in it is, and how many observations stand behind that
average.

That reduction is a streaming ``group_by`` over a lazy scan, so nothing wider
than one window ever exists in memory. Both entry points here take a lazy frame
(or a path they scan themselves) and return an eager frame of windows:

    chrom : Utf8     contig the window sits on
    start : Int64    window start, 0-based and a multiple of ``bin_size``
    end : Int64      window end, exclusive (``start + bin_size``)
    mean : Float64   mean of the value column over the window's observations
    n : Int64        observations behind ``mean``

``n`` is not decoration: a window mean computed from three CpGs and one computed
from four hundred are different measurements, and every consumer of this helper
(the group comparison, the PCA, the track) filters on it.

Named for the shape rather than for Bismark because the shape is the reusable
part. mosdepth per-base BED, a bedGraph of any signal and a tabular pileup all
bin through the same two calls; only the column names and the separator change.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import polars as pl

#: Window size used when a caller states none. 10 kb is the resolution at which
#: a mammalian CpG methylome stops being noise (a 10 kb window on hg38 holds
#: ~80 CpGs at the depths an nf-core megatest reaches) and still leaves a
#: genome-wide matrix small enough to correlate and to test window by window.
DEFAULT_BIN_SIZE = 10_000

#: Column names the two entry points return, in order.
BIN_SCHEMA: dict[str, type[pl.DataType]] = {
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "mean": pl.Float64,
    "n": pl.Int64,
}


def bin_coordinate_frame(
    frame: pl.LazyFrame,
    *,
    chrom_col: str = "chrom",
    pos_col: str = "start",
    value_col: str = "value",
    bin_size: int = DEFAULT_BIN_SIZE,
    weight_col: str | None = None,
    streaming: bool = True,
) -> pl.DataFrame:
    """Average ``value_col`` into fixed ``bin_size`` windows along the genome.

    Args:
        frame: Lazy frame with one row per coordinate. Never collected whole.
        chrom_col: Contig column.
        pos_col: Start coordinate column (0-based; the window a row falls in is
            ``pos // bin_size``).
        value_col: The value averaged over each window.
        bin_size: Window width in base pairs.
        weight_col: Optional column of observation weights (a coverage count,
            say). When set, ``mean`` is the weighted mean, which is what a
            per-site methylation call with a coverage column deserves; when
            null, every observation counts once, which is all a bedGraph
            supports.
        streaming: Run the collect through the streaming engine. The default is
            the whole point of this helper; pass False only for a frame already
            in memory, where the batching costs more than it saves.

    Returns:
        One row per (contig, window) that has at least one observation, sorted
        by contig then window, with the schema described in ``BIN_SCHEMA``.
    """
    if bin_size <= 0:
        raise ValueError(f"genomic_bins: bin_size must be positive, got {bin_size}")

    binned = frame.with_columns(
        ((pl.col(pos_col).cast(pl.Int64) // bin_size) * bin_size).alias("start")
    )
    if weight_col is None:
        value_agg = pl.col(value_col).cast(pl.Float64).mean().alias("mean")
    else:
        weight = pl.col(weight_col).cast(pl.Float64)
        value_agg = (
            (pl.col(value_col).cast(pl.Float64) * weight).sum() / weight.sum().replace(0.0, None)
        ).alias("mean")

    aggregated = (
        binned.group_by([chrom_col, "start"])
        .agg(value_agg, pl.len().alias("n"))
        .select(
            pl.col(chrom_col).cast(pl.Utf8).alias("chrom"),
            pl.col("start").cast(pl.Int64),
            (pl.col("start") + bin_size).cast(pl.Int64).alias("end"),
            pl.col("mean").cast(pl.Float64),
            pl.col("n").cast(pl.Int64),
        )
        .sort(["chrom", "start"])
    )
    return aggregated.collect(engine="streaming" if streaming else "in-memory")


def bin_delimited_file(
    path: str | Path,
    *,
    column_names: list[str],
    chrom_col: str = "chrom",
    pos_col: str = "start",
    value_col: str = "value",
    bin_size: int = DEFAULT_BIN_SIZE,
    weight_col: str | None = None,
    separator: str = "\t",
    skip_rows: int = 0,
    has_header: bool = False,
) -> pl.DataFrame:
    """Scan a delimited (optionally gzipped) coordinate file and bin it.

    ``pl.scan_csv`` decompresses ``.gz`` transparently and feeds the streaming
    engine batch by batch, so a 266 MB bedGraph of 46 million rows bins in a
    couple of seconds and never costs more than one batch of memory.

    Args:
        path: File to scan. ``.gz`` is fine.
        column_names: Names for the file's columns, in file order. Required
            because the formats this helper targets (bedGraph, mosdepth BED)
            ship no header line.
        chrom_col, pos_col, value_col, bin_size, weight_col: See
            ``bin_coordinate_frame``.
        separator: Field separator.
        skip_rows: Lines to drop before the data. A Bismark bedGraph opens with
            one ``track type=bedGraph`` line, which has a single field and would
            otherwise decide the column count.
        has_header: Whether the first kept line names the columns.
    """
    frame = pl.scan_csv(
        path,
        separator=separator,
        has_header=has_header,
        skip_rows=skip_rows,
        new_columns=column_names,
        schema_overrides={
            chrom_col: pl.Utf8,
            pos_col: pl.Int64,
            value_col: pl.Float64,
        },
    )
    return bin_coordinate_frame(
        frame,
        chrom_col=chrom_col,
        pos_col=pos_col,
        value_col=value_col,
        bin_size=bin_size,
        weight_col=weight_col,
    )


def complete_window_frame(
    files: Sequence[tuple[str, str]],
    *,
    column_names: list[str],
    chrom_col: str = "chrom",
    pos_col: str = "start",
    value_col: str = "value",
    bin_size: int = DEFAULT_BIN_SIZE,
    skip_rows: int = 0,
    min_obs: int = 1,
    min_windows_per_contig: int = 1,
    label: str = "genomic_bins",
) -> pl.DataFrame:
    """Bin one file per sample and keep the windows every sample measured.

    The shared front half of every cohort panel downstream of binning: each
    ``(path, sample)`` is streamed through ``bin_delimited_file``, windows with
    fewer than ``min_obs`` observations are dropped, only the windows left in
    **every** sample are kept (so a PCA, a correlation and a per-window test all
    read the same complete matrix), and contigs with fewer than
    ``min_windows_per_contig`` such windows are dropped, which removes unplaced
    scaffolds and the mitochondrion without naming an assembly.

    Returns a long frame ``sample, chromosome, start, end, mean, n``. Raises
    ``ValueError`` (prefixed with ``label``) when a file keeps no window or when
    the samples share none.
    """
    per_sample: list[pl.DataFrame] = []
    for path, sample in files:
        binned = bin_delimited_file(
            path,
            column_names=column_names,
            chrom_col=chrom_col,
            pos_col=pos_col,
            value_col=value_col,
            bin_size=bin_size,
            skip_rows=skip_rows,
        )
        kept = binned.filter(pl.col("n") >= min_obs).select(
            pl.lit(sample, pl.Utf8).alias("sample"),
            pl.col("chrom").alias("chromosome"),
            "start",
            "end",
            "mean",
            "n",
        )
        if kept.is_empty():
            raise ValueError(
                f"{label}: no window of {Path(path).name} reached {min_obs} observations"
            )
        per_sample.append(kept)
    if not per_sample:
        raise ValueError(f"{label}: no file to bin")

    long = pl.concat(per_sample)
    n_samples = long.get_column("sample").n_unique()
    complete = (
        long.group_by(["chromosome", "start"])
        .agg(pl.col("sample").n_unique().alias("_samples"))
        .filter(pl.col("_samples") == n_samples)
        .drop("_samples")
    )
    dense_contigs = (
        complete.group_by("chromosome")
        .agg(pl.len().alias("_windows"))
        .filter(pl.col("_windows") >= min_windows_per_contig)
        .get_column("chromosome")
        .to_list()
    )
    complete = complete.filter(pl.col("chromosome").is_in(dense_contigs))
    if complete.is_empty():
        raise ValueError(
            f"{label}: no window is covered in every sample on any contig with at least "
            f"{min_windows_per_contig} windows; the samples share no comparable genomic space"
        )
    return long.join(complete, on=["chromosome", "start"], how="inner")


def window_id_expr(
    chrom_col: str = "chromosome", start_col: str = "start", end_col: str = "end"
) -> pl.Expr:
    """``chr1:10000-20000``: the stable, sortable name of one window.

    A window needs a single string id the moment it becomes a row label (a
    heatmap's index, a volcano's feature) or a join key across reshapes. Built
    here so every consumer of a binned frame spells it the same way; recipes
    cannot import one another, so the alternative is three spellings that drift.
    """
    return pl.concat_str(
        [
            pl.col(chrom_col),
            pl.lit(":"),
            pl.col(start_col).cast(pl.Utf8),
            pl.lit("-"),
            pl.col(end_col).cast(pl.Utf8),
        ]
    ).alias("window_id")


def window_matrix(
    frame: pl.DataFrame,
    *,
    sample_col: str = "sample",
    value_col: str = "methylation_pct",
    chrom_col: str = "chromosome",
    start_col: str = "start",
    end_col: str = "end",
) -> pl.DataFrame:
    """Pivot a long binned frame to one row per sample, one column per window.

    The shape every cohort-level panel downstream of binning reads: a PCA, a
    sample correlation and a per-window group test all start from the same
    sample x window matrix, and they must start from *the same one*, or a
    reader comparing two tiles is comparing two different matrices.
    """
    required = {sample_col, chrom_col, start_col, end_col, value_col}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(
            f"genomic_bins.window_matrix: the binned frame lacks {sorted(missing)}, "
            f"got {frame.columns}"
        )
    return (
        frame.with_columns(window_id_expr(chrom_col, start_col, end_col))
        .pivot(on="window_id", index=sample_col, values=value_col)
        .sort(sample_col)
    )
