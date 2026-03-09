"""
Unified synthetic data generation for all bioinformatics modules.

All core modules (Progressive Filter, Feature Explorer, Contrast Manager,
Enrichment Explorer, DimRed Explorer) share the same expression matrix, sample
metadata, and DE results so that cross-module communication makes sense.

Domain-specific modules (Peak Explorer, Taxonomy Browser, Variant Inspector)
generate their own data but can still receive shared signals (e.g.,
highlighted_samples).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ─── Constants ────────────────────────────────────────────────────────────

CONDITIONS: list[str] = ["Control", "Treatment_A", "Treatment_B", "Treatment_C"]
CONTRASTS: list[str] = [
    "Treatment_A_vs_Control",
    "Treatment_B_vs_Control",
    "Treatment_C_vs_Control",
]

# Realistic pathway names grouped by source
PATHWAY_NAMES: dict[str, list[str]] = {
    "GO_BP": [
        "apoptotic process",
        "cell cycle",
        "DNA repair",
        "response to oxidative stress",
        "inflammatory response",
        "signal transduction",
        "protein phosphorylation",
        "transcription by RNA pol II",
        "cell migration",
        "angiogenesis",
        "autophagy",
        "immune response",
        "mRNA processing",
        "chromatin remodeling",
        "protein ubiquitination",
        "response to hypoxia",
        "Wnt signaling pathway",
        "Notch signaling pathway",
        "regulation of cell growth",
        "lipid metabolic process",
    ],
    "KEGG": [
        "MAPK signaling pathway",
        "PI3K-Akt signaling pathway",
        "p53 signaling pathway",
        "Cell cycle",
        "Apoptosis",
        "mTOR signaling pathway",
        "Jak-STAT signaling pathway",
        "NF-kappa B signaling pathway",
        "TNF signaling pathway",
        "TGF-beta signaling pathway",
        "Oxidative phosphorylation",
        "Glycolysis / Gluconeogenesis",
        "Citrate cycle (TCA cycle)",
        "Fatty acid metabolism",
        "Ribosome",
    ],
    "Reactome": [
        "Cell Cycle Checkpoints",
        "Signaling by EGFR",
        "Signaling by FGFR",
        "Signaling by VEGF",
        "Signaling by Interleukins",
        "Innate Immune System",
        "Adaptive Immune System",
        "Metabolism of proteins",
        "Metabolism of lipids",
        "Metabolism of RNA",
        "Translation",
        "Transcription",
        "DNA Repair",
        "Chromatin modifying enzymes",
        "Programmed Cell Death",
    ],
}

# Gene names for enrichment
GENE_NAMES_200: list[str] = [
    f"{prefix}{i}"
    for prefix in [
        "TP53",
        "BRCA",
        "MYC",
        "KRAS",
        "EGFR",
        "PTEN",
        "RB",
        "AKT",
        "MAPK",
        "JAK",
        "STAT",
        "BCL",
        "CASP",
        "CDK",
        "VEGF",
        "FGF",
        "TGFB",
        "WNT",
        "NOTCH",
        "HIF",
        "SOX",
        "GATA",
        "FOXO",
        "NFE2",
        "IL",
    ]
    for i in range(1, 9)
]


# ─── Core RNA-seq data ────────────────────────────────────────────────────


def generate_core_data(
    n_samples: int = 60,
    n_genes: int = 500,
    seed: int = 42,
) -> dict:
    """Generate expression matrix, sample metadata, and DE results.

    Used by: Progressive Filter, Feature Explorer, Contrast Manager,
    Enrichment Explorer, DimRed Explorer.

    Returns dict with keys:
        expression_df: DataFrame (samples × genes), log2 normalized
        metadata_df: DataFrame with sample_id, condition, batch, cell_type
        de_results: dict[contrast_name → DataFrame]
        correlation_matrix: DataFrame (gene × gene) Pearson correlation
        gene_names: list[str]
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

    while len(condition_labels) < n_samples:
        condition_labels.append(rng.choice(CONDITIONS))
        batch_labels.append(rng.choice(batches))
        cell_type_labels.append(rng.choice(cell_types))

    sample_ids = [f"Sample_{i + 1:03d}" for i in range(n_samples)]
    gene_names = [f"GENE_{i + 1:04d}" for i in range(n_genes)]

    metadata_df = pd.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": condition_labels[:n_samples],
            "batch": batch_labels[:n_samples],
            "cell_type": cell_type_labels[:n_samples],
        }
    )

    # Expression matrix: baseline + condition effects
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

    # Batch effect
    batch_effect = rng.normal(0, 0.3, n_genes)
    for i in range(n_samples):
        if batch_labels[i] == "Batch_2":
            expression[i, :] += batch_effect

    # Cell-type effect on genes 100-130
    cell_type_effects = {
        "Epithelial": rng.normal(0.5, 0.2, 30),
        "Fibroblast": rng.normal(-0.3, 0.2, 30),
        "Immune": rng.normal(0.8, 0.3, 30),
    }
    for i in range(n_samples):
        ct = cell_type_labels[i]
        expression[i, 100:130] += cell_type_effects[ct]

    expression = np.clip(expression, 0, 20)
    expression_df = pd.DataFrame(expression.round(3), columns=gene_names, index=sample_ids)

    # DE results per contrast
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
        log2fc = mean_treat - mean_ctrl

        noise = rng.uniform(0, 0.3, n_genes)
        raw_p = np.exp(-np.abs(log2fc) * 2.5) + noise * 0.1
        raw_p = np.clip(raw_p, 1e-300, 1.0)

        # BH adjustment
        sorted_idx = np.argsort(raw_p)
        padj = np.ones(n_genes)
        for rank, idx in enumerate(sorted_idx, 1):
            padj[idx] = raw_p[idx] * n_genes / rank
        padj = np.clip(padj, 0, 1)
        for i in range(len(sorted_idx) - 2, -1, -1):
            padj[sorted_idx[i]] = min(padj[sorted_idx[i]], padj[sorted_idx[i + 1]])

        significant = (padj < 0.05) & (np.abs(log2fc) > 1.0)
        neg_log10_pvalue = -np.log10(np.clip(raw_p, 1e-300, 1))

        significance = np.where(
            (np.abs(log2fc) > 1.5) & (padj < 0.05),
            np.where(log2fc > 0, "Up", "Down"),
            "NS",
        )

        de_df = pd.DataFrame(
            {
                "gene_name": gene_names,
                "log2fc": np.round(log2fc, 4),
                "pvalue": raw_p,
                "padj": padj,
                "neg_log10_pvalue": np.round(neg_log10_pvalue, 3),
                "mean_expression": np.round(mean_all, 3),
                "significant": significant,
                "significance": significance,
                "cluster": rng.choice(["A", "B", "C", "D"], size=n_genes, p=[0.3, 0.3, 0.2, 0.2]),
            }
        )
        de_results[contrast_name] = de_df

    # Correlation matrix (top 50 most variable genes for speed)
    var_genes = expression_df.std().nlargest(50).index.tolist()
    correlation_matrix = expression_df[var_genes].corr()

    return {
        "expression_df": expression_df,
        "metadata_df": metadata_df,
        "de_results": de_results,
        "correlation_matrix": correlation_matrix,
        "gene_names": gene_names,
    }


# ─── Enrichment data (uses same gene universe) ──────────────────────────


def generate_enrichment_data(
    de_results: dict[str, pd.DataFrame],
    seed: int = 42,
) -> dict:
    """Generate GSEA-like enrichment results consistent with core DE results.

    Returns dict with keys:
        enrichment_df: DataFrame of pathway enrichment results
        ranked_genes: dict[contrast → DataFrame] of ranked gene lists
    """
    rng = np.random.default_rng(seed + 100)

    # Build ranked gene lists from the DE results
    ranked_genes: dict[str, pd.DataFrame] = {}
    for contrast, de_df in de_results.items():
        sorted_de = de_df.sort_values("log2fc", ascending=False).reset_index(drop=True)
        ranked_genes[contrast] = pd.DataFrame(
            {
                "gene_name": sorted_de["gene_name"].values,
                "log2fc": sorted_de["log2fc"].values,
                "rank_position": np.arange(1, len(sorted_de) + 1),
            }
        )

    # Enrichment results
    rows = []
    for contrast in de_results:
        gene_list = ranked_genes[contrast]["gene_name"].tolist()
        for source, pathways in PATHWAY_NAMES.items():
            for pathway in pathways:
                nes = rng.normal(0, 1.8)
                abs_nes = abs(nes)
                pval = float(np.clip(10 ** (-abs_nes * rng.uniform(0.8, 2.5)), 1e-10, 1.0))
                padj = float(np.clip(pval * rng.uniform(1.0, 5.0), 1e-10, 1.0))
                gene_set_size = int(rng.integers(15, 301))
                le_size = max(5, int(gene_set_size * rng.uniform(0.2, 0.6)))

                if nes > 0:
                    le_genes = gene_list[:le_size]
                else:
                    le_genes = gene_list[-le_size:]

                gene_set = list(
                    rng.choice(gene_list, size=min(gene_set_size, len(gene_list)), replace=False)
                )

                rows.append(
                    {
                        "contrast": contrast,
                        "pathway_name": pathway,
                        "source": source,
                        "NES": round(nes, 4),
                        "pvalue": pval,
                        "padj": padj,
                        "gene_set_size": gene_set_size,
                        "leading_edge_size": le_size,
                        "leading_edge_genes": le_genes,
                        "gene_set": gene_set,
                    }
                )

    enrichment_df = pd.DataFrame(rows)

    return {
        "enrichment_df": enrichment_df,
        "ranked_genes": ranked_genes,
    }


# ─── Domain-specific data generators ────────────────────────────────────


def generate_peak_data(n_peaks: int = 3000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic ChIP-seq/ATAC-seq peak calls."""
    rng = np.random.default_rng(seed)

    chroms = rng.choice([f"chr{i}" for i in range(1, 23)] + ["chrX"], size=n_peaks)
    widths = rng.lognormal(mean=5.5, sigma=0.6, size=n_peaks).astype(int)
    widths = np.clip(widths, 100, 10000)

    fold_enrichment = rng.lognormal(mean=1.5, sigma=0.8, size=n_peaks)
    fold_enrichment = np.clip(fold_enrichment, 1.0, 50.0)

    scores = (fold_enrichment * 80 + rng.normal(0, 40, n_peaks)).astype(int)
    scores = np.clip(scores, 10, 1000)

    neg_log10_pvalue = scores / 50.0 + rng.exponential(2, n_peaks)
    neg_log10_pvalue = np.clip(neg_log10_pvalue, 0.5, 300)

    promoter_prob = np.clip(scores / 1200.0, 0.05, 0.50)
    non_promoter = ["5' UTR", "3' UTR", "Exon", "Intron", "Intergenic", "TTS"]
    non_promoter_p = [0.03, 0.05, 0.08, 0.35, 0.40, 0.09]
    annotations = []
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


# Taxonomy constants
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
TAXONOMY_CONDITIONS: list[str] = ["Healthy", "Disease"]


def generate_taxonomy_data(seed: int = 42) -> dict:
    """Generate synthetic 16S/metagenomics abundance data.

    Returns dict with keys:
        abundance_df: taxa × samples raw counts
        taxonomy_df: taxa × rank columns
        metadata_df: samples with condition column
    """
    rng = np.random.default_rng(seed)

    n_taxa = len(TAXA)
    samples_per_cond = 6
    n_samples = len(TAXONOMY_CONDITIONS) * samples_per_cond
    sample_ids = [f"Sample_{i + 1:02d}" for i in range(n_samples)]

    base_profile = rng.dirichlet(np.ones(n_taxa) * 2)
    counts = np.zeros((n_taxa, n_samples), dtype=int)
    for j in range(n_samples):
        condition_idx = j // samples_per_cond
        profile = base_profile.copy()
        if condition_idx == 1:
            profile[8:10] *= 3.0
            profile[13] *= 4.0
            profile[0:5] *= 0.4
            profile /= profile.sum()
        depth = rng.integers(10000, 100000)
        counts[:, j] = rng.multinomial(depth, profile)

    taxa_ids = [f"ASV_{i + 1:04d}" for i in range(n_taxa)]
    abundance_df = pd.DataFrame(counts, columns=sample_ids, index=taxa_ids)
    abundance_df.index.name = "taxon_id"

    taxonomy_df = pd.DataFrame(TAXA, index=taxa_ids)
    taxonomy_df.index.name = "taxon_id"

    conditions = []
    for cond in TAXONOMY_CONDITIONS:
        conditions.extend([cond] * samples_per_cond)

    metadata_df = pd.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": conditions,
            "batch": [f"Batch_{(i % 2) + 1}" for i in range(n_samples)],
        }
    )

    return {
        "abundance_df": abundance_df,
        "taxonomy_df": taxonomy_df,
        "metadata_df": metadata_df,
    }


# Variant constants
GENOME_LENGTH: int = 29903
GENE_REGIONS: list[dict] = [
    {"gene": "ORF1a", "start": 266, "end": 13468},
    {"gene": "ORF1b", "start": 13468, "end": 21555},
    {"gene": "S", "start": 21563, "end": 25384},
    {"gene": "ORF3a", "start": 25393, "end": 26220},
    {"gene": "E", "start": 26245, "end": 26472},
    {"gene": "M", "start": 26523, "end": 27191},
    {"gene": "ORF7a", "start": 27394, "end": 27759},
    {"gene": "N", "start": 28274, "end": 29533},
]

VARIANT_SAMPLES: list[str] = [
    "WW_Site1_W01",
    "WW_Site1_W02",
    "WW_Site1_W03",
    "WW_Site1_W04",
    "WW_Site2_W01",
    "WW_Site2_W02",
    "WW_Site2_W03",
    "WW_Site2_W04",
]


def generate_variant_data(n_variants: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic viral variant calls mimicking iVar TSV output."""
    rng = np.random.default_rng(seed)
    nucleotides = ["A", "C", "G", "T"]
    effect_types = ["missense", "synonymous", "nonsense", "frameshift", "upstream"]
    effect_probs = [0.55, 0.30, 0.02, 0.03, 0.10]

    rows = []
    positions = sorted(
        rng.choice(range(200, GENOME_LENGTH - 200), size=n_variants // 2, replace=False)
    )

    for sample in VARIANT_SAMPLES:
        n_shared = rng.integers(len(positions) // 3, len(positions))
        sample_positions = list(rng.choice(positions, size=n_shared, replace=False))
        n_private = rng.integers(5, 20)
        private_pos = rng.integers(200, GENOME_LENGTH - 200, size=n_private)
        sample_positions.extend(private_pos.tolist())
        sample_positions = sorted(set(sample_positions))

        for pos in sample_positions:
            ref = rng.choice(nucleotides)
            alt_choices = [n for n in nucleotides if n != ref]
            alt = rng.choice(alt_choices)

            if rng.random() < 0.3:
                alt_freq = rng.beta(20, 2)
            else:
                alt_freq = rng.beta(2, 10)

            total_depth = rng.integers(50, 5000)
            alt_depth = int(total_depth * alt_freq)
            alt_qual = rng.integers(20, 250)

            gene = "intergenic"
            for region in GENE_REGIONS:
                if region["start"] <= pos <= region["end"]:
                    gene = str(region["gene"])
                    break

            effect = rng.choice(effect_types, p=effect_probs)
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


# ─── Master data loader ─────────────────────────────────────────────────


def load_all_data(seed: int = 42) -> dict:
    """Load all synthetic data for the demo app.

    Returns a dict with all data needed by all modules.
    """
    core = generate_core_data(seed=seed)
    enrichment = generate_enrichment_data(core["de_results"], seed=seed)
    peak_df = generate_peak_data(seed=seed)
    taxonomy = generate_taxonomy_data(seed=seed)
    variant_df = generate_variant_data(seed=seed)

    return {
        # Core (shared by 5 modules)
        "expression_df": core["expression_df"],
        "metadata_df": core["metadata_df"],
        "de_results": core["de_results"],
        "correlation_matrix": core["correlation_matrix"],
        "gene_names": core["gene_names"],
        # Enrichment
        "enrichment_df": enrichment["enrichment_df"],
        "ranked_genes": enrichment["ranked_genes"],
        # Domain-specific
        "peak_df": peak_df,
        "taxonomy_abundance_df": taxonomy["abundance_df"],
        "taxonomy_df": taxonomy["taxonomy_df"],
        "taxonomy_metadata_df": taxonomy["metadata_df"],
        "variant_df": variant_df,
    }
