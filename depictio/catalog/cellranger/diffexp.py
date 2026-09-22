"""Cluster marker genes from Cell Ranger's differential-expression tables.

`analysis/diffexp/gene_expression_<resolution>/differential_expression.csv` is
wide: one row per gene, and three columns per cluster (`Cluster N Mean
Counts`, `Cluster N Log2 fold change`, `Cluster N Adjusted p value`), that
cluster against every other cell. This recipe melts it to one row per (gene,
cluster) and keeps the `MAX_GENES_PER_CLUSTER` most significant genes of each
cluster (ranked by adjusted p-value), which is what a marker table is read
for and keeps a 20k-gene x 10-cluster file from becoming 200k+ rows.

Cell Ranger writes ONE such file per clustering it ran: the graph-based one
plus a k-means one for every k it tried (k=2..10 by default). All of them are
read, and `resolution` says which file a row came from, so a dashboard can put
a resolution picker in front of the marker table instead of shipping the
graph-based clustering as the only answer. The per-file column sets differ
(k=2 has two clusters, the graph-based one had 14 here); the scan's schema
alignment fills the gaps with nulls, and a null adjusted p-value is what marks
a (file, cluster) pair that does not exist.

The sample is not a column either (one file per sample directory), so the raw
data collection is a **scan** (`include_file_paths`).

A template reusing this recipe declares::

    regex_config: {pattern: '.*/analysis/diffexp/gene_expression_[^/]+/differential_expression\\.csv$'}
    dc_specific_properties: {format: CSV, polars_kwargs: {include_file_paths: source_path}}

Output schema (canonical `da_barplot`/`volcano` schema columns: feature_id=gene,
contrast=cluster, lfc=log2fc/effect_size, significance=adjusted_pvalue,
category=cluster_label):
    sample : Utf8            sample the clustering was computed on
    resolution : Utf8         "graphclust", or "kmeans_<k>" for the k-means clusterings
    cluster : Utf8            "Cluster <n>", the cluster this gene was tested against the rest for
    cluster_label : Utf8      "C<n> top1/top2" marker genes for this cluster (same rule as
                              cellranger/cell_qc.py's cluster_label; computed independently
                              here so neither recipe depends on the other's row cap). The
                              k-means resolutions prefix it with "k<k> " so a label stays
                              unambiguous across resolutions while the graph-based labels
                              stay byte-identical to the cell hub's, which is what the
                              cluster_label link joins on.
    rank_in_cluster : Int64   1-based rank within the cluster, most significant (lowest
                              adjusted p-value) first
    gene_id : Utf8            Cell Ranger Feature ID
    gene : Utf8               Feature Name, bind as feature_id / label
    mean_counts : Float64     mean UMI counts for this gene inside the cluster
    log2fc : Float64          log2 fold change vs every other cluster
    adjusted_pvalue : Float64 BH-adjusted p-value
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "cellranger_diffexp_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="diffexp", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "resolution": pl.Utf8,
    "cluster": pl.Utf8,
    "cluster_label": pl.Utf8,
    "rank_in_cluster": pl.Int64,
    "gene_id": pl.Utf8,
    "gene": pl.Utf8,
    "mean_counts": pl.Float64,
    "log2fc": pl.Float64,
    "adjusted_pvalue": pl.Float64,
}

#: the clustering Cell Ranger itself reports on, and the one the cell hub's
#: `cluster_label` (and every cluster_label link) is built from.
GRAPHCLUST_RESOLUTION = "graphclust"

#: kept per cluster, ranked by adjusted p-value, a marker table, not the full matrix
MAX_GENES_PER_CLUSTER = 100

#: the 2 genes with the highest log2FC among these criteria label the cluster
#: (mirrors cellranger/cell_qc.py's cluster_label rule, computed independently)
_LABEL_PADJ_MAX = 0.05
_LABEL_MEAN_MIN = 0.5

_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/analysis/diffexp/"
_RESOLUTION_RE = r"analysis/diffexp/gene_expression_([^/]+)/differential_expression\.csv$"
_KMEANS_DIR_RE = re.compile(r"^kmeans_(\d+)_clusters$")
_CLUSTER_COL_RE = re.compile(r"^Cluster (\d+) Mean Counts$")


def _resolution_label(directory: str) -> str:
    """`gene_expression_<directory>` -> "graphclust" or "kmeans_<k>"."""
    if m := _KMEANS_DIR_RE.match(directory):
        return f"kmeans_{m.group(1)}"
    return directory


def _label_prefix(resolution: str) -> str:
    """Empty for the graph-based clustering, `k<k> ` for a k-means one."""
    if resolution == GRAPHCLUST_RESOLUTION:
        return ""
    return f"k{resolution.removeprefix('kmeans_')} "


def _cluster_labels(melted: pl.DataFrame) -> pl.DataFrame:
    """sample, resolution, cluster -> cluster_label, from the FULL melted table."""
    keys = ["sample", "resolution", "cluster"]
    qualifying = melted.filter(
        (pl.col("adjusted_pvalue") < _LABEL_PADJ_MAX) & (pl.col("mean_counts") > _LABEL_MEAN_MIN)
    )
    ranked = qualifying.with_columns(
        pl.col("log2fc").rank(method="ordinal", descending=True).over(keys).alias("_lfc_rank")
    ).filter(pl.col("_lfc_rank") <= 2)

    labels = []
    for (sample, resolution, cluster), group in ranked.group_by(keys, maintain_order=True):
        cid = str(cluster).removeprefix("Cluster ")
        top_genes = group.sort("_lfc_rank")["gene"].to_list()
        base = f"C{cid} {'/'.join(top_genes)}".strip()
        labels.append(
            {
                "sample": sample,
                "resolution": resolution,
                "cluster": cluster,
                "cluster_label": _label_prefix(str(resolution)) + base,
            }
        )

    all_clusters = melted.select(keys).unique()
    label_df = pl.DataFrame(
        labels,
        schema={
            "sample": pl.Utf8,
            "resolution": pl.Utf8,
            "cluster": pl.Utf8,
            "cluster_label": pl.Utf8,
        },
    )
    label_df = all_clusters.join(label_df, on=keys, how="left").with_columns(
        pl.when(pl.col("cluster_label").is_null())
        .then(
            pl.col("resolution").map_elements(_label_prefix, return_dtype=pl.Utf8)
            + pl.lit("C")
            + pl.col("cluster").str.replace("Cluster ", "")
        )
        .otherwise(pl.col("cluster_label"))
        .alias("cluster_label")
    )
    return label_df


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["diffexp"]
    if "source_path" not in df.columns:
        raise ValueError(
            "cellranger_diffexp: input has no 'source_path' column, the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )
    required = {"Feature ID", "Feature Name"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"cellranger_diffexp: input lacks columns {sorted(missing)}")

    cluster_ids = sorted(int(m.group(1)) for c in df.columns if (m := _CLUSTER_COL_RE.match(c)))
    if not cluster_ids:
        raise ValueError("cellranger_diffexp: no 'Cluster N Mean Counts' columns found")

    df = df.with_columns(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("source_path")
        .str.extract(_RESOLUTION_RE, 1)
        .map_elements(_resolution_label, return_dtype=pl.Utf8)
        .alias("resolution"),
    )
    if df.filter(pl.col("sample").is_null() | pl.col("resolution").is_null()).height:
        raise ValueError(
            "cellranger_diffexp: a row's source_path did not match the expected layout"
        )

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
                "resolution",
                pl.lit(f"Cluster {cid}").alias("cluster"),
                pl.col("Feature ID").cast(pl.Utf8).alias("gene_id"),
                pl.col("Feature Name").cast(pl.Utf8).alias("gene"),
                pl.col(mean_col).cast(pl.Float64, strict=False).alias("mean_counts"),
                pl.col(lfc_col).cast(pl.Float64, strict=False).alias("log2fc"),
                pl.col(pval_col).cast(pl.Float64, strict=False).alias("adjusted_pvalue"),
            )
        )
    melted = pl.concat(frames, how="vertical_relaxed")
    # A null p-value is a (file, cluster) pair that does not exist: k=2's file
    # carries no "Cluster 7" columns, and the scan filled them with nulls.
    melted = melted.filter(pl.col("adjusted_pvalue").is_not_null())

    keys = ["sample", "resolution", "cluster"]
    cluster_labels = _cluster_labels(melted)

    result = melted.with_columns(
        pl.col("adjusted_pvalue")
        .rank(method="ordinal")
        .over(keys)
        .cast(pl.Int64)
        .alias("rank_in_cluster")
    )
    result = result.filter(pl.col("rank_in_cluster") <= MAX_GENES_PER_CLUSTER)
    result = result.join(cluster_labels, on=keys, how="left")

    return result.select(list(EXPECTED_SCHEMA)).sort(
        ["sample", "resolution", "cluster", "adjusted_pvalue"]
    )
