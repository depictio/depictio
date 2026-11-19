"""Depth over the two ends of each genome, in fine bins, from mosdepth's per-base depth.

The depth profile of the Mapping tab bins each genome 50 bp wide or wider
(``coverage_bins``, catalog ``mosdepth/per_base_bins``): enough to see a dropout,
too coarse for a genome's ends, where the reads thin out over the last few
dozen bases and a consensus is least certain. A segmented virus also keeps
conserved termini at each segment's ends, which a de novo genome often misses.
This recipe reads the same per-base depth (runs of equal depth, ``chrom, start,
end, depth``) and bins the first and last ``END_BP`` bases of every reference
``BIN_BP`` wide, each bin keyed by its distance from the tip of the genome.

The file's place names the mapping, as for ``coverage_bins``:
``.../mosdepth/<sample>/[<prefix>-]<sample>_<reference>[...].per-base.bed.gz``.

Sources:
    per_base  ``variants/mapping-info/metrics/mosdepth/*/*.per-base.bed.gz``
    genomes   ``genomes``, the genome hub, optional (virus and segment)

Output schema:
    sample, reference, genome_id, chrom : Utf8
    end_region : Utf8       5' end or 3' end
    start, end : Int64      bin, 0-based half-open
    end_offset : Int64      bin centre's distance from the tip of its end, bp
    length : Int64          reference length, bp
    mean_depth : Float64    length-weighted mean depth over the bin
    min_depth : Int64       lowest depth in the bin
    virus_segment : Utf8
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import (
    genome_id,
    sample_from_path,
    split_mapping_name,
    strip_global_prefix,
)

#: Bases of each end binned, and the width of a bin there.
END_BP = 200
BIN_BP = 10

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="per_base",
        glob_pattern="variants/mapping-info/metrics/mosdepth/*/*.per-base.bed.gz",
        format="tsv",
        read_kwargs={"has_header": False, "infer_schema_length": 0, "quote_char": None},
        source_path="source_path",
        input_schema={
            "column_1": pl.Utf8,
            "column_2": pl.Utf8,
            "column_3": pl.Utf8,
            "column_4": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="genomes", dc_ref="genomes", optional=True, input_schema={"genome_id": pl.Utf8}
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "reference": pl.Utf8,
    "genome_id": pl.Utf8,
    "chrom": pl.Utf8,
    "end_region": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "end_offset": pl.Int64,
    "length": pl.Int64,
    "mean_depth": pl.Float64,
    "min_depth": pl.Int64,
    "virus_segment": pl.Utf8,
}

_SUFFIX = ".per-base.bed.gz"
_TOOL_DIRS = ("mosdepth", "genome", "metrics")


def _ids(path: str) -> list[str | None]:
    stem = PurePosixPath(path).name.removesuffix(_SUFFIX)
    sample = sample_from_path(f"{PurePosixPath(path).parent}/{stem}", _TOOL_DIRS)
    if sample == stem:
        sample = strip_global_prefix(stem)
        return [sample, None, sample]
    reference, _route, _step = split_mapping_name(stem, sample)
    return [sample, reference, genome_id(sample, reference)]


def _bin_window(runs: pl.DataFrame, region: str, lo: pl.Expr, hi: pl.Expr) -> pl.DataFrame:
    """Runs clipped to ``[lo, hi)``, cut into ``BIN_BP`` bins from ``lo``, one row per overlap."""
    clipped = (
        runs.with_columns(lo.alias("lo"), hi.alias("hi"))
        .with_columns(
            pl.max_horizontal("run_start", "lo").alias("rs"),
            pl.min_horizontal("run_end", "hi").alias("re"),
        )
        .filter(pl.col("re") > pl.col("rs"))
    )
    return (
        clipped.with_columns(
            pl.int_ranges(
                (pl.col("rs") - pl.col("lo")) // BIN_BP,
                (pl.col("re") - 1 - pl.col("lo")) // BIN_BP + 1,
            ).alias("bin")
        )
        .explode("bin")
        .with_columns(
            (pl.col("lo") + pl.col("bin") * BIN_BP).alias("start"),
            pl.min_horizontal(pl.col("lo") + (pl.col("bin") + 1) * BIN_BP, pl.col("hi")).alias(
                "end"
            ),
        )
        .with_columns(
            (pl.min_horizontal("re", "end") - pl.max_horizontal("rs", "start")).alias("overlap"),
            pl.lit(region).alias("end_region"),
        )
        .filter(pl.col("overlap") > 0)
        .select("source_path", "chrom", "length", "end_region", "start", "end", "depth", "overlap")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    runs = (
        sources["per_base"]
        .select(
            pl.col("source_path"),
            pl.col("column_1").alias("chrom"),
            pl.col("column_2").cast(pl.Int64, strict=False).alias("run_start"),
            pl.col("column_3").cast(pl.Int64, strict=False).alias("run_end"),
            pl.col("column_4").cast(pl.Int64, strict=False).alias("depth"),
        )
        .drop_nulls()
    )
    runs = runs.with_columns(pl.col("run_end").max().over("source_path", "chrom").alias("length"))
    # A reference shorter than both ends together is cut in two halves.
    edge = pl.min_horizontal(pl.lit(END_BP), pl.col("length") // 2)
    binned = (
        pl.concat(
            [
                _bin_window(runs, "5' end", pl.lit(0), edge),
                _bin_window(runs, "3' end", pl.col("length") - edge, pl.col("length")),
            ]
        )
        .group_by("source_path", "chrom", "length", "end_region", "start", "end")
        .agg(
            ((pl.col("depth") * pl.col("overlap")).sum() / pl.col("overlap").sum())
            .round(2)
            .alias("mean_depth"),
            pl.col("depth").min().alias("min_depth"),
        )
    )
    if binned.is_empty():
        raise ValueError("viralmetagenome genome_ends: no per-base depth to bin")
    centre = (pl.col("start") + pl.col("end")) // 2
    ids = binned["source_path"].map_elements(_ids, return_dtype=pl.List(pl.Utf8))
    out = binned.with_columns(
        ids.list.get(0).alias("sample"),
        ids.list.get(1).alias("reference"),
        ids.list.get(2).alias("genome_id"),
        pl.when(pl.col("end_region") == "5' end")
        .then(centre)
        .otherwise(pl.col("length") - centre)
        .alias("end_offset"),
    )
    genomes = sources.get("genomes")
    if genomes is not None and not genomes.is_empty() and "virus_segment" in genomes.columns:
        out = out.join(
            genomes.select("genome_id", "virus_segment").unique(subset="genome_id"),
            on="genome_id",
            how="left",
        )
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("virus_segment"))
    out = out.with_columns(pl.col("virus_segment").fill_null(pl.col("genome_id")))
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["sample", "genome_id", "chrom", "end_region", "start"]
    )
