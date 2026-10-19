"""Read depth along each reference, binned, from mosdepth's ``per-base.bed.gz``.

Without ``--by`` mosdepth writes the depth of every base as runs of equal depth
(``<prefix>.per-base.bed.gz``: chrom, start, end, depth). On a viral genome of a
few tens of kilobases that is ten thousand rows per mapping; this recipe folds
them into fixed bins, the length-weighted mean depth of each, so a coverage
track draws one lane per mapping with the dropouts still visible. The bin
width follows the reference length, the smallest of 50, 100, 200, 500, 1000,
2000 or 5000 bp that keeps a reference under about 600 bins.

The file's place names the mapping: nf-core/viralmetagenome writes
``.../mosdepth/<sample>/[<prefix>-]<sample>_<reference>[...].per-base.bed.gz``
(the reference a constraint or a de novo cluster), a flat layout
``.../mosdepth/<sample>.per-base.bed.gz``.

Output schema:
    sample : Utf8          sample id
    reference : Utf8       reference the reads were mapped to, null on a flat layout
    genome_id : Utf8       <sample>_<reference>, the key the consensus collections join on
    chrom : Utf8           reference sequence
    start : Int64          bin start, 0-based
    end : Int64            bin end
    position : Int64       bin centre
    mean_depth : Float64   length-weighted mean depth over the bin
    min_depth : Int64      lowest depth in the bin
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

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="per_base",
        glob_pattern="**/mosdepth/**/*.per-base.bed.gz",
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
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "reference": pl.Utf8,
    "genome_id": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "position": pl.Int64,
    "mean_depth": pl.Float64,
    "min_depth": pl.Int64,
}

BIN_STEPS = (50, 100, 200, 500, 1000, 2000, 5000)
MAX_BINS = 600
_SUFFIX = ".per-base.bed.gz"
_TOOL_DIRS = ("mosdepth", "genome", "metrics")


def bin_width(length: int) -> int:
    """The smallest bin width of ``BIN_STEPS`` that keeps ``length`` under ``MAX_BINS`` bins."""
    for step in BIN_STEPS:
        if length / step <= MAX_BINS:
            return step
    return BIN_STEPS[-1]


def _ids(path: str) -> list[str | None]:
    stem = PurePosixPath(path).name.removesuffix(_SUFFIX)
    sample = sample_from_path(f"{PurePosixPath(path).parent}/{stem}", _TOOL_DIRS)
    if sample == stem:
        sample = strip_global_prefix(stem)
        return [sample, None, sample]
    reference, _route, _step = split_mapping_name(stem, sample)
    return [sample, reference, genome_id(sample, reference)]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["per_base"]
    runs = df.select(
        pl.col("source_path"),
        pl.col("column_1").alias("chrom"),
        pl.col("column_2").cast(pl.Int64, strict=False).alias("run_start"),
        pl.col("column_3").cast(pl.Int64, strict=False).alias("run_end"),
        pl.col("column_4").cast(pl.Int64, strict=False).alias("depth"),
    ).drop_nulls()
    lengths = runs.group_by("source_path", "chrom").agg(pl.col("run_end").max().alias("length"))
    lengths = lengths.with_columns(
        pl.col("length").map_elements(bin_width, return_dtype=pl.Int64).alias("width")
    )
    runs = runs.join(lengths, on=["source_path", "chrom"])
    binned = (
        runs.with_columns(
            pl.int_ranges(
                pl.col("run_start") // pl.col("width"),
                (pl.col("run_end") - 1) // pl.col("width") + 1,
            ).alias("bin")
        )
        .explode("bin", empty_as_null=True)
        .with_columns(
            (pl.col("bin") * pl.col("width")).alias("start"),
            pl.min_horizontal((pl.col("bin") + 1) * pl.col("width"), pl.col("length")).alias("end"),
        )
        .with_columns(
            (pl.min_horizontal("run_end", "end") - pl.max_horizontal("run_start", "start")).alias(
                "overlap"
            )
        )
        .filter(pl.col("overlap") > 0)
        .group_by("source_path", "chrom", "start", "end")
        .agg(
            ((pl.col("depth") * pl.col("overlap")).sum() / pl.col("overlap").sum())
            .round(2)
            .alias("mean_depth"),
            pl.col("depth").min().alias("min_depth"),
        )
    )
    ids = binned["source_path"].map_elements(_ids, return_dtype=pl.List(pl.Utf8))
    out = binned.with_columns(
        ids.list.get(0).alias("sample"),
        ids.list.get(1).alias("reference"),
        ids.list.get(2).alias("genome_id"),
        ((pl.col("start") + pl.col("end")) // 2).alias("position"),
    )
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["sample", "genome_id", "chrom", "start"]
    )
