"""Sample structure of a Bambu gene matrix: PCA coordinates plus library metrics.

The first question anyone asks of a quantification run is whether the samples
separate the way the design says they should, and the second is whether any
library is an outlier on depth or complexity. Both are answered by the count
matrix alone, so this output carries the two-dimensional embedding and the
per-library readings side by side: one row per sample, which is also small
enough to pin as a table.

The embedding follows what DESeq2's ``plotPCA`` does: log-transform, keep the
``TOP_VARIABLE`` most variable genes, centre the genes (no scaling, so a
high-variance gene keeps its weight) and take the leading singular vectors.
The transform is an SVD from numpy, so nothing here depends on scikit-learn.

Output columns
    sample_id, condition            who the row is
    dim_1, dim_2, dim_3             embedding coordinates (precomputed mode)
    pc1_var_pct, pc2_var_pct        variance each axis explains, repeated per row
    total_counts                    library size, reads Bambu assigned
    n_genes_detected                genes with at least one read
    pct_protein_coding              share of the library in protein-coding genes
    top50_share_pct                 share of the library in its 50 top genes,
                                    the plainest library-complexity reading
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bambu import (
    condition_of,
    gene_biotype_expr,
    gene_id_expr,
    log_cpm_matrix,
    name_sample_columns,
    sample_names,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="header",
        glob_pattern="**/bambu/counts_gene.txt",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "n_rows": 1,
            "infer_schema_length": 0,
            "truncate_ragged_lines": True,
        },
    ),
    RecipeSource(
        ref="counts",
        glob_pattern="**/bambu/counts_gene.txt",
        format="tsv",
        read_kwargs={"has_header": False, "skip_rows": 1, "infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "condition": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_3": pl.Float64,
    "pc1_var_pct": pl.Float64,
    "pc2_var_pct": pl.Float64,
    "total_counts": pl.Float64,
    "n_genes_detected": pl.Int64,
    "pct_protein_coding": pl.Float64,
    "top50_share_pct": pl.Float64,
}

#: Genes kept for the embedding, ranked by variance of log CPM.
TOP_VARIABLE = 500
#: Genes counted for the library-complexity reading.
TOP_SHARE = 50


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Gene matrix -> one row per sample: PCA coordinates and library readings."""
    samples = sample_names(sources["header"].row(0))
    counts, descriptor = name_sample_columns(sources["counts"], samples)

    per_gene = (
        counts.with_columns(
            gene_id_expr(descriptor).alias("gene_id"),
            gene_biotype_expr(descriptor).fill_null("unannotated").alias("gene_biotype"),
        )
        .filter(pl.col("gene_id").is_not_null())
        .group_by("gene_id")
        .agg(
            pl.col("gene_biotype").drop_nulls().first().alias("gene_biotype"),
            *[pl.col(c).sum().alias(c) for c in samples],
        )
    )

    totals = {c: float(per_gene[c].sum() or 0.0) for c in samples}
    detected = {c: int(per_gene.filter(pl.col(c) > 0).height) for c in samples}
    coding = per_gene.filter(pl.col("gene_biotype") == "protein_coding")
    coding_counts = {c: float(coding[c].sum() or 0.0) for c in samples}
    top_share = {
        c: float(
            per_gene.select(pl.col(c)).to_series().sort(descending=True).head(TOP_SHARE).sum()
            or 0.0
        )
        for c in samples
    }

    log_cpm = log_cpm_matrix(per_gene, "gene_id", samples)
    variances = log_cpm.select(pl.concat_list([pl.col(c) for c in samples]).list.var().alias("var"))
    ranked = (
        log_cpm.with_columns(variances["var"].alias("_var"))
        .sort("_var", descending=True, nulls_last=True)
        .head(TOP_VARIABLE)
    )

    matrix = ranked.select(samples).to_numpy().astype(np.float64).T  # samples x genes
    matrix = np.nan_to_num(matrix, nan=0.0)
    centred = matrix - matrix.mean(axis=0)
    _, singular, right = np.linalg.svd(centred, full_matrices=False)
    coords = centred @ right[:3].T
    while coords.shape[1] < 3:
        coords = np.hstack([coords, np.zeros((coords.shape[0], 1))])
    explained = singular**2
    explained = explained / explained.sum() * 100.0 if explained.sum() else explained

    return (
        pl.DataFrame(
            {
                "sample_id": samples,
                "condition": [condition_of(s) for s in samples],
                "dim_1": coords[:, 0].tolist(),
                "dim_2": coords[:, 1].tolist(),
                "dim_3": coords[:, 2].tolist(),
                "pc1_var_pct": [float(explained[0]) if len(explained) else 0.0] * len(samples),
                "pc2_var_pct": [float(explained[1]) if len(explained) > 1 else 0.0] * len(samples),
                "total_counts": [totals[s] for s in samples],
                "n_genes_detected": [detected[s] for s in samples],
                "pct_protein_coding": [
                    (coding_counts[s] / totals[s] * 100.0) if totals[s] else 0.0 for s in samples
                ],
                "top50_share_pct": [
                    (top_share[s] / totals[s] * 100.0) if totals[s] else 0.0 for s in samples
                ],
            }
        )
        .with_columns(
            pl.col("n_genes_detected").cast(pl.Int64),
            *[
                pl.col(c).cast(pl.Float64)
                for c in EXPECTED_SCHEMA
                if EXPECTED_SCHEMA[c] is pl.Float64
            ],
        )
        .select(list(EXPECTED_SCHEMA))
        .sort("sample_id")
    )
