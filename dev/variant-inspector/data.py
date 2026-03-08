"""Synthetic viral variant data for the Variant Inspector prototype."""

import numpy as np
import pandas as pd

# SARS-CoV-2-like reference (simplified)
GENOME_LENGTH: int = 29903
GENE_REGIONS: list[dict[str, int | str]] = [
    {"gene": "ORF1a", "start": 266, "end": 13468},
    {"gene": "ORF1b", "start": 13468, "end": 21555},
    {"gene": "S", "start": 21563, "end": 25384},
    {"gene": "ORF3a", "start": 25393, "end": 26220},
    {"gene": "E", "start": 26245, "end": 26472},
    {"gene": "M", "start": 26523, "end": 27191},
    {"gene": "ORF7a", "start": 27394, "end": 27759},
    {"gene": "N", "start": 28274, "end": 29533},
]

NUCLEOTIDES: list[str] = ["A", "C", "G", "T"]
EFFECT_TYPES: list[str] = ["missense", "synonymous", "nonsense", "frameshift", "upstream"]
EFFECT_PROBS: list[float] = [0.55, 0.30, 0.02, 0.03, 0.10]

LINEAGES: list[str] = ["BA.5.2", "BA.5.1", "BQ.1.1", "XBB.1.5", "Other"]
SAMPLES: list[str] = [
    "WW_Site1_W01",
    "WW_Site1_W02",
    "WW_Site1_W03",
    "WW_Site1_W04",
    "WW_Site2_W01",
    "WW_Site2_W02",
    "WW_Site2_W03",
    "WW_Site2_W04",
]


def _get_gene_for_position(pos: int) -> str:
    """Map a genomic position to a gene name."""
    for region in GENE_REGIONS:
        if region["start"] <= pos <= region["end"]:
            return str(region["gene"])
    return "intergenic"


def generate_variant_data(n_variants: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic viral variant calls mimicking iVar TSV output.

    Args:
        n_variants: Number of variant positions.
        seed: Random seed.

    Returns:
        DataFrame with: position, ref, alt, alt_freq, alt_depth, total_depth,
        alt_qual, gene, effect, aa_change, sample.
    """
    rng = np.random.default_rng(seed)

    rows = []
    # Generate variant positions (some shared across samples)
    positions = sorted(
        rng.choice(range(200, GENOME_LENGTH - 200), size=n_variants // 2, replace=False)
    )

    for sample in SAMPLES:
        # Each sample sees a subset of variants plus some private ones
        n_shared = rng.integers(len(positions) // 3, len(positions))
        sample_positions = list(rng.choice(positions, size=n_shared, replace=False))
        n_private = rng.integers(5, 20)
        private_pos = rng.integers(200, GENOME_LENGTH - 200, size=n_private)
        sample_positions.extend(private_pos.tolist())
        sample_positions = sorted(set(sample_positions))

        for pos in sample_positions:
            ref = rng.choice(NUCLEOTIDES)
            alt_choices = [n for n in NUCLEOTIDES if n != ref]
            alt = rng.choice(alt_choices)

            # Allele frequency — bimodal: fixed mutations near 1.0, minority variants near 0.05-0.3
            if rng.random() < 0.3:
                alt_freq = rng.beta(20, 2)  # high frequency (near fixation)
            else:
                alt_freq = rng.beta(2, 10)  # low frequency (minority)

            total_depth = rng.integers(50, 5000)
            alt_depth = int(total_depth * alt_freq)
            alt_qual = rng.integers(20, 250)

            gene = _get_gene_for_position(pos)
            effect = rng.choice(EFFECT_TYPES, p=EFFECT_PROBS)

            aa_pos = (pos - 200) // 3
            if effect == "missense":
                aa_change = f"{rng.choice(list('ACDEFGHIKLMNPQRSTVWY'))}{aa_pos}{rng.choice(list('ACDEFGHIKLMNPQRSTVWY'))}"
            elif effect == "synonymous":
                aa = rng.choice(list("ACDEFGHIKLMNPQRSTVWY"))
                aa_change = f"{aa}{aa_pos}{aa}"
            else:
                aa_change = ""

            rows.append(
                {
                    "position": pos,
                    "ref": ref,
                    "alt": alt,
                    "alt_freq": round(alt_freq, 4),
                    "alt_depth": alt_depth,
                    "total_depth": total_depth,
                    "alt_qual": alt_qual,
                    "gene": gene,
                    "effect": effect,
                    "aa_change": aa_change,
                    "sample": sample,
                }
            )

    return pd.DataFrame(rows)


def generate_coverage_data(seed: int = 42) -> pd.DataFrame:
    """Generate per-position depth data for a single sample.

    Args:
        seed: Random seed.

    Returns:
        DataFrame with: position, depth (sampled at every 100bp).
    """
    rng = np.random.default_rng(seed)

    positions = list(range(1, GENOME_LENGTH + 1, 100))
    base_depth = 500
    # Smooth coverage with some dropouts
    depth = rng.normal(base_depth, 100, len(positions))
    # Add a few dropout regions
    for dropout_center in [5000, 15000, 22000]:
        idx = dropout_center // 100
        if idx < len(depth):
            spread = 10
            start = max(0, idx - spread)
            end = min(len(depth), idx + spread)
            depth[start:end] *= rng.uniform(0.05, 0.3)

    depth = np.clip(depth, 0, 3000).astype(int)

    return pd.DataFrame({"position": positions, "depth": depth})


def generate_lineage_data(seed: int = 42) -> pd.DataFrame:
    """Generate synthetic Freyja lineage abundance data per sample.

    Args:
        seed: Random seed.

    Returns:
        DataFrame with: sample, lineage, abundance.
    """
    rng = np.random.default_rng(seed)

    rows = []
    for sample in SAMPLES:
        # Each sample has a Dirichlet mix of lineages
        abundances = rng.dirichlet(np.array([3, 2, 1, 1, 0.5]))
        for lineage, abundance in zip(LINEAGES, abundances):
            rows.append(
                {
                    "sample": sample,
                    "lineage": lineage,
                    "abundance": round(abundance, 4),
                }
            )

    return pd.DataFrame(rows)
