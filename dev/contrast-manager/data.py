"""Synthetic RNA-seq data with pre-computed differential expression results.

Generates a 60-sample x 500-gene expression matrix and DE results for three
contrasts (Treatment_A/B/C vs Control).
"""

import numpy as np
import pandas as pd

CONDITIONS: list[str] = ["Control", "Treatment_A", "Treatment_B", "Treatment_C"]
CONTRASTS: list[str] = [
    "Treatment_A_vs_Control",
    "Treatment_B_vs_Control",
    "Treatment_C_vs_Control",
]


def generate_data(
    n_samples: int = 60,
    n_genes: int = 500,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Generate expression data, sample metadata, and DE results.

    Returns:
        Tuple of (expression_df, metadata_df, de_results):
            - expression_df: DataFrame (samples x genes), log2 normalized
            - metadata_df: DataFrame with sample_id, condition, batch, cell_type
            - de_results: dict mapping contrast name -> DE result DataFrame
    """
    rng = np.random.default_rng(seed)

    batches = ["Batch_1", "Batch_2"]
    cell_types = ["Epithelial", "Fibroblast", "Immune"]

    # Assign metadata: 15 samples per condition
    samples_per_condition = n_samples // len(CONDITIONS)
    condition_labels: list[str] = []
    batch_labels: list[str] = []
    cell_type_labels: list[str] = []

    for cond in CONDITIONS:
        for j in range(samples_per_condition):
            condition_labels.append(cond)
            batch_labels.append(batches[j % len(batches)])
            cell_type_labels.append(rng.choice(cell_types, p=[0.5, 0.3, 0.2]))

    # Fill remaining samples if n_samples not divisible by 4
    while len(condition_labels) < n_samples:
        condition_labels.append(rng.choice(CONDITIONS))
        batch_labels.append(rng.choice(batches))
        cell_type_labels.append(rng.choice(cell_types))

    sample_ids = [f"Sample_{i + 1:03d}" for i in range(n_samples)]

    metadata_df = pd.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": condition_labels[:n_samples],
            "batch": batch_labels[:n_samples],
            "cell_type": cell_type_labels[:n_samples],
        }
    )

    # Expression matrix: baseline + condition effects
    gene_names = [f"GENE_{i + 1:04d}" for i in range(n_genes)]
    gene_means = rng.uniform(4, 12, n_genes)
    gene_stds = rng.uniform(0.3, 1.0, n_genes)

    expression = np.zeros((n_samples, n_genes))
    for g in range(n_genes):
        expression[:, g] = rng.normal(gene_means[g], gene_stds[g], n_samples)

    # Condition-specific effects on first 100 genes
    n_de_genes = 100
    condition_effects = {
        "Control": np.zeros(n_de_genes),
        "Treatment_A": rng.normal(2.0, 0.5, n_de_genes),
        "Treatment_B": rng.normal(-1.5, 0.5, n_de_genes),
        "Treatment_C": rng.normal(1.0, 0.8, n_de_genes),
    }

    for i in range(n_samples):
        cond = condition_labels[i]
        expression[i, :n_de_genes] += condition_effects[cond]

    # Add batch effect
    batch_effect = rng.normal(0, 0.3, n_genes)
    for i in range(n_samples):
        if batch_labels[i] == "Batch_2":
            expression[i, :] += batch_effect

    expression = np.clip(expression, 0, 20)
    expression_df = pd.DataFrame(expression, columns=gene_names, index=sample_ids)
    expression_df = expression_df.round(3)

    # Pre-compute DE results for each contrast
    de_results: dict[str, pd.DataFrame] = {}
    control_mask = metadata_df["condition"] == "Control"
    control_expr = expression[control_mask.values]

    for contrast_name in CONTRASTS:
        treatment = contrast_name.replace("_vs_Control", "")
        treat_mask = metadata_df["condition"] == treatment
        treat_expr = expression[treat_mask.values]

        mean_treat = treat_expr.mean(axis=0)
        mean_ctrl = control_expr.mean(axis=0)
        mean_all = expression.mean(axis=0)
        log2fc = mean_treat - mean_ctrl  # already log2 scale

        # Simulate p-values: genes with large |log2fc| get small p-values
        noise = rng.uniform(0, 0.3, n_genes)
        raw_p = np.exp(-np.abs(log2fc) * 2.5) + noise * 0.1
        raw_p = np.clip(raw_p, 1e-300, 1.0)

        # BH adjustment (simplified)
        sorted_idx = np.argsort(raw_p)
        padj = np.ones(n_genes)
        for rank, idx in enumerate(sorted_idx, 1):
            padj[idx] = raw_p[idx] * n_genes / rank
        padj = np.clip(padj, 0, 1)
        # Ensure monotonicity
        for i in range(len(sorted_idx) - 2, -1, -1):
            padj[sorted_idx[i]] = min(padj[sorted_idx[i]], padj[sorted_idx[i + 1]])

        significant = (padj < 0.05) & (np.abs(log2fc) > 1.0)

        de_df = pd.DataFrame(
            {
                "gene_name": gene_names,
                "log2fc": np.round(log2fc, 4),
                "pvalue": raw_p,
                "padj": padj,
                "mean_expression": np.round(mean_all, 3),
                "significant": significant,
            }
        )
        de_results[contrast_name] = de_df

    return expression_df, metadata_df, de_results


def get_contrast_summary(
    metadata_df: pd.DataFrame, de_results: dict[str, pd.DataFrame]
) -> list[dict]:
    """Build summary rows for the contrast table.

    Returns list of dicts with: name, numerator, denominator,
    n_samples_num, n_samples_den, n_sig_genes, balance_warning.
    """
    rows = []
    for name, de_df in de_results.items():
        treatment = name.replace("_vs_Control", "")
        n_num = int((metadata_df["condition"] == treatment).sum())
        n_den = int((metadata_df["condition"] == "Control").sum())
        n_sig = int(de_df["significant"].sum())
        ratio = max(n_num, n_den) / max(min(n_num, n_den), 1)
        balance_warning = ratio > 2.0
        rows.append(
            {
                "name": name,
                "numerator": treatment,
                "denominator": "Control",
                "n_samples_num": n_num,
                "n_samples_den": n_den,
                "n_sig_genes": n_sig,
                "balance_warning": balance_warning,
            }
        )
    return rows
