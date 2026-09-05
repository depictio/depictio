"""Per-sample screening summary: the hub every funcscan dashboard filter hangs off.

nf-core/funcscan runs up to four independent screens (ARG, AMP, BGC, CAZyme),
each with its own aggregated report and no shared sample table (the run's
samplesheet is not published with the results). This recipe joins the four
tidied catalog collections on ``sample`` into one row per sample with the
headline counts of every screen, so a single sample filter can drive all the
tabs and the overview cards read one table.

Every source is an optional ``dc_ref``: a screen the run did not enable is
pruned from the project and its columns are filled with 0.

Output columns:
    sample, arg_hits, arg_genes, arg_tools, amp_candidates, amp_high_confidence,
    bgc_regions, bgc_classes, cazymes, cazyme_families, screens
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="arg", dc_ref="hamronization_report", optional=True),
    RecipeSource(ref="amp", dc_ref="ampcombi_summary", optional=True),
    RecipeSource(ref="bgc", dc_ref="combgc_summary", optional=True),
    RecipeSource(ref="cazyme", dc_ref="dbcan_overview", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "arg_hits": pl.Int64,
    "arg_genes": pl.Int64,
    "arg_tools": pl.Int64,
    "amp_candidates": pl.Int64,
    "amp_high_confidence": pl.Int64,
    "bgc_regions": pl.Int64,
    "bgc_classes": pl.Int64,
    "cazymes": pl.Int64,
    "cazyme_families": pl.Int64,
    "screens": pl.Int64,
}

# Candidates whose best tool probability reaches this are counted as
# high-confidence AMPs (AMPcombi's own default parse-tables cut-off is 0.6).
AMP_HIGH_CONFIDENCE = 0.8


def _summary(df: pl.DataFrame | None, aggs: list[pl.Expr]) -> pl.DataFrame | None:
    if df is None or df.is_empty():
        return None
    return df.group_by("sample").agg(*aggs)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Outer-join the per-screen sample counts; absent screens contribute zeros."""
    parts = [
        _summary(
            sources.get("arg"),
            [
                pl.len().cast(pl.Int64).alias("arg_hits"),
                pl.col("gene_symbol").n_unique().cast(pl.Int64).alias("arg_genes"),
                pl.col("tool").n_unique().cast(pl.Int64).alias("arg_tools"),
            ],
        ),
        _summary(
            sources.get("amp"),
            [
                pl.len().cast(pl.Int64).alias("amp_candidates"),
                (pl.col("prob_max") >= AMP_HIGH_CONFIDENCE)
                .sum()
                .cast(pl.Int64)
                .alias("amp_high_confidence"),
            ],
        ),
        _summary(
            sources.get("bgc"),
            [
                pl.len().cast(pl.Int64).alias("bgc_regions"),
                pl.col("product_class").n_unique().cast(pl.Int64).alias("bgc_classes"),
            ],
        ),
        _summary(
            sources.get("cazyme"),
            [
                pl.len().cast(pl.Int64).alias("cazymes"),
                pl.col("family").n_unique().cast(pl.Int64).alias("cazyme_families"),
            ],
        ),
    ]
    present = [p for p in parts if p is not None]
    if not present:
        raise ValueError("screening_summary: none of the four screening collections is available")

    out = present[0]
    for part in present[1:]:
        out = out.join(part, on="sample", how="full", coalesce=True)

    count_cols = [c for c in EXPECTED_SCHEMA if c not in ("sample", "screens")]
    out = out.with_columns(
        *[
            (pl.col(c) if c in out.columns else pl.lit(0)).fill_null(0).cast(pl.Int64).alias(c)
            for c in count_cols
        ]
    )
    screen_flags = [
        (pl.col("arg_hits") > 0),
        (pl.col("amp_candidates") > 0),
        (pl.col("bgc_regions") > 0),
        (pl.col("cazymes") > 0),
    ]
    return (
        out.with_columns(
            pl.sum_horizontal(*[f.cast(pl.Int64) for f in screen_flags])
            .cast(pl.Int64)
            .alias("screens")
        )
        .sort("sample")
        .select(list(EXPECTED_SCHEMA))
    )
