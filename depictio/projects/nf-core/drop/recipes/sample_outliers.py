"""Outliers per sample across the three DROP analyses: the sample-level quality read.

A rare-disease sample is expected to carry a handful of outliers: a few genes
expressed far from the cohort, a few aberrantly spliced genes, perhaps one
mono-allelic variant. A sample with hundreds of aberrant genes is usually a quality
or batch problem, not a patient, which is why OUTRIDER and FRASER report the
aberrant count per sample next to their calls. The outlier files hold only the
samples that have a call, so this recipe starts from the sample hub and counts a
sample with no call as zero.

``expression_nominal`` and ``splicing_nominal`` count the genes at a nominal p-value
(raw, uncorrected: see ``expression_outliers``), which stay informative on a run too
small for anything to pass the adjusted cut-offs; ``total_outliers`` counts calls only.

Every analysis is optional (``--ae_skip``, ``--as_skip``, ``--mae_skip``); a skipped
one leaves its counts at zero, and the template drops the collection of the
analysis that did not run.

Sources:
    samples      the sample hub
    expression   OUTRIDER calls (optional)
    splicing     FRASER calls (optional)
    mae          mono-allelic expression calls (optional)

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={"sample": pl.Utf8, "drop_group": pl.Utf8, "count_source": pl.Utf8},
    ),
    RecipeSource(
        ref="expression",
        dc_ref="expression_outliers",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "gene_id": pl.Utf8,
            "z_score": pl.Float64,
            "significant": pl.Boolean,
            "nominal": pl.Boolean,
            "hpo_match": pl.Boolean,
        },
    ),
    RecipeSource(
        ref="splicing",
        dc_ref="splicing_outliers",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "gene_name": pl.Utf8,
            "significant": pl.Boolean,
            "nominal": pl.Boolean,
            "hpo_match": pl.Boolean,
        },
    ),
    RecipeSource(
        ref="mae",
        dc_ref="mae_variants",
        optional=True,
        input_schema={"sample": pl.Utf8, "mono_allelic": pl.Boolean},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "drop_group": pl.Utf8,
    "count_source": pl.Utf8,
    "expression_outliers": pl.Int64,
    "over_expressed": pl.Int64,
    "under_expressed": pl.Int64,
    "splicing_outliers": pl.Int64,
    "mae_calls": pl.Int64,
    "mae_variants_tested": pl.Int64,
    "total_outliers": pl.Int64,
    "expression_nominal": pl.Int64,
    "splicing_nominal": pl.Int64,
    "nominal_hits": pl.Int64,
    "phenotype_matches": pl.Int64,
    "has_outlier": pl.Utf8,
}


def _counts(df: pl.DataFrame | None, aggs: list[pl.Expr]) -> pl.DataFrame:
    """Per-sample counts of one analysis (empty frame when the analysis did not run)."""
    if df is None or df.is_empty():
        names = [a.meta.output_name() for a in aggs]
        return pl.DataFrame(schema={"sample": pl.Utf8, **{n: pl.Int64 for n in names}})
    return df.group_by("sample").agg(aggs)


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per sample: its calls in each analysis, zero where it has none."""
    hub = sources["samples"].select("sample", "drop_group", "count_source")

    expression = sources.get("expression")
    ae = _counts(
        expression.filter(pl.col("significant")) if expression is not None else None,
        [
            pl.len().cast(pl.Int64).alias("expression_outliers"),
            (pl.col("z_score") > 0).sum().cast(pl.Int64).alias("over_expressed"),
            (pl.col("z_score") < 0).sum().cast(pl.Int64).alias("under_expressed"),
            pl.col("hpo_match").sum().cast(pl.Int64).alias("_ae_hpo"),
        ],
    )
    splicing = sources.get("splicing")
    sp = _counts(
        splicing.filter(pl.col("significant")) if splicing is not None else None,
        [
            pl.col("gene_name").n_unique().cast(pl.Int64).alias("splicing_outliers"),
            pl.col("hpo_match").sum().cast(pl.Int64).alias("_as_hpo"),
        ],
    )
    # Nominal hits (raw p-value): what a run too small to pass the adjusted cut-offs still says.
    ae_nom = _counts(
        expression.filter(pl.col("nominal")) if expression is not None else None,
        [pl.len().cast(pl.Int64).alias("expression_nominal")],
    )
    sp_nom = _counts(
        splicing.filter(pl.col("nominal")) if splicing is not None else None,
        [pl.col("gene_name").n_unique().cast(pl.Int64).alias("splicing_nominal")],
    )
    mae = sources.get("mae")
    mae_all = _counts(mae, [pl.len().cast(pl.Int64).alias("mae_variants_tested")])
    mae_called = _counts(
        mae.filter(pl.col("mono_allelic")) if mae is not None else None,
        [pl.len().cast(pl.Int64).alias("mae_calls")],
    )

    out = hub
    for part in (ae, sp, ae_nom, sp_nom, mae_all, mae_called):
        out = out.join(part, on="sample", how="left")
    for column in (
        "expression_outliers",
        "over_expressed",
        "under_expressed",
        "splicing_outliers",
        "expression_nominal",
        "splicing_nominal",
        "mae_calls",
        "mae_variants_tested",
        "_ae_hpo",
        "_as_hpo",
    ):
        if column not in out.columns:
            out = out.with_columns(pl.lit(0, dtype=pl.Int64).alias(column))
        out = out.with_columns(pl.col(column).fill_null(0).cast(pl.Int64))
    out = out.with_columns(
        (pl.col("expression_outliers") + pl.col("splicing_outliers") + pl.col("mae_calls")).alias(
            "total_outliers"
        ),
        (pl.col("expression_nominal") + pl.col("splicing_nominal")).alias("nominal_hits"),
        (pl.col("_ae_hpo") + pl.col("_as_hpo")).alias("phenotype_matches"),
    ).with_columns(
        pl.when(pl.col("total_outliers") > 0)
        .then(pl.lit("with outliers"))
        .otherwise(pl.lit("no outlier"))
        .alias("has_outlier")
    )
    return out.select(list(OUTPUT_SCHEMA)).sort(
        ["total_outliers", "sample"], descending=[True, False]
    )
