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
   decimation for a genome-wide screen: keeping the CpG-densest windows instead
   would quietly turn every downstream panel into a CpG-island panel.

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

import re
from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bismark_names import sample_id_from_filename
from depictio.recipes.lib.genomic_bins import bin_delimited_file

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

SOURCE_PATH_COL = "source_path"

#: Window width. See ``genomic_bins.DEFAULT_BIN_SIZE`` for why 10 kb.
BIN_SIZE = 10_000
#: A window mean is a measurement only once enough CpGs stand behind it.
MIN_CPGS_PER_WINDOW = 20
#: Contigs with fewer surviving windows than this are assembly debris.
MIN_WINDOWS_PER_CONTIG = 50
#: Windows kept per sample after the uniform genome-wide stride.
MAX_WINDOWS_PER_SAMPLE = 20_000
#: Labels of the CpG-density tertiles, sparsest first. A stand-in for the CGI
#: annotation nf-core/methylseq does not bundle, computed on the whole matrix so
#: a window carries the same class in every library.
CPG_DENSITY_CLASSES = ("CpG-poor", "Intermediate", "CpG-dense")

# `_1_val_1_bismark_bt2_pe.deduplicated.bedGraph.gz` and its single-end,
# hisat2, `--skip_trimming` and `--skip_deduplication` spellings.
_SUFFIX_RE = re.compile(
    r"(_\d+)?(_val_\d+)?_bismark_[a-z0-9]+_(pe|se)(\.deduplicated)?\.bedGraph\.gz$", re.IGNORECASE
)
_BEDGRAPH_COLUMNS = ["chrom", "start", "end", "pct"]


def _source_paths(index: pl.DataFrame) -> list[str]:
    if index.is_empty():
        raise ValueError(f"bismark_binned_methylation: '{RAW_DC_TAG}' is empty")
    if SOURCE_PATH_COL not in index.columns:
        raise ValueError(
            f"bismark_binned_methylation: '{RAW_DC_TAG}' must be scanned with "
            f"include_file_paths={SOURCE_PATH_COL}"
        )
    return sorted({str(p) for p in index.get_column(SOURCE_PATH_COL).to_list() if p})


def _contig_order(frame: pl.DataFrame, column: str = "chromosome") -> pl.DataFrame:
    """Add the sort key that puts chr1..chr22 before chrX, chrY and the rest."""
    return frame.with_columns(
        pl.col(column).str.extract(r"^(?:chr)?(\d+)$", 1).cast(pl.Int64).alias("_contig_number")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Stream every bedGraph into windows, keep the complete comparable matrix."""
    paths = _source_paths(sources["index"])

    per_sample: list[pl.DataFrame] = []
    for path in paths:
        binned = bin_delimited_file(
            path,
            column_names=_BEDGRAPH_COLUMNS,
            chrom_col="chrom",
            pos_col="start",
            value_col="pct",
            bin_size=BIN_SIZE,
            skip_rows=1,
        )
        kept = binned.filter(pl.col("n") >= MIN_CPGS_PER_WINDOW).select(
            pl.lit(sample_id_from_filename(path, _SUFFIX_RE), pl.Utf8).alias("sample"),
            pl.col("chrom").alias("chromosome"),
            pl.col("start"),
            pl.col("end"),
            pl.col("mean").alias("methylation_pct"),
            pl.col("n").alias("n_cpg"),
        )
        if kept.is_empty():
            raise ValueError(
                f"bismark_binned_methylation: no window of {Path(path).name} reached "
                f"{MIN_CPGS_PER_WINDOW} CpGs"
            )
        per_sample.append(kept)

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
        .filter(pl.col("_windows") >= MIN_WINDOWS_PER_CONTIG)
        .get_column("chromosome")
        .to_list()
    )
    complete = complete.filter(pl.col("chromosome").is_in(dense_contigs))
    if complete.is_empty():
        raise ValueError(
            "bismark_binned_methylation: no window is covered in every sample on any contig "
            f"with at least {MIN_WINDOWS_PER_CONTIG} windows; the libraries share no "
            "comparable genomic space"
        )

    ordered = _contig_order(complete).sort(
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
