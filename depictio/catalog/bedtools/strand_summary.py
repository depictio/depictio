"""Per-library totals of the strand-split coverage bedGraphs.

The library-level reading of ``bedtools genomecov -bg -strand +/-``, streamed
from the same files as ``strand_bins.py`` through
``depictio/recipes/lib/strand_coverage.py``. Each number is a question a
nascent-transcription library is checked against before its signal is read:

* ``plus_share_pct``: the plus strand's share of the signal. Genes sit on both
  strands about equally, so a library far from 50 has lost one strand
  (a protocol or library-strandedness problem).
* ``mito_pct``: the share of the signal on the mitochondrial contig. Run-on
  libraries pick up mitochondrial transcription; a large share is depth that
  says nothing about nuclear genes.
* ``off_main_pct``: the share outside the chromosomes (unplaced and alt
  scaffolds, the mitochondrion, a viral episome), the contigs the windows leave
  out.
* ``hotspot_share_pct``: the share of the chromosome signal held by the top 1%
  of 250 kb windows. Ribosomal DNA arrays and a few very highly transcribed
  loci concentrate the reads of a poorly depleted library in a handful of
  windows; a high share means the rest of the genome is read from what is left.

Output schema:
    sample : Utf8                library
    plus_read_bases : Float64    plus-strand depth summed over the genome (read bases)
    minus_read_bases : Float64   minus-strand read bases
    total_read_bases : Float64   both strands
    covered_mb : Float64         bases with any coverage, both strands summed, in Mb
    max_depth : Float64          deepest base of either strand
    plus_share_pct : Float64     plus strand, in percent of both
    mito_pct : Float64           mitochondrial contig, in percent of both strands
    off_main_pct : Float64       contigs outside the chromosomes, in percent
    hotspot_share_pct : Float64  top 1% of chromosome windows, in percent of the chromosome signal
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
    "plus_read_bases": pl.Float64,
    "minus_read_bases": pl.Float64,
    "total_read_bases": pl.Float64,
    "covered_mb": pl.Float64,
    "max_depth": pl.Float64,
    "plus_share_pct": pl.Float64,
    "mito_pct": pl.Float64,
    "off_main_pct": pl.Float64,
    "hotspot_share_pct": pl.Float64,
}

#: Share of the chromosome windows counted as hotspots.
HOTSPOT_FRACTION = 0.01


def _pct(part: pl.Expr, whole: pl.Expr) -> pl.Expr:
    return part / whole.replace(0.0, None) * 100


def summarise(contigs: pl.DataFrame, windows: pl.DataFrame, main: list[str]) -> pl.DataFrame:
    """The per-library table from per-contig totals and per-window read bases.

    ``contigs``: ``sample, strand, chrom, read_bases, covered_bases, max_depth``.
    ``windows``: ``sample, strand, chrom, start, read_bases``.
    """
    is_mito = pl.col("chrom").str.contains(sc.MITO_RE)
    on_main = pl.col("chrom").is_in(main)
    library = contigs.group_by("sample").agg(
        pl.col("read_bases").filter(pl.col("strand") == "plus").sum().alias("plus_read_bases"),
        pl.col("read_bases").filter(pl.col("strand") == "minus").sum().alias("minus_read_bases"),
        pl.col("read_bases").sum().alias("total_read_bases"),
        (pl.col("covered_bases").sum() / 1e6).alias("covered_mb"),
        pl.col("max_depth").max().alias("max_depth"),
        pl.col("read_bases").filter(is_mito).sum().alias("_mito"),
        pl.col("read_bases").filter(~on_main).sum().alias("_off_main"),
    )
    per_window = (
        windows.filter(on_main)
        .group_by("sample", "chrom", "start")
        .agg(pl.col("read_bases").sum())
        .with_columns(
            pl.col("read_bases")
            .rank(method="ordinal", descending=True)
            .over("sample")
            .alias("_rank"),
            pl.len().over("sample").alias("_windows"),
        )
    )
    hotspots = per_window.group_by("sample").agg(
        _pct(
            pl.col("read_bases")
            .filter(pl.col("_rank") <= (pl.col("_windows") * HOTSPOT_FRACTION).ceil())
            .sum(),
            pl.col("read_bases").sum(),
        ).alias("hotspot_share_pct")
    )
    return (
        library.join(hotspots, on="sample", how="left")
        .with_columns(
            _pct(pl.col("plus_read_bases"), pl.col("total_read_bases")).alias("plus_share_pct"),
            _pct(pl.col("_mito"), pl.col("total_read_bases")).alias("mito_pct"),
            _pct(pl.col("_off_main"), pl.col("total_read_bases")).alias("off_main_pct"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort("sample")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Stream each strand bedGraph twice (contig totals, windows) and summarise."""
    files = sc.files_from_index(sources["index"], "bedtools_strand_summary")
    contig_frames: list[pl.DataFrame] = []
    window_frames: list[pl.DataFrame] = []
    for path, sample, strand in files:
        tag = [pl.lit(sample, pl.Utf8).alias("sample"), pl.lit(strand, pl.Utf8).alias("strand")]
        contig_frames.append(sc.contig_totals(path).select(*tag, pl.all()))
        window_frames.append(sc.bin_bedgraph(path).select(*tag, "chrom", "start", "read_bases"))
    windows = pl.concat(window_frames)
    return summarise(pl.concat(contig_frames), windows, sc.main_contigs(windows))
