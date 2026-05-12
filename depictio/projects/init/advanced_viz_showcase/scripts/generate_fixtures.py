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
        rows.append([gene, round(effect, 4), f"{pval:.6e}", gene, pathway])

write_tsv(
    OUT / "volcano_demo.tsv",
    ["feature_id", "effect_size", "significance", "label", "category"],
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
    row = (
        [sid, cluster_labels[i], round(5.0 + 0.6 * float(feature_matrix_np[i, 0]), 3)]
        + [round(float(feature_matrix_np[i, j]), 4) for j in range(N_FEATURES)]
    )
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
    ("pca", run_pca, feature_df, {"n_components": 2}),
    ("umap", run_umap, feature_df, {"n_components": 2}),
    ("tsne", run_tsne, feature_df, {"n_components": 2}),
    ("pcoa", run_pcoa, non_negative_df, {"n_components": 2}),
]

for method, runner, input_df, params in methods:
    coords = runner(input_df, **params)
    dim_1 = np.asarray(coords["dim_1"].to_list(), dtype=np.float64)
    dim_2 = np.asarray(coords["dim_2"].to_list(), dtype=np.float64)
    # `color` = a quantitative variable correlated with dim_1 plus jitter, so
    # the embedding renderer's "colour by" shows a visible gradient.
    color = dim_1 + NP_RNG.normal(0.0, 0.3, size=len(dim_1))
    rows = []
    for sid, x, y, cluster, c in zip(
        coords["sample_id"].to_list(), dim_1, dim_2, cluster_labels, color
    ):
        rows.append([sid, round(float(x), 4), round(float(y), 4), cluster, round(float(c), 3)])
    write_tsv(
        OUT / f"embedding_{method}.tsv",
        ["sample_id", "dim_1", "dim_2", "cluster", "color"],
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
for chrom in CHROMS:
    # Approx 40 noise points per chromosome
    chrom_len = R.randint(45_000_000, 200_000_000)
    for _ in range(40):
        pos = R.randint(1_000_000, chrom_len)
        score = max(0.05, R.gauss(1.5, 0.7))
        rows.append([chrom, pos, round(score, 3), "", "-log10(padj)"])
    # Plus designed hits
    for pos, rsid, score in HITS.get(chrom, []):
        rows.append([chrom, pos, score, rsid, "-log10(padj)"])


# Sort by chromosome then position for nicer file ordering
def _chrom_key(c: str) -> int:
    suffix = c.replace("chr", "")
    return 100 if suffix == "X" else int(suffix)


rows.sort(key=lambda r: (_chrom_key(r[0]), r[1]))

write_tsv(
    OUT / "manhattan_demo.tsv",
    ["chr", "pos", "score", "feature", "score_kind"],
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


rows = []
for s in SAMPLES:
    # Per-sample total in 5k–50k range so the OFF state of the normalise
    # toggle shows realistic raw-count y-axis values.
    sample_total = R.randint(5_000, 50_000)

    # Phylum-level: allocate counts directly.
    phylum_weights = {p: max(0.01, R.gauss(1.0, 0.6)) for p in PHYLA}
    phylum_counts = _allocate_counts(sample_total, phylum_weights)
    for p, count in phylum_counts.items():
        rows.append([s, p, "Phylum", count, p])

    # Genus-level: within each phylum, distribute the phylum's counts across
    # its genera so the Phylum and Genus rows agree on per-sample totals.
    for p in PHYLA:
        if not GENERA[p]:
            continue
        genus_weights = {g: max(0.01, R.gauss(1.0, 0.5)) for g in GENERA[p]}
        genus_counts = _allocate_counts(phylum_counts[p], genus_weights)
        for g, count in genus_counts.items():
            rows.append([s, g, "Genus", count, f"{p};{g}"])

write_tsv(
    OUT / "stacked_taxonomy_demo.tsv",
    ["sample_id", "taxon", "rank", "abundance", "lineage"],
    rows,
)
