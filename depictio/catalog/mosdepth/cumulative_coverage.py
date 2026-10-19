"""Cumulative coverage curve per mapping, from mosdepth's ``global.dist.txt``.

``<prefix>.mosdepth.global.dist.txt`` lists, for each contig and for the
``total``, the share of bases covered at least at each depth. This recipe
keeps the ``total`` rows (a mapping onto one reference has one contig, and the
total of several is what a breadth figure reads) as percentages: every depth
up to 100X, then a log-spaced grid, so a deep run does not list thousands of
depths a curve cannot tell apart.

The file's place names the mapping as for ``mosdepth/per_base_bins``:
``.../mosdepth/<sample>/[<prefix>-]<sample>_<reference>[...]`` on
nf-core/viralmetagenome, ``.../mosdepth/<sample>...`` on a flat layout.

Output schema:
    sample : Utf8           sample id
    reference : Utf8        reference the reads were mapped to, null on a flat layout
    genome_id : Utf8        <sample>_<reference>, the key the consensus collections join on
    depth : Int64           depth threshold
    bases_pct : Float64     bases covered at least at that depth, percent
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
        ref="dist",
        glob_pattern="**/mosdepth/**/*.mosdepth.global.dist.txt",
        format="tsv",
        read_kwargs={"has_header": False, "infer_schema_length": 0, "quote_char": None},
        source_path="source_path",
        input_schema={
            "column_1": pl.Utf8,
            "column_2": pl.Utf8,
            "column_3": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "reference": pl.Utf8,
    "genome_id": pl.Utf8,
    "depth": pl.Int64,
    "bases_pct": pl.Float64,
}

_SUFFIX = ".mosdepth.global.dist.txt"
_TOOL_DIRS = ("mosdepth", "genome", "metrics")
# Every depth to 100X, then 20 points per decade.
_GRID = sorted(set(range(101)) | {round(10 ** (k / 20)) for k in range(40, 141)})


def _ids(path: str) -> list[str | None]:
    stem = PurePosixPath(path).name.removesuffix(_SUFFIX)
    sample = sample_from_path(f"{PurePosixPath(path).parent}/{stem}", _TOOL_DIRS)
    if sample == stem:
        sample = strip_global_prefix(stem)
        return [sample, None, sample]
    reference, _route, _step = split_mapping_name(stem, sample)
    return [sample, reference, genome_id(sample, reference)]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["dist"]
    rows = df.select(
        pl.col("source_path"),
        pl.col("column_1").alias("chrom"),
        pl.col("column_2").cast(pl.Int64, strict=False).alias("depth"),
        (pl.col("column_3").cast(pl.Float64, strict=False) * 100.0).round(2).alias("bases_pct"),
    ).drop_nulls()
    # The `total` rows when the file has them, else the single contig.
    has_total = rows.group_by("source_path").agg((pl.col("chrom") == "total").any().alias("_t"))
    rows = rows.join(has_total, on="source_path").filter(
        (pl.col("chrom") == "total") | ~pl.col("_t")
    )
    rows = rows.filter(pl.col("depth").is_in(_GRID))
    ids = rows["source_path"].map_elements(_ids, return_dtype=pl.List(pl.Utf8))
    out = rows.with_columns(
        ids.list.get(0).alias("sample"),
        ids.list.get(1).alias("reference"),
        ids.list.get(2).alias("genome_id"),
    )
    return (
        out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .unique(subset=["genome_id", "depth"], keep="first")
        .sort(["sample", "genome_id", "depth"])
    )
