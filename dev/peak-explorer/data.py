"""Synthetic ChIP-seq/ATAC-seq peak data for the Peak Explorer prototype.

Generates peaks with correlated properties so that threshold-driven analysis
reveals meaningful annotation enrichment: high-score peaks are more likely
to be Promoter annotations, making the enrichment curve non-trivial.
"""

import numpy as np
import pandas as pd

ANNOTATION_CATEGORIES: list[str] = [
    "Promoter",
    "5' UTR",
    "3' UTR",
    "Exon",
    "Intron",
    "Intergenic",
    "TTS",
]

SAMPLES: list[str] = [
    "H3K27ac_rep1",
    "H3K27ac_rep2",
    "H3K4me3_rep1",
    "H3K4me3_rep2",
    "Input_rep1",
    "Input_rep2",
]

NUMERIC_COLS: list[str] = [
    "score",
    "neg_log10_pvalue",
    "fold_enrichment",
    "width",
    "distance_to_tss",
]
CATEGORICAL_COLS: list[str] = ["annotation", "chr"]

COLUMN_LABELS: dict[str, str] = {
    "score": "Peak Score",
    "neg_log10_pvalue": "-log10(p-value)",
    "fold_enrichment": "Fold Enrichment",
    "width": "Peak Width (bp)",
    "distance_to_tss": "Distance to TSS",
    "annotation": "Annotation",
    "chr": "Chromosome",
    "peak_id": "Peak ID",
    "nearest_gene": "Nearest Gene",
}


def generate_peak_data(n_peaks: int = 3000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic peak calls with correlated properties.

    High-score peaks correlate with higher fold enrichment, more significant
    p-values, and Promoter annotation — making annotation enrichment curves
    and threshold-driven filtering analytically interesting.
    """
    rng = np.random.default_rng(seed)

    chroms = rng.choice([f"chr{i}" for i in range(1, 23)] + ["chrX"], size=n_peaks)
    widths = rng.lognormal(mean=5.5, sigma=0.6, size=n_peaks).astype(int)
    widths = np.clip(widths, 100, 10000)

    # Fold enrichment (base signal strength)
    fold_enrichment = rng.lognormal(mean=1.5, sigma=0.8, size=n_peaks)
    fold_enrichment = np.clip(fold_enrichment, 1.0, 50.0)

    # Score correlates with fold enrichment
    scores = (fold_enrichment * 80 + rng.normal(0, 40, n_peaks)).astype(int)
    scores = np.clip(scores, 10, 1000)

    # -log10(pvalue) correlates with score
    neg_log10_pvalue = scores / 50.0 + rng.exponential(2, n_peaks)
    neg_log10_pvalue = np.clip(neg_log10_pvalue, 0.5, 300)

    # Annotation: promoter probability INCREASES with score (key for enrichment)
    promoter_prob = np.clip(scores / 1200.0, 0.05, 0.50)
    annotations = []
    non_promoter = ["5' UTR", "3' UTR", "Exon", "Intron", "Intergenic", "TTS"]
    non_promoter_p = [0.03, 0.05, 0.08, 0.35, 0.40, 0.09]
    for pp in promoter_prob:
        if rng.random() < pp:
            annotations.append("Promoter")
        else:
            annotations.append(rng.choice(non_promoter, p=non_promoter_p))

    distance_to_tss = (rng.exponential(50000, n_peaks) * (1 - scores / 1500.0)).astype(int)
    distance_to_tss = np.clip(distance_to_tss, 0, 500000)

    gene_names = [f"GENE_{rng.integers(1, 25000):05d}" for _ in range(n_peaks)]
    starts = rng.integers(1000, 200_000_000, n_peaks)

    return pd.DataFrame(
        {
            "peak_id": [f"Peak_{i + 1:05d}" for i in range(n_peaks)],
            "chr": chroms,
            "start": starts,
            "end": starts + widths,
            "width": widths,
            "score": scores,
            "neg_log10_pvalue": np.round(neg_log10_pvalue, 2),
            "fold_enrichment": np.round(fold_enrichment, 2),
            "annotation": annotations,
            "nearest_gene": gene_names,
            "distance_to_tss": distance_to_tss,
        }
    )


def generate_consensus_matrix(
    peak_df: pd.DataFrame,
    samples: list[str] | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate consensus peak × sample binary matrix."""
    if samples is None:
        samples = SAMPLES
    rng = np.random.default_rng(seed)
    base_prob = np.clip(peak_df["score"].values / 1000, 0.1, 0.95)
    matrix = np.zeros((len(peak_df), len(samples)), dtype=int)
    for j in range(len(samples)):
        matrix[:, j] = rng.binomial(1, base_prob)
    return pd.DataFrame(matrix, columns=samples, index=peak_df["peak_id"])
