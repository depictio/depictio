"""Synthetic RNA-seq data for single-gene deep-dive exploration.

Generates an expression matrix (samples x genes) with sample metadata,
pre-computed DE results (Treatment_A vs Control), and a gene-gene
correlation matrix.
"""

import numpy as np
import pandas as pd
from scipy import stats

# Metadata column definitions
METADATA_COLS: list[str] = ["condition", "batch", "cell_type"]

COLUMN_LABELS: dict[str, str] = {
    "condition": "Condition",
    "batch": "Batch",
    "cell_type": "Cell Type",
    "sample_id": "Sample ID",
}

# Realistic gene names mixed in with generic ones
REALISTIC_GENES: list[str] = [
    "TP53", "BRCA1", "MYC", "EGFR", "KRAS", "BRAF", "PIK3CA", "PTEN",
    "AKT1", "RB1", "CDKN2A", "NRAS", "ERBB2", "ALK", "ROS1", "MET",
    "FGFR1", "CDH1", "VHL", "APC", "SMAD4", "CTNNB1", "IDH1", "JAK2",
    "ABL1", "NOTCH1", "FOXP3", "IL6", "TNF", "VEGFA", "BCL2", "BAX",
    "CASP3", "STAT3", "MTOR", "RAF1", "SRC", "FOS", "JUN", "GAPDH",
    "ACTB", "TUBB", "CDK4", "CDK6", "CCND1", "CCNE1", "PLK1", "AURKA",
    "BRD4", "EZH2",
]


def generate_all_data(
    n_samples: int = 60,
    n_genes: int = 500,
    seed: int = 42,
) -> dict:
    """Generate all data needed for the gene explorer.

    Returns:
        Dict with keys: expression_df, metadata_df, de_results_df, correlation_df, gene_names
    """
    rng = np.random.default_rng(seed)

    conditions = ["Control", "Treatment_A", "Treatment_B", "Treatment_C"]
    batches = ["Batch_1", "Batch_2"]
    cell_types = ["Epithelial", "Fibroblast", "Immune"]

    # ── Assign metadata ───────────────────────────────────────────
    samples_per_condition = n_samples // len(conditions)
    condition_labels = []
    batch_labels = []
    cell_type_labels = []

    for cond in conditions:
        for j in range(samples_per_condition):
            condition_labels.append(cond)
            batch_labels.append(batches[j % len(batches)])
            cell_type_labels.append(rng.choice(cell_types, p=[0.5, 0.3, 0.2]))

    while len(condition_labels) < n_samples:
        condition_labels.append(rng.choice(conditions))
        batch_labels.append(rng.choice(batches))
        cell_type_labels.append(rng.choice(cell_types))

    condition_labels = condition_labels[:n_samples]
    batch_labels = batch_labels[:n_samples]
    cell_type_labels = cell_type_labels[:n_samples]
    sample_ids = [f"Sample_{i + 1:03d}" for i in range(n_samples)]

    metadata_df = pd.DataFrame({
        "sample_id": sample_ids,
        "condition": condition_labels,
        "batch": batch_labels,
        "cell_type": cell_type_labels,
    })

    # ── Gene names ────────────────────────────────────────────────
    n_realistic = min(len(REALISTIC_GENES), n_genes)
    gene_names = list(REALISTIC_GENES[:n_realistic])
    for i in range(n_genes - n_realistic):
        gene_names.append(f"GENE_{i + 1:04d}")

    # ── Expression matrix ─────────────────────────────────────────
    gene_means = rng.uniform(4, 12, n_genes)
    gene_stds = rng.uniform(0.3, 1.0, n_genes)

    expression = np.zeros((n_samples, n_genes))
    for g in range(n_genes):
        expression[:, g] = rng.normal(gene_means[g], gene_stds[g], n_samples)

    # Inject condition-specific signal into first 100 genes
    n_variable = min(100, n_genes)
    condition_effects = {
        "Control": np.zeros(n_variable),
        "Treatment_A": rng.normal(2.0, 0.5, n_variable),
        "Treatment_B": rng.normal(-1.5, 0.5, n_variable),
        "Treatment_C": rng.normal(1.0, 0.8, n_variable),
    }
    for i in range(n_samples):
        expression[i, :n_variable] += condition_effects[condition_labels[i]]

    # Batch effect
    batch_effect = rng.normal(0, 0.3, n_genes)
    for i in range(n_samples):
        if batch_labels[i] == "Batch_2":
            expression[i, :] += batch_effect

    expression = np.clip(expression, 0, 20)

    expression_df = pd.DataFrame(
        expression, columns=gene_names, index=sample_ids
    ).round(3)

    # ── DE results (Treatment_A vs Control) ───────────────────────
    ctrl_mask = np.array([c == "Control" for c in condition_labels])
    treat_mask = np.array([c == "Treatment_A" for c in condition_labels])

    de_rows = []
    for g_idx, gene in enumerate(gene_names):
        ctrl_vals = expression[ctrl_mask, g_idx]
        treat_vals = expression[treat_mask, g_idx]
        log2fc = float(np.mean(treat_vals) - np.mean(ctrl_vals))
        t_stat, pval = stats.ttest_ind(treat_vals, ctrl_vals, equal_var=False)
        mean_expr = float(np.mean(expression[:, g_idx]))
        de_rows.append({
            "gene_name": gene,
            "log2fc": round(log2fc, 4),
            "pvalue": max(pval, 1e-300),
            "mean_expression": round(mean_expr, 3),
        })

    de_results_df = pd.DataFrame(de_rows)

    # Adjust p-values (BH correction)
    from scipy.stats import false_discovery_control
    de_results_df["padj"] = false_discovery_control(
        de_results_df["pvalue"].values, method="bh"
    )

    # Rank by absolute log2fc descending
    de_results_df["rank"] = (
        de_results_df["log2fc"].abs().rank(ascending=False, method="min").astype(int)
    )
    de_results_df = de_results_df.sort_values("rank").reset_index(drop=True)

    # ── Correlation matrix ────────────────────────────────────────
    correlation_df = pd.DataFrame(
        np.corrcoef(expression.T),
        index=gene_names,
        columns=gene_names,
    ).round(4)

    return {
        "expression_df": expression_df,
        "metadata_df": metadata_df,
        "de_results_df": de_results_df,
        "correlation_df": correlation_df,
        "gene_names": gene_names,
    }


def get_top_correlated(
    gene: str,
    correlation_df: pd.DataFrame,
    expression_df: pd.DataFrame,
    n: int = 10,
) -> pd.DataFrame:
    """Return top N most correlated genes for a given gene.

    Returns DataFrame with columns: gene_name, pearson_r, pvalue.
    """
    if gene not in correlation_df.index:
        return pd.DataFrame(columns=["gene_name", "pearson_r", "pvalue"])

    corr_series = correlation_df[gene].drop(gene).abs().sort_values(ascending=False)
    top_genes = corr_series.head(n).index.tolist()

    rows = []
    gene_vals = expression_df[gene].values
    for other in top_genes:
        r_val = correlation_df.loc[gene, other]
        _, p_val = stats.pearsonr(gene_vals, expression_df[other].values)
        rows.append({
            "gene_name": other,
            "pearson_r": round(float(r_val), 4),
            "pvalue": float(p_val),
        })

    return pd.DataFrame(rows)
