"""Strand-specific coverage bedGraphs, binned into genomic windows.

Nascent-transcription pipelines (nf-core/nascent: GRO-seq, PRO-seq and their
relatives) publish one coverage bedGraph per library and strand, written by
``bedtools genomecov -bg -strand +`` and ``-strand -``:

    coverage_graphs/<sample>.plus.bedGraph
    coverage_graphs/<sample>.minus.bedGraph

Four columns, no header: contig, start, end, read depth over that interval.
A human library holds 4 to 10 million intervals per strand (100 to 450 MB), so
nothing here reads a file whole. Each file streams through
``depictio/recipes/lib/genomic_bins.py``, whose lazy ``group_by`` keeps one batch
in memory at a time.

What a window holds is **read bases**: depth times interval width, summed over
the intervals that start in the window. Averaging the depth column itself (what
``bin_coordinate_frame`` does with a plain value) would weigh a 1 bp interval
like a 5 kb one; the product is the quantity a coverage track integrates, and it
divides into a per-million share of the library without any read-length
assumption. An interval that straddles a window edge is counted in the window
its start falls in, which at 100 kb and wider moves a negligible share.

Shared by the bedtools catalog recipes (``bedtools/strand_bins.py``
and ``bedtools/strand_summary.py``) because recipes may not import one
another.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import polars as pl

from depictio.recipes.lib.genomic_bins import bin_coordinate_frame

#: ``<sample>.plus.bedGraph`` / ``<sample>.minus.bedGraph``, gzipped or not.
#: The ``dreg`` bedGraph nf-core/nascent writes beside them (a signed 3' end
#: count for dREG) does not match and is never read as coverage.
STRAND_BEDGRAPH_RE = re.compile(r"^(?P<sample>.+)\.(?P<strand>plus|minus)\.bedGraph(?:\.gz)?$")
#: Column names of a bedtools bedGraph, which ships no header line.
BEDGRAPH_COLUMNS = ["chrom", "start", "end", "depth"]
#: Column of the index scan that carries each file's path.
SOURCE_PATH_COL = "source_path"
#: Window width of every binned panel. 250 kb leaves about 12,000 windows on a
#: mammalian genome: fine enough to separate loci a megabase apart, coarse
#: enough for one lane per library to draw genome-wide from a table.
WINDOW_SIZE = 250_000
#: A contig with fewer windows than this is assembly debris (unplaced and alt
#: scaffolds, the mitochondrion, a viral episome): its signal still counts in the
#: library total, but it gets no window of its own.
MIN_WINDOWS_PER_CONTIG = 20
#: Mitochondrial contig names across UCSC, Ensembl and GenBank-style references.
MITO_RE = r"^(?:chr)?(?:M|MT|Mito|mitochondrion)$"


def strand_bedgraph_files(paths: Iterable[str]) -> list[tuple[str, str, str]]:
    """``(path, sample, strand)`` for each strand bedGraph among ``paths``, sorted.

    Paths that are not a plus or minus bedGraph (the dREG bedGraph, anything
    else a recursive scan picked up) are skipped.
    """
    out: list[tuple[str, str, str]] = []
    for path in sorted({str(p) for p in paths if p}):
        match = STRAND_BEDGRAPH_RE.match(Path(path).name)
        if match:
            out.append((path, match.group("sample"), match.group("strand")))
    return out


def files_from_index(index: pl.DataFrame | None, label: str) -> list[tuple[str, str, str]]:
    """The strand bedGraphs a one-row-per-file index scan points at.

    Raises ``ValueError`` (prefixed with ``label``) when the index is empty,
    lacks the path column or names no strand bedGraph.
    """
    if index is None or index.is_empty():
        raise ValueError(f"{label}: the bedGraph index is empty")
    if SOURCE_PATH_COL not in index.columns:
        raise ValueError(
            f"{label}: the bedGraph index must be scanned with include_file_paths={SOURCE_PATH_COL}"
        )
    files = strand_bedgraph_files(index.get_column(SOURCE_PATH_COL).to_list())
    if not files:
        raise ValueError(f"{label}: no <sample>.plus/.minus.bedGraph among the indexed files")
    return files


def scan_bedgraph(path: str) -> pl.LazyFrame:
    """Lazy scan of one bedGraph with a ``read_bases`` column (depth x width)."""
    frame = pl.scan_csv(
        path,
        separator="\t",
        has_header=False,
        new_columns=BEDGRAPH_COLUMNS,
        schema_overrides={
            "chrom": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "depth": pl.Float64,
        },
        comment_prefix="track",
    )
    return frame.with_columns(
        (pl.col("depth") * (pl.col("end") - pl.col("start"))).alias("read_bases")
    )


def contig_totals(path: str) -> pl.DataFrame:
    """Per-contig read bases, covered bases and maximum depth of one bedGraph."""
    return (
        scan_bedgraph(path)
        .group_by("chrom")
        .agg(
            pl.col("read_bases").sum().alias("read_bases"),
            (pl.col("end") - pl.col("start")).sum().alias("covered_bases"),
            pl.col("depth").max().alias("max_depth"),
        )
        .collect(engine="streaming")
    )


def bin_bedgraph(path: str, bin_size: int = WINDOW_SIZE) -> pl.DataFrame:
    """Read bases per ``bin_size`` window of one bedGraph.

    Columns: ``chrom, start, end, read_bases, n`` (``n`` the intervals that
    started in the window). Windows with no interval are absent.
    """
    binned = bin_coordinate_frame(
        scan_bedgraph(path),
        chrom_col="chrom",
        pos_col="start",
        value_col="read_bases",
        bin_size=bin_size,
    )
    return binned.with_columns((pl.col("mean") * pl.col("n")).alias("read_bases")).drop("mean")


def main_contigs(windows: pl.DataFrame, min_windows: int = MIN_WINDOWS_PER_CONTIG) -> list[str]:
    """Contigs holding at least ``min_windows`` windows with signal, in any library."""
    return (
        windows.select("chrom", "start")
        .unique()
        .group_by("chrom")
        .agg(pl.len().alias("_windows"))
        .filter(pl.col("_windows") >= min_windows)
        .get_column("chrom")
        .to_list()
    )


def contig_order_expr(column: str = "chromosome") -> pl.Expr:
    """Sort key putting chr1..chr22 (or 1..22) first, in number order."""
    return (
        pl.col(column)
        .str.extract(r"^(?:chr)?(\d+)$", 1)
        .cast(pl.Int64, strict=False)
        .alias("_contig_number")
    )


#: Windows kept for a comparison across libraries: those whose mean signal is at
#: least the median window's (the transcribed half of the genome) ...
TRANSCRIBED_QUANTILE = 0.5
#: ... and below this quantile, which drops the hotspot windows (ribosomal DNA
#: arrays, a few very highly transcribed loci) whose share moves with how well
#: a library was depleted rather than with transcription.
HOTSPOT_QUANTILE = 0.995


def window_id_expr() -> pl.Expr:
    """``chr1:250000-500000``, the stable name of one window."""
    return pl.concat_str(
        [
            pl.col("chromosome"),
            pl.lit(":"),
            pl.col("start").cast(pl.Utf8),
            pl.lit("-"),
            pl.col("end").cast(pl.Utf8),
        ]
    ).alias("window_id")


def comparable_windows(bins: pl.DataFrame) -> pl.DataFrame:
    """``window_id, chromosome, start, end, position, mean_rpm`` of the windows to compare.

    ``bins`` is the window table of ``bedtools/strand_bins.py``. A window is
    kept when its mean ``signal_rpm`` over the libraries lies between the
    ``TRANSCRIBED_QUANTILE`` and ``HOTSPOT_QUANTILE`` of all window means.
    """
    means = (
        bins.with_columns(window_id_expr())
        .group_by("window_id", "chromosome", "start", "end", "position")
        .agg(pl.col("signal_rpm").mean().alias("mean_rpm"))
    )
    low = means.get_column("mean_rpm").quantile(TRANSCRIBED_QUANTILE)
    high = means.get_column("mean_rpm").quantile(HOTSPOT_QUANTILE)
    if low is None or high is None:
        raise ValueError("strand_coverage: no window to compare")
    return means.filter(
        (pl.col("mean_rpm") >= low) & (pl.col("mean_rpm") <= high) & (pl.col("mean_rpm") > 0)
    )
