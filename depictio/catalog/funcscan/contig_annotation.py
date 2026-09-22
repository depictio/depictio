"""Per-contig annotation summary: the four funcscan screens on one locus.

nf-core/funcscan annotates every assembly once (Pyrodigal / Prodigal / Bakta /
Prokka) and then screens the predicted proteins four independent times. The
annotation itself is not published with the AWS megatest results, but every
screen carries the contig its feature sits on, so the annotated locus layer can
be rebuilt from the screens themselves: one row per contig that carries at
least one feature, with how many features each screen put there.

Contig names come from the assembler that produced the MGnify assemblies and
carry the length and the k-mer coverage in the name itself
(``ERZ1664511.16-NODE-16-length-49668-cov-9.810473``), which is where
``contig_length`` and ``contig_coverage`` are read from. A contig whose name
does not follow that convention keeps a null length and is simply absent from
the density axis rather than dropped.

Every source is an optional ``dc_ref``: a screen the run did not enable
contributes zeros instead of pruning the collection.

Output columns:
    sample, contig, contig_length, contig_coverage, arg_hits, amp_candidates,
    bgc_regions, cazyme_genes, features, screens_on_contig, features_per_kb,
    top_screen
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
    "contig": pl.Utf8,
    "contig_length": pl.Int64,
    "contig_coverage": pl.Float64,
    "arg_hits": pl.Int64,
    "amp_candidates": pl.Int64,
    "bgc_regions": pl.Int64,
    "cazyme_genes": pl.Int64,
    "features": pl.Int64,
    "screens_on_contig": pl.Int64,
    "features_per_kb": pl.Float64,
    "top_screen": pl.Utf8,
}

# Which column each screen contributes, in the order the labels are read.
_SCREEN_COLUMNS = {
    "arg": "arg_hits",
    "amp": "amp_candidates",
    "bgc": "bgc_regions",
    "cazyme": "cazyme_genes",
}
_SCREEN_LABELS = {
    "arg_hits": "ARG",
    "amp_candidates": "AMP",
    "bgc_regions": "BGC",
    "cazyme_genes": "CAZyme",
}


def _counts(df: pl.DataFrame | None, out_col: str) -> pl.DataFrame | None:
    """One row per (sample, contig) with the features this screen put there."""
    if df is None or df.is_empty():
        return None
    if "contig" not in df.columns or "sample" not in df.columns:
        return None
    return (
        df.select(
            pl.col("sample").cast(pl.Utf8),
            pl.col("contig").cast(pl.Utf8),
        )
        .drop_nulls()
        .group_by("sample", "contig")
        .agg(pl.len().cast(pl.Int64).alias(out_col))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Outer-join the per-contig feature counts of every screen that ran."""
    parts = [_counts(sources.get(ref), col) for ref, col in _SCREEN_COLUMNS.items()]
    present = [p for p in parts if p is not None]
    if not present:
        raise ValueError("contig_annotation: none of the four screening collections is available")

    out = present[0]
    for part in present[1:]:
        out = out.join(part, on=["sample", "contig"], how="full", coalesce=True)

    count_cols = list(_SCREEN_COLUMNS.values())
    out = out.with_columns(
        *[
            (pl.col(c) if c in out.columns else pl.lit(0)).fill_null(0).cast(pl.Int64).alias(c)
            for c in count_cols
        ]
    )

    # The assembler writes the contig length and the k-mer coverage into the
    # name; a contig named any other way keeps a null and drops out of the
    # density axis instead of out of the table.
    length = pl.col("contig").str.extract(r"length-(\d+)", 1).cast(pl.Int64, strict=False)
    coverage = pl.col("contig").str.extract(r"cov-([0-9.]+)", 1).cast(pl.Float64, strict=False)

    out = out.with_columns(
        length.alias("contig_length"),
        coverage.alias("contig_coverage"),
        pl.sum_horizontal(*[pl.col(c) for c in count_cols]).cast(pl.Int64).alias("features"),
        pl.sum_horizontal(*[(pl.col(c) > 0).cast(pl.Int64) for c in count_cols])
        .cast(pl.Int64)
        .alias("screens_on_contig"),
    )

    # Ties go to the first screen in _SCREEN_LABELS order, which is the reading
    # order of the tabs; a contig with a single screen simply names it.
    top_screen = pl.lit(None, dtype=pl.Utf8)
    running_max = pl.lit(0, dtype=pl.Int64)
    for col in count_cols:
        top_screen = (
            pl.when(pl.col(col) > running_max)
            .then(pl.lit(_SCREEN_LABELS[col]))
            .otherwise(top_screen)
        )
        running_max = pl.max_horizontal(running_max, pl.col(col))

    return (
        out.with_columns(
            pl.when(pl.col("contig_length") > 0)
            .then(pl.col("features") * 1000.0 / pl.col("contig_length"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("features_per_kb"),
            top_screen.alias("top_screen"),
        )
        .sort("sample", "features", "contig", descending=[False, True, False])
        .select(list(EXPECTED_SCHEMA))
    )
