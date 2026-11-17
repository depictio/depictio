"""Library-level structure of a long feature count table: correlation and PCA.

Every count-based pipeline asks the same two questions of its libraries: which
ones resemble each other (a correlation matrix), and along which axis they
differ most (a PCA). Both start from one matrix, and they must start from the
same one, or a reader comparing the heatmap with the embedding compares two
different selections of genes:

* the features detected (``min_counts`` reads) in at least half of the libraries,
* on ``log2(cpm + 1)``,
* for the PCA, the ``top_variable`` of those with the largest variance across
  libraries, centred per feature.

The input is the long table of ``catalog/subread/gene_counts``
(``gene_id, sample, counts, log2_cpm``); the helpers are shape-generic and work
for any long count table with those four columns.
"""

from __future__ import annotations

import numpy as np
import polars as pl

#: Reads a feature needs in a library to count as detected there.
MIN_COUNTS = 10
#: Features kept for the PCA, by variance across libraries.
TOP_VARIABLE = 2000


def expressed_matrix(
    counts: pl.DataFrame,
    *,
    min_counts: int = MIN_COUNTS,
    value_col: str = "log2_cpm",
) -> pl.DataFrame:
    """Wide ``gene_id`` x library matrix of ``value_col`` over the expressed features.

    A feature is kept when it reaches ``min_counts`` in at least half of the
    libraries (rounded up). Raises ``ValueError`` when none does.
    """
    samples = sorted(counts.get_column("sample").unique().to_list())
    needed = max(1, -(-len(samples) // 2))
    kept = (
        counts.group_by("gene_id")
        .agg((pl.col("counts") >= min_counts).sum().alias("_detected"))
        .filter(pl.col("_detected") >= needed)
        .select("gene_id")
    )
    if kept.is_empty():
        raise ValueError(
            f"count_matrix: no feature reaches {min_counts} reads in half of the libraries"
        )
    wide = (
        counts.join(kept, on="gene_id")
        .pivot(on="sample", index="gene_id", values=value_col, aggregate_function="first")
        .fill_null(0.0)
    )
    return wide.select("gene_id", *[s for s in samples if s in wide.columns]).sort("gene_id")


def spearman(matrix: pl.DataFrame) -> pl.DataFrame:
    """Square Spearman correlation of the library columns of ``matrix``.

    ``matrix`` is ``gene_id`` plus one column per library. Returns ``sample``
    plus one Float64 column per library, rows in the column order.
    """
    samples = [c for c in matrix.columns if c != "gene_id"]
    ranks = np.column_stack(
        [matrix.get_column(s).rank(method="average").to_numpy().astype(float) for s in samples]
    )
    corr = np.corrcoef(ranks, rowvar=False) if len(samples) > 1 else np.ones((1, 1))
    corr = np.atleast_2d(corr)
    return pl.DataFrame(
        {"sample": samples, **{s: corr[:, j].round(4).tolist() for j, s in enumerate(samples)}},
        schema={"sample": pl.Utf8, **{s: pl.Float64 for s in samples}},
    )


def pca(matrix: pl.DataFrame, *, top_variable: int = TOP_VARIABLE) -> pl.DataFrame:
    """PCA of the libraries over the ``top_variable`` most variable features.

    Returns ``sample, pc1, pc2, pc3, pc1_variance, pc2_variance, pc3_variance``
    (variance explained, in percent). Components a run is too small to have
    (two libraries have one) are null.
    """
    samples = [c for c in matrix.columns if c != "gene_id"]
    values = matrix.select(samples).to_numpy().astype(float)  # features x libraries
    if values.shape[0] > top_variable:
        keep = np.argsort(values.var(axis=1))[::-1][:top_variable]
        values = values[keep]
    x = values.T - values.T.mean(axis=0)
    _u, singular, vt = np.linalg.svd(x, full_matrices=False)
    coords = x @ vt.T
    variance = singular**2
    share = variance / variance.sum() * 100 if variance.sum() > 0 else variance
    out: dict[str, list] = {"sample": samples}
    for i in range(3):
        if i < coords.shape[1]:
            out[f"pc{i + 1}"] = coords[:, i].tolist()
            out[f"pc{i + 1}_variance"] = [float(share[i])] * len(samples)
        else:
            out[f"pc{i + 1}"] = [None] * len(samples)
            out[f"pc{i + 1}_variance"] = [None] * len(samples)
    schema = {"sample": pl.Utf8, **{k: pl.Float64 for k in out if k != "sample"}}
    frame = pl.DataFrame(out, schema=schema)
    return frame.select(
        "sample", "pc1", "pc2", "pc3", "pc1_variance", "pc2_variance", "pc3_variance"
    )
