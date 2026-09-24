"""Genome-wide CpG methylation in fixed windows, one row per sample per window.

``bismark_methylation_extractor --bedGraph`` writes one
``<sample>.deduplicated.bedGraph.gz`` per library: a gzipped four-column
bedGraph (``chrom``, ``start``, ``end``, ``% methylation``) with **one row per
covered CpG**, which on a human megatest is 8 to 46 million rows and 750 MB for
the run. It is the only file a methylseq run publishes that carries methylation
at genomic coordinates, and every methylome-scale panel a reader expects (a
track, a sample PCA, a correlation matrix, a region-level group comparison) is
downstream of it.

Nothing here is ever read into memory whole. Each file is streamed through
``depictio/recipes/lib/genomic_bins.py``, which bins it to
``BIN_SIZE``-base windows with a lazy ``group_by``; the 750 MB of this megatest
bin in about seven seconds and cost one streaming batch of memory. What lands in
the data collection is a small, comparable matrix:

1. windows with fewer than ``MIN_CPGS_PER_WINDOW`` CpGs in a sample are dropped:
   a window mean over three CpGs is not a measurement of that window;
2. only windows that survive that cut in **every** sample are kept, so the
   matrix is complete and PCA, correlation and a per-window test all read the
   same rows rather than each imputing their own holes;
3. contigs left with fewer than ``MIN_WINDOWS_PER_CONTIG`` windows are dropped,
   which removes the unplaced scaffolds and the mitochondrion without naming a
   single assembly;
4. what remains is strided down to ``MAX_WINDOWS_PER_SAMPLE`` evenly spaced
   windows. A uniform stride over the genome-ordered windows is the honest
   decimation for drawing and for the cohort-structure panels (PCA,
   correlation, top-variable windows): keeping the CpG-densest windows instead
   would quietly turn every downstream panel into a CpG-island panel.

The stride is a drawing budget, not a statistical one: the group comparison
(``window_group_compare.py``) re-bins the same files through the same helper
and tests every eligible window, never this decimated subset.

The recipe reads its input file paths from a one-row-per-file **index** data
collection rather than from a glob source, because a glob source reads every
matched file into memory before the recipe sees it. The index is the ordinary
raw-scan idiom with ``n_rows: 1``: the scan is lazy, so one row is read per
file, and what the recipe actually wants from it is the ``source_path`` column.
The template declares it as::

    - data_collection_tag: "bismark_bedgraph_index"
      config:
        type: Table
        metatype: Aggregate
        scan:
          mode: recursive
          scan_parameters: {regex_config: {pattern: '.*\\.bedGraph\\.gz$'}}
        dc_specific_properties:
          format: TSV
          polars_kwargs:
            separator: "\\t"
            has_header: false
            skip_rows: 1          # the `track type=bedGraph` line
            n_rows: 1
            new_columns: [chrom, start, end, pct]
            include_file_paths: source_path
            infer_schema_length: 0

A ``cpg_density_class`` rides along because the question a reader asks next is
always "is this a CpG island or the bulk genome", and nf-core/methylseq bundles
no CGI or TSS annotation at any version. CpG density is the property a CGI is
defined by, so the tertiles of ``n_cpg`` are the annotation-free stratification
of the same axis: CpG-poor, Intermediate, CpG-dense. It is a proxy, it is
labelled as one, and it lets a feature-class panel exist without shipping a
genome build's BED files.

Output schema:
    sample : Utf8              library the window was measured in
    chromosome : Utf8          contig the window sits on
    start : Int64              window start, 0-based, a multiple of BIN_SIZE
    end : Int64                window end, exclusive
    position : Int64           window centre, the coordinate a track plots on
    methylation_pct : Float64  mean % methylation over the window's CpGs
    n_cpg : Int64              CpGs behind that mean
    cpg_density_class : Utf8   CpG-poor / Intermediate / CpG-dense, by n_cpg tertile
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import bismark_names

RAW_DC_TAG = "bismark_bedgraph_index"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="index", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "position": pl.Int64,
    "methylation_pct": pl.Float64,
    "n_cpg": pl.Int64,
    "cpg_density_class": pl.Utf8,
}

#: Window width and eligibility cut-offs, shared with the group comparison
#: through ``depictio/recipes/lib/bismark_names.py``.
BIN_SIZE = bismark_names.WINDOW_SIZE
MIN_CPGS_PER_WINDOW = bismark_names.MIN_CPGS_PER_WINDOW
MIN_WINDOWS_PER_CONTIG = bismark_names.MIN_WINDOWS_PER_CONTIG
#: Windows kept per sample after the uniform genome-wide stride.
MAX_WINDOWS_PER_SAMPLE = 20_000
#: Labels of the CpG-density tertiles, sparsest first. A stand-in for the CGI
#: annotation nf-core/methylseq does not bundle, computed on the whole matrix so
#: a window carries the same class in every library.
CPG_DENSITY_CLASSES = ("CpG-poor", "Intermediate", "CpG-dense")


def _contig_order(frame: pl.DataFrame, column: str = "chromosome") -> pl.DataFrame:
    """Add the sort key that puts chr1..chr22 before chrX, chrY and the rest."""
    return frame.with_columns(
        pl.col(column).str.extract(r"^(?:chr)?(\d+)$", 1).cast(pl.Int64).alias("_contig_number")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Stream every bedGraph into windows, keep the complete matrix, stride it."""
    long = bismark_names.eligible_methylation_windows(
        sources["index"], "bismark_binned_methylation"
    )
    windows = long.select("chromosome", "start").unique()
    ordered = _contig_order(windows).sort(
        ["_contig_number", "chromosome", "start"], nulls_last=True
    )
    stride = max(1, -(-ordered.height // MAX_WINDOWS_PER_SAMPLE))
    kept_windows = (
        ordered.with_row_index("_rank")
        .filter(pl.col("_rank") % stride == 0)
        .select("chromosome", "start", "_contig_number")
    )

    kept = long.join(kept_windows, on=["chromosome", "start"], how="inner")
    # Tertile cuts on the whole kept matrix, so a window's class does not change
    # from one library to the next.
    low, high = kept.get_column("n_cpg").quantile(1 / 3), kept.get_column("n_cpg").quantile(2 / 3)
    poor, intermediate, dense = CPG_DENSITY_CLASSES
    return (
        kept.with_columns(
            (pl.col("start") + BIN_SIZE // 2).cast(pl.Int64).alias("position"),
            pl.when(pl.col("n_cpg") <= low)
            .then(pl.lit(poor))
            .when(pl.col("n_cpg") <= high)
            .then(pl.lit(intermediate))
            .otherwise(pl.lit(dense))
            .cast(pl.Utf8)
            .alias("cpg_density_class"),
        )
        .sort(["sample", "_contig_number", "chromosome", "start"], nulls_last=True)
        .select(list(EXPECTED_SCHEMA))
    )
