"""Generate deterministic synthetic TSV fixtures for the advanced-viz showcase.

Run once; outputs are committed under ../data/. No external deps — uses
stdlib only so it runs in any Python 3.10+ environment.

Each TSV's column schema matches the canonical schema declared in
depictio/models/components/advanced_viz/schemas.py so the showcase
dashboards can bind to them with zero remapping.
"""

from __future__ import annotations

import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(exist_ok=True)

R = random.Random(20260512)


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
# 2. Embedding: 90 samples in 3 clusters (gaussians in 2D + a third cluster
#    for variety).
# columns: sample_id, dim_1, dim_2, cluster, color
# ---------------------------------------------------------------------------
CLUSTERS = {
    "control": ((-3.0, -1.5), 0.8),
    "treatment": ((2.5, 1.0), 1.0),
    "recovery": ((0.5, 3.5), 0.7),
}
rows = []
i = 0
for cluster_name, ((cx, cy), spread) in CLUSTERS.items():
    n = 30
    for _ in range(n):
        x = R.gauss(cx, spread)
        y = R.gauss(cy, spread)
        # `color` is a quantitative variable (mock gene expression) loosely
        # correlated with dim_1 so the embedding has a visible gradient when
        # colour-by is enabled in the renderer.
        color = max(0.0, 5.0 + 0.6 * x + R.gauss(0, 1.5))
        rows.append([f"S{i:03d}", round(x, 4), round(y, 4), cluster_name, round(color, 3)])
        i += 1

write_tsv(
    OUT / "embedding_demo.tsv",
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
# 4. Stacked taxonomy: 18 samples x 9 taxa, two ranks (Phylum + Genus), summing
#    to ~1 within each (sample, rank).
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


def _norm(d: dict[str, float]) -> dict[str, float]:
    total = sum(d.values())
    return {k: v / total for k, v in d.items()} if total > 0 else d


rows = []
for s in SAMPLES:
    # Phylum-level
    phylum_abund = {p: max(0.0, R.gauss(1.0, 0.6)) for p in PHYLA}
    phylum_abund = _norm(phylum_abund)
    for p, a in phylum_abund.items():
        rows.append([s, p, "Phylum", round(a, 4), p])
    # Genus-level
    genus_abund: dict[str, float] = {}
    for p in PHYLA:
        # Distribute the phylum's abundance across its genera
        weights = {g: max(0.0, R.gauss(1.0, 0.5)) for g in GENERA[p]}
        wsum = sum(weights.values()) or 1.0
        for g, w in weights.items():
            genus_abund[g] = phylum_abund[p] * (w / wsum)
    genus_abund = _norm(genus_abund)
    for p in PHYLA:
        for g in GENERA[p]:
            rows.append([s, g, "Genus", round(genus_abund[g], 4), f"{p};{g}"])

write_tsv(
    OUT / "stacked_taxonomy_demo.tsv",
    ["sample_id", "taxon", "rank", "abundance", "lineage"],
    rows,
)
