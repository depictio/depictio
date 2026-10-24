"""Strand-split coverage in 250 kb windows, one row per library per window.

``bedtools genomecov -bg -strand +`` and ``-strand -`` write one bedGraph per
library and strand (``<sample>.plus.bedGraph``, ``<sample>.minus.bedGraph``),
4 to 10 million intervals each on a human genome. Each file is streamed through
``depictio/recipes/lib/strand_coverage.py`` (a lazy ``group_by`` that never
holds a file) into the read bases of each ``WINDOW_SIZE`` window, then:

1. both strands of a library are normalised by the library's total read bases,
   every contig included, so a window reads in parts per million of the
   library's signal (``plus_rpm``, ``minus_rpm``, their sum ``signal_rpm``) and
   libraries sequenced to different depths compare directly;
2. only contigs with at least ``MIN_WINDOWS_PER_CONTIG`` windows get windows
   (the chromosomes): unplaced and alt scaffolds, the mitochondrion and a viral
   episome stay in the library total but get no row, without naming an
   assembly;
3. every library gets every window of those contigs, a window with no read
   reading 0 rather than missing, so a time course or a correlation reads a
   complete matrix.

``plus_share_pct`` is the plus strand's share of the window's signal: genes
transcribed on one strand dominate their window, so the share swings between
the strands along a chromosome and sits near 50 for the genome as a whole.

The recipe reads its file paths from a one-row-per-file **index** collection
(``bedgraph_strand_index``, a raw scan with ``n_rows: 1`` and
``include_file_paths: source_path``) rather than from a glob source, because a
glob source reads every matched file into memory before the recipe sees it.

Output schema:
    sample : Utf8            library
    chromosome : Utf8        contig of the window
    start : Int64            window start, 0-based, a multiple of WINDOW_SIZE
    end : Int64              window end, exclusive
    position : Int64         window centre, where a track draws it
    plus_rpm : Float64       plus-strand read bases, per million of the library's
    minus_rpm : Float64      minus-strand read bases, per million of the library's
    signal_rpm : Float64     both strands, per million of the library's
    log2_signal : Float64    log2(signal_rpm + 1)
    plus_share_pct : Float64 plus strand's share of the window's signal (null without signal)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import strand_coverage as sc

RAW_DC_TAG = "bedgraph_strand_index"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="index", dc_ref=RAW_DC_TAG, input_schema={sc.SOURCE_PATH_COL: pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "position": pl.Int64,
    "plus_rpm": pl.Float64,
    "minus_rpm": pl.Float64,
    "signal_rpm": pl.Float64,
    "log2_signal": pl.Float64,
    "plus_share_pct": pl.Float64,
}

WINDOW_SIZE = sc.WINDOW_SIZE
MIN_WINDOWS_PER_CONTIG = sc.MIN_WINDOWS_PER_CONTIG


def binned_files(files: list[tuple[str, str, str]], bin_size: int = WINDOW_SIZE) -> pl.DataFrame:
    """Long ``sample, strand, chrom, start, read_bases`` over every strand file."""
    frames = [
        sc.bin_bedgraph(path, bin_size).select(
            pl.lit(sample, pl.Utf8).alias("sample"),
            pl.lit(strand, pl.Utf8).alias("strand"),
            "chrom",
            "start",
            "read_bases",
        )
        for path, sample, strand in files
    ]
    return pl.concat(frames)


def windows_from_binned(long: pl.DataFrame, bin_size: int = WINDOW_SIZE) -> pl.DataFrame:
    """The normalised, complete window table from the long binned frame."""
    totals = long.group_by("sample").agg(pl.col("read_bases").sum().alias("_library"))
    contigs = sc.main_contigs(long)
    if not contigs:
        raise ValueError(
            f"bedtools_strand_bins: no contig holds {MIN_WINDOWS_PER_CONTIG} windows with signal"
        )
    on_main = long.filter(pl.col("chrom").is_in(contigs))
    per_strand = on_main.pivot(
        on="strand",
        index=["sample", "chrom", "start"],
        values="read_bases",
        aggregate_function="sum",
    )
    for strand in ("plus", "minus"):
        if strand not in per_strand.columns:
            per_strand = per_strand.with_columns(pl.lit(0.0).alias(strand))
    grid = (
        on_main.select("chrom", "start")
        .unique()
        .join(on_main.select("sample").unique(), how="cross")
    )
    full = (
        grid.join(per_strand, on=["sample", "chrom", "start"], how="left")
        .join(totals, on="sample", how="left")
        .with_columns(pl.col("plus").fill_null(0.0), pl.col("minus").fill_null(0.0))
    )
    scale = 1e6 / pl.col("_library").replace(0.0, None)
    out = full.with_columns(
        (pl.col("plus") * scale).alias("plus_rpm"),
        (pl.col("minus") * scale).alias("minus_rpm"),
    ).with_columns(
        (pl.col("plus_rpm") + pl.col("minus_rpm")).alias("signal_rpm"),
    )
    return (
        out.with_columns(
            pl.col("chrom").alias("chromosome"),
            (pl.col("start") + bin_size).alias("end"),
            (pl.col("start") + bin_size // 2).alias("position"),
            (pl.col("signal_rpm") + 1.0).log(2).alias("log2_signal"),
            pl.when(pl.col("signal_rpm") > 0)
            .then(pl.col("plus_rpm") / pl.col("signal_rpm") * 100)
            .otherwise(None)
            .alias("plus_share_pct"),
            sc.contig_order_expr("chrom"),
        )
        .sort(["sample", "_contig_number", "chromosome", "start"], nulls_last=True)
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Stream every strand bedGraph into windows and normalise per library."""
    files = sc.files_from_index(sources["index"], "bedtools_strand_bins")
    return windows_from_binned(binned_files(files))
