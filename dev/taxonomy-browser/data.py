"""Synthetic 16S/metagenomics data for the Taxonomy Browser prototype."""

import numpy as np
import pandas as pd

# Taxonomy hierarchy (simplified)
TAXA: list[dict[str, str]] = [
    {
        "kingdom": "Bacteria",
        "phylum": "Firmicutes",
        "class": "Bacilli",
        "order": "Lactobacillales",
        "family": "Lactobacillaceae",
        "genus": "Lactobacillus",
        "species": "L. acidophilus",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Firmicutes",
        "class": "Bacilli",
        "order": "Lactobacillales",
        "family": "Streptococcaceae",
        "genus": "Streptococcus",
        "species": "S. thermophilus",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Firmicutes",
        "class": "Clostridia",
        "order": "Clostridiales",
        "family": "Lachnospiraceae",
        "genus": "Roseburia",
        "species": "R. intestinalis",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Firmicutes",
        "class": "Clostridia",
        "order": "Clostridiales",
        "family": "Ruminococcaceae",
        "genus": "Faecalibacterium",
        "species": "F. prausnitzii",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Firmicutes",
        "class": "Clostridia",
        "order": "Clostridiales",
        "family": "Clostridiaceae",
        "genus": "Clostridium",
        "species": "C. difficile",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Bacteroidetes",
        "class": "Bacteroidia",
        "order": "Bacteroidales",
        "family": "Bacteroidaceae",
        "genus": "Bacteroides",
        "species": "B. fragilis",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Bacteroidetes",
        "class": "Bacteroidia",
        "order": "Bacteroidales",
        "family": "Bacteroidaceae",
        "genus": "Bacteroides",
        "species": "B. thetaiotaomicron",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Bacteroidetes",
        "class": "Bacteroidia",
        "order": "Bacteroidales",
        "family": "Prevotellaceae",
        "genus": "Prevotella",
        "species": "P. copri",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Proteobacteria",
        "class": "Gammaproteobacteria",
        "order": "Enterobacterales",
        "family": "Enterobacteriaceae",
        "genus": "Escherichia",
        "species": "E. coli",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Proteobacteria",
        "class": "Gammaproteobacteria",
        "order": "Enterobacterales",
        "family": "Enterobacteriaceae",
        "genus": "Klebsiella",
        "species": "K. pneumoniae",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Actinobacteria",
        "class": "Actinobacteria",
        "order": "Bifidobacteriales",
        "family": "Bifidobacteriaceae",
        "genus": "Bifidobacterium",
        "species": "B. longum",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Actinobacteria",
        "class": "Actinobacteria",
        "order": "Bifidobacteriales",
        "family": "Bifidobacteriaceae",
        "genus": "Bifidobacterium",
        "species": "B. breve",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Verrucomicrobia",
        "class": "Verrucomicrobiae",
        "order": "Verrucomicrobiales",
        "family": "Akkermansiaceae",
        "genus": "Akkermansia",
        "species": "A. muciniphila",
    },
    {
        "kingdom": "Bacteria",
        "phylum": "Fusobacteria",
        "class": "Fusobacteriia",
        "order": "Fusobacteriales",
        "family": "Fusobacteriaceae",
        "genus": "Fusobacterium",
        "species": "F. nucleatum",
    },
    {
        "kingdom": "Archaea",
        "phylum": "Euryarchaeota",
        "class": "Methanobacteria",
        "order": "Methanobacteriales",
        "family": "Methanobacteriaceae",
        "genus": "Methanobrevibacter",
        "species": "M. smithii",
    },
]

RANK_ORDER: list[str] = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]

CONDITIONS: list[str] = ["Healthy", "Disease"]
SAMPLES_PER_CONDITION: int = 6


def generate_abundance_data(seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate synthetic taxonomic abundance data.

    Returns:
        Tuple of (abundance_df, taxonomy_df, metadata_df).
        - abundance_df: taxa (rows) × samples (columns), raw counts
        - taxonomy_df: taxa (rows) × rank columns
        - metadata_df: samples (rows) with condition column
    """
    rng = np.random.default_rng(seed)

    n_taxa = len(TAXA)
    n_samples = len(CONDITIONS) * SAMPLES_PER_CONDITION
    sample_ids = [f"Sample_{i + 1:02d}" for i in range(n_samples)]

    # Base abundance profile (Dirichlet-like)
    base_profile = rng.dirichlet(np.ones(n_taxa) * 2)

    # Generate counts per sample with condition-specific shifts
    counts = np.zeros((n_taxa, n_samples), dtype=int)
    for j in range(n_samples):
        condition_idx = j // SAMPLES_PER_CONDITION
        profile = base_profile.copy()

        # Disease samples: increase Proteobacteria (indices 8,9) and
        # Fusobacterium (13), decrease Firmicutes (0-4)
        if condition_idx == 1:  # Disease
            profile[8:10] *= 3.0
            profile[13] *= 4.0
            profile[0:5] *= 0.4
            profile /= profile.sum()

        # Sample depth: 10k-100k reads
        depth = rng.integers(10000, 100000)
        counts[:, j] = rng.multinomial(depth, profile)

    taxa_ids = [f"ASV_{i + 1:04d}" for i in range(n_taxa)]

    abundance_df = pd.DataFrame(counts, columns=sample_ids, index=taxa_ids)
    abundance_df.index.name = "taxon_id"

    taxonomy_df = pd.DataFrame(TAXA, index=taxa_ids)
    taxonomy_df.index.name = "taxon_id"

    conditions = []
    for cond in CONDITIONS:
        conditions.extend([cond] * SAMPLES_PER_CONDITION)

    metadata_df = pd.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": conditions,
            "batch": [f"Batch_{(i % 2) + 1}" for i in range(n_samples)],
        }
    )

    return abundance_df, taxonomy_df, metadata_df


def compute_relative_abundance(counts_df: pd.DataFrame) -> pd.DataFrame:
    """Convert raw counts to relative abundance (proportions summing to 1)."""
    return counts_df.div(counts_df.sum(axis=0), axis=1)


def aggregate_by_rank(
    abundance_df: pd.DataFrame,
    taxonomy_df: pd.DataFrame,
    rank: str,
) -> pd.DataFrame:
    """Aggregate abundance table by a taxonomic rank.

    Args:
        abundance_df: taxa × samples counts.
        taxonomy_df: taxa × rank columns.
        rank: One of RANK_ORDER.

    Returns:
        Aggregated DataFrame with rank values as index.
    """
    merged = abundance_df.copy()
    merged[rank] = taxonomy_df[rank].values
    return merged.groupby(rank).sum()


def compute_alpha_diversity(counts_df: pd.DataFrame) -> pd.DataFrame:
    """Compute Shannon and Simpson diversity indices per sample.

    Args:
        counts_df: taxa × samples raw counts.

    Returns:
        DataFrame with sample, shannon, simpson columns.
    """
    results = []
    for sample in counts_df.columns:
        counts = counts_df[sample].values.astype(float)
        total = counts.sum()
        if total == 0:
            results.append({"sample": sample, "shannon": 0.0, "simpson": 0.0})
            continue

        proportions = counts / total
        proportions = proportions[proportions > 0]

        shannon = -np.sum(proportions * np.log(proportions))
        simpson = 1 - np.sum(proportions**2)
        results.append(
            {"sample": sample, "shannon": round(shannon, 3), "simpson": round(simpson, 4)}
        )

    return pd.DataFrame(results)
