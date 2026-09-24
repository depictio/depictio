"""riboWaltz P-site frame distribution per library and transcript region.

riboWaltz assigns every P-site to one of the three reading frames relative to
the annotated start codon and writes, per library, a ``*.ribowaltz.frames.tsv``
table (``sample, region, frame, count, scaled_count``) with one row per region
(5' UTR, CDS, 3' UTR) and frame. A translating ribosome moves one codon at a
time, so a good Ribo-seq library piles its CDS P-sites into one frame while the
UTRs stay close to a third each.

Output: one row per library, region and frame.
    sample : Utf8     library id (the ``.ribowaltz`` suffix riboWaltz appends is removed)
    region : Utf8     5' UTR, CDS or 3' UTR
    frame : Utf8      "Frame 0", "Frame 1", "Frame 2"
    count : Int64     P-sites in this region and frame
    pct : Float64     share of the region's P-sites in this frame, in percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="frames",
        glob_pattern="**/*.ribowaltz.frames.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "region": pl.Utf8,
    "frame": pl.Utf8,
    "count": pl.Int64,
    "pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Frame counts per library and region, with the within-region share."""
    df = sources["frames"]
    out = df.select(
        pl.col("sample").cast(pl.Utf8).str.replace(r"\.ribowaltz$", "").alias("sample"),
        pl.col("region").cast(pl.Utf8),
        pl.format("Frame {}", pl.col("frame").cast(pl.Int64)).alias("frame"),
        pl.col("count").cast(pl.Float64).fill_null(0).round(0).cast(pl.Int64).alias("count"),
    )
    total = pl.col("count").sum().over(["sample", "region"])
    return (
        out.with_columns(
            pl.when(total > 0)
            .then(pl.col("count") * 100.0 / total)
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("pct")
        )
        .sort("sample", "region", "frame")
        .select(list(EXPECTED_SCHEMA))
    )
