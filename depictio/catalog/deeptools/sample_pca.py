"""deepTools plotPCA coordinates in long form, one row per sample.

``plotPCA --outFileNameData`` writes the sample loadings of the PCA it ran on a
``multiBamSummary`` bin matrix: a comment line, then one row per component
holding every sample's coordinate on it plus that component's eigenvalue. The
samples are the COLUMNS, so this recipe transposes the file into one row per
sample with the first three components side by side, which is what an embedding
scatter binds.

The eigenvalues are turned into the share of variance each component explains
and carried on every row, so a dashboard can label the axes without a second
data collection.

Output schema:
    sample : Utf8            library in the bin matrix
    pc1 : Float64            coordinate on the first component
    pc2 : Float64            coordinate on the second component
    pc3 : Float64            coordinate on the third component, null with < 3
    pc1_variance : Float64   share of variance the first component explains
    pc2_variance : Float64   share of variance the second component explains
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pca",
        glob_pattern="**/*.plotPCA.tab",
        format="TSV",
        # deepTools opens the file with a `#plotPCA --outFileNameData` line and
        # quotes nothing; `comment_prefix` drops it so the real header is read.
        read_kwargs={"infer_schema_length": 0, "comment_prefix": "#"},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "pc1": pl.Float64,
    "pc2": pl.Float64,
    "pc3": pl.Float64,
    "pc1_variance": pl.Float64,
    "pc2_variance": pl.Float64,
}

_COMPONENT_COL = "Component"
_EIGENVALUE_COL = "Eigenvalue"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Transpose the component rows into one row per sample."""
    raw = sources["pca"]
    if raw.is_empty():
        raise ValueError("deeptools_sample_pca: the matched plotPCA file is empty")
    if _COMPONENT_COL not in raw.columns:
        raise ValueError(
            f"deeptools_sample_pca: expected a '{_COMPONENT_COL}' column, got {raw.columns}"
        )

    sample_columns = [c for c in raw.columns if c not in (_COMPONENT_COL, _EIGENVALUE_COL)]
    if not sample_columns:
        raise ValueError("deeptools_sample_pca: the file declared no sample columns")

    frame = raw.with_columns(pl.col(_COMPONENT_COL).cast(pl.Int64, strict=False))

    variance: dict[int, float] = {}
    if _EIGENVALUE_COL in raw.columns:
        eigen = frame.select(
            pl.col(_COMPONENT_COL), pl.col(_EIGENVALUE_COL).cast(pl.Float64, strict=False)
        ).drop_nulls()
        total = eigen[_EIGENVALUE_COL].sum() or 0.0
        if total > 0:
            variance = {
                int(component): value / total
                for component, value in zip(
                    eigen[_COMPONENT_COL].to_list(), eigen[_EIGENVALUE_COL].to_list()
                )
            }

    loadings: dict[int, dict[str, float | None]] = {}
    for record in frame.iter_rows(named=True):
        component = record[_COMPONENT_COL]
        if component is None:
            continue
        loadings[int(component)] = {column: _as_float(record[column]) for column in sample_columns}

    rows = [
        {
            "sample": sample,
            "pc1": loadings.get(1, {}).get(sample),
            "pc2": loadings.get(2, {}).get(sample),
            "pc3": loadings.get(3, {}).get(sample),
            "pc1_variance": variance.get(1),
            "pc2_variance": variance.get(2),
        }
        for sample in sample_columns
    ]
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .with_columns(
            pl.col("sample").cast(pl.Utf8),
            *[
                pl.col(c).cast(pl.Float64, strict=False)
                for c in ("pc1", "pc2", "pc3", "pc1_variance", "pc2_variance")
            ],
        )
        .select(list(EXPECTED_SCHEMA))
        .sort("sample")
    )


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
