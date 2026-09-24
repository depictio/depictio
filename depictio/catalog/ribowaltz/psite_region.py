"""riboWaltz P-site share per transcript region, against the transcriptome expectation.

``*.ribowaltz.psite_region.tsv`` holds, per library, the P-sites that fall in
the 5' UTR, the CDS and the 3' UTR, plus three rows labelled ``RNAs``: the share
each region would get if reads fell uniformly along the transcripts (their
length share). Ribosome footprints should be strongly enriched in the CDS
compared with that expectation; a library that follows the expectation looks
like fragmented RNA rather than protected footprints.

Output: one row per library and region.
    sample : Utf8         library id
    region : Utf8         5' UTR, CDS or 3' UTR
    scope : Utf8          constant "P-sites", the single composition level a
                          stacked bar needs
    count : Int64         P-sites in the region
    pct : Float64         share of the library's P-sites, in percent
    expected_pct : Float64  length share of the region over the same transcripts, in percent
    enrichment : Float64  pct / expected_pct (1 means no enrichment)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="regions",
        glob_pattern="**/*.ribowaltz.psite_region.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "region": pl.Utf8,
    "scope": pl.Utf8,
    "count": pl.Int64,
    "pct": pl.Float64,
    "expected_pct": pl.Float64,
    "enrichment": pl.Float64,
}

# Label riboWaltz gives the transcript-length expectation rows.
EXPECTED_LABEL = "RNAs"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Observed P-site share per region, joined to the file's own expectation rows."""
    df = sources["regions"].with_columns(
        pl.col("sample").cast(pl.Utf8),
        pl.col("region").cast(pl.Utf8),
        pl.col("count").cast(pl.Float64).fill_null(0),
    )
    observed = df.filter(pl.col("sample") != EXPECTED_LABEL)
    expected = (
        df.filter(pl.col("sample") == EXPECTED_LABEL)
        .with_columns(
            (pl.col("count") * 100.0 / pl.col("count").sum().over("source_path")).alias(
                "expected_pct"
            )
        )
        .select("source_path", "region", "expected_pct")
    )
    out = (
        observed.with_columns(
            pl.col("sample").str.replace(r"\.ribowaltz$", ""),
            (pl.col("count") * 100.0 / pl.col("count").sum().over("source_path")).alias("pct"),
        )
        .join(expected, on=["source_path", "region"], how="left")
        .with_columns(
            pl.lit("P-sites").alias("scope"),
            pl.col("count").round(0).cast(pl.Int64),
            pl.col("pct").cast(pl.Float64),
            pl.col("expected_pct").cast(pl.Float64),
            pl.when(pl.col("expected_pct") > 0)
            .then(pl.col("pct") / pl.col("expected_pct"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("enrichment"),
        )
    )
    return out.sort("sample", "region").select(list(EXPECTED_SCHEMA))
