"""ORF classes per library and caller: the composition behind the ORF stacked bars.

Counts the ORFs each caller reported in each library by the shared ORF class
(Annotated CDS, N-terminal variant, Upstream ORF, Downstream ORF, Internal
ORF, Novel ORF) and turns the counts into a within-library share, so libraries
of different depth compare on the same scale. ``caller`` is the level the
stacked bar switches between.

Sources: the ``ribotish_orfs`` and ``ribocode_orfs`` data collections (catalog
recipes ``ribotish/orfs.py`` and ``ribocode/orfs.py``). Either may be absent
when the run skipped that caller.

Output: sample, caller, orf_class : Utf8; orfs : Int64; pct : Float64.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="ribotish", dc_ref="ribotish_orfs", optional=True),
    RecipeSource(ref="ribocode", dc_ref="ribocode_orfs", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "orf_class": pl.Utf8,
    "orfs": pl.Int64,
    "pct": pl.Float64,
}

CALLERS = {"ribotish": "Ribo-TISH", "ribocode": "RiboCode"}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """ORF counts and shares per library, caller and class."""
    frames = []
    for ref, label in CALLERS.items():
        df = sources.get(ref)
        if df is None or df.is_empty():
            continue
        frames.append(
            df.group_by("sample", "orf_class")
            .agg(pl.col("orf_id").n_unique().cast(pl.Int64).alias("orfs"))
            .with_columns(pl.lit(label).alias("caller"))
        )
    if not frames:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    out = pl.concat(frames, how="diagonal_relaxed")
    return (
        out.with_columns(
            (pl.col("orfs") * 100.0 / pl.col("orfs").sum().over("sample", "caller"))
            .cast(pl.Float64)
            .alias("pct")
        )
        .with_columns(pl.col("sample").cast(pl.Utf8))
        .sort("sample", "caller", "orf_class")
        .select(list(EXPECTED_SCHEMA))
    )
