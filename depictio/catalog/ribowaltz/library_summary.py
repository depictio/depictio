"""One row per Ribo-seq library: the riboWaltz quality readouts side by side.

Pools three riboWaltz tables of the same library into the numbers a reviewer
compares across libraries:

* ``frame0_cds_pct``: share of CDS P-sites in frame 0, the annotated reading
  frame. Around 33 % means no periodicity; well-phased footprints reach well
  above half.
* ``frame_bias``: that share minus the larger of the two other frames, in
  percentage points. Negative when another frame dominates, which usually
  means the P-site offsets are wrong for that library.
* ``cds_pct`` and the two UTR shares: where the P-sites fall, and
  ``cds_enrichment``, the CDS share over the CDS length share riboWaltz reports
  for the same transcripts.
* ``modal_length`` and ``length_iqr``: the read length most reads have and the
  spread around it.

Sources: the ``*.ribowaltz.frames.tsv``, ``*.ribowaltz.psite_region.tsv`` and
``*.ribowaltz.length_distribution.tsv`` files of every library.

Output schema: see ``EXPECTED_SCHEMA``; ``sample`` is the key.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_READ = {"infer_schema_length": 10000}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="frames", glob_pattern="**/*.ribowaltz.frames.tsv", format="tsv", read_kwargs=_READ
    ),
    RecipeSource(
        ref="regions",
        glob_pattern="**/*.ribowaltz.psite_region.tsv",
        format="tsv",
        read_kwargs=_READ,
        source_path="source_path",
    ),
    RecipeSource(
        ref="lengths",
        glob_pattern="**/*.ribowaltz.length_distribution.tsv",
        format="tsv",
        read_kwargs=_READ,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "psites": pl.Int64,
    "frame0_cds_pct": pl.Float64,
    "frame_bias": pl.Float64,
    "cds_pct": pl.Float64,
    "utr5_pct": pl.Float64,
    "utr3_pct": pl.Float64,
    "cds_enrichment": pl.Float64,
    "modal_length": pl.Int64,
    "length_iqr": pl.Int64,
}

EXPECTED_LABEL = "RNAs"
_SUFFIX = r"\.ribowaltz$"


def _sample(col: str = "sample") -> pl.Expr:
    return pl.col(col).cast(pl.Utf8).str.replace(_SUFFIX, "").alias("sample")


def _frames(df: pl.DataFrame) -> pl.DataFrame:
    cds = df.filter(pl.col("region").cast(pl.Utf8) == "CDS").select(
        _sample(),
        pl.col("frame").cast(pl.Int64).alias("frame"),
        pl.col("count").cast(pl.Float64).fill_null(0).alias("count"),
    )
    shares = cds.with_columns(
        (pl.col("count") * 100.0 / pl.col("count").sum().over("sample")).alias("share")
    )
    return shares.group_by("sample").agg(
        pl.col("share").filter(pl.col("frame") == 0).first().alias("frame0_cds_pct"),
        (
            pl.col("share").filter(pl.col("frame") == 0).first()
            - pl.col("share").filter(pl.col("frame") != 0).max()
        ).alias("frame_bias"),
    )


def _regions(df: pl.DataFrame) -> pl.DataFrame:
    df = df.with_columns(
        pl.col("sample").cast(pl.Utf8),
        pl.col("region").cast(pl.Utf8),
        pl.col("count").cast(pl.Float64).fill_null(0),
    )
    expected = (
        df.filter((pl.col("sample") == EXPECTED_LABEL) & (pl.col("region") == "CDS"))
        .join(
            df.filter(pl.col("sample") == EXPECTED_LABEL)
            .group_by("source_path")
            .agg(pl.col("count").sum().alias("total")),
            on="source_path",
        )
        .select("source_path", (pl.col("count") * 100.0 / pl.col("total")).alias("cds_expected"))
    )
    observed = df.filter(pl.col("sample") != EXPECTED_LABEL).with_columns(
        (pl.col("count") * 100.0 / pl.col("count").sum().over("source_path")).alias("share")
    )
    wide = observed.group_by("source_path", "sample").agg(
        pl.col("count").sum().round(0).cast(pl.Int64).alias("psites"),
        pl.col("share").filter(pl.col("region") == "CDS").first().alias("cds_pct"),
        pl.col("share").filter(pl.col("region") == "5' UTR").first().alias("utr5_pct"),
        pl.col("share").filter(pl.col("region") == "3' UTR").first().alias("utr3_pct"),
    )
    return (
        wide.join(expected, on="source_path", how="left")
        .with_columns(
            _sample(),
            pl.when(pl.col("cds_expected") > 0)
            .then(pl.col("cds_pct") / pl.col("cds_expected"))
            .otherwise(None)
            .alias("cds_enrichment"),
        )
        .drop("source_path", "cds_expected")
    )


def _lengths(df: pl.DataFrame) -> pl.DataFrame:
    df = df.select(
        _sample(),
        pl.col("length").cast(pl.Int64),
        pl.col("count").cast(pl.Float64).fill_null(0),
    ).sort("sample", "length")
    cum = pl.col("count").cum_sum().over("sample") / pl.col("count").sum().over("sample")
    df = df.with_columns(cum.alias("cum"))
    return df.group_by("sample").agg(
        pl.col("length").sort_by("count", descending=True).first().alias("modal_length"),
        (
            pl.col("length").filter(pl.col("cum") >= 0.75).min()
            - pl.col("length").filter(pl.col("cum") >= 0.25).min()
        ).alias("length_iqr"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join the three per-library readouts on the library id."""
    out = (
        _regions(sources["regions"])
        .join(_frames(sources["frames"]), on="sample", how="full", coalesce=True)
        .join(_lengths(sources["lengths"]), on="sample", how="full", coalesce=True)
    )
    casts = {name: dtype for name, dtype in EXPECTED_SCHEMA.items()}
    return (
        out.with_columns([pl.col(c).cast(t) for c, t in casts.items()])
        .sort("sample")
        .select(list(EXPECTED_SCHEMA))
    )
