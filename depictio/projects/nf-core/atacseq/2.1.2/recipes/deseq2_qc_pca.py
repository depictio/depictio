"""DESeq2 QC principal components of the consensus counts, with each sample's group.

atacseq 2.x still runs ``deseq2_qc.r`` on the merged-library consensus counts and
publishes ``consensus_peaks.mLb.clN.pca.vals.txt``. This recipe delegates the
parsing to the catalog's ``deseq2/qc_pca.py`` (same columns, components resolved
per matrix) and adds the design group of each point.

What 2.x lost is the differential test: the PCA is now the only view of whether
the samples separate by group, and the shared output has no group to colour by.
The pipeline names every sample ``<group>_REP<replicate>`` (the validated
samplesheet builds it, and ``sample_design.py`` splits it the same way), so the
group is the sample id without its replicate suffix.

Output schema: the catalog recipe's, plus
    group : Utf8   design group of the sample, the key of the family colours
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: The catalog recipe this one delegates the PCA parsing to.
_SHARED = "deseq2/qc_pca.py"
#: The shared recipe resolves the components per file through this column.
_PATH_COL = "_pca_source_path"
#: ``<group>_REP<replicate>`` -> ``<group>``, as in ``sample_design.py``.
_REPLICATE_SUFFIX = r"_REP\d+$"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: one sample id column plus PCn components whose names carry the variance.
    RecipeSource(
        ref="pca",
        glob_pattern="**/merged_library/macs2/*/consensus/deseq2/*.pca.vals.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "comment_prefix": "#", "quote_char": '"'},
        source_path=_PATH_COL,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_1_percent": pl.Float64,
    "dim_2_percent": pl.Float64,
    "pca_set": pl.Utf8,
    "group": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "dim_3": pl.Float64,
    "dim_3_percent": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Parse the PCA with the catalog recipe, then derive each sample's group."""
    # Imported here, not at module level: this module is itself loaded by
    # depictio.recipes.
    from depictio.recipes import load_recipe

    out = load_recipe(_SHARED).transform({"pca": sources["pca"]})
    return out.with_columns(pl.col("sample_id").str.replace(_REPLICATE_SUFFIX, "").alias("group"))
