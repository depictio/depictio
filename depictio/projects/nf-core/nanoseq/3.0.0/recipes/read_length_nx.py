"""The Nx ladder of each library, from the read-length histogram samtools stats keeps.

N50 is one rung of a ladder: Nx is the read length L such that reads at least
L long hold x percent of the library's bases. NanoStat reports N50 alone, and
the per-read table a full Nx curve would come from (NanoPlot ``--raw``, pycoQC)
is not something nanoseq publishes. The ``RL`` block of every ``samtools
stats`` report is, and it is an exact read-length histogram, so the whole
ladder falls out of it: sort the lengths longest first, accumulate
``length * count`` and read off where the running share crosses each x.

Two libraries with the same N50 can have very different ladders: a long flat
top is a library whose yield sits in a few very long reads, a steep drop is one
whose reads are all about the same length. That is the reading this curve is
for, and the one a bar of N50 values cannot give.

Output, one row per sample and rung (x = 1 .. 99):

    sample       library the ladder belongs to
    nx           the rung, as a percentage of the library's bases
    read_length  Nx: the shortest read length inside that share
    bases_share  share of the bases held by reads at least that long (>= nx)

The ``RL`` histogram covers every primary read in the BAM, mapped or not, so
the ladder is the library the aligner was given, not only what it placed.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

RAW_DC_TAG = "samtools_stats_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

RAW_LINE_COL = "raw_line"
SOURCE_PATH_COL = "source_path"

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "nx": pl.Float64,
    "read_length": pl.Float64,
    "bases_share": pl.Float64,
}

#: Rungs of the ladder, in percent of the library's bases.
RUNGS = list(range(1, 100))


def _sample_of(path: str) -> str:
    """`minimap2/samtools_stats/A549_R1.sorted.bam.stats` -> `A549_R1`."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    for suffix in (".stats", ".stat"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return strip_stage_suffixes(name)


def _read_lengths(lines: list[str | None]) -> pl.DataFrame:
    """The ``RL`` rows of one report as (length, count), invalid rows dropped."""
    frame = pl.DataFrame({"line": [str(line or "") for line in lines]})
    parts = frame.filter(pl.col("line").str.starts_with("RL\t")).select(
        pl.col("line").str.split("\t").alias("f")
    )
    return (
        parts.select(
            pl.col("f")
            .list.get(1, null_on_oob=True)
            .cast(pl.Float64, strict=False)
            .alias("length"),
            pl.col("f").list.get(2, null_on_oob=True).cast(pl.Float64, strict=False).alias("count"),
        )
        .drop_nulls()
        .filter((pl.col("length") > 0) & (pl.col("count") > 0))
    )


def _ladder(sample: str, histogram: pl.DataFrame) -> pl.DataFrame:
    """One sample's histogram -> its Nx rungs."""
    ranked = (
        histogram.group_by("length")
        .agg(pl.col("count").sum())
        .sort("length", descending=True)
        .with_columns((pl.col("length") * pl.col("count")).cum_sum().alias("cum_bases"))
    )
    total = float(ranked["cum_bases"][-1]) if ranked.height else 0.0
    if total <= 0:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    ranked = ranked.with_columns((pl.col("cum_bases") * 100.0 / total).alias("share"))
    lengths = ranked["length"].to_list()
    shares = ranked["share"].to_list()
    rows: list[dict[str, object]] = []
    cursor = 0
    for rung in RUNGS:
        while cursor < len(shares) - 1 and shares[cursor] < rung:
            cursor += 1
        rows.append(
            {
                "sample": sample,
                "nx": float(rung),
                "read_length": float(lengths[cursor]),
                "bases_share": float(shares[cursor]),
            }
        )
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Raw samtools stats lines -> one Nx ladder per library."""
    raw = sources["raw"]
    ladders = [
        _ladder(_sample_of(str(path)), _read_lengths(block[RAW_LINE_COL].to_list()))
        for (path,), block in raw.group_by(SOURCE_PATH_COL, maintain_order=True)
    ]
    if not ladders:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    return pl.concat(ladders).select(list(EXPECTED_SCHEMA)).sort(["sample", "nx"])
