"""Per-cell UMAP / t-SNE / PCA coordinates joined to the graph-based clusters.

Cell Ranger's secondary analysis writes one CSV per projection
(`analysis/umap/gene_expression_2_components/projection.csv`,
`analysis/tsne/.../projection.csv`, `analysis/pca/.../projection.csv`, 10
components) and one for the graph-based clustering
(`analysis/clustering/gene_expression_graphclust/clusters.csv`), each keyed on
the cell barcode. None of the four files carries a sample column, so all four
are read through **scan** data collections (`include_file_paths`) and the
sample is recovered from the path, then joined on `(sample, barcode)`.

A template reusing this recipe declares four raw scan data collections whose
regex targets each analysis subdirectory, e.g.::

    regex_config: {pattern: 'analysis/clustering/gene_expression_graphclust/clusters\\.csv$'}
    regex_config: {pattern: 'analysis/umap/[^/]+/projection\\.csv$'}
    regex_config: {pattern: 'analysis/tsne/[^/]+/projection\\.csv$'}
    regex_config: {pattern: 'analysis/pca/[^/]+/projection\\.csv$'}

each with `dc_specific_properties: {format: CSV, polars_kwargs: {include_file_paths: source_path}}`.

Output schema (canonical `embedding` schema columns for three renders, UMAP,
t-SNE and the first 3 PCs, sharing one table):
    sample : Utf8      sample the cell was sequenced in
    barcode : Utf8      cell barcode
    cluster : Utf8       "Cluster <n>", the graph-based cluster id as a label (bind to `color` too;
                         text, not an int, so it plots categorically rather than on a numeric scale)
    umap_1, umap_2 : Float64
    tsne_1, tsne_2 : Float64
    pc_1, pc_2, pc_3 : Float64  first 3 of Cell Ranger's 10 reported PCs
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

CLUSTERS_DC_TAG = "cellranger_clusters_raw"
UMAP_DC_TAG = "cellranger_umap_raw"
TSNE_DC_TAG = "cellranger_tsne_raw"
PCA_DC_TAG = "cellranger_pca_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="clusters", dc_ref=CLUSTERS_DC_TAG),
    RecipeSource(ref="umap", dc_ref=UMAP_DC_TAG),
    RecipeSource(ref="tsne", dc_ref=TSNE_DC_TAG),
    RecipeSource(ref="pca", dc_ref=PCA_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "barcode": pl.Utf8,
    "cluster": pl.Utf8,
    "umap_1": pl.Float64,
    "umap_2": pl.Float64,
    "tsne_1": pl.Float64,
    "tsne_2": pl.Float64,
    "pc_1": pl.Float64,
    "pc_2": pl.Float64,
    "pc_3": pl.Float64,
}

_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/"


def _with_sample(df: pl.DataFrame, dc_name: str) -> pl.DataFrame:
    if "source_path" not in df.columns:
        raise ValueError(
            f"cellranger_embedding: '{dc_name}' has no 'source_path' column, "
            "it must be scanned with polars_kwargs.include_file_paths"
        )
    out = df.with_columns(pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"))
    if out.filter(pl.col("sample").is_null()).height:
        raise ValueError(f"cellranger_embedding: a row's source_path in '{dc_name}' did not match")
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    clusters = _with_sample(sources["clusters"], "clusters").select(
        "sample",
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        ("Cluster " + pl.col("Cluster").cast(pl.Int64, strict=False).cast(pl.Utf8)).alias(
            "cluster"
        ),
    )
    umap = _with_sample(sources["umap"], "umap").select(
        "sample",
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        pl.col("UMAP-1").cast(pl.Float64, strict=False).alias("umap_1"),
        pl.col("UMAP-2").cast(pl.Float64, strict=False).alias("umap_2"),
    )
    tsne = _with_sample(sources["tsne"], "tsne").select(
        "sample",
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        pl.col("TSNE-1").cast(pl.Float64, strict=False).alias("tsne_1"),
        pl.col("TSNE-2").cast(pl.Float64, strict=False).alias("tsne_2"),
    )
    pca = _with_sample(sources["pca"], "pca").select(
        "sample",
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        pl.col("PC-1").cast(pl.Float64, strict=False).alias("pc_1"),
        pl.col("PC-2").cast(pl.Float64, strict=False).alias("pc_2"),
        pl.col("PC-3").cast(pl.Float64, strict=False).alias("pc_3"),
    )

    result = (
        clusters.join(umap, on=["sample", "barcode"], how="left")
        .join(tsne, on=["sample", "barcode"], how="left")
        .join(pca, on=["sample", "barcode"], how="left")
    )
    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "barcode"])
