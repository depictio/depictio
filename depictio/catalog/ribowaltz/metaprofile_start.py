"""riboWaltz metagene P-site profile around the start codon.

``*.ribowaltz.metaprofile_psite.tsv`` holds, per library, the P-site signal
summed over all transcripts at each nucleotide around the annotated start and
stop codons (``region`` = ``Distance from start (nt)`` / ``Distance from stop
(nt)``). This recipe keeps the start-codon window; ``metaprofile_stop.py`` the
stop-codon one. A clean library shows a peak at the start codon and a 3-nt
saw-tooth along the CDS.

Output: one row per library and position.
    sample : Utf8       library id
    position : Int64    distance from the first nucleotide of the start codon, nt
    signal : Float64    share of the window's P-site signal at this position, in percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="profile",
        glob_pattern="**/*.ribowaltz.metaprofile_psite.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "position": pl.Int64,
    "signal": pl.Float64,
}

ANCHOR = "start"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """The start-codon window, renormalised to percent per library."""
    df = sources["profile"].filter(
        pl.col("region").cast(pl.Utf8).str.to_lowercase().str.contains(f"from {ANCHOR}")
    )
    df = df.select(
        pl.col("sample").cast(pl.Utf8).str.replace(r"\.ribowaltz$", "").alias("sample"),
        pl.col("x").cast(pl.Int64).alias("position"),
        pl.col("y").cast(pl.Float64).fill_null(0.0).alias("signal"),
    )
    total = pl.col("signal").sum().over("sample")
    return (
        df.with_columns(
            pl.when(total > 0).then(pl.col("signal") * 100.0 / total).otherwise(0.0).alias("signal")
        )
        .sort("sample", "position")
        .select(list(EXPECTED_SCHEMA))
    )
