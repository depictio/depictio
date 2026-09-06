"""Generate deterministic synthetic TSV fixtures for the advanced-viz showcase.

Run once; outputs are committed under ``../data/``. Requires ``numpy``,
``polars``, ``umap-learn`` and ``scikit-learn`` — all of which Depictio
already depends on. Other than that the script is plain Python.

Each TSV's column schema matches the canonical schema declared in
depictio/models/components/advanced_viz/schemas.py so the showcase
dashboards can bind to them with zero remapping.

What this script produces under ``data/`` (run from the repo root):

    volcano_demo.tsv           — feature_id / effect_size / significance / label / category
    manhattan_demo.tsv         — chr / pos / score / feature / score_kind
    stacked_taxonomy_demo.tsv  — sample_id / taxon / rank / abundance (raw counts) / lineage
    embedding_pca.tsv          — sample_id / dim_1 / dim_2 / cluster / color
    embedding_umap.tsv         — same schema, UMAP coords
    embedding_tsne.tsv         — same schema, t-SNE coords
    embedding_pcoa.tsv         — same schema, PCoA on Bray-Curtis distances

The four embedding TSVs all come from the same 90×200 sample×feature
matrix; only the dim-reduction method differs. This is what makes the
"Clustering" tabs honest demonstrations of PCA / UMAP / t-SNE / PCoA
rather than four hand-crafted scatter plots.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import polars as pl

# Make `depictio.recipes.lib.dimreduction` importable when the script is run
# from the repo root (``python depictio/projects/.../generate_fixtures.py``).
# parents[5] is the worktree root: scripts → advanced_viz_showcase → init →
# projects → depictio → <repo root>.
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from depictio.recipes.lib.dimreduction import (  # noqa: E402 (sys.path tweak must precede)
    run_pca,
    run_pcoa,
    run_tsne,
    run_umap,
)

OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(exist_ok=True)

# Two seeded RNGs: ``R`` for stdlib randomness in the volcano / manhattan /
# taxonomy blocks (keeps git history of those TSVs stable across runs),
# ``NP_RNG`` for the feature-matrix synthesis used by the embedding methods.
R = random.Random(20260512)
NP_RNG = np.random.default_rng(20260512)


def write_tsv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join("" if v is None else str(v) for v in row) + "\n")
    print(f"wrote {path.name}: {len(rows)} rows")


# ---------------------------------------------------------------------------
# 1. Volcano: 200 differential features across 2 contrasts.
# columns: feature_id, effect_size, significance, label, category
# ---------------------------------------------------------------------------
GENES = [f"GENE{i:03d}" for i in range(200)]
CONTRASTS = ["treated_vs_control", "high_dose_vs_low_dose"]
PATHWAYS = [
    "Glycolysis",
    "Apoptosis",
    "Cell cycle",
    "DNA repair",
    "Inflammation",
    "Oxidative phosphorylation",
]

rows = []
for gene in GENES:
    for contrast in CONTRASTS:
        # ~15% of features are "hits": large |effect| + small p
        is_hit = R.random() < 0.15
        if is_hit:
            effect = R.gauss(0, 1) + (R.choice([-1, 1]) * R.uniform(2.0, 4.5))
            pval = 10 ** R.uniform(-10, -2)
        else:
            effect = R.gauss(0, 0.6)
            pval = 10 ** R.uniform(-2, 0)
        pathway = R.choice(PATHWAYS)
        # avg_log_intensity drives the MA plot's x-axis. Drawn ~U(2, 14) with
        # a faint correlation to |effect| (hits tend to be measured at
        # higher intensity in real RNA-seq). The MA dashboard binds to the
        # SAME volcano_demo DC and reads `avg_log_intensity` for x.
        intensity = R.uniform(2.0, 14.0) + min(2.0, abs(effect) * 0.3)
        rows.append(
            [
                gene,
                round(effect, 4),
                f"{pval:.6e}",
                gene,
                pathway,
                round(intensity, 3),
            ]
        )

write_tsv(
    OUT / "volcano_demo.tsv",
    ["feature_id", "effect_size", "significance", "label", "category", "avg_log_intensity"],
    rows,
)


# ---------------------------------------------------------------------------
# 2. Embedding: real PCA / UMAP / t-SNE / PCoA on a shared 90×80 feature
#    matrix with three well-separated Gaussian clusters. Each method writes
#    its own TSV so the four "Clustering" dashboard tabs show a different
#    projection of the SAME underlying data.
#
#    Signal/noise tuning:
#      - 80 features (was 200) → less noise dimensionality
#      - 20 SIGNAL features per cluster (out of 80) with mean +4.0
#      - σ=0.5 inside each cluster
#    With this configuration PCA explains >40% variance on the first two
#    components and UMAP/t-SNE find three crisp islands rather than blurred
#    clouds — the previous weaker signal (200 features, mean +2.0) drowned
#    the structure under noise.
#
# columns (each file): sample_id, dim_1, dim_2, cluster, color
# ---------------------------------------------------------------------------
N_FEATURES = 80
SAMPLES_PER_CLUSTER = 30
CLUSTER_NAMES = ["control", "treatment", "recovery"]
SIGNATURE_SIZE = 20
SIGNAL_STRENGTH = 4.0
NOISE_SIGMA = 0.5

# 1) Build the feature matrix.
sample_ids: list[str] = []
cluster_labels: list[str] = []
feature_rows: list[np.ndarray] = []

for cluster_idx, cluster_name in enumerate(CLUSTER_NAMES):
    signature = NP_RNG.choice(N_FEATURES, size=SIGNATURE_SIZE, replace=False)
    mean = np.zeros(N_FEATURES)
    mean[signature] = SIGNAL_STRENGTH
    for _ in range(SAMPLES_PER_CLUSTER):
        sample_ids.append(f"S{len(sample_ids):03d}")
        cluster_labels.append(cluster_name)
        feature_rows.append(NP_RNG.normal(loc=mean, scale=NOISE_SIGMA))

feature_matrix_np = np.stack(feature_rows)  # (90, N_FEATURES)

# Also write the raw sample×feature matrix as a TSV — this is the input
# the live Celery clustering uses (the dashboard's clustering tabs can
# point at this DC + a method, and the API recomputes PCA/UMAP/t-SNE/PCoA
# on demand via depictio/api/v1/celery_tasks.compute_embedding).
#
# Extra columns (cluster, color) ride along so the Embedding renderer's
# "Colour by" dropdown has something to pick in live mode — the task's
# `extra_cols` payload field threads them through unchanged. Numeric
# feature columns are auto-detected; string columns like `cluster` are
# skipped by the dim-reduction helpers.
feature_tsv_rows = []
for i, sid in enumerate(sample_ids):
    row = [sid, cluster_labels[i], round(5.0 + 0.6 * float(feature_matrix_np[i, 0]), 3)] + [
        round(float(feature_matrix_np[i, j]), 4) for j in range(N_FEATURES)
    ]
    feature_tsv_rows.append(row)
write_tsv(
    OUT / "embedding_features.tsv",
    ["sample_id", "cluster", "color"] + [f"feat_{j}" for j in range(N_FEATURES)],
    feature_tsv_rows,
)

# Pack as a polars wide DataFrame for the dim-reduction helpers.
feature_df = pl.DataFrame(
    {
        "sample_id": sample_ids,
        **{f"feat_{i}": feature_matrix_np[:, i].tolist() for i in range(N_FEATURES)},
    }
)

# 2) Run each method and emit a TSV.
# PCoA's Bray-Curtis distance is defined for non-negative vectors, so shift
# the matrix into the non-negative orthant before handing it to run_pcoa.
non_negative_df = feature_df.with_columns(
    [(pl.col(c) + 5.0).clip(lower_bound=0.0) for c in feature_df.columns if c != "sample_id"]
)

methods: list[tuple[str, callable, pl.DataFrame, dict]] = [
    # Emit a 3rd dim per method so the EmbeddingRenderer's View=3D toggle has
    # static data to plot (in addition to the live-compute path that fills
    # dim_3 dynamically when n_components flips to 3).
    ("pca", run_pca, feature_df, {"n_components": 3}),
    ("umap", run_umap, feature_df, {"n_components": 3}),
    ("tsne", run_tsne, feature_df, {"n_components": 3}),
    ("pcoa", run_pcoa, non_negative_df, {"n_components": 3}),
]

for method, runner, input_df, params in methods:
    coords = runner(input_df, **params)
    dim_1 = np.asarray(coords["dim_1"].to_list(), dtype=np.float64)
    dim_2 = np.asarray(coords["dim_2"].to_list(), dtype=np.float64)
    dim_3 = np.asarray(coords["dim_3"].to_list(), dtype=np.float64)
    # `color` = a quantitative variable correlated with dim_1 plus jitter, so
    # the embedding renderer's "colour by" shows a visible gradient.
    color = dim_1 + NP_RNG.normal(0.0, 0.3, size=len(dim_1))
    rows = []
    for sid, x, y, z, cluster, c in zip(
        coords["sample_id"].to_list(), dim_1, dim_2, dim_3, cluster_labels, color
    ):
        rows.append(
            [
                sid,
                round(float(x), 4),
                round(float(y), 4),
                round(float(z), 4),
                cluster,
                round(float(c), 3),
            ]
        )
    write_tsv(
        OUT / f"embedding_{method}.tsv",
        ["sample_id", "dim_1", "dim_2", "dim_3", "cluster", "color"],
        rows,
    )


# ---------------------------------------------------------------------------
# 3. Manhattan: ~1000 SNP-like rows across chr1..chr22 + chrX, with a few
#    real "peaks" spiking above the threshold line.
# columns: chr, pos, score, feature, score_kind
# ---------------------------------------------------------------------------
CHROMS = [f"chr{i}" for i in range(1, 23)] + ["chrX"]
# A few designed hits
HITS = {
    "chr1": [(115_000_000, "rs10001", 9.2)],
    "chr6": [(28_000_000, "rs60002", 12.6), (32_000_000, "rs60003", 8.4)],
    "chr11": [(7_500_000, "rs110001", 7.1)],
    "chr17": [(40_000_000, "rs170001", 10.3)],
    "chr19": [(45_500_000, "rs190001", 8.0)],
}

rows = []
# Counter used to mint synthetic rsIDs for the noise rows so every row has
# a feature label (a real SNP fixture would never have empty IDs — the
# previous fixture used empty strings for non-hits, which made the
# underlying-data table show blanks in the feature column for ~99% of rows).
# Real-world rsIDs are 1–9 digits; mix a few short and long IDs.
noise_rs_counter = 1_000_000  # start outside the curated HITS namespace
rs_used: set[str] = set()
for _, lst in HITS.items():
    for _pos, rsid, _score in lst:
        rs_used.add(rsid)

for chrom in CHROMS:
    # Approx 40 noise points per chromosome
    chrom_len = R.randint(45_000_000, 200_000_000)
    for _ in range(40):
        pos = R.randint(1_000_000, chrom_len)
        score = max(0.05, R.gauss(1.5, 0.7))
        # Bump until the rs is unused (cheap; collisions are rare).
        while True:
            rs = f"rs{noise_rs_counter}"
            noise_rs_counter += 1
            if rs not in rs_used:
                rs_used.add(rs)
                break
        rows.append([chrom, pos, round(score, 3), rs, "-log10(padj)"])
    # Plus designed hits
    for pos, rsid, score in HITS.get(chrom, []):
        rows.append([chrom, pos, score, rsid, "-log10(padj)"])


# Sort by chromosome then position for nicer file ordering
def _chrom_key(c: str) -> int:
    suffix = c.replace("chr", "")
    return 100 if suffix == "X" else int(suffix)


rows.sort(key=lambda r: (_chrom_key(r[0]), r[1]))

# Derived p_value column for the QQ plot — drives the QQ showcase tab
# without adding a second fixture. p_value = 10**-score is the inverse of
# the manhattan `score` (-log10(padj)).
for r in rows:
    score = float(r[2])
    p = max(1e-12, min(1.0, 10 ** (-score)))
    r.append(f"{p:.6e}")

write_tsv(
    OUT / "manhattan_demo.tsv",
    ["chr", "pos", "score", "feature", "score_kind", "p_value"],
    rows,
)


# ---------------------------------------------------------------------------
# 4. Stacked taxonomy: 18 samples × 9 taxa, two ranks (Phylum + Genus).
#    abundance is INTEGER raw read counts now (per-sample totals in
#    5,000–50,000 range) — the previous fixture was already per-sample
#    normalised, which made the renderer's "normalise to one" toggle look
#    like a no-op. With raw counts the toggle now has a visible effect: OFF
#    shows raw counts; ON locks the y-axis to [0, 1] and stacks to fractions.
# columns: sample_id, taxon, rank, abundance, lineage
# ---------------------------------------------------------------------------
SAMPLES = [f"sample_{c}_{n}" for c in ("gut", "skin", "soil") for n in range(1, 7)]
PHYLA = ["Firmicutes", "Bacteroidetes", "Proteobacteria", "Actinobacteria", "Verrucomicrobia"]
GENERA = {
    "Firmicutes": ["Lactobacillus", "Faecalibacterium", "Clostridium"],
    "Bacteroidetes": ["Bacteroides", "Prevotella"],
    "Proteobacteria": ["Escherichia"],
    "Actinobacteria": ["Bifidobacterium"],
    "Verrucomicrobia": ["Akkermansia"],
}


def _allocate_counts(total: int, weights: dict[str, float]) -> dict[str, int]:
    """Split ``total`` across keys proportionally to ``weights``.

    Returns integer counts that sum to ``total`` (rounding remainder goes to
    the largest-weight key so totals are exact).
    """
    wsum = sum(weights.values()) or 1.0
    raw = {k: total * w / wsum for k, w in weights.items()}
    out = {k: int(round(v)) for k, v in raw.items()}
    drift = total - sum(out.values())
    if drift != 0:
        # Add the drift to the key with the largest fractional component.
        adjust_key = max(raw, key=lambda k: raw[k] - int(raw[k]))
        out[adjust_key] += drift
    return out


# Pre-built kingdom mapping so each rank row carries its full ancestry
# split into separate columns — drives the sunburst hierarchical viz.
KINGDOM = "Bacteria"

rows = []
for s in SAMPLES:
    # Per-sample total in 5k–50k range so the OFF state of the normalise
    # toggle shows realistic raw-count y-axis values.
    sample_total = R.randint(5_000, 50_000)

    # Phylum-level: allocate counts directly.
    phylum_weights = {p: max(0.01, R.gauss(1.0, 0.6)) for p in PHYLA}
    phylum_counts = _allocate_counts(sample_total, phylum_weights)
    for p, count in phylum_counts.items():
        # Phylum rows: leaf-level columns (Class/Order/Family/Genus) blank.
        rows.append([s, p, "Phylum", count, p, KINGDOM, p, "", "", "", ""])

    # Genus-level: within each phylum, distribute the phylum's counts across
    # its genera so the Phylum and Genus rows agree on per-sample totals.
    for p in PHYLA:
        if not GENERA[p]:
            continue
        genus_weights = {g: max(0.01, R.gauss(1.0, 0.5)) for g in GENERA[p]}
        genus_counts = _allocate_counts(phylum_counts[p], genus_weights)
        for g, count in genus_counts.items():
            rows.append(
                [
                    s,
                    g,
                    "Genus",
                    count,
                    f"{p};{g}",
                    KINGDOM,
                    p,
                    f"{p}_class",
                    f"{p}_order",
                    f"{p}_family",
                    g,
                ]
            )

write_tsv(
    OUT / "stacked_taxonomy_demo.tsv",
    [
        "sample_id",
        "taxon",
        "rank",
        "abundance",
        "lineage",
        "Kingdom",
        "Phylum",
        "Class",
        "Order",
        "Family",
        "Genus",
    ],
    rows,
)


# ---------------------------------------------------------------------------
# 5. Rarefaction: alpha-diversity (faith_pd, observed_features, shannon) over
#    12 sequencing depths, 10 iterations per (sample, depth). Same 18 samples
#    as the taxonomy fixture for visual continuity. Mirrors the QIIME2
#    alpha-rarefaction output (faith_pd / observed_features / shannon are the
#    three standard metrics emitted by `qiime diversity alpha-rarefaction`).
# columns: sample_id, depth, iter, faith_pd, observed_features, shannon, habitat
# ---------------------------------------------------------------------------
HABITAT_BY_SAMPLE = {s: s.split("_")[1] for s in SAMPLES}  # gut / skin / soil
DEPTHS = [500, 1000, 2000, 4000, 6000, 8000, 12000, 16000, 22000, 30000, 40000, 50000]
ITERS = list(range(10))

# Per-sample asymptote + saturation rate so curves look biologically plausible
# — gut samples saturate at higher diversity than skin / soil.
ASYMPTOTE = {"gut": 28.0, "skin": 14.0, "soil": 20.0}
SATURATION = {"gut": 6000.0, "skin": 3500.0, "soil": 5000.0}

rows = []
for s in SAMPLES:
    hab = HABITAT_BY_SAMPLE[s]
    asym = ASYMPTOTE[hab] * R.uniform(0.85, 1.15)
    sat = SATURATION[hab] * R.uniform(0.85, 1.15)
    for d in DEPTHS:
        # Asymptotic curve: y = asym * (1 - exp(-d / sat)) + noise.
        # Using `math` for exp keeps the script's only ML dep (numpy) for the
        # embedding block.
        import math as _math

        expected = asym * (1.0 - _math.exp(-d / sat))
        # observed_features rises faster than faith_pd typically; scale.
        feat_factor = 8.0
        # shannon is bounded log2(n_features); saturates to ~log2(asym * feat_factor).
        shannon_max = _math.log2(max(2.0, asym * feat_factor))
        shannon_expected = shannon_max * (1.0 - _math.exp(-d / (sat * 0.7)))
        for it in ITERS:
            faith = max(0.0, expected + R.gauss(0, 0.4))
            obs = max(0.0, expected * feat_factor + R.gauss(0, 4.0))
            shannon = max(0.0, shannon_expected + R.gauss(0, 0.08))
            rows.append([s, d, it, round(faith, 3), round(obs, 1), round(shannon, 3), hab])

write_tsv(
    OUT / "rarefaction_demo.tsv",
    ["sample_id", "depth", "iter", "faith_pd", "observed_features", "shannon", "habitat"],
    rows,
)


# ---------------------------------------------------------------------------
# 6. ANCOM-BC differentials: 200 taxa across 3 contrasts. Drives the merged
#    DaBarplotRenderer in both its faceted ('All' tab) and single-contrast
#    (per-contrast tab) layouts.
# columns: feature_id, contrast, lfc, significance, label, neg_log10_q
# ---------------------------------------------------------------------------
TAXA = [f"OTU{i:04d}" for i in range(200)]
CONTRASTS_BC = ["gut_vs_skin", "gut_vs_soil", "skin_vs_soil"]
PHYLA = ["Firmicutes", "Bacteroidetes", "Proteobacteria", "Actinobacteria", "Verrucomicrobia"]

rows = []
for taxon in TAXA:
    phylum = R.choice(PHYLA)
    for contrast in CONTRASTS_BC:
        is_hit = R.random() < 0.18
        if is_hit:
            lfc = R.gauss(0, 0.5) + (R.choice([-1, 1]) * R.uniform(1.5, 4.0))
            sig = 10 ** R.uniform(-8, -2)
        else:
            lfc = R.gauss(0, 0.6)
            sig = 10 ** R.uniform(-2, 0)
        import math as _math

        rows.append(
            [
                taxon,
                contrast,
                round(lfc, 3),
                f"{sig:.6e}",
                f"{phylum};{taxon}",
                round(-_math.log10(max(sig, 1e-300)), 3),
            ]
        )

write_tsv(
    OUT / "ancombc_demo.tsv",
    ["feature_id", "contrast", "lfc", "significance", "label", "neg_log10_q"],
    rows,
)


# ---------------------------------------------------------------------------
# 7. GSEA / GO / pathway enrichment dot plot.
# columns: term, source, nes, padj, gene_count, leading_edge
# ---------------------------------------------------------------------------
SOURCES_GSEA = ["GO_BP", "GO_CC", "KEGG", "Reactome", "Hallmark"]
PATHWAY_NOUNS = [
    "Glycolysis",
    "Apoptosis",
    "Cell cycle",
    "DNA repair",
    "Inflammation",
    "Oxidative phosphorylation",
    "Lipid metabolism",
    "Protein folding",
    "Translation",
    "Innate immunity",
    "T-cell receptor signaling",
    "ER stress response",
    "Hypoxia response",
    "Wnt signaling",
    "Notch signaling",
    "MAPK cascade",
    "TGF-β signaling",
    "Autophagy",
    "Mitochondrial biogenesis",
    "Ribosome biogenesis",
    "Spliceosome",
    "Extracellular matrix",
    "Chemokine signaling",
    "Cytokine signaling",
]

rows = []
pathway_id = 0
for src in SOURCES_GSEA:
    # 12–18 pathways per source for variety.
    for _ in range(R.randint(12, 18)):
        noun = R.choice(PATHWAY_NOUNS)
        term = f"{src}: {noun} ({pathway_id})"
        pathway_id += 1
        is_hit = R.random() < 0.55
        if is_hit:
            nes = R.choice([-1, 1]) * R.uniform(1.4, 3.2)
            padj = 10 ** R.uniform(-12, -2)
        else:
            nes = R.gauss(0, 0.6)
            padj = 10 ** R.uniform(-2, 0)
        gene_count = R.randint(15, 220)
        leading_edge = ",".join(f"GENE{R.randint(0, 199):03d}" for _ in range(R.randint(3, 8)))
        rows.append([term, src, round(nes, 3), f"{padj:.6e}", gene_count, leading_edge])

write_tsv(
    OUT / "gsea_demo.tsv",
    ["term", "source", "nes", "padj", "gene_count", "leading_edge"],
    rows,
)


# ---------------------------------------------------------------------------
# 8. UpSet plot input: 400 features × membership in 5 differential-expression
#    contrasts. Binary 0/1 columns — the plotly-upset task auto-detects them.
#    Some features participate in multiple contrasts (overlapping sets), some
#    are exclusive — exactly the kind of pattern UpSet visualises well.
# columns: feature_id, feature_group, contrastA, contrastB, contrastC,
#          contrastD, contrastE
# ---------------------------------------------------------------------------
UPSET_SETS = ["contrastA", "contrastB", "contrastC", "contrastD", "contrastE"]
# Per-set probability a feature belongs to it (asymmetric → diverse overlaps).
SET_PROB = {
    "contrastA": 0.30,
    "contrastB": 0.25,
    "contrastC": 0.18,
    "contrastD": 0.12,
    "contrastE": 0.08,
}
# Categorical bucket used by the dashboard's MultiSelect filter so the user can
# pre-filter the UpSet to a biologically interpretable feature subset before
# intersections are computed. Deterministic by index → seed JSONs reference
# stable values across regenerations.
UPSET_GROUPS = [
    "transcription_factor",
    "kinase",
    "metabolic",
    "signalling",
    "structural",
]

rows = []
for i in range(400):
    feat = f"FEAT{i:04d}"
    group = UPSET_GROUPS[i % len(UPSET_GROUPS)]
    memberships = [1 if R.random() < SET_PROB[s] else 0 for s in UPSET_SETS]
    # Guarantee a few "all five" features so the highest-degree intersection
    # is visible — otherwise random sampling rarely produces them.
    if i < 5:
        memberships = [1, 1, 1, 1, 1]
    rows.append([feat, group] + memberships)

write_tsv(
    OUT / "upset_demo.tsv",
    ["feature_id", "feature_group"] + UPSET_SETS,
    rows,
)


# ---------------------------------------------------------------------------
# 9. Single-cell marker dot plot: 6 clusters × 25 marker genes. Each row is
#    one (cluster, gene) cell with mean_expression (continuous → colour) and
#    frac_expressing (0–1 → marker size).
# columns: cluster, gene, mean_expression, frac_expressing
# ---------------------------------------------------------------------------
DOTPLOT_CLUSTERS = ["T_cell", "B_cell", "Monocyte", "NK", "Dendritic", "Plasma"]
DOTPLOT_GENES = [
    "CD3D",
    "CD4",
    "CD8A",
    "FOXP3",
    "IL7R",
    "CD19",
    "CD20",
    "MS4A1",
    "BANK1",
    "CD14",
    "LYZ",
    "CSF1R",
    "FCGR1A",
    "NKG7",
    "GNLY",
    "KLRD1",
    "CD1C",
    "CLEC10A",
    "HLA-DRA",
    "MZB1",
    "JCHAIN",
    "XBP1",
    "GAPDH",
    "ACTB",
    "RPL13",
]

# Per-cluster marker profile: genes 0-4 mark T_cell, 5-8 mark B_cell, etc.
# The last three are housekeeping (broadly expressed in all clusters).
CLUSTER_MARKER_RANGES = {
    "T_cell": (0, 5),
    "B_cell": (5, 9),
    "Monocyte": (9, 13),
    "NK": (13, 16),
    "Dendritic": (16, 19),
    "Plasma": (19, 22),
}

rows = []
for cluster in DOTPLOT_CLUSTERS:
    lo, hi = CLUSTER_MARKER_RANGES[cluster]
    for gi, gene in enumerate(DOTPLOT_GENES):
        if gi >= 22:  # housekeeping
            mean_expr = R.uniform(3.5, 4.5)
            frac = R.uniform(0.85, 0.99)
        elif lo <= gi < hi:  # marker for this cluster
            mean_expr = R.uniform(2.5, 4.5)
            frac = R.uniform(0.55, 0.95)
        else:  # off-target
            mean_expr = R.uniform(0.0, 1.0)
            frac = R.uniform(0.02, 0.20)
        rows.append([cluster, gene, round(mean_expr, 3), round(frac, 3)])

write_tsv(
    OUT / "dotplot_demo.tsv",
    ["cluster", "gene", "mean_expression", "frac_expressing"],
    rows,
)


# ---------------------------------------------------------------------------
# 10. Lollipop / needle plot fixture: 4 genes × ~60 variants × 5 consequence
#     categories. Position is bounded per-gene so the plot looks realistic.
# columns: feature_id, position, category, effect
# ---------------------------------------------------------------------------
LOLLIPOP_GENES = {
    "TP53": 2_500,
    "BRCA1": 5_500,
    "EGFR": 1_300,
    "KRAS": 800,
}
CONSEQUENCES = [
    "missense_variant",
    "synonymous_variant",
    "stop_gained",
    "frameshift_variant",
    "splice_region_variant",
]
CONS_WEIGHTS = [0.45, 0.25, 0.10, 0.12, 0.08]

rows = []
for gene, gene_len in LOLLIPOP_GENES.items():
    n_variants = R.randint(50, 80)
    for _ in range(n_variants):
        pos = R.randint(1, gene_len)
        cat = R.choices(CONSEQUENCES, weights=CONS_WEIGHTS)[0]
        # Variant effect strength — drives marker size when bound.
        effect = round(abs(R.gauss(1.0, 0.6)) + 0.1, 3)
        rows.append([gene, pos, cat, effect])

write_tsv(
    OUT / "lollipop_demo.tsv",
    ["feature_id", "position", "category", "effect"],
    rows,
)


# ---------------------------------------------------------------------------
# 11. Oncoplot fixture: 40 samples × 30 genes × 5 mutation types, sparse
#     (most cells empty — typical of cancer cohorts). Long-format: one row
#     per observed (sample, gene, mutation_type) triple.
# columns: sample_id, gene, mutation_type
# ---------------------------------------------------------------------------
ONCO_SAMPLES = [f"TCGA-{i:03d}" for i in range(40)]
ONCO_GENES = [
    "TP53",
    "KRAS",
    "PIK3CA",
    "BRAF",
    "EGFR",
    "APC",
    "PTEN",
    "BRCA1",
    "BRCA2",
    "ATM",
    "CDKN2A",
    "RB1",
    "NRAS",
    "STK11",
    "KEAP1",
    "ARID1A",
    "SMAD4",
    "CTNNB1",
    "MLL3",
    "FBXW7",
    "NF1",
    "VHL",
    "GNAS",
    "AKT1",
    "MYC",
    "ERBB2",
    "MET",
    "ALK",
    "ROS1",
    "RET",
]
MUTATION_TYPES = [
    "Missense_Mutation",
    "Nonsense_Mutation",
    "Frame_Shift_Del",
    "Frame_Shift_Ins",
    "In_Frame_Del",
]
MUT_WEIGHTS = [0.55, 0.15, 0.12, 0.10, 0.08]
# Per-gene mutation frequency: top genes hit in ~30% of samples, tail in <5%.
GENE_FREQ = {
    g: max(0.03, 0.30 * (0.85**i) + R.uniform(-0.02, 0.02)) for i, g in enumerate(ONCO_GENES)
}

rows = []
for sample in ONCO_SAMPLES:
    for gene in ONCO_GENES:
        if R.random() < GENE_FREQ[gene]:
            mut_type = R.choices(MUTATION_TYPES, weights=MUT_WEIGHTS)[0]
            rows.append([sample, gene, mut_type])

write_tsv(
    OUT / "oncoplot_demo.tsv",
    ["sample_id", "gene", "mutation_type"],
    rows,
)


# ---------------------------------------------------------------------------
# 12. Coverage track: SARS-CoV-2 read depth per 200bp bin × multiple samples.
#     Sourced from a viralrecon-bowtie2-mosdepth run when present on disk
#     (the user's local copy lives under ~/Data/viralrecon/...); otherwise
#     synthesised so CI without that file still produces a working fixture.
#     The renderer faceted-by-sample uses `sample`; coloured-by-category uses
#     the derived `gene_region` annotation lane (SARS-CoV-2 gene map).
# columns: chrom, start, end, position, coverage, sample, gene_region
# ---------------------------------------------------------------------------
COVERAGE_MOSDEPTH_TSV = Path(
    "/Users/tweber/Data/viralrecon/viralrecon-testdata/run_1/"
    "variants/bowtie2/mosdepth/genome/all_samples.mosdepth.coverage.tsv"
)

# SARS-CoV-2 (MN908947.3) gene map. Closed intervals matching NCBI annotation;
# bins whose centre falls outside any feature get labelled "intergenic".
SARSCOV2_GENES: list[tuple[str, int, int]] = [
    ("5'UTR", 1, 265),
    ("ORF1ab", 266, 21555),
    ("S", 21563, 25384),
    ("ORF3a", 25393, 26220),
    ("E", 26245, 26472),
    ("M", 26523, 27191),
    ("ORF6", 27202, 27387),
    ("ORF7a", 27394, 27759),
    ("ORF7b", 27756, 27887),
    ("ORF8", 27894, 28259),
    ("N", 28274, 29533),
    ("ORF10", 29558, 29674),
    ("3'UTR", 29675, 29903),
]


def _gene_region_for(pos: int) -> str:
    for name, lo, hi in SARSCOV2_GENES:
        if lo <= pos <= hi:
            return name
    return "intergenic"


def generate_coverage_track_demo() -> None:
    """Write coverage_track_demo.tsv from real mosdepth output if available.

    Falls back to a synthesised 6-sample × 30 kb track with a few designed
    coverage dips (so the renderer's smoothing / color toggles have visible
    effects in CI / fresh clones without the upstream data).
    """
    header = ["chrom", "start", "end", "position", "coverage", "sample", "gene_region"]
    rows: list[list] = []
    if COVERAGE_MOSDEPTH_TSV.exists():
        with COVERAGE_MOSDEPTH_TSV.open() as f:
            head = f.readline().strip().split("\t")
            idx = {c: head.index(c) for c in ("chrom", "start", "end", "coverage", "sample")}
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                start = int(parts[idx["start"]])
                end = int(parts[idx["end"]])
                pos = (start + end) // 2
                rows.append(
                    [
                        parts[idx["chrom"]],
                        start,
                        end,
                        pos,
                        round(float(parts[idx["coverage"]]), 3),
                        parts[idx["sample"]],
                        _gene_region_for(pos),
                    ]
                )
        write_tsv(OUT / "coverage_track_demo.tsv", header, rows)
        return

    # Synthesised fallback: 6 samples × 30 kb / 200 bp = ~150 bins/sample.
    fallback_samples = [f"SAMPLE_{i:02d}" for i in range(1, 7)]
    fallback_chrom = "MN908947.3"
    bin_size = 200
    genome_len = 29903
    for sample in fallback_samples:
        # Per-sample base depth and a couple of designed dips to make the
        # smoothing / threshold toggles visible.
        base_depth = R.uniform(800.0, 4500.0)
        dip_centres = [R.randint(2000, 28000) for _ in range(R.randint(1, 3))]
        for start in range(0, genome_len, bin_size):
            end = min(start + bin_size, genome_len)
            pos = (start + end) // 2
            depth = base_depth * R.gauss(1.0, 0.18)
            for dc in dip_centres:
                if abs(pos - dc) < 800:
                    depth *= max(0.05, abs(pos - dc) / 800.0)
            depth = max(0.0, depth)
            rows.append(
                [
                    fallback_chrom,
                    start,
                    end,
                    pos,
                    round(depth, 3),
                    sample,
                    _gene_region_for(pos),
                ]
            )
    write_tsv(OUT / "coverage_track_demo.tsv", header, rows)


generate_coverage_track_demo()


# ---------------------------------------------------------------------------
# 13. Categorical flow / Sankey: per-sample lineage classification across
#     three ordered categorical levels (qc_status → lineage → clade), pulled
#     from a viralrecon-multiqc pangolin + nextclade output if available.
#     Synthesises a realistic SARS-CoV-2-flavoured table otherwise.
# columns: sample_id, qc_status, lineage, clade
# ---------------------------------------------------------------------------
PANGOLIN_YAML = Path(
    "/Users/tweber/Data/viralrecon/viralrecon-testdata/run_1/"
    "multiqc/multiqc_data/multiqc_pangolin.yaml"
)
NEXTCLADE_YAML = Path(
    "/Users/tweber/Data/viralrecon/viralrecon-testdata/run_1/"
    "multiqc/multiqc_data/multiqc_nextclade_clade.yaml"
)


def _parse_pangolin_yaml(path: Path) -> dict[str, dict[str, str]]:
    """Tiny dependency-free parser for multiqc_pangolin.yaml's two-level form.

    File shape:
        SAMPLE_01:
          lineage: B.1.1.7
          qc_status: pass
          ...

    Returns {sample_id: {key: value}} with string values only.
    """
    out: dict[str, dict[str, str]] = {}
    current: str | None = None
    with path.open() as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith(" "):
                # Top-level key (sample id) — strip trailing colon.
                current = line.rstrip(":").strip()
                out[current] = {}
            else:
                if current is None:
                    continue
                stripped = line.strip()
                if ":" not in stripped:
                    continue
                key, _, value = stripped.partition(":")
                value = value.strip().strip("'\"")
                out[current][key.strip()] = value
    return out


def generate_categorical_flow_demo() -> None:
    header = ["sample_id", "qc_status", "lineage", "clade"]
    rows: list[list] = []
    if PANGOLIN_YAML.exists() and NEXTCLADE_YAML.exists():
        pangolin = _parse_pangolin_yaml(PANGOLIN_YAML)
        nextclade = _parse_pangolin_yaml(NEXTCLADE_YAML)
        for sample, fields in sorted(pangolin.items()):
            qc = (fields.get("qc_status") or "unknown").lower()
            lineage = fields.get("lineage") or "Unassigned"
            clade = (nextclade.get(sample) or {}).get("clade") or "unknown"
            rows.append([sample, qc, lineage, clade])
        write_tsv(OUT / "categorical_flow_demo.tsv", header, rows)
        return

    # Synthesised fallback: 60 samples drawn from a realistic SARS-CoV-2
    # qc/lineage/clade joint distribution so the Sankey demo still looks
    # meaningful without the upstream YAMLs.
    LINEAGE_BY_CLADE = {
        "20A": ["B.1", "B.1.1"],
        "20B": ["B.1.1.7", "B.1.1"],
        "20I": ["B.1.1.7"],
        "21J": ["B.1.617.2", "AY.4"],
        "21K": ["BA.1", "BA.1.1"],
        "21L": ["BA.2", "BA.2.12.1"],
        "22B": ["BA.5", "BA.5.2"],
    }
    CLADES = list(LINEAGE_BY_CLADE)
    for i in range(60):
        sample = f"SAMPLE_{i + 1:02d}"
        clade = R.choice(CLADES)
        # ~10% fail QC overall; failures often skew to Unassigned lineage.
        qc = "fail" if R.random() < 0.10 else "pass"
        lineage = (
            "Unassigned" if qc == "fail" and R.random() < 0.5 else R.choice(LINEAGE_BY_CLADE[clade])
        )
        rows.append([sample, qc, lineage, clade])
    write_tsv(OUT / "categorical_flow_demo.tsv", header, rows)


generate_categorical_flow_demo()


# 14. Signal profile: TSS enrichment, the canonical use of the `profile` kind.
#     One curve per ATAC library over distance to the transcription start site,
#     with a bootstrap confidence ribbon. Two of the eight libraries are
#     deliberately flat — a low TSS enrichment score is *the* ATAC-seq QC
#     failure, and a demo where every curve passes shows nothing.
# columns: series, x, y, lower, upper
# ---------------------------------------------------------------------------
PROFILE_X_MIN = -2000
PROFILE_X_MAX = 2000
PROFILE_X_STEP = 25

# (series, is_good). One failing library per condition, so the flat curves read
# as a per-library problem rather than a treatment effect.
PROFILE_LIBRARIES = [
    ("CTRL_rep1", True),
    ("CTRL_rep2", True),
    ("CTRL_rep3", True),
    ("CTRL_rep4", False),
    ("TREAT_rep1", True),
    ("TREAT_rep2", True),
    ("TREAT_rep3", False),
    ("TREAT_rep4", True),
]


def generate_profile_demo() -> None:
    """Write profile_demo.tsv: 8 TSS enrichment curves with confidence ribbons.

    The curve is the usual sum of three components on a background of 1.0
    (enrichment is a ratio to the flanking signal, so 1.0 is "no enrichment"):
    a sharp core at the TSS, a broad promoter shoulder, and the +1 / -1
    nucleosome bumps that a well-fragmented library resolves at roughly
    ±190 bp. Failing libraries get the same components with a core three times
    as wide and a fraction of the amplitude, which is what under-digested or
    high-background ATAC actually looks like.
    """
    header = ["series", "x", "y", "lower", "upper"]
    rows: list[list] = []
    xs = np.arange(PROFILE_X_MIN, PROFILE_X_MAX + 1, PROFILE_X_STEP, dtype=float)

    for series, is_good in PROFILE_LIBRARIES:
        if is_good:
            peak = R.uniform(9.5, 14.5)  # TSS enrichment score
            core_sd = R.uniform(100.0, 130.0)
            nucleosome = R.uniform(0.14, 0.22)
            depth = R.uniform(0.90, 1.20)  # usable-read factor -> ribbon width
        else:
            peak = R.uniform(2.2, 3.1)
            core_sd = R.uniform(290.0, 360.0)
            nucleosome = R.uniform(0.02, 0.05)
            depth = R.uniform(0.35, 0.50)

        core = np.exp(-0.5 * (xs / core_sd) ** 2)
        broad = 0.30 * np.exp(-0.5 * (xs / 650.0) ** 2)
        nuc = nucleosome * (
            np.exp(-0.5 * ((xs - 190.0) / 80.0) ** 2)
            + 0.78 * np.exp(-0.5 * ((xs + 190.0) / 80.0) ** 2)
            + 0.48 * np.exp(-0.5 * ((xs - 380.0) / 95.0) ** 2)
            + 0.36 * np.exp(-0.5 * ((xs + 380.0) / 95.0) ** 2)
        )
        shape = core + broad + nuc
        # Normalise on the value at x=0 so `peak` really is the enrichment the
        # curve reaches at the TSS, whatever the shoulder terms contribute.
        amp = (peak - 1.0) / float(shape[len(shape) // 2])
        smooth = 1.0 + amp * shape

        # Bootstrap standard error: grows with the signal and shrinks with
        # depth, so the two failing libraries carry visibly fatter ribbons.
        se = (0.06 / depth) * smooth**0.75 + 0.02 / depth
        noisy = smooth + NP_RNG.normal(0.0, 0.55, size=xs.size) * se
        noisy = np.maximum(noisy, 0.05)
        lower = np.maximum(noisy - 1.96 * se, 0.0)
        upper = noisy + 1.96 * se

        for x, y, lo, hi in zip(xs, noisy, lower, upper):
            rows.append(
                [series, int(x), round(float(y), 4), round(float(lo), 4), round(float(hi), 4)]
            )

    write_tsv(OUT / "profile_demo.tsv", header, rows)


generate_profile_demo()


# NN. Signal matrix: an ATAC-seq signal matrix around peak summits — the
#     canonical deepTools `computeMatrix reference-point` output, in the long
#     form the renderer reads (one row per region × offset, not one column
#     per bin).
# columns: region_id, position, value, group
# ---------------------------------------------------------------------------
# Offsets from the summit, in the 50 bp bins a real matrix is computed in.
SIGNAL_MATRIX_FLANK = 1000
SIGNAL_MATRIX_BIN = 50

# The three classes the demo is built to separate, and how many peaks each
# gets. The shapes matter more than the counts: a promoter-like peak is a
# narrow spike with nucleosome shoulders either side, an enhancer-like peak is
# a broad low mound, and the background class is essentially flat. Sorting by
# total signal inside each panel is then what produces the banding.
SIGNAL_MATRIX_CLASSES = [
    ("promoter", 110),
    ("enhancer", 120),
    ("background", 70),
]


def _signal_matrix_profile(group: str, offsets: np.ndarray) -> np.ndarray:
    """One region's mean signal at every offset, before noise.

    Returns a vector the same length as ``offsets``; the caller adds the
    per-bin noise so the drawn matrix is grainy rather than analytic.
    """
    if group == "promoter":
        # Sharp summit (sigma 90-160 bp, so 4-6 of the 50 bp bins carry it)
        # plus the +1/-1 nucleosome shoulders at ~190 bp that give an ATAC
        # promoter its three-band look.
        amplitude = float(np.exp(NP_RNG.normal(2.3, 0.45)))
        width = float(NP_RNG.uniform(90.0, 160.0))
        shoulder = amplitude * float(NP_RNG.uniform(0.12, 0.28))
        curve = amplitude * np.exp(-0.5 * (offsets / width) ** 2)
        for centre in (-190.0, 190.0):
            curve = curve + shoulder * np.exp(-0.5 * ((offsets - centre) / 95.0) ** 2)
        return curve
    if group == "enhancer":
        # Broad mound (sigma 320-520 bp), lower and slightly off-centre: an
        # enhancer summit is called less precisely than a TSS.
        amplitude = float(np.exp(NP_RNG.normal(1.3, 0.5)))
        width = float(NP_RNG.uniform(320.0, 520.0))
        shift = float(NP_RNG.normal(0.0, 90.0))
        return amplitude * np.exp(-0.5 * ((offsets - shift) / width) ** 2)
    # Background: a very wide, very low bump — visually flat, which is the
    # point. It is what the colour scale's low end has to stay useful for.
    amplitude = float(NP_RNG.uniform(0.2, 1.0))
    width = float(NP_RNG.uniform(700.0, 1200.0))
    return amplitude * np.exp(-0.5 * (offsets / width) ** 2)


def generate_signal_matrix_demo() -> None:
    header = ["region_id", "position", "value", "group"]
    offsets = np.arange(-SIGNAL_MATRIX_FLANK, SIGNAL_MATRIX_FLANK + 1, SIGNAL_MATRIX_BIN)

    # Peaks are numbered along the genome and classified afterwards, so the
    # class does not correlate with the id — the panels have to come from the
    # `group` column rather than from a lucky row order.
    labels = [group for group, count in SIGNAL_MATRIX_CLASSES for _ in range(count)]
    order = NP_RNG.permutation(len(labels))
    groups = [labels[i] for i in order]

    rows: list[list] = []
    for i, group in enumerate(groups, start=1):
        region_id = f"PEAK_{i:04d}"
        # Baseline open chromatin plus Poisson-flavoured per-bin noise: the
        # spread grows with the signal, so the spike bins are the grainy ones.
        curve = _signal_matrix_profile(group, offsets) + 0.25
        noise = NP_RNG.normal(0.0, 1.0, size=offsets.size) * (0.12 + 0.18 * np.sqrt(curve))
        values = np.clip(curve + noise, 0.0, None)
        for position, value in zip(offsets, values):
            rows.append([region_id, int(position), round(float(value), 3), group])

    write_tsv(OUT / "signal_matrix_demo.tsv", header, rows)


generate_signal_matrix_demo()


# NN. Fusion structure: six well-known oncogenic gene fusions with their real
# protein-domain composition.
# columns: fusion_id, partner, feature, start, end, breakpoint, retained,
#          domain_class
# ---------------------------------------------------------------------------
# Curated rather than sampled: the point of this fixture is that a life
# scientist recognises the fusions and the domains, so there is nothing here
# for ``R`` to randomise. Each entry is
# ``(fusion_id, [(5' partner, [(domain, retained, class), ...]),
#                (3' partner, [...])])``, listed 5' partner first and, within a
# partner, N- to C-terminus.
#
# ``retained`` is the fraction of the domain that survives the fusion, in
# [0, 1]: 1.0 for a domain the breakpoint leaves whole, 0.0 for one the
# breakpoint removes entirely (the renderer still draws its outline, so the
# picture shows what was lost as well as what was kept), and a fraction for a
# domain the breakpoint cuts through.
FUSION_STRUCTURES: list[tuple[str, list[tuple[str, list[tuple[str, float, str]]]]]] = [
    # CML / Ph+ ALL. p210 breaks in the major breakpoint cluster region, so BCR
    # keeps its oligomerisation coiled coil (which is what dimerises and thereby
    # activates the ABL1 kinase) and loses the C2 / RacGAP end.
    (
        "BCR--ABL1",
        [
            (
                "BCR",
                [
                    ("Coiled-coil oligomerisation", 1.0, "Oligomerisation"),
                    ("Ser/Thr kinase", 1.0, "Kinase"),
                    ("RhoGEF (DH)", 1.0, "Signalling"),
                    ("PH", 1.0, "Signalling"),
                    ("C2 (CalB)", 0.0, "Signalling"),
                    ("Rac GTPase-activating", 0.0, "Signalling"),
                ],
            ),
            (
                "ABL1",
                [
                    ("N-terminal cap (myristoyl)", 0.0, "Regulatory"),
                    ("SH3", 1.0, "Adaptor"),
                    ("SH2", 1.0, "Adaptor"),
                    ("Protein tyrosine kinase", 1.0, "Kinase"),
                    ("F-actin binding", 1.0, "Cytoskeletal"),
                ],
            ),
        ],
    ),
    # NSCLC, variant 1 (EML4 exon 13 :: ALK exon 20). The breakpoint cuts the
    # HELP domain and shears off most of the WD40 propeller.
    (
        "EML4--ALK",
        [
            (
                "EML4",
                [
                    ("Coiled-coil trimerisation", 1.0, "Oligomerisation"),
                    ("Basic region", 1.0, "Regulatory"),
                    ("HELP", 0.62, "Cytoskeletal"),
                    ("WD40 repeats", 0.18, "Adaptor"),
                ],
            ),
            (
                "ALK",
                [
                    ("MAM", 0.0, "Receptor ectodomain"),
                    ("Glycine-rich region", 0.0, "Receptor ectodomain"),
                    ("Protein tyrosine kinase", 1.0, "Kinase"),
                ],
            ),
        ],
    ),
    # Prostate cancer, T1/E4. TMPRSS2 contributes its androgen-responsive first
    # exon and no protein at all: every one of its domains is lost, which is why
    # its lane is drawn as three empty outlines.
    (
        "TMPRSS2--ERG",
        [
            (
                "TMPRSS2",
                [
                    ("LDL-receptor class A", 0.0, "Receptor ectodomain"),
                    ("SRCR", 0.0, "Receptor ectodomain"),
                    ("Peptidase S1", 0.0, "Peptidase"),
                ],
            ),
            (
                "ERG",
                [
                    ("PNT (SAM/Pointed)", 0.55, "Oligomerisation"),
                    ("ETS DNA-binding", 1.0, "DNA binding"),
                    ("C-terminal transactivation", 1.0, "Transactivation"),
                ],
            ),
        ],
    ),
    # Ewing sarcoma, type 1 (EWSR1 exon 7 :: FLI1 exon 6). EWSR1 donates its
    # SYGQ-rich transactivation domain to the FLI1 DNA-binding domain; the
    # EWSR1 RNA-binding end and the FLI1 PNT domain are both left behind.
    (
        "EWSR1--FLI1",
        [
            (
                "EWSR1",
                [
                    ("SYGQ-rich transactivation", 1.0, "Transactivation"),
                    ("IQ motif", 0.42, "Regulatory"),
                    ("RRM", 0.0, "RNA binding"),
                    ("RanBP2-type zinc finger", 0.0, "RNA binding"),
                ],
            ),
            (
                "FLI1",
                [
                    ("PNT (SAM/Pointed)", 0.0, "Oligomerisation"),
                    ("ETS DNA-binding", 1.0, "DNA binding"),
                    ("C-terminal transactivation", 1.0, "Transactivation"),
                ],
            ),
        ],
    ),
    # Papillary thyroid carcinoma, RET/PTC1. The CCDC6 coiled coil replaces the
    # whole RET ectodomain, so the receptor dimerises without a ligand.
    (
        "CCDC6--RET",
        [
            (
                "CCDC6",
                [
                    ("Coiled-coil dimerisation", 1.0, "Oligomerisation"),
                    ("C-terminal domain", 0.0, "Regulatory"),
                ],
            ),
            (
                "RET",
                [
                    ("Cadherin-like repeats", 0.0, "Receptor ectodomain"),
                    ("Cysteine-rich domain", 0.0, "Receptor ectodomain"),
                    ("Protein tyrosine kinase", 1.0, "Kinase"),
                ],
            ),
        ],
    ),
    # Lung adenocarcinoma. Same 3' partner as CCDC6--RET and the same
    # consequence, reached through a different oligomerising 5' partner — the
    # comparison the small multiples are for.
    (
        "KIF5B--RET",
        [
            (
                "KIF5B",
                [
                    ("Kinesin motor", 1.0, "Cytoskeletal"),
                    ("Coiled-coil stalk", 0.68, "Oligomerisation"),
                    ("Cargo-binding tail", 0.0, "Adaptor"),
                ],
            ),
            (
                "RET",
                [
                    ("Cadherin-like repeats", 0.0, "Receptor ectodomain"),
                    ("Cysteine-rich domain", 0.0, "Receptor ectodomain"),
                    ("Protein tyrosine kinase", 1.0, "Kinase"),
                ],
            ),
        ],
    ),
]


def generate_fusion_structure_demo() -> None:
    """Write fusion_structure_demo.tsv: six oncogenic fusions, domain by domain.

    Coordinates are the end-to-end *slot* layout the renderer expects, not
    amino-acid positions: the domains of a fusion are laid out in listed order,
    one unit slot each, 5' partner first, so slot ``k`` becomes
    ``start = k, end = k + 1``. The 5' lane therefore occupies ``[0, n5)`` and
    the 3' lane ``[n5, n5 + n3)``, which puts the two partners genuinely end to
    end and makes ``breakpoint = n5`` a single seam between the lanes. This is
    the same convention the arriba ``fusion_domains`` recipe uses, because
    arriba reports which domains survive but never where they are.
    """
    header = [
        "fusion_id",
        "partner",
        "feature",
        "start",
        "end",
        "breakpoint",
        "retained",
        "domain_class",
    ]
    rows: list[list] = []
    for fusion_id, partners in FUSION_STRUCTURES:
        n5 = len(partners[0][1])
        slot = 0
        for partner, domains in partners:
            for feature, retained, domain_class in domains:
                rows.append(
                    [
                        fusion_id,
                        partner,
                        feature,
                        slot,
                        slot + 1,
                        n5,
                        round(retained, 2),
                        domain_class,
                    ]
                )
                slot += 1
    write_tsv(OUT / "fusion_structure_demo.tsv", header, rows)


generate_fusion_structure_demo()


# ---------------------------------------------------------------------------
# NN. Gene arrow track: biosynthetic gene clusters on five bacterial contigs.
#     One antiSMASH-style BGC region per contig (its core biosynthetic genes
#     plus tailoring / transport / regulatory genes) with unrelated flanking
#     genes either side of the region boundary. That contrast is the point of
#     the kind: the coloured core reads as the cluster only because the grey
#     `flanking` neighbourhood is drawn next to it.
# columns: contig, feature_id, start, end, strand, gene_class, label,
#          region_start, region_end
# ---------------------------------------------------------------------------
# `core` genes are the ones antiSMASH would call as the cluster's backbone:
# long (2.7-4.5 kb) and worth a label under the arrow. `accessory` genes sit
# inside the region but are tailoring / transport / regulation, so they are
# shorter. Everything outside the region is `flanking` and carries only its
# locus-tag ordinal as a label.
BGC_CLUSTERS: list[dict] = [
    {
        "contig": "CTG1",
        "product": "NRPS",
        "core": ["nrpsA", "nrpsB", "nrpsC"],
        "accessory": ["mbtH", "thioE", "abcT1", "abcT2", "luxR", "cyp450", "mfsT", "gcnA"],
    },
    {
        "contig": "CTG2",
        "product": "T1PKS",
        "core": ["pksA", "pksB", "pksC"],
        "accessory": ["acpP", "ketoR", "atII", "tetR", "cyp112", "mfsY", "glcD", "oxyB"],
    },
    {
        "contig": "CTG3",
        "product": "terpene",
        "core": ["sqhC", "crtE"],
        "accessory": ["crtB", "crtI", "idi", "hmgR", "ispA", "marR", "cyp51", "dxs"],
    },
    {
        "contig": "CTG4",
        "product": "RiPP-like",
        "core": ["lanM", "lanB"],
        "accessory": ["lanA", "lanC", "lanT", "immA", "abcT3", "rgrA", "pepP", "nisP"],
    },
    {
        "contig": "CTG5",
        "product": "betalactone",
        "core": ["lctC", "lctB"],
        "accessory": ["fabH", "acpS", "adhE", "amtB", "estA", "araC", "cyp71", "sdrA"],
    },
]


def generate_gene_arrow_track_demo() -> None:
    """Write gene_arrow_track_demo.tsv: five BGC loci with their neighbourhood.

    Genes are laid out head-to-tail along each contig with small intergenic
    gaps, CDS-sized (lengths are multiples of 3, 300-4500 bp) and grouped into
    operon-like same-strand runs. The region band is padded past the outermost
    region gene the way antiSMASH pads a called region, and every row of a
    contig carries that contig's band so the lane can draw it.
    """
    header = [
        "contig",
        "feature_id",
        "start",
        "end",
        "strand",
        "gene_class",
        "label",
        "region_start",
        "region_end",
    ]
    rows: list[list] = []

    for cluster in BGC_CLUSTERS:
        contig = cluster["contig"]
        product = cluster["product"]
        core_names: list[str] = list(cluster["core"])
        accessory: list[str] = list(cluster["accessory"])
        R.shuffle(accessory)

        n_left = R.randint(5, 8)
        n_region = R.randint(8, 12)
        n_right = R.randint(5, 8)

        cursor = R.randint(400, 1800)
        ordinal = 5
        strand = R.choice(["+", "-"])
        genes: list[list] = []

        for slot in range(n_left + n_region + n_right):
            in_region = n_left <= slot < n_left + n_region
            # Operon-like runs: the strand holds for a few genes, then flips.
            if R.random() < 0.28:
                strand = "-" if strand == "+" else "+"

            region_slot = slot - n_left
            if in_region and region_slot < len(core_names):
                label = core_names[region_slot]
                length = 3 * R.randint(900, 1500)  # 2.7-4.5 kb backbone gene
            elif in_region:
                label = accessory[(region_slot - len(core_names)) % len(accessory)]
                length = 3 * R.randint(200, 700)  # 0.6-2.1 kb tailoring gene
            else:
                label = f"{ordinal:05d}"
                length = 3 * R.randint(100, 600)  # 0.3-1.8 kb neighbour

            start = cursor
            end = start + length - 1
            genes.append(
                [
                    contig,
                    f"{contig}_{ordinal:05d}",
                    start,
                    end,
                    strand,
                    product if in_region else "flanking",
                    label,
                ]
            )
            cursor = end + R.randint(18, 260)  # intergenic gap
            ordinal += 5

        # The band edges land in the intergenic space on either side of the
        # region rather than a fixed pad: a pad wide enough to be visible on a
        # 40 kb lane would reach past the first flanking gene, and a grey arrow
        # sitting inside the shaded band is exactly the reading this fixture is
        # meant to teach against.
        region_genes = genes[n_left : n_left + n_region]
        region_start = (genes[n_left - 1][3] + region_genes[0][2]) // 2
        region_end = (region_genes[-1][3] + genes[n_left + n_region][2]) // 2
        rows.extend(gene + [region_start, region_end] for gene in genes)

    write_tsv(OUT / "gene_arrow_track_demo.tsv", header, rows)


generate_gene_arrow_track_demo()


# NN. GSEA running enrichment score: the weighted Kolmogorov-Smirnov walk over
#     a ranked list of 800 genes, for 5 Hallmark-style gene sets with
#     deliberately different enrichment behaviour.
# columns: gene_set, rank, running_es, member, metric
# ---------------------------------------------------------------------------
# (gene set, size, profile). `profile` shapes where the members sit in the
# ranked list, which is what makes the four curves tell four different stories:
#   "top"    — members crowd the positive tail   -> large positive ES
#   "bottom" — members crowd the negative tail   -> large negative ES
#   "flat"   — members spread uniformly          -> curve wanders around zero
GSEA_SETS: list[tuple[str, int, str, float]] = [
    ("HALLMARK_INTERFERON_ALPHA_RESPONSE", 95, "top", 9.0),
    ("HALLMARK_E2F_TARGETS", 130, "top", 3.5),
    ("HALLMARK_MYC_TARGETS_V1", 110, "bottom", 7.0),
    ("HALLMARK_TNFA_SIGNALING_VIA_NFKB", 85, "bottom", 2.5),
    ("HALLMARK_APOPTOSIS", 75, "flat", 0.0),
]


def generate_gsea_running_score_demo() -> None:
    """Write gsea_running_score_demo.tsv — one row per (gene set, rank).

    The running score is *computed*, not sketched: the weighted KS walk GSEA
    itself runs (``p = 1``, i.e. the ``weighted`` scoring scheme), so the curve
    starts at zero, returns to zero at the last rank, and its extremum is the
    enrichment score. Faking the curve would put the peak, the leading-edge
    shading and the hit rug out of register with one another.
    """
    n_genes = 800
    header = ["gene_set", "rank", "running_es", "member", "metric"]

    # A dedicated child of NP_RNG. `spawn` derives it from the module seed
    # without consuming draws from the parent, so this TSV comes out identical
    # whether the function runs on its own or after every generator above it.
    rng = NP_RNG.spawn(1)[0]

    # Ranking metric: a signed, slightly convex ramp from ~+3 to ~-3 with a
    # little jitter, sorted descending so `rank` really is the rank order.
    x = np.linspace(1.0, -1.0, n_genes)
    metric = 3.0 * np.sign(x) * np.abs(x) ** 1.6 + rng.normal(0.0, 0.03, n_genes)
    metric = np.sort(metric)[::-1]
    abs_metric = np.abs(metric)

    rows: list[list] = []
    for name, size, profile, strength in GSEA_SETS:
        # Membership weights over the ranked list. An exponential preference
        # for one tail concentrates the hits there; `flat` is uniform.
        frac = np.arange(n_genes) / (n_genes - 1)
        if profile == "top":
            weights = np.exp(-strength * frac)
        elif profile == "bottom":
            weights = np.exp(-strength * (1.0 - frac))
        else:
            weights = np.ones(n_genes)
        weights /= weights.sum()

        member_idx = rng.choice(n_genes, size=size, replace=False, p=weights)
        is_member = np.zeros(n_genes, dtype=bool)
        is_member[member_idx] = True

        # Weighted Kolmogorov-Smirnov walk (p = 1):
        #   hit  at rank i: += |metric_i| / sum(|metric| over hits)
        #   miss at rank i: -= 1 / (N - Nh)
        n_hits = int(is_member.sum())
        norm_hit = float(abs_metric[is_member].sum())
        miss_step = 1.0 / (n_genes - n_hits)
        running = 0.0
        for i in range(n_genes):
            if is_member[i]:
                running += abs_metric[i] / norm_hit
            else:
                running -= miss_step
            value = round(running, 6)
            if value == 0:  # normalise a rounded -0.0
                value = 0.0
            rows.append(
                [
                    name,
                    i + 1,
                    value,
                    "true" if is_member[i] else "false",
                    round(float(metric[i]), 4),
                ]
            )

    write_tsv(OUT / "gsea_running_score_demo.tsv", header, rows)


generate_gsea_running_score_demo()


# NN. Sashimi: splice junctions across an exon-skipping event.
# columns: chrom, start, end, count, sample, annotation
# --------------------------------------------------------------------------
# Two loci on one chromosome, ~45.7 Mb apart, so the renderer's 1 Mb-gap locus
# clustering resolves two regions and opens on the busier one instead of
# drawing both as hairline spikes across a whole chromosome.
#
# Locus A is the story: an 8-exon gene whose third exon is a cassette. The two
# junctions that splice *into* and *out of* E3 (the inclusion pair) collapse in
# the knockdown samples while the junction that bridges E2 straight to E4 (the
# skipping junction, novel) goes from a handful of reads to the strongest arc
# in the lane. Locus B is ordinary constitutive splicing at a lower depth — it
# exists to give the locus picker a second entry.
SASHIMI_CHROM = "chr12"

# (exon start, exon end) — locus A, the cassette-exon gene. E3 is the cassette.
_SASHIMI_EXONS_A = [
    (6530000, 6530420),
    (6534100, 6534320),
    (6538900, 6539050),  # E3, skipped in the knockdown
    (6543700, 6543980),
    (6549200, 6549410),
    (6555600, 6555880),
    (6561300, 6561540),
    (6566800, 6567240),
]

# (exon start, exon end) — locus B, 45.7 Mb downstream.
_SASHIMI_EXONS_B = [
    (52300000, 52300380),
    (52304200, 52304460),
    (52308900, 52309120),
    (52313500, 52313760),
    (52318200, 52318640),
]

# Two conditions, two replicates each. The knockdown is where E3 is skipped.
_SASHIMI_SAMPLES = [
    ("CTRL_rep1", "ctrl"),
    ("CTRL_rep2", "ctrl"),
    ("KD_rep1", "kd"),
    ("KD_rep2", "kd"),
]


def _sashimi_junctions() -> list[tuple[int, int, str, dict[str, float]]]:
    """(start, end, annotation, {condition: mean read support}) per junction.

    The mean is per condition so the exon-skipping contrast is authored rather
    than sampled: inclusion junctions are ~190 reads in control and ~34 in the
    knockdown, and the skipping junction runs the other way, 4 vs 165.
    """
    a = _SASHIMI_EXONS_A
    b = _SASHIMI_EXONS_B
    junctions: list[tuple[int, int, str, dict[str, float]]] = []

    # Locus A, consecutive-exon (known) junctions. The two that flank the
    # cassette exon carry the inclusion signal; the rest are constitutive.
    for i in range(len(a) - 1):
        donor, acceptor = a[i][1], a[i + 1][0]
        flanks_cassette = i in (1, 2)  # E2->E3 and E3->E4
        means = {"ctrl": 190.0, "kd": 34.0} if flanks_cassette else {"ctrl": 212.0, "kd": 205.0}
        junctions.append((donor, acceptor, "known", means))

    # The exon-skipping junction: E2 donor straight to E4 acceptor.
    junctions.append((a[1][1], a[3][0], "novel", {"ctrl": 4.0, "kd": 165.0}))
    # Two low-support novel sites for texture: an alternative donor inside E5
    # and an alternative acceptor inside E7.
    junctions.append((a[4][1] - 80, a[5][0], "novel", {"ctrl": 12.0, "kd": 11.0}))
    junctions.append((a[5][1], a[6][0] + 110, "novel", {"ctrl": 9.0, "kd": 8.0}))

    # Locus B: constitutive splicing at a lower depth, no condition effect.
    for i in range(len(b) - 1):
        junctions.append((b[i][1], b[i + 1][0], "known", {"ctrl": 56.0, "kd": 54.0}))
    junctions.append((b[1][1], b[3][0], "novel", {"ctrl": 7.0, "kd": 6.0}))
    junctions.append((b[2][1], b[3][0] + 120, "novel", {"ctrl": 5.0, "kd": 5.0}))

    return junctions


def generate_sashimi_demo() -> None:
    """Write sashimi_demo.tsv — 64 junction rows over two loci on one chromosome."""
    header = ["chrom", "start", "end", "count", "sample", "annotation"]
    rows: list[list] = []

    # Per-sample library depth, so replicates differ in scale without blurring
    # the condition contrast.
    depth = {name: R.uniform(0.85, 1.2) for name, _ in _SASHIMI_SAMPLES}

    for start, end, annotation, means in _sashimi_junctions():
        for sample, condition in _SASHIMI_SAMPLES:
            mean = means[condition] * depth[sample]
            count = max(1, int(round(mean * R.gauss(1.0, 0.12))))
            rows.append([SASHIMI_CHROM, start, end, count, sample, annotation])

    write_tsv(OUT / "sashimi_demo.tsv", header, rows)


generate_sashimi_demo()
