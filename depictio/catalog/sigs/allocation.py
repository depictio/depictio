"""SIGS' COSMIC signature allocation, one row per tumor and signature.

SIGS (hmftools) fits the tumor's 96-context SNV counts to a set of COSMIC
mutational signatures by non-negative least squares and writes
``<tumor>.sig.allocation.tsv``: one row per signature with the number of SNVs
allocated to it and that number as a fraction of all SNVs (``percent`` holds a
0 to 1 fraction). The residual row (``MISALLOC``, when present) is the share no
signature explains and is kept. The tumor id is the file name before
``.sig.allocation.tsv``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="allocation",
        glob_pattern="**/*.sig.allocation.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "signature": pl.Utf8,
    "allocation": pl.Float64,
    "fraction": pl.Float64,
    "percent": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.sig\.allocation\.tsv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["allocation"]
    fraction = pl.col("percent").cast(pl.Float64, strict=False)
    return (
        df.select(
            pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
            pl.col("signature"),
            pl.col("allocation").cast(pl.Float64, strict=False),
            fraction.alias("fraction"),
            (fraction * 100.0).alias("percent"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "allocation"], descending=[False, True])
    )
