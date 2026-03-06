"""Synthetic GSEA data for the enrichment explorer prototype.

Generates realistic gene set enrichment analysis results with multiple
contrasts, ranked gene lists, and an expression matrix for heatmaps.
"""

import numpy as np
import pandas as pd

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
        "vesicle-mediated transport",
        "protein folding",
        "mitotic cell cycle",
        "cellular response to DNA damage",
        "regulation of apoptotic process",
        "positive regulation of transcription",
        "negative regulation of cell proliferation",
        "cell adhesion",
        "intracellular signal transduction",
        "response to cytokine",
        "regulation of gene expression",
        "protein transport",
        "RNA splicing",
        "cellular response to stress",
        "regulation of translation",
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
        "Drug metabolism",
        "Ribosome",
        "Proteasome",
        "Spliceosome",
        "DNA replication",
        "Mismatch repair",
        "Nucleotide excision repair",
        "Base excision repair",
        "Toll-like receptor signaling",
        "NOD-like receptor signaling",
        "Chemokine signaling pathway",
        "Focal adhesion",
        "ECM-receptor interaction",
        "Tight junction",
        "Gap junction",
        "Regulation of actin cytoskeleton",
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
        "SUMOylation",
        "Ubiquitin-mediated proteolysis",
        "Programmed Cell Death",
        "Cellular responses to stress",
        "Mitotic G1-G1/S phases",
        "S Phase",
        "G2/M Checkpoints",
        "Mitotic Spindle Checkpoint",
        "Membrane Trafficking",
        "Axon guidance",
        "Hemostasis",
        "Platelet activation",
        "Extracellular matrix organization",
        "Collagen formation",
        "Elastic fibre formation",
        "GPCR downstream signaling",
    ],
}

# Master gene list (200 genes)
GENE_NAMES: list[str] = [
    f"{prefix}{i}"
    for prefix in [
        "TP53", "BRCA", "MYC", "KRAS", "EGFR", "PTEN", "RB", "AKT",
        "MAPK", "JAK", "STAT", "BCL", "CASP", "CDK", "VEGF", "FGF",
        "TGFB", "WNT", "NOTCH", "HIF", "SOX", "GATA", "FOXO", "NFE2",
        "IL",
    ]
    for i in range(1, 9)
]

CONTRASTS: list[str] = [
    "Treatment_A_vs_Control",
    "Treatment_B_vs_Control",
]

CONDITIONS: list[str] = ["Control", "Treatment_A", "Treatment_B"]


def generate_gsea_data(
    seed: int = 42,
) -> dict:
    """Generate all synthetic GSEA data.

    Returns a dict with keys:
        - enrichment_df: DataFrame of pathway enrichment results
        - ranked_genes: dict[contrast, DataFrame] of ranked gene lists
        - expression_df: DataFrame (genes x samples) expression matrix
        - sample_meta_df: DataFrame of sample metadata
    """
    rng = np.random.default_rng(seed)

    # ── Ranked gene lists per contrast ─────────────────────────────
    ranked_genes: dict[str, pd.DataFrame] = {}
    for contrast in CONTRASTS:
        log2fc = rng.normal(0, 1.5, len(GENE_NAMES))
        # Sort by log2fc descending to create rank
        order = np.argsort(-log2fc)
        genes_sorted = [GENE_NAMES[i] for i in order]
        log2fc_sorted = log2fc[order]
        ranked_genes[contrast] = pd.DataFrame(
            {
                "gene_name": genes_sorted,
                "log2fc": np.round(log2fc_sorted, 4),
                "rank_position": np.arange(1, len(GENE_NAMES) + 1),
            }
        )

    # ── Enrichment results ─────────────────────────────────────────
    rows = []
    for contrast in CONTRASTS:
        gene_list = ranked_genes[contrast]["gene_name"].tolist()
        for source, pathways in PATHWAY_NAMES.items():
            for pathway in pathways:
                nes = rng.normal(0, 1.8)
                # p-value inversely correlated with |NES|
                abs_nes = abs(nes)
                pval = float(np.clip(10 ** (-abs_nes * rng.uniform(0.8, 2.5)), 1e-10, 1.0))
                padj = float(np.clip(pval * rng.uniform(1.0, 5.0), 1e-10, 1.0))
                gene_set_size = int(rng.integers(15, 301))
                # Leading edge: subset of the ranked gene list
                le_size = max(5, int(gene_set_size * rng.uniform(0.2, 0.6)))
                if nes > 0:
                    # Leading edge from top of ranked list
                    le_genes = gene_list[:le_size]
                else:
                    # Leading edge from bottom of ranked list
                    le_genes = gene_list[-le_size:]

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
                        # Store the full gene set for running ES computation
                        "gene_set": list(rng.choice(gene_list, size=min(gene_set_size, len(gene_list)), replace=False)),
                    }
                )

    enrichment_df = pd.DataFrame(rows)

    # ── Expression matrix (200 genes x 60 samples) ────────────────
    n_samples = 60
    samples_per_cond = n_samples // len(CONDITIONS)
    sample_ids = [f"S{i + 1:03d}" for i in range(n_samples)]
    condition_labels = []
    batch_labels = []
    for ci, cond in enumerate(CONDITIONS):
        for j in range(samples_per_cond):
            condition_labels.append(cond)
            batch_labels.append(f"Batch_{(j % 2) + 1}")

    sample_meta_df = pd.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": condition_labels,
            "batch": batch_labels,
        }
    )

    # Base expression
    gene_means = rng.uniform(4, 12, len(GENE_NAMES))
    expr = np.zeros((len(GENE_NAMES), n_samples))
    for g in range(len(GENE_NAMES)):
        expr[g, :] = rng.normal(gene_means[g], 0.8, n_samples)

    # Condition effects on first 50 genes
    cond_effects = {
        "Control": np.zeros(50),
        "Treatment_A": rng.normal(1.5, 0.5, 50),
        "Treatment_B": rng.normal(-1.2, 0.5, 50),
    }
    for si in range(n_samples):
        cond = condition_labels[si]
        expr[:50, si] += cond_effects[cond]

    expr = np.clip(expr, 0, 20).round(3)
    expression_df = pd.DataFrame(expr, index=GENE_NAMES, columns=sample_ids)

    return {
        "enrichment_df": enrichment_df,
        "ranked_genes": ranked_genes,
        "expression_df": expression_df,
        "sample_meta_df": sample_meta_df,
    }
