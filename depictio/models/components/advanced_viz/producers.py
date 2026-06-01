"""Producer registry — known bioinformatics tool outputs and their viz affinity.

Each `Producer` describes the typical output of a specific tool (e.g.
DESeq2's `results()` TSV, mosdepth's per-region BED) by:
    - a fingerprint of required column names (the smallest set that
      reliably identifies the tool's output among other tabular files);
    - the viz kinds whose `CANONICAL_SCHEMAS` the producer's columns can
      satisfy after a role→column rename (declared here);
    - a one-line description used in UI badges / docs.

`KNOWN_PRODUCERS` below is the hand-curated core: a small, vetted set kept
in one file. The community-extensible surface lives alongside it as
declarative YAML under ``depictio/catalog/`` (loaded by
``advanced_viz/catalog.py``), which compiles down to the same `Producer`
primitive. Use `all_producers()` — not `KNOWN_PRODUCERS` directly — to get
the merged set (curated wins on name collisions).

Used by:
    suggest_producers(dc_schema) -> list[(Producer, confidence)]
        — Reverse lookup: "which known tool's output does this DC look
        like?" Drives the React DC card's "Suggested visualisations"
        chips and the component-creation flow's DC pre-filter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

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
        # `id` alone would fingerprint nearly every TSV — pair it with `lfc`
        # so this only fires on real ANCOM-BC slice files.
        required_columns=frozenset({"id", "lfc"}),
        feeds_viz=("da_barplot",),
        role_mapping={
            "da_barplot": {
                "feature_id": "id",
                "lfc": "lfc",
            }
        },
        notes="One of a pair — join with q_val_slice.csv on `id`, then melt across contrast cols.",
    ),
    Producer(
        name="ancombc_results_joined",
        tool="ANCOM-BC (joined results)",
        description="Long-form ANCOM-BC results table (id × contrast × lfc × q_val).",
        required_columns=frozenset({"id", "contrast", "lfc", "q_val"}),
        feeds_viz=("volcano", "da_barplot"),
        role_mapping={
            "volcano": {
                "feature_id": "id",
                "effect_size": "lfc",
                "significance": "q_val",
            },
            "da_barplot": {
                "feature_id": "id",
                "contrast": "contrast",
                "lfc": "lfc",
                "significance": "q_val",
            },
        },
        notes="Produced by the ampliseq `ancombc.py` recipe from per-contrast slice files.",
    ),
    Producer(
        name="viralrecon_variants_long",
        tool="nf-core/viralrecon variants (long)",
        description="Per-sample variant calls with functional annotations.",
        required_columns=frozenset({"sample", "CHROM", "POS", "REF", "ALT", "GENE"}),
        feeds_viz=("lollipop", "oncoplot", "manhattan"),
        role_mapping={
            "lollipop": {
                "feature_id": "GENE",
                "position": "POS",
                "category": "EFFECT",
            },
            "oncoplot": {
                "sample_id": "sample",
                "gene": "GENE",
                "mutation_type": "EFFECT",
            },
            "manhattan": {
                "chr": "CHROM",
                "pos": "POS",
                "score": "AF",
            },
        },
        notes="Distinct from `ivar_variants_vcf`: long-form (no `#CHROM`, has `sample` per row).",
    ),
    # ------------------------------------------------------------------
    # Role-named fingerprints — match DCs whose columns already use the
    # advanced-viz role names verbatim (files coming out of an nf-core
    # template recipe, or hand-curated to match). Each producer mirrors
    # one entry in CANONICAL_SCHEMAS where the role-name set is
    # discriminating enough to fingerprint reliably.
    # ------------------------------------------------------------------
    Producer(
        name="volcano_role_table",
        tool="Volcano table",
        description="Differential-expression / abundance table with role-named columns.",
        required_columns=frozenset({"feature_id", "effect_size", "significance"}),
        feeds_viz=("volcano",),
        role_mapping={
            "volcano": {
                "feature_id": "feature_id",
                "effect_size": "effect_size",
                "significance": "significance",
            }
        },
    ),
    Producer(
        name="da_barplot_role_table",
        tool="DA barplot table",
        description="Differential-abundance per-contrast log-fold-change table.",
        required_columns=frozenset({"feature_id", "contrast", "lfc"}),
        feeds_viz=("da_barplot",),
        role_mapping={
            "da_barplot": {
                "feature_id": "feature_id",
                "contrast": "contrast",
                "lfc": "lfc",
            }
        },
    ),
    Producer(
        name="manhattan_role_table",
        tool="Manhattan table",
        description="Genome-wide variant / association track (chr × pos × score).",
        required_columns=frozenset({"chr", "pos", "score"}),
        feeds_viz=("manhattan",),
        role_mapping={"manhattan": {"chr": "chr", "pos": "pos", "score": "score"}},
    ),
    Producer(
        name="lollipop_role_table",
        tool="Lollipop table",
        description="Per-feature positional variants (feature_id × position × category).",
        required_columns=frozenset({"feature_id", "position", "category"}),
        feeds_viz=("lollipop",),
        role_mapping={
            "lollipop": {
                "feature_id": "feature_id",
                "position": "position",
                "category": "category",
            }
        },
    ),
    Producer(
        name="oncoplot_role_table",
        tool="Oncoplot table",
        description="Sample × gene × mutation_type matrix in long form.",
        required_columns=frozenset({"sample_id", "gene", "mutation_type"}),
        feeds_viz=("oncoplot",),
        role_mapping={
            "oncoplot": {
                "sample_id": "sample_id",
                "gene": "gene",
                "mutation_type": "mutation_type",
            }
        },
    ),
    Producer(
        name="coverage_track_role_table",
        tool="Coverage track table",
        description="Per-window coverage depth (chromosome × position × value).",
        required_columns=frozenset({"chromosome", "position", "value"}),
        feeds_viz=("coverage_track",),
        role_mapping={
            "coverage_track": {
                "chromosome": "chromosome",
                "position": "position",
                "value": "value",
            }
        },
    ),
    Producer(
        name="embedding_role_table",
        tool="Embedding table",
        description="2D sample projection (sample_id × dim_1 × dim_2) — PCA / UMAP / PCoA.",
        required_columns=frozenset({"sample_id", "dim_1", "dim_2"}),
        feeds_viz=("embedding",),
        role_mapping={
            "embedding": {
                "sample_id": "sample_id",
                "dim_1": "dim_1",
                "dim_2": "dim_2",
            }
        },
    ),
    Producer(
        name="stacked_taxonomy_role_table",
        tool="Stacked taxonomy table",
        description="Per-sample taxonomic abundance (sample_id × taxon × rank × abundance).",
        required_columns=frozenset({"sample_id", "taxon", "rank", "abundance"}),
        feeds_viz=("stacked_taxonomy",),
        role_mapping={
            "stacked_taxonomy": {
                "sample_id": "sample_id",
                "taxon": "taxon",
                "rank": "rank",
                "abundance": "abundance",
            }
        },
    ),
    Producer(
        name="rarefaction_role_table",
        tool="Rarefaction table",
        description="Alpha-diversity rarefaction curve (sample_id × depth × metric).",
        required_columns=frozenset({"sample_id", "depth", "metric"}),
        feeds_viz=("rarefaction",),
        role_mapping={
            "rarefaction": {
                "sample_id": "sample_id",
                "depth": "depth",
                "metric": "metric",
            }
        },
    ),
    Producer(
        name="ma_role_table",
        tool="MA-plot table",
        description="Differential-expression MA shape (feature_id × avg_log_intensity × log2_fold_change).",
        required_columns=frozenset({"feature_id", "avg_log_intensity", "log2_fold_change"}),
        feeds_viz=("ma",),
        role_mapping={
            "ma": {
                "feature_id": "feature_id",
                "avg_log_intensity": "avg_log_intensity",
                "log2_fold_change": "log2_fold_change",
            }
        },
    ),
    Producer(
        name="dot_plot_role_table",
        tool="Dot-plot table",
        description="Single-cell marker summary (cluster × gene × mean_expression × frac_expressing).",
        required_columns=frozenset({"cluster", "gene", "mean_expression", "frac_expressing"}),
        feeds_viz=("dot_plot",),
        role_mapping={
            "dot_plot": {
                "cluster": "cluster",
                "gene": "gene",
                "mean_expression": "mean_expression",
                "frac_expressing": "frac_expressing",
            }
        },
    ),
    Producer(
        name="enrichment_role_table",
        tool="Enrichment table",
        description="Pathway enrichment results (term × NES × padj × gene_count).",
        required_columns=frozenset({"term", "nes", "padj", "gene_count"}),
        feeds_viz=("enrichment",),
        role_mapping={
            "enrichment": {
                "term": "term",
                "nes": "nes",
                "padj": "padj",
                "gene_count": "gene_count",
            }
        },
    ),
    # ------------------------------------------------------------------
    # Common-shape fingerprints — match real-world file conventions where
    # column names don't line up with the role names. Cover the gaps the
    # role-named producers above leave: sankey/sunburst with hierarchical
    # taxonomy columns, long-form rarefaction with raw metric columns,
    # wide alpha-diversity summary tables.
    # ------------------------------------------------------------------
    Producer(
        name="taxonomy_levels_long",
        tool="Hierarchical taxonomy table",
        description=(
            "Per-sample hierarchical taxonomy "
            "(sample × Kingdom × Phylum × Class × Order × Family × Genus × abundance) "
            "— feeds sankey + sunburst."
        ),
        # Kingdom..Genus + abundance is the discriminating shape. We require
        # all 6 ranks to avoid accidental matches on lower-resolution tables.
        required_columns=frozenset(
            {"Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "abundance"}
        ),
        feeds_viz=("sankey", "sunburst"),
        role_mapping={
            # sankey's step_cols is a multi-column list inferred at render
            # time from the Kingdom..Genus column block — no single-column
            # role mapping to declare here.
            "sankey": {},
            "sunburst": {"abundance": "abundance"},
        },
    ),
    Producer(
        name="rarefaction_iter_long",
        tool="Rarefaction iteration table",
        description=(
            "Per-sample rarefaction curve in long form "
            "(sample_id × depth × iter × metric column(s))."
        ),
        # `iter` is the discriminator vs other (sample_id, depth, ...) tables.
        # The metric column varies by pipeline (shannon, observed_features,
        # faith_pd, evenness…) so we don't list it in required_columns; the
        # binding UI lets the user pick at component-creation time.
        required_columns=frozenset({"sample_id", "depth", "iter"}),
        feeds_viz=("rarefaction",),
        role_mapping={
            "rarefaction": {
                "sample_id": "sample_id",
                "depth": "depth",
                # metric column resolved by the binding UI from the numeric
                # columns alongside depth/iter.
            }
        },
        notes="Companion to `rarefaction_role_table` for files using raw metric column names.",
    ),
    Producer(
        name="taxonomy_abundance_long",
        tool="Long-form taxonomy abundance",
        description=(
            "Per-sample taxonomy with relative abundance and rank columns "
            "(sample_id × taxonomy × rel_abundance × Kingdom × Phylum × …). "
            "Source shape for the ampliseq taxonomy-heatmap recipe."
        ),
        # `taxonomy` + `rel_abundance` together discriminate against the
        # other taxonomy shapes (sankey/sunburst use `abundance`; stacked
        # uses `taxon`).
        required_columns=frozenset({"sample_id", "taxonomy", "rel_abundance"}),
        feeds_viz=("complex_heatmap", "stacked_taxonomy", "sunburst"),
        role_mapping={
            "complex_heatmap": {"index": "Phylum"},
            "stacked_taxonomy": {
                "sample_id": "sample_id",
                "taxon": "taxonomy",
                "abundance": "rel_abundance",
                # `rank` not directly available — derive from Kingdom/Phylum
                # columns at component-creation time.
            },
            "sunburst": {"abundance": "rel_abundance"},
        },
        notes="Pivot to wide (Phylum × sample) for ComplexHeatmap — see recipes/taxonomy_heatmap.py.",
    ),
    Producer(
        name="alpha_diversity_wide",
        tool="Alpha diversity table",
        description=(
            "Per-sample alpha-diversity metrics in wide form "
            "(sample_id × shannon × observed_features × evenness × …)."
        ),
        # `evenness` is the discriminator vs `rarefaction_iter_long`: both
        # shapes share sample_id/shannon/observed_features, but long-form
        # rarefaction never carries evenness as a column.
        required_columns=frozenset({"sample_id", "shannon", "observed_features", "evenness"}),
        feeds_viz=(),  # No advanced-viz kind for wide alpha-diversity yet —
        # surfaced as an informational badge only.
        role_mapping={},
        notes="Wide summary; reshape to long via .melt(id_vars=['sample_id']) if feeding rarefaction.",
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


@lru_cache(maxsize=1)
def all_producers() -> tuple[Producer, ...]:
    """The full producer surface: hand-curated `KNOWN_PRODUCERS` + the
    community catalog (``depictio/catalog/*.yaml``), de-duplicated by name.

    Hand-curated producers win on name collisions, so the catalog can only
    *add* coverage — never silently override a vetted fingerprint. This is
    the single accessor the suggestion engine should consult.
    """
    # Lazy import: catalog.py imports Producer from this module, so importing
    # it at top level would create a cycle.
    from depictio.models.components.advanced_viz.catalog import load_catalog_producers

    by_name: dict[str, Producer] = {p.name: p for p in KNOWN_PRODUCERS}
    for p in load_catalog_producers():
        by_name.setdefault(p.name, p)
    return tuple(by_name.values())


def get_producer(name: str) -> Producer | None:
    """Lookup a producer by its stable id (curated or catalog-provided)."""
    for p in all_producers():
        if p.name == name:
            return p
    return None
