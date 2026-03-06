"""Synthetic volcano dataset generation for the conditional highlighting prototype."""

import numpy as np
import pandas as pd

NUMERIC_COLS: list[str] = ["log2fc", "neg_log10_pvalue", "mean_expression"]
CATEGORICAL_COLS: list[str] = ["cluster", "significance"]
COLUMN_LABELS: dict[str, str] = {
    "log2fc": "log2(FC)",
    "neg_log10_pvalue": "-log10(p-value)",
    "mean_expression": "Mean Expression",
    "cluster": "Cluster",
    "significance": "Significance",
    "gene_name": "Gene",
}


def generate_volcano_data(n_genes: int = 2000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic volcano plot data with realistic gene expression patterns.

    Creates a dataset with a mixture of non-significant genes (centered around 0)
    and significantly up/down-regulated genes, mimicking a typical differential
    expression analysis output.

    Args:
        n_genes: Number of genes to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with columns: gene_name, log2fc, neg_log10_pvalue,
        mean_expression, cluster, significance.
    """
    rng = np.random.default_rng(seed)

    n_ns = int(n_genes * 0.7)
    n_up = int(n_genes * 0.15)
    n_down = n_genes - n_ns - n_up

    # Log2 fold change: mixture distribution
    log2fc = np.concatenate(
        [
            rng.normal(0, 0.5, n_ns),
            rng.normal(2.5, 0.8, n_up),
            rng.normal(-2.5, 0.8, n_down),
        ]
    )

    # P-values: correlated with fold change magnitude
    base_pval = np.clip(
        10 ** -(np.abs(log2fc) * rng.uniform(1, 4, n_genes)),
        1e-50,
        1,
    )
    neg_log10_pvalue = -np.log10(base_pval)

    # Mean expression (lognormal)
    mean_expression = rng.lognormal(mean=2, sigma=1, size=n_genes)

    # Cluster assignment
    clusters = rng.choice(["A", "B", "C", "D"], size=n_genes, p=[0.3, 0.3, 0.2, 0.2])

    # Significance classification (|log2FC| > 1.5 AND -log10(p) > 1.3)
    significance = np.where(
        (np.abs(log2fc) > 1.5) & (neg_log10_pvalue > 1.3),
        np.where(log2fc > 0, "Up", "Down"),
        "NS",
    )

    gene_names = [f"GENE_{i:04d}" for i in range(n_genes)]

    return pd.DataFrame(
        {
            "gene_name": gene_names,
            "log2fc": np.round(log2fc, 3),
            "neg_log10_pvalue": np.round(neg_log10_pvalue, 3),
            "mean_expression": np.round(mean_expression, 3),
            "cluster": clusters,
            "significance": significance,
        }
    )
