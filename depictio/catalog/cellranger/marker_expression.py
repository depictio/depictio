"""Dot-plot table: mean log-normalised expression and detection rate of the
top marker genes, per cluster, for every cluster (not just the marker's own
cluster) so the dot plot shows cluster-specificity.

The marker gene list is the union of each graph-based cluster's top
`TOP_MARKERS_PER_CLUSTER` genes (by `rank_in_cluster`, i.e. adjusted
p-value) from `cellranger_diffexp` (`dc_ref`, already extended with
`cluster_label`). Expression is read from the filtered feature-barcode
matrix, restricted to just those marker genes (a small `isin` filter on a
17M-row scan, not a group_by over all 30k genes), CP10k-normalised using
`cellranger_cell_qc`'s already-computed `n_umi` per cell (no re-summing).

A template reusing this recipe declares five sources, four already shared by
`dc_ref` with `cellranger/cell_qc.py` and `cellranger/diffexp.py`::

    SOURCES = [
        RecipeSource(ref="diffexp", dc_ref="cellranger_diffexp"),
        RecipeSource(ref="matrix", dc_ref="cellranger_filtered_matrix_raw"),
        RecipeSource(ref="features", dc_ref="cellranger_filtered_features_raw"),
        RecipeSource(ref="barcode_index", dc_ref="cellranger_filtered_barcode_index_raw"),
        RecipeSource(ref="cell_qc", dc_ref="cellranger_cell_qc"),
    ]

Output schema (canonical `dot_plot` schema columns):
    cluster_label : Utf8       "C<n> top1/top2"
    gene : Utf8                  marker gene symbol
    mean_expression : Float64    mean log1p(CP10k) over EVERY cell in the cluster (0 for
                                  cells with no UMI of this gene, not just the detected ones)
    frac_expressing : Float64    fraction of the cluster's cells with >=1 UMI of this gene
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

DIFFEXP_DC_TAG = "cellranger_diffexp"
MATRIX_DC_TAG = "cellranger_filtered_matrix_raw"
FEATURES_DC_TAG = "cellranger_filtered_features_raw"
BARCODE_INDEX_DC_TAG = "cellranger_filtered_barcode_index_raw"
CELL_QC_DC_TAG = "cellranger_cell_qc"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="diffexp", dc_ref=DIFFEXP_DC_TAG),
    RecipeSource(ref="matrix", dc_ref=MATRIX_DC_TAG),
    RecipeSource(ref="features", dc_ref=FEATURES_DC_TAG),
    RecipeSource(ref="barcode_index", dc_ref=BARCODE_INDEX_DC_TAG),
    RecipeSource(ref="cell_qc", dc_ref=CELL_QC_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "cluster_label": pl.Utf8,
    "gene": pl.Utf8,
    "mean_expression": pl.Float64,
    "frac_expressing": pl.Float64,
}

#: top markers per cluster kept in the union gene list
TOP_MARKERS_PER_CLUSTER = 5

_MATRIX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_FEATURES_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_BARCODE_INDEX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"

_CP10K = 1e4


def _with_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> pl.DataFrame:
    if "source_path" not in df.columns:
        raise ValueError(
            f"cellranger_marker_expression: '{dc_name}' has no 'source_path' column, "
            "it must be scanned with polars_kwargs.include_file_paths"
        )
    out = df.with_columns(pl.col("source_path").str.extract(pattern, 1).alias("sample"))
    if out.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            f"cellranger_marker_expression: a row's source_path in '{dc_name}' did not match"
        )
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    diffexp = sources["diffexp"]
    matrix = _with_sample(sources["matrix"], _MATRIX_SAMPLE_RE, "matrix")
    features = _with_sample(sources["features"], _FEATURES_SAMPLE_RE, "features")
    barcode_index = _with_sample(
        sources["barcode_index"], _BARCODE_INDEX_SAMPLE_RE, "barcode_index"
    )
    cell_qc = sources["cell_qc"]

    required_diffexp = {"cluster_label", "gene_id", "gene", "rank_in_cluster"}
    if missing := required_diffexp - set(diffexp.columns):
        raise ValueError(f"cellranger_marker_expression: diffexp lacks columns {sorted(missing)}")
    required_cell_qc = {"sample", "barcode", "cluster_label", "n_umi"}
    if missing := required_cell_qc - set(cell_qc.columns):
        raise ValueError(f"cellranger_marker_expression: cell_qc lacks columns {sorted(missing)}")

    markers = diffexp.filter(pl.col("rank_in_cluster") <= TOP_MARKERS_PER_CLUSTER)
    marker_genes = markers.select("gene_id", "gene").unique()
    all_clusters = cell_qc.select("cluster_label").unique()

    # every (cluster_label, marker gene) pair, so the dot plot shows
    # cluster-specificity rather than one dot per gene.
    grid = all_clusters.join(marker_genes, how="cross")

    # restrict the matrix to marker-gene rows only, tiny compared to the full scan.
    marker_gene_idx = features.join(
        marker_genes.select("gene_id"), left_on="feature_id", right_on="gene_id", how="inner"
    ).select("sample", pl.col("gene_idx").cast(pl.Int64), pl.col("feature_name").alias("gene"))

    matrix_typed = matrix.select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("barcode_idx").cast(pl.Int64),
        pl.col("count").cast(pl.Int64, strict=False),
    )
    matrix_markers = matrix_typed.join(marker_gene_idx, on=["sample", "gene_idx"], how="inner")

    bc_lookup = barcode_index.select(
        "sample", pl.col("barcode_idx").cast(pl.Int64), pl.col("barcode").cast(pl.Utf8)
    )
    matrix_markers = matrix_markers.join(bc_lookup, on=["sample", "barcode_idx"], how="inner")

    cell_meta = cell_qc.select("sample", "barcode", "cluster_label", "n_umi")
    matrix_markers = matrix_markers.join(cell_meta, on=["sample", "barcode"], how="inner")
    matrix_markers = matrix_markers.with_columns(
        (pl.col("count") / pl.col("n_umi") * _CP10K).log1p().alias("_log1p_cp10k")
    )

    cluster_sizes = cell_qc.group_by("cluster_label").agg(
        pl.len().cast(pl.Int64).alias("_n_cells_in_cluster")
    )

    per_cluster_gene = matrix_markers.group_by(["cluster_label", "gene"]).agg(
        pl.col("_log1p_cp10k").sum().alias("_sum_log1p"),
        pl.len().cast(pl.Int64).alias("_n_detected"),
    )

    result = grid.join(per_cluster_gene, on=["cluster_label", "gene"], how="left").join(
        cluster_sizes, on="cluster_label", how="left"
    )
    result = result.with_columns(
        pl.col("_sum_log1p").fill_null(0.0),
        pl.col("_n_detected").fill_null(0),
    )
    result = result.with_columns(
        (pl.col("_sum_log1p") / pl.col("_n_cells_in_cluster")).alias("mean_expression"),
        (pl.col("_n_detected") / pl.col("_n_cells_in_cluster")).alias("frac_expressing"),
    )

    return result.select(list(EXPECTED_SCHEMA)).sort(["cluster_label", "gene"])
