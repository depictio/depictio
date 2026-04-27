"""Synthetic RNA-seq expression data for dimensionality reduction exploration.

Generates a realistic expression matrix (samples x genes) with sample metadata,
mimicking a multi-condition RNA-seq experiment with batch effects.
"""

import numpy as np
import pandas as pd

# Metadata column definitions
METADATA_COLS: list[str] = ["condition", "batch", "replicate", "cell_type"]

# Human-readable labels
COLUMN_LABELS: dict[str, str] = {
    "condition": "Condition",
    "batch": "Batch",
    "replicate": "Replicate",
    "cell_type": "Cell Type",
    "sample_id": "Sample ID",
}


def generate_expression_data(
    n_samples: int = 60,
    n_genes: int = 500,
    n_variable_genes: int = 100,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate synthetic RNA-seq expression matrix with sample metadata.

    Creates a dataset with 4 conditions, 2 batches, and clear separation
    in PCA space. A subset of genes are highly variable across conditions
    to create realistic clustering patterns.

    Args:
        n_samples: Total number of samples.
        n_genes: Total number of genes.
        n_variable_genes: Number of genes with condition-specific expression.
        seed: Random seed for reproducibility.

    Returns:
        Tuple of (expression_df, metadata_df):
            - expression_df: DataFrame (samples x genes) with log2-normalized counts
            - metadata_df: DataFrame with sample metadata columns
    """
    rng = np.random.default_rng(seed)

    conditions = ["Control", "Treatment_A", "Treatment_B", "Treatment_C"]
    batches = ["Batch_1", "Batch_2"]
    cell_types = ["Epithelial", "Fibroblast", "Immune"]

    # Assign metadata
    samples_per_condition = n_samples // len(conditions)
    condition_labels = []
    batch_labels = []
    cell_type_labels = []
    replicate_labels = []

    for i, cond in enumerate(conditions):
        for j in range(samples_per_condition):
            condition_labels.append(cond)
            batch_labels.append(batches[j % len(batches)])
            cell_type_labels.append(rng.choice(cell_types, p=[0.5, 0.3, 0.2]))
            replicate_labels.append(f"Rep_{j + 1}")

    # Fill remaining samples
    while len(condition_labels) < n_samples:
        condition_labels.append(rng.choice(conditions))
        batch_labels.append(rng.choice(batches))
        cell_type_labels.append(rng.choice(cell_types))
        replicate_labels.append(f"Rep_{len(replicate_labels) + 1}")

    sample_ids = [f"Sample_{i + 1:03d}" for i in range(n_samples)]

    metadata_df = pd.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": condition_labels[:n_samples],
            "batch": batch_labels[:n_samples],
            "cell_type": cell_type_labels[:n_samples],
            "replicate": replicate_labels[:n_samples],
        }
    )

    # Build expression matrix
    # Baseline: moderate expression with gene-specific means
    gene_means = rng.uniform(4, 12, n_genes)
    gene_stds = rng.uniform(0.3, 1.0, n_genes)

    expression = np.zeros((n_samples, n_genes))
    for g in range(n_genes):
        expression[:, g] = rng.normal(gene_means[g], gene_stds[g], n_samples)

    # Inject condition-specific signal into variable genes
    condition_effects = {
        "Control": np.zeros(n_variable_genes),
        "Treatment_A": rng.normal(2.0, 0.5, n_variable_genes),
        "Treatment_B": rng.normal(-1.5, 0.5, n_variable_genes),
        "Treatment_C": rng.normal(1.0, 0.8, n_variable_genes),
    }

    for i in range(n_samples):
        cond = condition_labels[i]
        expression[i, :n_variable_genes] += condition_effects[cond]

    # Add batch effect (smaller than condition effect)
    batch_effect = rng.normal(0, 0.4, n_genes)
    for i in range(n_samples):
        if batch_labels[i] == "Batch_2":
            expression[i, :] += batch_effect

    # Add cell-type effect on a different gene subset
    ct_start = n_variable_genes
    ct_end = min(ct_start + 30, n_genes)
    ct_effects = {
        "Epithelial": rng.normal(1.5, 0.3, ct_end - ct_start),
        "Fibroblast": rng.normal(-1.0, 0.3, ct_end - ct_start),
        "Immune": rng.normal(0.5, 0.3, ct_end - ct_start),
    }
    for i in range(n_samples):
        ct = cell_type_labels[i]
        expression[i, ct_start:ct_end] += ct_effects[ct]

    # Clip to realistic range
    expression = np.clip(expression, 0, 20)

    gene_names = [f"GENE_{i + 1:04d}" for i in range(n_genes)]
    expression_df = pd.DataFrame(expression, columns=gene_names, index=sample_ids)
    expression_df = expression_df.round(3)

    return expression_df, metadata_df


def get_top_variable_genes(expression_df: pd.DataFrame, n: int = 50) -> list[str]:
    """Return the top N most variable genes by standard deviation."""
    stds = expression_df.std(axis=0).sort_values(ascending=False)
    return stds.head(n).index.tolist()
