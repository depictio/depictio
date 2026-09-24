"""Distribution of per-CpG methylation, one curve per library.

The single most diagnostic picture of a bisulfite library is not a mean, it is
the shape of the per-site distribution: a healthy mammalian methylome is
strongly bimodal, a tall peak at 0 % (unmethylated CpG islands and promoters)
and a taller one at 100 % (the methylated bulk of the genome), with very little
in between. A library that has lost the bimodality, or whose 0 % peak has
drifted upward, is telling you about incomplete bisulfite conversion or about
coverage too shallow for a site call, long before any mean does.

Bismark publishes the per-CpG percentages in the same
``<sample>.deduplicated.bedGraph.gz`` the window binning reads: 8 to 46 million
rows per library. This recipe streams each file a second time (a lazy scan plus
a ``group_by`` over a 50-bucket histogram costs about three seconds for the whole
run) and keeps only the histogram, so what lands in the collection is 50 rows
per sample rather than 300 million.

Buckets are ``BIN_WIDTH_PCT`` wide and named by their centre, so the curve a
``profile`` draws has an x axis in percent that means what it says. The y axis
is the share of the sample's CpGs in the bucket rather than the raw count,
because the libraries in a run differ by an order of magnitude in depth and an
unnormalised histogram would only redraw that.

Reads its input file paths from the ``bismark_bedgraph_index`` collection; see
``binned_methylation.py`` for why an index rather than a glob source, and for
the data collection that declares it.

Output schema:
    sample : Utf8                library the CpGs were called in
    series : Utf8               the sample, under the name the profile kind binds
    methylation_bin : Float64   bucket centre, in % methylation
    n_cpgs : Int64              CpGs of this library in the bucket
    fraction_of_cpgs : Float64  n_cpgs as a % of the library's called CpGs
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bismark_names import (
    BEDGRAPH_COLUMNS,
    BEDGRAPH_SUFFIX_RE,
    sample_id_from_filename,
)

RAW_DC_TAG = "bismark_bedgraph_index"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="index", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "series": pl.Utf8,
    "methylation_bin": pl.Float64,
    "n_cpgs": pl.Int64,
    "fraction_of_cpgs": pl.Float64,
}

SOURCE_PATH_COL = "source_path"

#: Bucket width in percentage points. 2 % gives 50 buckets, which is enough
#: resolution to separate the 0 % and 100 % spikes from their shoulders and few
#: enough points to draw seven curves without thinning.
BIN_WIDTH_PCT = 2.0


def _histogram(path: str) -> pl.DataFrame:
    """Stream one bedGraph into its per-CpG methylation histogram."""
    n_buckets = int(round(100.0 / BIN_WIDTH_PCT))
    frame = pl.scan_csv(
        path,
        separator="\t",
        has_header=False,
        skip_rows=1,  # the `track type=bedGraph` line
        new_columns=BEDGRAPH_COLUMNS,
        schema_overrides={"chrom": pl.Utf8, "start": pl.Int64, "pct": pl.Float64},
    )
    bucket = (
        (pl.col("pct").cast(pl.Float64) / BIN_WIDTH_PCT)
        .floor()
        .clip(0, n_buckets - 1)
        .cast(pl.Int64)
    )
    return (
        frame.with_columns(bucket.alias("_bucket"))
        .group_by("_bucket")
        .agg(pl.len().alias("n_cpgs"))
        .collect(engine="streaming")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One histogram per bedGraph, normalised to the library's CpG total."""
    index = sources["index"]
    if index.is_empty():
        raise ValueError(f"bismark_methylation_density: '{RAW_DC_TAG}' is empty")
    if SOURCE_PATH_COL not in index.columns:
        raise ValueError(
            f"bismark_methylation_density: '{RAW_DC_TAG}' must be scanned with "
            f"include_file_paths={SOURCE_PATH_COL}"
        )

    frames: list[pl.DataFrame] = []
    for path in sorted({str(p) for p in index.get_column(SOURCE_PATH_COL).to_list() if p}):
        histogram = _histogram(path)
        if histogram.is_empty():
            raise ValueError(f"bismark_methylation_density: {Path(path).name} holds no CpG")
        sample = sample_id_from_filename(path, BEDGRAPH_SUFFIX_RE)
        total = int(histogram.get_column("n_cpgs").sum())
        frames.append(
            histogram.select(
                pl.lit(sample, pl.Utf8).alias("sample"),
                pl.lit(sample, pl.Utf8).alias("series"),
                ((pl.col("_bucket") + 0.5) * BIN_WIDTH_PCT)
                .cast(pl.Float64)
                .alias("methylation_bin"),
                pl.col("n_cpgs").cast(pl.Int64),
                (pl.col("n_cpgs") / total * 100.0).cast(pl.Float64).alias("fraction_of_cpgs"),
            )
        )

    return pl.concat(frames).sort(["sample", "methylation_bin"]).select(list(EXPECTED_SCHEMA))
