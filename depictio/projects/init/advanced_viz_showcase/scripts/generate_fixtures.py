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
# 6. ANCOM-BC differentials: 200 taxa across 3 contrasts. Drives both the
#    ANCOMBCDifferentialsRenderer (ranked horizontal bar for one contrast)
#    and the DaBarplotRenderer (faceted top-N per contrast).
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
