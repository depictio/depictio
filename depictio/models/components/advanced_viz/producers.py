"""Producer registry — known bioinformatics tool outputs and their viz affinity.

Each `Producer` describes the canonical output of a specific tool (e.g.
DESeq2's `results()` TSV, mosdepth's per-region BED) by:
    - a fingerprint of required column names (the smallest set that
      reliably identifies the tool's output among other tabular files);
    - the viz kinds whose `CANONICAL_SCHEMAS` the producer's columns can
      satisfy after a role→column rename (declared here);
    - a one-line description used in UI badges / docs.

This is the in-repo alternative to an nf-core-modules-style install
system: depictio's producer surface (~60 candidates across 18 viz kinds)
is small enough that a single file works better than a package manager.
Adding a new producer is one entry here + a test.

Used by:
    suggest_producers(dc_schema) -> list[(Producer, confidence)]
        — Reverse lookup: "which known tool's output does this DC look
        like?" Drives the React DC card's "Suggested visualisations"
        chips and the component-creation flow's DC pre-filter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from depictio.models.components.types import AdvancedVizKind


@dataclass(frozen=True)
class Producer:
    """A known tool-output fingerprint and its viz affinity.

    Attributes:
        name: Stable id (`{tool}_{format}`). Used in API responses and
            CI/test assertions.
        tool: Display name of the upstream tool / library.
        description: One-line summary suitable for a UI tooltip.
        required_columns: Column names that MUST be present for a DC
            schema to match this producer. Match is case-sensitive (most
            bioinformatics tools emit fixed column casing).
        feeds_viz: Viz kinds whose CANONICAL_SCHEMAS roles can be
            satisfied by this producer's columns (after the role_mapping
            below). Each must appear as a key in `role_mapping`.
        role_mapping: Per-viz_kind dict mapping viz role → producer
            column name. Lets the UI pre-fill bindings without the user
            naming columns by hand.
        notes: Optional extra context (header quirks, reshape needed,
            etc.) — surfaced in the docs / fixture manifest.
    """

    name: str
    tool: str
    description: str
    required_columns: frozenset[str]
    feeds_viz: tuple[AdvancedVizKind, ...]
    role_mapping: dict[AdvancedVizKind, dict[str, str]] = field(default_factory=dict)
    notes: str = ""


# Registry of known tool outputs. Add a new entry per (tool, output-shape)
# pair — keep the required_columns minimal but discriminating (4-6 cols is
# usually enough to disambiguate from other tabular formats).
KNOWN_PRODUCERS: tuple[Producer, ...] = (
    Producer(
        name="deseq2_results",
        tool="DESeq2 / edgeR / limma",
        description="Differential-expression results table (gene × log2FC × padj).",
        required_columns=frozenset({"baseMean", "log2FoldChange", "padj"}),
        feeds_viz=("volcano", "ma", "qq"),
        role_mapping={
            "volcano": {
                "feature_id": "gene_id",
                "effect_size": "log2FoldChange",
                "significance": "padj",
            },
            "ma": {
                "feature_id": "gene_id",
                "avg_log_intensity": "baseMean",
                "log2_fold_change": "log2FoldChange",
            },
            "qq": {"p_value": "pvalue"},
        },
        notes="Plain TSV. The id column is often a rowname — first column may be unnamed.",
    ),
    # NOTE: `deseq2_vst_matrix` was removed — its single-column `{gene_id}`
    # fingerprint matched every DESeq2 results table too, causing spurious
    # `complex_heatmap` suggestions on differential-expression DCs. Wide-matrix
    # heatmap candidacy is detected client-side by the float-column count and
    # name-pattern heuristics in AdvancedVizBuilder.tsx (MIN_FLOAT_COLS +
    # STAT_LIKE_FLOAT_COL_NAMES).
    Producer(
        name="mosdepth_coverage",
        tool="mosdepth",
        description="Per-region read-depth track (BED-like).",
        required_columns=frozenset({"chrom", "start", "end"}),
        feeds_viz=("coverage_track",),
        role_mapping={
            "coverage_track": {
                "chromosome": "chrom",
                "position": "start",
                "value": "coverage",
            }
        },
        notes="Coverage column name varies: 'coverage' (nf-core) or 'depth' (raw mosdepth).",
    ),
    Producer(
        name="bracken_sample",
        tool="Bracken",
        description="Per-sample taxonomic abundance estimate.",
        required_columns=frozenset(
            {"name", "taxonomy_id", "taxonomy_lvl", "new_est_reads", "fraction_total_reads"}
        ),
        feeds_viz=("sunburst", "stacked_taxonomy"),
        role_mapping={
            "sunburst": {"abundance": "new_est_reads"},
            "stacked_taxonomy": {
                "taxon": "name",
                "rank": "taxonomy_lvl",
                "abundance": "new_est_reads",
            },
        },
        notes="`name` is the leaf-level taxon; lineage may need to be re-derived from rank.",
    ),
    Producer(
        name="qiime2_alpha_rarefaction",
        tool="QIIME2 alpha-rarefaction",
        description="WIDE alpha-diversity table (sample × depth_iter columns).",
        required_columns=frozenset({"sample-id"}),
        feeds_viz=("rarefaction",),
        role_mapping={
            "rarefaction": {
                "sample_id": "sample-id",
                # depth + metric are pivoted from the wide depth-N_iter-M columns
                # at ingest time — see notes.
            }
        },
        notes="WIDE table — needs polars .melt(id_vars=['sample-id']) + regex split of column name.",
    ),
    Producer(
        name="qiime2_feature_table",
        tool="QIIME2 feature-table",
        description="Feature × sample abundance table (biom-derived TSV).",
        # The discriminating signal here is the `#OTU ID` first column AFTER
        # skipping the `# Constructed from biom file` comment line.
        required_columns=frozenset({"#OTU ID"}),
        feeds_viz=("stacked_taxonomy",),
        role_mapping={
            "stacked_taxonomy": {
                "sample_id": "sample",
                "taxon": "#OTU ID",
                "abundance": "abundance",
            }
        },
        notes="Needs polars_kwargs `comment_prefix='#'` + melt to long form.",
    ),
    Producer(
        name="ancombc_lfc_slice",
        tool="ANCOM-BC differentials",
        description="Per-contrast log-fold-change slice (one CSV per contrast group).",
        required_columns=frozenset({"id"}),
        feeds_viz=("da_barplot",),
        role_mapping={
            "da_barplot": {
                "feature_id": "id",
                # contrast + lfc come from melting the contrast columns
                # (e.g. (Intercept), mix8a, …) and joining with q_val_slice.
            }
        },
        notes="One of a pair — join with q_val_slice.csv on `id`, then melt across contrast cols.",
    ),
    Producer(
        name="ivar_variants_vcf",
        tool="ivar variants (VCF)",
        description="Per-sample variant calls in VCF format.",
        # VCF has a leading `#CHROM` column header after the ## metadata block;
        # ingest requires polars_kwargs comment_prefix='##' + rename `#CHROM` → `CHROM`.
        required_columns=frozenset({"#CHROM", "POS", "REF", "ALT"}),
        feeds_viz=("lollipop",),
        role_mapping={
            "lollipop": {
                "feature_id": "GENE",
                "position": "POS",
                "category": "EFFECT",
            }
        },
        notes="VCF: needs `##` comment skip, `#CHROM`→`CHROM` rename, INFO/ANN parse for GENE/EFFECT.",
    ),
    Producer(
        name="rnaseq_deseq2_pca",
        tool="DESeq2 PCA (nf-core/rnaseq MultiQC)",
        description="Two-dimensional sample projection from DESeq2 vst().",
        required_columns=frozenset({"Sample", "x", "y"}),
        feeds_viz=("embedding",),
        role_mapping={
            "embedding": {"sample_id": "Sample", "dim_1": "x", "dim_2": "y"},
        },
        notes="Tiny TSV (~few hundred bytes) — easy quick-start fixture.",
    ),
    Producer(
        name="qiime2_newick",
        tool="QIIME2 phylogenetic_tree",
        description="Rooted Newick tree (separate from tip metadata).",
        # Newick is not tabular — fingerprint here is a sentinel: phylogeny
        # DCs use DCPhylogenyConfig (file-backed), not a DC schema. We list
        # this producer for completeness so the suggestion engine can still
        # report "phylogenetic" as a possibility when the DC is a phylogeny
        # type rather than a table.
        required_columns=frozenset(),
        feeds_viz=("phylogenetic",),
        role_mapping={"phylogenetic": {}},
        notes="Newick is file-backed via DCPhylogenyConfig — not a column-shape match.",
    ),
)


def get_producer(name: str) -> Producer | None:
    """Lookup a producer by its stable id."""
    for p in KNOWN_PRODUCERS:
        if p.name == name:
            return p
    return None
