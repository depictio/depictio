"""hmftools BamTools alignment summary, one row per DNA sample.

BamTools (hmftools ``bam-tools``) walks each DNA BAM once and writes
``<sample>.bam_metric.summary.tsv``: one header and one data row with the read
counts (total, duplicate, dual-strand, off-target), the coverage statistics
over the genome or the target regions (mean, standard deviation, median, MAD),
the fractions of bases lost to low mapping quality, duplicates, unmapped reads,
low base quality, read overlap and the coverage cap, and the fraction of bases
covered at 1x, 5x, 10x ... 100x (``DepthCoverage_<N>``).

Every fraction is a 0 to 1 value (BamTools names them Percent). The
``DepthCoverage_<N>`` columns become ``frac_ge_<N>x``; the depths present vary
with the BamTools version, so only 10x, 20x, 30x and 60x are required. The
sample id is the file name before ``.bam_metric.summary.tsv``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        glob_pattern="**/*.bam_metric.summary.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

_RENAMES: dict[str, tuple[str, type[pl.DataType]]] = {
    "TotalRegionBases": ("region_bases", pl.Int64),
    "TotalReads": ("total_reads", pl.Int64),
    "DuplicateReads": ("duplicate_reads", pl.Int64),
    "DualStrandReads": ("dual_strand_reads", pl.Int64),
    "MeanCoverage": ("mean_coverage", pl.Float64),
    "StdDevCoverage": ("sd_coverage", pl.Float64),
    "MedianCoverage": ("median_coverage", pl.Float64),
    "MadCoverage": ("mad_coverage", pl.Float64),
    "LowMapQualPercent": ("low_map_qual_frac", pl.Float64),
    "DuplicatePercent": ("duplicate_frac", pl.Float64),
    "UnmappedPercent": ("unmapped_frac", pl.Float64),
    "LowBaseQualPercent": ("low_base_qual_frac", pl.Float64),
    "OverlappingReadPercent": ("overlapping_read_frac", pl.Float64),
    "CappedCoverage": ("capped_coverage_frac", pl.Float64),
}

#: Depth thresholds every BamTools version reports.
REQUIRED_DEPTHS = (10, 20, 30, 60)

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    **{out: dtype for out, dtype in _RENAMES.values()},
    **{f"frac_ge_{d}x": pl.Float64 for d in REQUIRED_DEPTHS},
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    f"frac_ge_{d}x": pl.Float64 for d in (1, 5, 15, 25, 40, 50, 70, 80, 90, 100)
}

_SAMPLE_RE = r"([^/]+)\.bam_metric\.summary\.tsv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["summary"]
    for raw in _RENAMES:
        if raw not in df.columns:
            df = df.with_columns(pl.lit(None, pl.Utf8).alias(raw))
    depth_cols = sorted(
        (c for c in df.columns if c.startswith("DepthCoverage_")),
        key=lambda c: int(c.split("_")[1]),
    )
    for d in REQUIRED_DEPTHS:
        if f"DepthCoverage_{d}" not in depth_cols:
            depth_cols.append(f"DepthCoverage_{d}")
            df = df.with_columns(pl.lit(None, pl.Utf8).alias(f"DepthCoverage_{d}"))
    return df.select(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        *[
            pl.col(raw).cast(pl.Float64, strict=False).round(0).cast(pl.Int64).alias(out)
            if dtype == pl.Int64
            else pl.col(raw).cast(pl.Float64, strict=False).alias(out)
            for raw, (out, dtype) in _RENAMES.items()
        ],
        *[
            pl.col(c).cast(pl.Float64, strict=False).alias(f"frac_ge_{c.split('_')[1]}x")
            for c in depth_cols
        ],
    ).sort("sample")
