"""DESeq2 QC principal components per antibody, with each library's condition.

The 2.1.0 override of the shared `nf-core/chipseq/deseq2_qc_pca.py`. nf-core/chipseq
2.x still runs `deseq2_qc.r` on the consensus counts of each antibody and still
publishes `<antibody>.consensus_peaks.pca.vals_mqc.tsv` in the same shape, so the
components are resolved exactly as the shared recipe does it (per matrix, the set
named by the longest common prefix of its samples) and the output keeps its
columns.

What 2.x lost is the differential test: the PCA is now the only view of whether the
libraries of one antibody separate by condition. The shared output has no
condition, only `consensus_set`, which takes one value on a run with one antibody.
So this override joins the condition of each library from the `design` hub, when
that collection is passed in, and the dashboard colours the points by it.

Output schema: the shared recipe's, plus
    condition : Utf8   condition of the library on the design hub (optional)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: The shared recipe this override delegates the PCA parsing to.
_SHARED = "nf-core/chipseq/deseq2_qc_pca.py"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: one sample id column plus PCn components whose names carry the variance.
    RecipeSource(
        ref="pca",
        glob_pattern="**/*pca.vals_mqc.tsv",
        format="TSV",
        read_kwargs={
            "infer_schema_length": 0,
            "comment_prefix": "#",
            "quote_char": '"',
        },
    ),
    RecipeSource(
        ref="design",
        dc_ref="design",
        optional=True,
        input_schema={"sample_id": pl.Utf8, "condition": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "consensus_set": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_1_percent": pl.Float64,
    "dim_2_percent": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "condition": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Parse the PCA with the shared recipe, then attach each library's condition."""
    # Imported here, not at module level: this module is itself loaded by
    # depictio.recipes. Without a version the name resolves to the shared recipe.
    from depictio.recipes import load_recipe

    out = load_recipe(_SHARED).transform({"pca": sources["pca"]})
    design = sources.get("design")
    if design is None or design.is_empty() or "condition" not in design.columns:
        return out
    conditions = design.select(
        pl.col("sample_id").cast(pl.Utf8), pl.col("condition").cast(pl.Utf8)
    ).unique(subset="sample_id", keep="first")
    return out.join(conditions, on="sample_id", how="left").select(
        [*OUTPUT_SCHEMA, *OPTIONAL_OUTPUT_SCHEMA]
    )
