"""Synthetic ChIP-seq/ATAC-seq peak data for the Peak Explorer prototype."""

import numpy as np
import pandas as pd

CHROMOSOMES: list[str] = [f"chr{i}" for i in range(1, 23)] + ["chrX", "chrY"]
CHR_SIZES: dict[str, int] = {
    "chr1": 248_956_422, "chr2": 242_193_529, "chr3": 198_295_559,
    "chr4": 190_214_555, "chr5": 181_538_259, "chr6": 170_805_979,
    "chr7": 159_345_973, "chr8": 145_138_636, "chr9": 138_394_717,
    "chr10": 133_797_422, "chr11": 135_086_622, "chr12": 133_275_309,
    "chr13": 114_364_328, "chr14": 107_043_718, "chr15": 101_991_189,
    "chr16": 90_338_345, "chr17": 83_257_441, "chr18": 80_373_285,
    "chr19": 58_617_616, "chr20": 64_444_167, "chr21": 46_709_983,
    "chr22": 50_818_468, "chrX": 156_040_895, "chrY": 57_227_415,
}

ANNOTATION_CATEGORIES: list[str] = [
    "Promoter", "5' UTR", "3' UTR", "Exon", "Intron", "Intergenic", "TTS",
]
ANNOTATION_PROBS: list[float] = [0.15, 0.03, 0.05, 0.08, 0.35, 0.30, 0.04]

SAMPLES: list[str] = ["H3K27ac_rep1", "H3K27ac_rep2", "H3K4me3_rep1", "H3K4me3_rep2",
                       "Input_rep1", "Input_rep2"]


def generate_peak_data(n_peaks: int = 3000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic peak calls mimicking MACS2 narrowPeak output.

    Args:
        n_peaks: Number of peaks.
        seed: Random seed.

    Returns:
        DataFrame with: peak_id, chr, start, end, width, score, pvalue,
        fold_enrichment, annotation, nearest_gene, distance_to_tss.
    """
    rng = np.random.default_rng(seed)

    # Random chromosomes weighted by size
    chr_weights = np.array([CHR_SIZES[c] for c in CHROMOSOMES], dtype=float)
    chr_weights /= chr_weights.sum()
    chroms = rng.choice(CHROMOSOMES, size=n_peaks, p=chr_weights)

    # Random positions within chromosome
    starts = np.array([rng.integers(1000, CHR_SIZES[c] - 10000) for c in chroms])
    widths = rng.lognormal(mean=5.5, sigma=0.6, size=n_peaks).astype(int)
    widths = np.clip(widths, 100, 10000)
    ends = starts + widths

    # Score (0-1000 range like MACS2)
    scores = rng.lognormal(mean=4.5, sigma=1.2, size=n_peaks)
    scores = np.clip(scores, 10, 1000).astype(int)

    # -log10(pvalue)
    pvalues = rng.exponential(scale=8, size=n_peaks)
    pvalues = np.clip(pvalues, 1, 300)

    # Fold enrichment
    fold_enrichment = rng.lognormal(mean=1.5, sigma=0.8, size=n_peaks)
    fold_enrichment = np.clip(fold_enrichment, 1.0, 50.0)

    # Annotation categories
    annotations = rng.choice(
        ANNOTATION_CATEGORIES, size=n_peaks, p=ANNOTATION_PROBS,
    )

    # Nearest gene and distance to TSS
    gene_names = [f"GENE_{rng.integers(1, 25000):05d}" for _ in range(n_peaks)]
    distance_to_tss = rng.exponential(scale=50000, size=n_peaks).astype(int)
    # Promoter peaks should be close to TSS
    promoter_mask = annotations == "Promoter"
    distance_to_tss[promoter_mask] = rng.integers(0, 2000, size=promoter_mask.sum())

    return pd.DataFrame(
        {
            "peak_id": [f"Peak_{i + 1:05d}" for i in range(n_peaks)],
            "chr": chroms,
            "start": starts,
            "end": ends,
            "width": widths,
            "score": scores,
            "neg_log10_pvalue": np.round(pvalues, 2),
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
    """Generate a synthetic consensus peak × sample binary matrix.

    Args:
        peak_df: Peak DataFrame (uses peak_id).
        samples: Sample names.
        seed: Random seed.

    Returns:
        DataFrame with peak_id as index and samples as columns (0/1 values).
    """
    if samples is None:
        samples = SAMPLES
    rng = np.random.default_rng(seed)

    n_peaks = len(peak_df)
    n_samples = len(samples)

    # Higher-scoring peaks more likely to be present across samples
    base_prob = np.clip(peak_df["score"].values / 1000, 0.1, 0.95)
    matrix = np.zeros((n_peaks, n_samples), dtype=int)
    for j in range(n_samples):
        matrix[:, j] = rng.binomial(1, base_prob)

    return pd.DataFrame(matrix, columns=samples, index=peak_df["peak_id"])


def generate_frip_scores(
    samples: list[str] | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic FRiP (Fraction of Reads in Peaks) scores.

    Args:
        samples: Sample names.
        seed: Random seed.

    Returns:
        DataFrame with sample and frip columns.
    """
    if samples is None:
        samples = SAMPLES
    rng = np.random.default_rng(seed)

    frip = rng.beta(a=5, b=3, size=len(samples))
    # Input samples have low FRiP
    for i, s in enumerate(samples):
        if "Input" in s:
            frip[i] = rng.uniform(0.01, 0.08)

    return pd.DataFrame({"sample": samples, "frip": np.round(frip, 3)})
