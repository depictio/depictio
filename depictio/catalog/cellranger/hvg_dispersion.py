"""Feature selection, the step between the count matrix and the PCA nobody sees.

Cell Ranger writes two files next to the PCA it ran and neither has ever been
read by a dashboard: `dispersion.csv` (normalised dispersion for every gene it
measured) and `features_selected.csv` (the genes it kept as variable and ran the
PCA on). Together they are the mean-dispersion plot every single-cell tutorial
draws, and the answer to "why is this gene missing from the embedding".

Mean expression is not in either file, so it is computed here, from the same
streaming MatrixMarket scan the rest of the module uses: per-cell UMI totals
come from a `group_by` over the triplets (no dependency on the cell hub), and a
gene's mean expression is the average of log1p(CP10k) over EVERY cell, zeros
included, which is what makes the cloud a cloud rather than a detected-only
sample.

A template reusing this recipe declares two new raw scans plus three already
shared by `dc_ref`::

    # cellranger_dispersion_raw: analysis/pca/*/dispersion.csv
    # cellranger_features_selected_raw: analysis/pca/*/features_selected.csv,
    #   whose header names one column and whose rows carry two (an unnamed
    #   1-based index), so it is scanned headerless past the first line:
    #   polars_kwargs: {has_header: false, skip_rows: 1,
    #                   new_columns: [selection_rank, feature]}
    SOURCES = [
        RecipeSource(ref="dispersion", dc_ref="cellranger_dispersion_raw"),
        RecipeSource(ref="selected", dc_ref="cellranger_features_selected_raw", optional=True),
        RecipeSource(ref="matrix", dc_ref="cellranger_filtered_matrix_raw"),
        RecipeSource(ref="features", dc_ref="cellranger_filtered_features_raw"),
    ]

Output schema (canonical `scatter_xy` columns: x=mean_expression,
y=normalized_dispersion, color=selection, label=gene):
    sample : Utf8                   sample the PCA was computed on
    gene : Utf8                      gene symbol
    normalized_dispersion : Float64  Cell Ranger's normalised dispersion
    mean_expression : Float64        mean log1p(CP10k) over every called cell
    detection_rate : Float64         share of cells with at least 1 UMI of this gene
    selection : Utf8                 "selected" | "not selected", whether Cell Ranger kept
                                      the gene for the PCA (constant "unknown" when the run
                                      did not publish features_selected.csv)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cellranger_samples import with_sample_column

DISPERSION_DC_TAG = "cellranger_dispersion_raw"
SELECTED_DC_TAG = "cellranger_features_selected_raw"
MATRIX_DC_TAG = "cellranger_filtered_matrix_raw"
FEATURES_DC_TAG = "cellranger_filtered_features_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="dispersion", dc_ref=DISPERSION_DC_TAG),
    RecipeSource(ref="selected", dc_ref=SELECTED_DC_TAG, optional=True),
    RecipeSource(ref="matrix", dc_ref=MATRIX_DC_TAG),
    RecipeSource(ref="features", dc_ref=FEATURES_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "gene": pl.Utf8,
    "normalized_dispersion": pl.Float64,
    "mean_expression": pl.Float64,
    "detection_rate": pl.Float64,
    "selection": pl.Utf8,
}

_PCA_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/pca/"
_MATRIX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_FEATURES_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"

_CP10K = 1e4

SELECTED = "selected"
NOT_SELECTED = "not selected"
UNKNOWN = "unknown"


def _with_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> pl.DataFrame:
    return with_sample_column(df, pattern, dc_name, "cellranger_hvg_dispersion")


def _gene_statistics(matrix: pl.DataFrame, features: pl.DataFrame) -> pl.DataFrame:
    """sample, gene -> mean log1p(CP10k) over every cell, and detection rate."""
    typed = matrix.select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("barcode_idx").cast(pl.Int64),
        pl.col("count").cast(pl.Int64, strict=False),
    )
    per_cell = typed.group_by(["sample", "barcode_idx"]).agg(pl.col("count").sum().alias("_n_umi"))
    n_cells = per_cell.group_by("sample").agg(pl.len().cast(pl.Float64).alias("_n_cells"))

    normalised = typed.join(per_cell, on=["sample", "barcode_idx"], how="inner").with_columns(
        (pl.col("count") / pl.col("_n_umi") * _CP10K).log1p().alias("_expression")
    )
    per_gene = normalised.group_by(["sample", "gene_idx"]).agg(
        pl.col("_expression").sum().alias("_sum_expression"),
        pl.len().cast(pl.Float64).alias("_n_detected"),
    )
    per_gene = per_gene.join(n_cells, on="sample", how="left").with_columns(
        (pl.col("_sum_expression") / pl.col("_n_cells")).alias("mean_expression"),
        (pl.col("_n_detected") / pl.col("_n_cells")).alias("detection_rate"),
    )

    gene_names = features.select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("feature_name").cast(pl.Utf8).alias("gene"),
    )
    return (
        per_gene.join(gene_names, on=["sample", "gene_idx"], how="inner")
        .group_by(["sample", "gene"])
        .agg(
            pl.col("mean_expression").sum(),
            pl.col("detection_rate").max(),
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    dispersion = _with_sample(sources["dispersion"], _PCA_SAMPLE_RE, "dispersion")
    matrix = _with_sample(sources["matrix"], _MATRIX_SAMPLE_RE, "matrix")
    features = _with_sample(sources["features"], _FEATURES_SAMPLE_RE, "features")
    selected = sources.get("selected")

    if "Feature" not in dispersion.columns or "Normalized.Dispersion" not in dispersion.columns:
        raise ValueError(
            "cellranger_hvg_dispersion: dispersion.csv must carry 'Feature' and "
            f"'Normalized.Dispersion', got {sorted(dispersion.columns)}"
        )

    table = dispersion.select(
        "sample",
        pl.col("Feature").cast(pl.Utf8).alias("gene"),
        pl.col("Normalized.Dispersion")
        .cast(pl.Float64, strict=False)
        .alias("normalized_dispersion"),
    ).drop_nulls("gene")
    # Cell Ranger writes NaN for a gene it could not normalise, and those are
    # exactly the genes it then left out of features_selected.csv. The rows stay
    # (dropping them would make `selection` a constant column, and a constant
    # column is a dead filter) but the NaN becomes a null: polars' median skips
    # a null and propagates a NaN, so a card on this column reads as a number
    # only this way round.
    table = table.with_columns(
        pl.when(pl.col("normalized_dispersion").is_finite())
        .then(pl.col("normalized_dispersion"))
        .otherwise(None)
        .alias("normalized_dispersion")
    )

    stats = _gene_statistics(matrix, features)
    table = table.join(stats, on=["sample", "gene"], how="left").with_columns(
        pl.col("mean_expression").fill_null(0.0),
        pl.col("detection_rate").fill_null(0.0),
    )

    if selected is not None and selected.height and "feature" in selected.columns:
        picked = (
            _with_sample(selected, _PCA_SAMPLE_RE, "selected")
            .select("sample", pl.col("feature").cast(pl.Utf8).alias("gene"))
            .drop_nulls()
            .unique()
            .with_columns(pl.lit(True).alias("_selected"))
        )
        table = table.join(picked, on=["sample", "gene"], how="left").with_columns(
            pl.when(pl.col("_selected").fill_null(False))
            .then(pl.lit(SELECTED))
            .otherwise(pl.lit(NOT_SELECTED))
            .alias("selection")
        )
    else:
        table = table.with_columns(pl.lit(UNKNOWN).alias("selection"))

    return table.select(list(EXPECTED_SCHEMA)).sort(
        ["sample", "normalized_dispersion"], descending=[False, True]
    )
