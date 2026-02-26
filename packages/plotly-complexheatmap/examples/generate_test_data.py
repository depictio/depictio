#!/usr/bin/env python
"""Generate test CSV datasets for Depictio heatmap integration testing.

Creates two datasets:
  1. ``heatmap_test_data.csv`` — 60 genes × 20 samples with annotation columns
  2. ``heatmap_small.csv`` — 15 genes × 8 samples (quick smoke test)

Usage::

    python examples/generate_test_data.py
    python examples/generate_test_data.py --output-dir /tmp/test_data
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def generate_large_dataset(seed: int = 42) -> pd.DataFrame:
    """Generate a 60×20 gene expression dataset with rich metadata columns."""
    rng = np.random.default_rng(seed)

    n_genes, n_samples = 60, 20
    expression = rng.standard_normal((n_genes, n_samples))

    # Embedded expression clusters
    expression[:20, :7] += 3.0
    expression[20:40, 7:14] += 2.5
    expression[40:, 14:] -= 1.5

    gene_names = [f"gene_{i:03d}" for i in range(n_genes)]
    sample_names = [f"sample_{j:02d}" for j in range(n_samples)]

    df = pd.DataFrame(expression, columns=sample_names)
    df.insert(0, "gene", gene_names)

    # Categorical annotations
    df.insert(
        1,
        "pathway",
        ["Apoptosis"] * 15 + ["Cell_Cycle"] * 15 + ["Metabolism"] * 10 + ["Signaling"] * 10 + ["Immune"] * 10,
    )
    df.insert(
        2,
        "chromosome",
        rng.choice(["chr1", "chr2", "chr3", "chr7", "chr17", "chrX"], size=n_genes).tolist(),
    )

    # Numeric annotations
    df.insert(3, "gene_length_kb", np.round(rng.uniform(0.5, 15.0, size=n_genes), 2))
    df.insert(4, "gc_content", np.round(rng.uniform(0.35, 0.65, size=n_genes), 3))
    df.insert(5, "mutation_score", np.round(rng.exponential(scale=2.0, size=n_genes), 2))
    df.insert(6, "log2fc", np.round(rng.normal(0, 1.5, size=n_genes), 2))

    return df


def generate_small_dataset(seed: int = 123) -> pd.DataFrame:
    """Generate a 15×8 compact dataset for quick testing."""
    rng = np.random.default_rng(seed)

    n_genes, n_samples = 15, 8
    expression = rng.standard_normal((n_genes, n_samples))
    expression[:5, :4] += 2.0
    expression[5:10, 4:] += 1.5

    df = pd.DataFrame(
        expression,
        columns=[f"sample_{j}" for j in range(n_samples)],
    )
    df.insert(0, "gene", [f"gene_{i}" for i in range(n_genes)])
    df.insert(
        1,
        "pathway",
        ["Apoptosis"] * 5 + ["Cell_Cycle"] * 5 + ["Metabolism"] * 5,
    )
    df.insert(2, "score", np.round(rng.uniform(0.0, 10.0, size=n_genes), 2))

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate heatmap test data")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "output",
        help="Output directory for CSV files",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    large = generate_large_dataset()
    large_path = args.output_dir / "heatmap_test_data.csv"
    large.to_csv(large_path, index=False)
    print(f"  Large dataset: {large_path}  ({large.shape[0]} rows × {large.shape[1]} cols)")

    small = generate_small_dataset()
    small_path = args.output_dir / "heatmap_small.csv"
    small.to_csv(small_path, index=False)
    print(f"  Small dataset: {small_path}  ({small.shape[0]} rows × {small.shape[1]} cols)")


if __name__ == "__main__":
    main()
