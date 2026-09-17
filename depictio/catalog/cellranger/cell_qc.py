"""The cell hub: one row per called cell (filtered-matrix barcode), with QC
metrics, cluster assignments, embeddings, CellBender agreement and a
MAD-based QC flag.

Cell Ranger's filtered feature-barcode matrix carries every gene x cell
non-zero UMI count as a MatrixMarket triplet (`gene_idx barcode_idx count`),
tens of millions of entries. This recipe never densifies it: the raw matrix
and the feature/barcode index lists are all **streaming scans**
(`include_file_paths`, `row_index_name`/`row_index_offset` recovering
1-based positional indices), and per-cell QC metrics are computed with a
single columnar `group_by` (mirrors `barcode_rank.py`'s approach, but on the
smaller filtered matrix: 8 767 barcodes x 29 972 features here, not the raw
matrix's background droplets).

A template reusing this recipe declares five NEW raw scan data collections
(beyond the four already shared with `cellranger/embedding.py` and
`cellranger/diffexp.py` via `dc_ref`)::

    # cellranger_filtered_matrix_raw: skip the 3 MatrixMarket header lines
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        separator: " "
        has_header: false
        skip_rows: 3
        new_columns: [gene_idx, barcode_idx, count]
        include_file_paths: source_path

    # cellranger_filtered_features_raw: tab-separated, 1-based row == gene_idx
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        separator: "\\t"
        has_header: false
        new_columns: [feature_id, feature_name, feature_type]
        include_file_paths: source_path
        row_index_name: gene_idx
        row_index_offset: 1

    # cellranger_filtered_barcode_index_raw: 1-based row == matrix barcode_idx
    # (a second raw DC over the same file cellranger_filtered_barcodes_raw
    # scans for barcode_rank.py, here WITH the row index the join needs)
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        has_header: false
        new_columns: [barcode]
        include_file_paths: source_path
        row_index_name: barcode_idx
        row_index_offset: 1

    # cellranger_kmeans_clusters_raw: all 9 k in one scan, k recovered from path
    dc_specific_properties:
      format: CSV
      polars_kwargs: {include_file_paths: source_path}

    # cellranger_cellbender_barcodes_raw: barcodes CellBender kept as cells
    # (shared tag: cell_calls_by_method.py and aligner_summary.py reference
    # the same DC, declared once in template.yaml)
    dc_specific_properties:
      format: CSV
      polars_kwargs: {has_header: false, new_columns: [barcode], include_file_paths: source_path}

Plus `dc_ref` reuse of four already-shared raw scans
(`cellranger_clusters_raw`, `cellranger_umap_raw`, `cellranger_tsne_raw`,
`cellranger_pca_raw`) and the wide `cellranger_diffexp_raw` table (to derive
`cluster_label`, independently from `cellranger/diffexp.py`'s own melt, so
neither recipe depends on the other's row cap).

MAD rules (sc-best-practices), computed per sample on log1p values:
    - low outlier: log1p(n_umi) or log1p(n_genes) < median - 5 * MAD
    - high pct_top20 outlier: pct_top20 > median + 5 * MAD (on the raw %, not log1p)
    - high pct_mito outlier: pct_mito > median + 3 * MAD, OR pct_mito > 8

`cluster_label` = "C<n> <top1>/<top2>": the 2 genes with the highest log2FC
among {adjusted p-value < 0.05, mean_counts > 0.5} for that graph-based
cluster in the raw diffexp table. A cluster with fewer than 2 qualifying
genes falls back to however many it has ("C<n> <top1>") or just "C<n>".

Output schema (canonical `embedding`/`scatter_xy`/`sankey`/`knee_plot`-adjacent
per-cell table, the hub every other cellranger cell-level output joins to):
    sample : Utf8
    barcode : Utf8              10x cell barcode, with the -1 suffix
    barcode_core : Utf8         barcode without the Cell Ranger "-1" suffix
    n_umi : Int64                total UMI counts for this cell
    n_genes : Int64               genes with >=1 UMI in this cell
    pct_mito : Float64            % of n_umi from MT- genes
    pct_ribo : Float64            % of n_umi from RPS/RPL genes
    pct_hb : Float64               % of n_umi from HBA/HBB genes
    pct_top20 : Float64            % of n_umi from the 20 highest-expressed genes
    log10_n_umi : Float64
    log10_n_genes : Float64
    graphclust : Utf8              "C1".."Cn", the graph-based cluster id
    cluster_label : Utf8           "C<n> <top1>/<top2>" marker genes
    kmeans_2 .. kmeans_10 : Utf8   "C1".."Ck" per k
    umap_1, umap_2 : Float64
    tsne_1, tsne_2 : Float64
    pc_1, pc_2, pc_3 : Float64
    cellbender_cell : Boolean      True if CellBender also called this barcode a cell
    mad_low_umi, mad_low_genes, mad_high_top20, mad_high_mito : Boolean
    qc_status : Utf8                "pass" | "flagged"
    qc_reason : Utf8                 "pass", or the first failing MAD criterion
    qc_flagged : Int64                0/1 form of qc_status, so a card can average it into a "% flagged"
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

MATRIX_DC_TAG = "cellranger_filtered_matrix_raw"
FEATURES_DC_TAG = "cellranger_filtered_features_raw"
BARCODE_INDEX_DC_TAG = "cellranger_filtered_barcode_index_raw"
GRAPHCLUST_DC_TAG = "cellranger_clusters_raw"
KMEANS_DC_TAG = "cellranger_kmeans_clusters_raw"
UMAP_DC_TAG = "cellranger_umap_raw"
TSNE_DC_TAG = "cellranger_tsne_raw"
PCA_DC_TAG = "cellranger_pca_raw"
CELLBENDER_CELLS_DC_TAG = "cellranger_cellbender_barcodes_raw"
DIFFEXP_RAW_DC_TAG = "cellranger_diffexp_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="matrix", dc_ref=MATRIX_DC_TAG),
    RecipeSource(ref="features", dc_ref=FEATURES_DC_TAG),
    RecipeSource(ref="barcode_index", dc_ref=BARCODE_INDEX_DC_TAG),
    RecipeSource(ref="graphclust", dc_ref=GRAPHCLUST_DC_TAG),
    RecipeSource(ref="kmeans", dc_ref=KMEANS_DC_TAG),
    RecipeSource(ref="umap", dc_ref=UMAP_DC_TAG),
    RecipeSource(ref="tsne", dc_ref=TSNE_DC_TAG),
    RecipeSource(ref="pca", dc_ref=PCA_DC_TAG),
    RecipeSource(ref="cellbender_cells", dc_ref=CELLBENDER_CELLS_DC_TAG),
    RecipeSource(ref="diffexp", dc_ref=DIFFEXP_RAW_DC_TAG),
]

_KMEANS_KS = list(range(2, 11))

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "barcode": pl.Utf8,
    "barcode_core": pl.Utf8,
    "n_umi": pl.Int64,
    "n_genes": pl.Int64,
    "pct_mito": pl.Float64,
    "pct_ribo": pl.Float64,
    "pct_hb": pl.Float64,
    "pct_top20": pl.Float64,
    "log10_n_umi": pl.Float64,
    "log10_n_genes": pl.Float64,
    "graphclust": pl.Utf8,
    "cluster_label": pl.Utf8,
    **{f"kmeans_{k}": pl.Utf8 for k in _KMEANS_KS},
    "umap_1": pl.Float64,
    "umap_2": pl.Float64,
    "tsne_1": pl.Float64,
    "tsne_2": pl.Float64,
    "pc_1": pl.Float64,
    "pc_2": pl.Float64,
    "pc_3": pl.Float64,
    "cellbender_cell": pl.Boolean,
    "mad_low_umi": pl.Boolean,
    "mad_low_genes": pl.Boolean,
    "mad_high_top20": pl.Boolean,
    "mad_high_mito": pl.Boolean,
    "qc_status": pl.Utf8,
    "qc_reason": pl.Utf8,
    "qc_flagged": pl.Int64,
}

_MATRIX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_FEATURES_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_BARCODE_INDEX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_GRAPHCLUST_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/"
_KMEANS_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/clustering/"
_KMEANS_K_RE = re.compile(r"gene_expression_kmeans_(\d+)_clusters/clusters\.csv$")
_UMAP_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/"
_TSNE_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/"
_PCA_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/"
_CELLBENDER_SAMPLE_RE = r"cellranger/([^/]+)/cellbender_removebackground/"
_DIFFEXP_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/diffexp/"
_DIFFEXP_CLUSTER_COL_RE = re.compile(r"^Cluster (\d+) Mean Counts$")

# sc-best-practices MAD multipliers.
_MAD_K_COUNT = 5.0
_MAD_K_TOP20 = 5.0
_MAD_K_MITO = 3.0
_MITO_HARD_PCT = 8.0

#: genes with high adj-p / low log2fc kept per cluster before ranking for the
#: cluster label, generous enough to never miss the true top-2 by log2fc.
_LABEL_PADJ_MAX = 0.05
_LABEL_MEAN_MIN = 0.5


def _with_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> pl.DataFrame:
    if "source_path" not in df.columns:
        raise ValueError(
            f"cellranger_cell_qc: '{dc_name}' has no 'source_path' column, it must be "
            "scanned with polars_kwargs.include_file_paths"
        )
    out = df.with_columns(pl.col("source_path").str.extract(pattern, 1).alias("sample"))
    if out.filter(pl.col("sample").is_null()).height:
        raise ValueError(f"cellranger_cell_qc: a row's source_path in '{dc_name}' did not match")
    return out


def _cluster_labels(diffexp_raw: pl.DataFrame) -> pl.DataFrame:
    """sample, cluster ("Cluster N") -> cluster_label ("C<n> top1/top2")."""
    df = _with_sample(diffexp_raw, _DIFFEXP_SAMPLE_RE, "diffexp")
    cluster_ids = sorted(
        int(m.group(1)) for c in df.columns if (m := _DIFFEXP_CLUSTER_COL_RE.match(c))
    )
    if not cluster_ids:
        raise ValueError("cellranger_cell_qc: no 'Cluster N Mean Counts' columns in diffexp")

    frames = []
    for cid in cluster_ids:
        mean_col = f"Cluster {cid} Mean Counts"
        lfc_col = f"Cluster {cid} Log2 fold change"
        pval_col = f"Cluster {cid} Adjusted p value"
        if lfc_col not in df.columns or pval_col not in df.columns:
            continue
        frames.append(
            df.select(
                "sample",
                pl.lit(cid).alias("cluster_id"),
                pl.col("Feature Name").cast(pl.Utf8).alias("gene"),
                pl.col(mean_col).cast(pl.Float64, strict=False).alias("mean_counts"),
                pl.col(lfc_col).cast(pl.Float64, strict=False).alias("log2fc"),
                pl.col(pval_col).cast(pl.Float64, strict=False).alias("adjusted_pvalue"),
            )
        )
    melted = pl.concat(frames, how="vertical_relaxed")
    qualifying = melted.filter(
        (pl.col("adjusted_pvalue") < _LABEL_PADJ_MAX) & (pl.col("mean_counts") > _LABEL_MEAN_MIN)
    )
    ranked = qualifying.with_columns(
        pl.col("log2fc")
        .rank(method="ordinal", descending=True)
        .over(["sample", "cluster_id"])
        .alias("_rank")
    ).filter(pl.col("_rank") <= 2)

    labels = []
    for (sample, cid), group in ranked.group_by(["sample", "cluster_id"], maintain_order=True):
        top_genes = group.sort("_rank")["gene"].to_list()
        suffix = "/".join(top_genes) if top_genes else ""
        label = f"C{cid} {suffix}".strip() if suffix else f"C{cid}"
        labels.append({"sample": sample, "cluster_id": cid, "cluster_label": label})

    # Clusters with zero qualifying genes still need a bare "C<n>" label.
    all_clusters = melted.select("sample", "cluster_id").unique()
    label_df = pl.DataFrame(
        labels, schema={"sample": pl.Utf8, "cluster_id": pl.Int64, "cluster_label": pl.Utf8}
    )
    label_df = all_clusters.join(label_df, on=["sample", "cluster_id"], how="left").with_columns(
        pl.when(pl.col("cluster_label").is_null())
        .then(pl.lit("C") + pl.col("cluster_id").cast(pl.Utf8))
        .otherwise(pl.col("cluster_label"))
        .alias("cluster_label")
    )
    return label_df.with_columns(
        (pl.lit("Cluster ") + pl.col("cluster_id").cast(pl.Utf8)).alias("cluster")
    ).select("sample", "cluster", "cluster_label")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    matrix = _with_sample(sources["matrix"], _MATRIX_SAMPLE_RE, "matrix")
    features = _with_sample(sources["features"], _FEATURES_SAMPLE_RE, "features")
    barcode_index = _with_sample(
        sources["barcode_index"], _BARCODE_INDEX_SAMPLE_RE, "barcode_index"
    )
    graphclust = _with_sample(sources["graphclust"], _GRAPHCLUST_SAMPLE_RE, "graphclust")
    kmeans_raw = _with_sample(sources["kmeans"], _KMEANS_SAMPLE_RE, "kmeans")
    umap = _with_sample(sources["umap"], _UMAP_SAMPLE_RE, "umap")
    tsne = _with_sample(sources["tsne"], _TSNE_SAMPLE_RE, "tsne")
    pca = _with_sample(sources["pca"], _PCA_SAMPLE_RE, "pca")
    cellbender_cells = _with_sample(
        sources["cellbender_cells"], _CELLBENDER_SAMPLE_RE, "cellbender_cells"
    )
    cluster_labels = _cluster_labels(sources["diffexp"])

    # --- gene flags (mito / ribo / hb), joined onto the matrix by gene_idx ---
    flags = features.select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("feature_name").str.starts_with("MT-").fill_null(False).alias("is_mito"),
        (
            pl.col("feature_name").str.starts_with("RPS")
            | pl.col("feature_name").str.starts_with("RPL")
        )
        .fill_null(False)
        .alias("is_ribo"),
        (
            pl.col("feature_name").str.starts_with("HBA")
            | pl.col("feature_name").str.starts_with("HBB")
        )
        .fill_null(False)
        .alias("is_hb"),
    )

    matrix_typed = matrix.select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("barcode_idx").cast(pl.Int64),
        pl.col("count").cast(pl.Int64, strict=False),
    )
    matrix_flagged = matrix_typed.join(flags, on=["sample", "gene_idx"], how="left")

    # --- per-cell QC metrics, one columnar group_by over 17M rows ---
    per_cell = matrix_flagged.group_by(["sample", "barcode_idx"]).agg(
        pl.col("count").sum().alias("n_umi"),
        pl.len().cast(pl.Int64).alias("n_genes"),
        (pl.col("count") * pl.col("is_mito").cast(pl.Int64)).sum().alias("_mito_umi"),
        (pl.col("count") * pl.col("is_ribo").cast(pl.Int64)).sum().alias("_ribo_umi"),
        (pl.col("count") * pl.col("is_hb").cast(pl.Int64)).sum().alias("_hb_umi"),
        pl.col("count").sort(descending=True).head(20).sum().alias("_top20_umi"),
    )
    per_cell = per_cell.with_columns(
        (pl.col("_mito_umi") / pl.col("n_umi") * 100).alias("pct_mito"),
        (pl.col("_ribo_umi") / pl.col("n_umi") * 100).alias("pct_ribo"),
        (pl.col("_hb_umi") / pl.col("n_umi") * 100).alias("pct_hb"),
        (pl.col("_top20_umi") / pl.col("n_umi") * 100).alias("pct_top20"),
    ).drop("_mito_umi", "_ribo_umi", "_hb_umi", "_top20_umi")
    per_cell = per_cell.with_columns(
        pl.col("n_umi").log10().alias("log10_n_umi"),
        pl.col("n_genes").log10().alias("log10_n_genes"),
    )

    # --- translate barcode_idx back to the barcode string ---
    bc_lookup = barcode_index.select(
        "sample", pl.col("barcode_idx").cast(pl.Int64), pl.col("barcode").cast(pl.Utf8)
    )
    per_cell = per_cell.join(bc_lookup, on=["sample", "barcode_idx"], how="inner").drop(
        "barcode_idx"
    )
    per_cell = per_cell.with_columns(
        pl.col("barcode").str.replace(r"-\d+$", "").alias("barcode_core")
    )

    # --- graph-based cluster + label ---
    graphclust_typed = graphclust.select(
        "sample",
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        pl.col("Cluster").cast(pl.Int64, strict=False).alias("_cluster_id"),
    ).with_columns(
        (pl.lit("C") + pl.col("_cluster_id").cast(pl.Utf8)).alias("graphclust"),
        (pl.lit("Cluster ") + pl.col("_cluster_id").cast(pl.Utf8)).alias("cluster"),
    )
    graphclust_typed = graphclust_typed.join(
        cluster_labels, on=["sample", "cluster"], how="left"
    ).select("sample", "barcode", "graphclust", "cluster_label")

    per_cell = per_cell.join(graphclust_typed, on=["sample", "barcode"], how="left")

    # --- kmeans clusters, long -> wide (kmeans_2 .. kmeans_10) ---
    kmeans_typed = kmeans_raw.with_columns(
        pl.col("source_path").str.extract(_KMEANS_K_RE.pattern, 1).cast(pl.Int64).alias("_k"),
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        (pl.lit("C") + pl.col("Cluster").cast(pl.Int64, strict=False).cast(pl.Utf8)).alias(
            "_kmeans_label"
        ),
    )
    if kmeans_typed.filter(pl.col("_k").is_null()).height:
        raise ValueError("cellranger_cell_qc: a kmeans source_path did not carry a 'k'")
    kmeans_wide = kmeans_typed.select("sample", "barcode", "_k", "_kmeans_label").pivot(
        on="_k", index=["sample", "barcode"], values="_kmeans_label"
    )
    kmeans_wide = kmeans_wide.rename(
        {str(k): f"kmeans_{k}" for k in _KMEANS_KS if str(k) in kmeans_wide.columns}
    )
    for k in _KMEANS_KS:
        col = f"kmeans_{k}"
        if col not in kmeans_wide.columns:
            kmeans_wide = kmeans_wide.with_columns(pl.lit(None, dtype=pl.Utf8).alias(col))
    per_cell = per_cell.join(kmeans_wide, on=["sample", "barcode"], how="left")

    # --- embeddings ---
    umap_typed = umap.select(
        "sample",
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        pl.col("UMAP-1").cast(pl.Float64, strict=False).alias("umap_1"),
        pl.col("UMAP-2").cast(pl.Float64, strict=False).alias("umap_2"),
    )
    tsne_typed = tsne.select(
        "sample",
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        pl.col("TSNE-1").cast(pl.Float64, strict=False).alias("tsne_1"),
        pl.col("TSNE-2").cast(pl.Float64, strict=False).alias("tsne_2"),
    )
    pca_typed = pca.select(
        "sample",
        pl.col("Barcode").cast(pl.Utf8).alias("barcode"),
        pl.col("PC-1").cast(pl.Float64, strict=False).alias("pc_1"),
        pl.col("PC-2").cast(pl.Float64, strict=False).alias("pc_2"),
        pl.col("PC-3").cast(pl.Float64, strict=False).alias("pc_3"),
    )
    per_cell = (
        per_cell.join(umap_typed, on=["sample", "barcode"], how="left")
        .join(tsne_typed, on=["sample", "barcode"], how="left")
        .join(pca_typed, on=["sample", "barcode"], how="left")
    )

    # --- CellBender agreement ---
    cb_cells = cellbender_cells.select(
        "sample", pl.col("barcode").cast(pl.Utf8), pl.lit(True).alias("cellbender_cell")
    ).unique()
    per_cell = per_cell.join(cb_cells, on=["sample", "barcode"], how="left").with_columns(
        pl.col("cellbender_cell").fill_null(False)
    )

    # --- MAD-based QC flags, per sample ---
    stats = per_cell.group_by("sample").agg(
        pl.col("log10_n_umi").median().alias("_med_log_umi"),
        (pl.col("log10_n_umi") - pl.col("log10_n_umi").median())
        .abs()
        .median()
        .alias("_mad_log_umi"),
        pl.col("log10_n_genes").median().alias("_med_log_genes"),
        (pl.col("log10_n_genes") - pl.col("log10_n_genes").median())
        .abs()
        .median()
        .alias("_mad_log_genes"),
        pl.col("pct_top20").median().alias("_med_top20"),
        (pl.col("pct_top20") - pl.col("pct_top20").median()).abs().median().alias("_mad_top20"),
        pl.col("pct_mito").median().alias("_med_mito"),
        (pl.col("pct_mito") - pl.col("pct_mito").median()).abs().median().alias("_mad_mito"),
    )
    # MAD -> approx-normal-consistent scale, standard 1.4826 factor.
    _C = 1.4826
    per_cell = per_cell.join(stats, on="sample", how="left").with_columns(
        (
            pl.col("log10_n_umi")
            < pl.col("_med_log_umi") - _MAD_K_COUNT * _C * pl.col("_mad_log_umi")
        ).alias("mad_low_umi"),
        (
            pl.col("log10_n_genes")
            < pl.col("_med_log_genes") - _MAD_K_COUNT * _C * pl.col("_mad_log_genes")
        ).alias("mad_low_genes"),
        (
            pl.col("pct_top20") > pl.col("_med_top20") + _MAD_K_TOP20 * _C * pl.col("_mad_top20")
        ).alias("mad_high_top20"),
        (
            (pl.col("pct_mito") > pl.col("_med_mito") + _MAD_K_MITO * _C * pl.col("_mad_mito"))
            | (pl.col("pct_mito") > _MITO_HARD_PCT)
        ).alias("mad_high_mito"),
    )

    per_cell = per_cell.with_columns(
        pl.when(pl.col("mad_low_umi"))
        .then(pl.lit("low_umi"))
        .when(pl.col("mad_low_genes"))
        .then(pl.lit("low_genes"))
        .when(pl.col("mad_high_top20"))
        .then(pl.lit("high_top20"))
        .when(pl.col("mad_high_mito"))
        .then(pl.lit("high_mito"))
        .otherwise(pl.lit("pass"))
        .alias("qc_reason"),
    )
    per_cell = per_cell.with_columns(
        pl.when(pl.col("qc_reason") == "pass")
        .then(pl.lit("pass"))
        .otherwise(pl.lit("flagged"))
        .alias("qc_status")
    )
    per_cell = per_cell.with_columns(
        (pl.col("qc_status") == "flagged").cast(pl.Int64).alias("qc_flagged")
    )

    per_cell = per_cell.with_columns(
        pl.col("graphclust").fill_null("Unassigned"),
        pl.col("cluster_label").fill_null("Unassigned"),
    )

    return per_cell.select(list(EXPECTED_SCHEMA)).sort(["sample", "barcode"])
