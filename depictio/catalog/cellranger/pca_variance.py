"""Variance explained by each of Cell Ranger's reported PCA components.

`analysis/pca/gene_expression_10_components/variance.csv` has no sample
column (one file per sample directory), so the raw data collection is a
**scan** (`include_file_paths`).

A template reusing this recipe declares::

    regex_config: {pattern: 'analysis/pca/[^/]+/variance\\.csv$'}
    dc_specific_properties: {format: CSV, polars_kwargs: {include_file_paths: source_path}}

Output schema:
    sample : Utf8               sample the PCA was computed on
    pc : Int64                   component number, 1-based
    variance_explained : Float64 proportion of total variance this component explains
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "cellranger_pca_variance_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="variance", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "pc": pl.Int64,
    "variance_explained": pl.Float64,
}

_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/pca/"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["variance"]
    if "source_path" not in df.columns:
        raise ValueError(
            "cellranger_pca_variance: input has no 'source_path' column, the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )
    required = {"PC", "Proportion.Variance.Explained"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"cellranger_pca_variance: input lacks columns {sorted(missing)}")

    result = df.select(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("PC").cast(pl.Int64, strict=False).alias("pc"),
        pl.col("Proportion.Variance.Explained")
        .cast(pl.Float64, strict=False)
        .alias("variance_explained"),
    )
    if result.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            "cellranger_pca_variance: a row's source_path did not match the expected layout"
        )

    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "pc"])
