"""Canonical column schemas per viz_kind, plus editor-time binding validation.

Each viz declares a small required schema keyed by ROLE (not by raw column
name). When the user binds a viz to a DC, the editor reads the DC's polars
schema, calls validate_binding(config, dc_schema), and surfaces any
missing-column or wrong-dtype problems in the builder UI.

Per-pipeline recipes are responsible for producing DCs whose columns can
play these roles; the recipe's own EXPECTED_SCHEMA validates the actual
column names + dtypes (see depictio/recipes/__init__.py:validate_schema).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Literal

from depictio.models.components.advanced_viz.configs import (
    EmbeddingConfig,
    ManhattanConfig,
    StackedTaxonomyConfig,
    VizConfig,
    VolcanoConfig,
)
from depictio.models.components.types import AdvancedVizKind

# Canonical, viz-side required schema. Role -> set of acceptable polars dtype
# names. We accept dtype NAMES (strings as polars emits via `str(dtype)`)
# rather than polars classes so this module stays import-cheap and works
# against the JSON-stringified schemas the API exposes.
#
# Numeric roles accept the broader family (Int8..Int64, Float32/64) to keep
# the validator forgiving across pipelines that emit different widths.
_INT = frozenset({"Int8", "Int16", "Int32", "Int64", "UInt8", "UInt16", "UInt32", "UInt64"})
_FLOAT = frozenset({"Float32", "Float64"})
_NUMERIC = _INT | _FLOAT
_STRING = frozenset({"String", "Utf8"})
# A membership flag. Recipes that cannot emit a real Boolean write 0/1, so the
# integer types are accepted alongside it rather than rejected as a mismatch.
_BOOLEAN = frozenset({"Boolean"}) | _INT

CANONICAL_SCHEMAS: dict[AdvancedVizKind, dict[str, frozenset[str]]] = {
    # The plain plane: one point per row. Only the two axes are required, which
    # is what lets it bind almost anything; colour, size and the hover/selection
    # label are optional because the twenty-eight code-mode scatters it replaces
    # use them in every combination.
    "scatter_xy": {
        "x": _NUMERIC,
        "y": _NUMERIC,
    },
    # One curve per series over an ordered numeric axis. Deliberately named for
    # the shape, not a domain: a TSS enrichment profile, a fragment-length
    # ladder, a Hill diversity curve and a rank-abundance curve are the same
    # three columns. `rarefaction` is this shape with ecology role names.
    "profile": {
        "series": _STRING,
        "x": _NUMERIC,
        "y": _NUMERIC,
    },
    # The metagene heatmap that sits under a `profile`: one row per region, one
    # column per position offset, rows ordered by signal. Long format, because a
    # wide frame would need one column per bin.
    "signal_matrix": {
        "region_id": _STRING,
        "position": _NUMERIC,
        "value": _NUMERIC,
    },
    # A fusion drawn as its two partners with the retained protein domains laid
    # along them. One row per domain, plus the breakpoint offset per partner.
    "fusion_structure": {
        "fusion_id": _STRING,
        "partner": _STRING,
        "feature": _STRING,
        "start": _NUMERIC,
        "end": _NUMERIC,
    },
    # A locus map: arrow glyphs per coding sequence along a contig, which is how
    # a biosynthetic gene cluster or a resistance cassette is read.
    "gene_arrow_track": {
        "contig": _STRING,
        "feature_id": _STRING,
        "start": _NUMERIC,
        "end": _NUMERIC,
        "strand": _STRING,
    },
    # The GSEA running enrichment score along the ranked gene list, with the set
    # members as a rug underneath.
    "gsea_running_score": {
        "gene_set": _STRING,
        "rank": _NUMERIC,
        "running_es": _FLOAT,
    },
    # Splice junctions as arcs over a genomic interval, weighted by read support.
    "sashimi": {
        "chr": _STRING,
        "start": _NUMERIC,
        "end": _NUMERIC,
        "count": _NUMERIC,
    },
    "volcano": {
        "feature_id": _STRING,
        "effect_size": _FLOAT,
        "significance": _FLOAT,
    },
    "embedding": {
        "sample_id": _STRING,
        "dim_1": _FLOAT,
        "dim_2": _FLOAT,
    },
    "manhattan": {
        "chr": _STRING,
        "pos": _INT,
        "score": _FLOAT,
    },
    # Same three roles as `manhattan`, drawn by GenomeSpy on a locus scale. Kept
    # identical on purpose so any DC a Manhattan binds renders here unchanged;
    # the optional roles (end, sample, category) are what turn the same rows
    # into intervals, per-sample lanes and a coloured coverage profile.
    "genome_view": {
        "chr": _STRING,
        "pos": _INT,
        "score": _FLOAT,
    },
    "stacked_taxonomy": {
        "sample_id": _STRING,
        "taxon": _STRING,
        "rank": _STRING,
        "abundance": _NUMERIC,
    },
    # Phylogenetic validates the *metadata* DC only: the tree DC is a
    # phylogeny-type DC (not tabular) so it has no column schema. The
    # `taxon` role joins metadata rows to tip labels in the tree.
    "phylogenetic": {
        "taxon": _STRING,
    },
    "rarefaction": {
        "sample_id": _STRING,
        "depth": _NUMERIC,
        "metric": _NUMERIC,
    },
    "da_barplot": {
        "feature_id": _STRING,
        "contrast": _STRING,
        "lfc": _FLOAT,
    },
    "enrichment": {
        "term": _STRING,
        "nes": _FLOAT,
        "padj": _FLOAT,
        "gene_count": _NUMERIC,
    },
    # ComplexHeatmap doesn't follow the column-role pattern — its only
    # required column is the row-id (index_column). Numeric matrix columns
    # are inferred from the rest of the DC schema by the Celery worker.
    "complex_heatmap": {
        "index": _STRING,
    },
    # UpSet — no canonical column-role schema; the renderer enumerates
    # binary columns at compute time. Editor validation is a no-op.
    "upset_plot": {},
    "ma": {
        "feature_id": _STRING,
        "avg_log_intensity": _FLOAT,
        "log2_fold_change": _FLOAT,
    },
    "dot_plot": {
        "cluster": _STRING,
        "gene": _STRING,
        "mean_expression": _FLOAT,
        "frac_expressing": _FLOAT,
    },
    "lollipop": {
        "feature_id": _STRING,
        "position": _INT,
        "category": _STRING,
    },
    "qq": {
        "p_value": _FLOAT,
    },
    # Sunburst uses a multi-column `rank_cols` list (no single <role>_col
    # mapping). Only `abundance` validates against the standard pattern;
    # the renderer enforces the rank columns at runtime.
    "sunburst": {
        "abundance": _NUMERIC,
    },
    "oncoplot": {
        "sample_id": _STRING,
        "gene": _STRING,
        "mutation_type": _STRING,
    },
    "coverage_track": {
        "chromosome": _STRING,
        "position": _INT,
        "value": _NUMERIC,
    },
    # Sankey's ``step_cols`` is a multi-column list (no single <role>_col
    # mapping) — like Sunburst's rank_cols. The renderer validates step
    # presence at compute time; the editor enforces ≥2 columns via the
    # Pydantic config's ``min_length=2``.
    "sankey": {},
    "pr_benchmark": {
        "label": _STRING,
        "recall": _FLOAT,
        "precision": _FLOAT,
        "f1": _FLOAT,
    },
    "roc_pr_curve": {
        "recall": _FLOAT,
        "precision": _FLOAT,
    },
    "confusion_matrix": {
        "label": _STRING,
        "tp": _NUMERIC,
        "fp": _NUMERIC,
        "fn": _NUMERIC,
    },
    "metric_ci_bars": {
        "label": _STRING,
        "value": _FLOAT,
        "lower": _FLOAT,
        "upper": _FLOAT,
    },
    # One binned resolution of a Hi-C matrix, one row per (bin, bin) pair,
    # intra- or inter-chromosomal. Coordinate-bound and below the JBrowse
    # boundary: bins, never per-read pairs. Only a triangle needs to be
    # present; the renderer mirrors it (`symmetric`).
    "contact_map": {
        "chrom1": _STRING,
        "start1": _NUMERIC,
        "chrom2": _STRING,
        "start2": _NUMERIC,
        "count": _NUMERIC,
    },
    # Barcode-rank ("knee") curve: one row per barcode rank per sample, UMI
    # count descending with rank. The cell-calling threshold comes from the
    # optional `is_cell` flag, or is estimated from the curve.
    "knee_plot": {
        "sample": _STRING,
        "rank": _NUMERIC,
        "umi_count": _NUMERIC,
    },
    # Ancient-DNA misincorporation profile: frequency of each base change at
    # each position from a read end, for both ends. `end` is "5p" or "3p".
    "damage_profile": {
        "sample": _STRING,
        "end": _STRING,
        "position": _NUMERIC,
        "base_change": _STRING,
        "frequency": _NUMERIC,
    },
    # Two-group comparison computed on demand: one row per observation
    # (cell, sample) named by `index`; the feature columns are inferred like
    # complex_heatmap's matrix. The two groups are the dashboard's saved
    # selection groups, resolved at compute time, not a bound column.
    "group_compare": {
        "index": _STRING,
    },
    # Isoform structures: one row per exon / CDS block of a transcript on a
    # base-pair axis, transcripts stacked per gene.
    "transcript_structure": {
        "transcript_id": _STRING,
        "gene_id": _STRING,
        "chrom": _STRING,
        "start": _NUMERIC,
        "end": _NUMERIC,
        "feature": _STRING,
        "strand": _STRING,
    },
    # Copy-number profile: one row per bin or per called segment with its
    # log2 ratio; the optional `segment` role tells the two apart.
    "cnv_profile": {
        "sample": _STRING,
        "chrom": _STRING,
        "start": _NUMERIC,
        "end": _NUMERIC,
        "log2": _NUMERIC,
    },
    # Chord diagram: one row per link between two loci (fusion partners,
    # structural-variant breakends, translocations).
    "genome_chord": {
        "chrom_a": _STRING,
        "pos_a": _NUMERIC,
        "chrom_b": _STRING,
        "pos_b": _NUMERIC,
    },
    # One row read as text. Only the identifier is a role: every other column
    # of the collection is a field the card can show, so listing them here
    # would be a second copy of the schema that goes stale on the next
    # pipeline release.
    "record_card": {
        "id": _STRING,
    },
    # One polyline per sample across N numeric axes. The axes are inferred
    # from the numeric columns the same way `complex_heatmap` infers its
    # matrix, so only the line identity is a required role.
    "parallel_coordinates": {
        "sample": _STRING,
    },
}

# Per-role column-name aliases used by `suggest_viz_kinds`. The suggester
# matches schemas against viz kinds by checking that each required role has
# a column whose NAME is in the role's alias set AND whose dtype is in the
# role's accepted dtype set (CANONICAL_SCHEMAS above). Pure dtype matches no
# longer count toward confidence — they were turning every Numeric+String
# DC into a 13-viz suggestion soup.
#
# Aliases are matched case-insensitively. Each set contains the literal role
# name plus common real-world variants (nf-core / QIIME2 / DESeq2 outputs,
# typical short forms). When adding support for a new tool output whose columns
# map to a viz role, mirror those column names here so the dtype-aware suggester
# surfaces the matching viz kind.
ROLE_NAMES: dict[AdvancedVizKind, dict[str, frozenset[str]]] = {
    "volcano": {
        "feature_id": frozenset(
            {
                "feature_id",
                "gene_id",
                "id",
                "gene",
                "feature",
                "name",
                "symbol",
            }
        ),
        "effect_size": frozenset(
            {
                "effect_size",
                "log2foldchange",
                "log2_fold_change",
                "lfc",
                "logfc",
                "log2fc",
                "fc",
            }
        ),
        "significance": frozenset(
            {
                "significance",
                "padj",
                "pvalue",
                "p_value",
                "p_adj",
                "q_val",
                "qvalue",
                "qval",
                "fdr",
            }
        ),
    },
    "embedding": {
        "sample_id": frozenset({"sample_id", "sample-id", "sample"}),
        "dim_1": frozenset(
            {
                "dim_1",
                "dim1",
                "x",
                "pc1",
                "pca1",
                "umap1",
                "umap_1",
                "tsne1",
                "tsne_1",
                "comp1",
            }
        ),
        "dim_2": frozenset(
            {
                "dim_2",
                "dim2",
                "y",
                "pc2",
                "pca2",
                "umap2",
                "umap_2",
                "tsne2",
                "tsne_2",
                "comp2",
            }
        ),
    },
    "manhattan": {
        "chr": frozenset({"chr", "chrom", "chromosome", "#chrom"}),
        "pos": frozenset({"pos", "position", "bp"}),
        "score": frozenset(
            {
                "score",
                "p_value",
                "pvalue",
                "p",
                "neg_log_p",
                "minus_log10_p",
                "af",
            }
        ),
    },
    "genome_view": {
        "chr": frozenset({"chr", "chrom", "chromosome", "#chrom", "contig"}),
        "pos": frozenset({"pos", "position", "bp", "start", "chromstart"}),
        "score": frozenset(
            {
                "score",
                "p_value",
                "pvalue",
                "neg_log_p",
                "minus_log10_p",
                "af",
                "coverage",
                "depth",
                "value",
                "signal",
            }
        ),
    },
    "stacked_taxonomy": {
        "sample_id": frozenset({"sample_id", "sample-id", "sample"}),
        "taxon": frozenset(
            {"taxon", "taxonomy", "lineage", "name", "otu", "otu_id", "asv", "taxa"}
        ),
        "rank": frozenset({"rank", "taxonomy_lvl", "level", "taxon_rank"}),
        "abundance": frozenset(
            {
                "abundance",
                "rel_abundance",
                "relative_abundance",
                "new_est_reads",
                "fraction_total_reads",
                "count",
                "reads",
                "frequency",
            }
        ),
    },
    "phylogenetic": {
        "taxon": frozenset({"taxon", "tip", "tip_label", "label", "leaf", "name"}),
    },
    "rarefaction": {
        "sample_id": frozenset({"sample_id", "sample-id", "sample"}),
        "depth": frozenset({"depth", "sampling_depth", "rarefaction_depth"}),
        "metric": frozenset(
            {
                "metric",
                "shannon",
                "observed_features",
                "faith_pd",
                "evenness",
                "chao1",
                "simpson",
                "value",
            }
        ),
    },
    "da_barplot": {
        "feature_id": frozenset({"feature_id", "id", "name", "gene"}),
        "contrast": frozenset({"contrast", "comparison", "group"}),
        "lfc": frozenset({"lfc", "log2fc", "log2_fold_change", "logfc"}),
    },
    "enrichment": {
        "term": frozenset({"term", "pathway", "go_term", "gene_set", "description"}),
        "nes": frozenset({"nes", "normalized_enrichment_score"}),
        "padj": frozenset({"padj", "p_adj", "fdr", "q_val", "qvalue"}),
        "gene_count": frozenset({"gene_count", "size", "n_genes", "count"}),
    },
    "complex_heatmap": {
        # complex_heatmap's only required role is a string row-id — make it
        # explicit rather than matching any String column.
        "index": frozenset(
            {
                "index",
                "id",
                "feature_id",
                "gene_id",
                "sample_id",
                "name",
                "row",
            }
        ),
    },
    "upset_plot": {},
    "ma": {
        "feature_id": frozenset({"feature_id", "gene_id", "id"}),
        "avg_log_intensity": frozenset(
            {
                "avg_log_intensity",
                "basemean",
                "log_basemean",
                "log_intensity",
                "a",
            }
        ),
        "log2_fold_change": frozenset(
            {
                "log2_fold_change",
                "log2foldchange",
                "lfc",
                "logfc",
                "m",
            }
        ),
    },
    "dot_plot": {
        "cluster": frozenset({"cluster", "celltype", "cell_type", "group"}),
        "gene": frozenset({"gene", "feature", "marker"}),
        "mean_expression": frozenset(
            {
                "mean_expression",
                "avg_expression",
                "mean_expr",
            }
        ),
        "frac_expressing": frozenset(
            {
                "frac_expressing",
                "pct_expressing",
                "frac",
                "pct",
            }
        ),
    },
    "lollipop": {
        "feature_id": frozenset({"feature_id", "gene", "feature"}),
        "position": frozenset({"position", "pos", "aa_pos", "site"}),
        "category": frozenset({"category", "effect", "type", "consequence"}),
        # Optional roles are scored against their own name server-side
        # (`_score_kind` only consults this map for required roles), but the
        # backend-less picker in Tool Studio ranks every role's candidates
        # through `role_names`; without these a `label` binding offers the
        # DC's string columns in alphabetical order.
        "label": frozenset({"label", "name", "gene_name", "symbol", "gene_symbol"}),
    },
    "qq": {
        "p_value": frozenset({"p_value", "pvalue", "p", "padj", "fdr"}),
    },
    "sunburst": {
        "abundance": frozenset(
            {
                "abundance",
                "rel_abundance",
                "relative_abundance",
                "count",
                "reads",
                "frequency",
                "new_est_reads",
                "fraction_total_reads",
            }
        ),
    },
    "oncoplot": {
        "sample_id": frozenset({"sample_id", "sample", "tumor_sample_barcode"}),
        "gene": frozenset({"gene", "hugo_symbol"}),
        "mutation_type": frozenset(
            {
                "mutation_type",
                "variant_classification",
                "effect",
                "consequence",
            }
        ),
    },
    "coverage_track": {
        "chromosome": frozenset({"chromosome", "chrom", "chr", "#chrom"}),
        "position": frozenset({"position", "pos", "start"}),
        "value": frozenset({"value", "coverage", "depth", "score"}),
    },
    "sankey": {},
    "pr_benchmark": {
        "label": frozenset({"label", "tool", "caller", "sample", "name"}),
        "recall": frozenset({"recall", "sensitivity", "tpr"}),
        "precision": frozenset({"precision", "ppv"}),
        "f1": frozenset({"f1", "f1_score", "fmeasure"}),
    },
    "roc_pr_curve": {
        "recall": frozenset({"recall", "sensitivity", "tpr"}),
        "precision": frozenset({"precision", "ppv"}),
    },
    "confusion_matrix": {
        "label": frozenset({"label", "tool", "caller", "sample", "name"}),
        "tp": frozenset({"tp", "tp_comp", "tp_base", "true_positives"}),
        "fp": frozenset({"fp", "false_positives"}),
        "fn": frozenset({"fn", "false_negatives"}),
    },
    "metric_ci_bars": {
        "label": frozenset({"label", "tool", "caller", "sample", "name"}),
        "value": frozenset({"value", "precision", "recall", "f1"}),
        "lower": frozenset({"lower", "ci_lower", "recall_lower", "precision_lower"}),
        "upper": frozenset({"upper", "ci_upper", "recall_upper", "precision_upper"}),
    },
    "scatter_xy": {
        "x": frozenset({"x", "x_value", "value_x"}),
        "y": frozenset({"y", "y_value", "value_y"}),
        "label": frozenset({"label", "name", "id", "feature_id", "sample", "sample_id"}),
        "color": frozenset({"color", "colour", "group", "category", "class", "condition"}),
        "size": frozenset({"size", "weight", "count", "n", "magnitude"}),
    },
    "profile": {
        "series": frozenset({"series", "sample", "sample_id", "group", "curve", "track"}),
        "x": frozenset({"x", "position", "distance", "offset", "bin", "depth", "tss_distance"}),
        "y": frozenset({"y", "value", "signal", "score", "coverage", "mean", "enrichment"}),
    },
    "signal_matrix": {
        "region_id": frozenset({"region_id", "peak_id", "region", "interval_id", "id", "name"}),
        "position": frozenset({"position", "offset", "bin", "distance", "tss_distance", "x"}),
        "value": frozenset({"value", "signal", "score", "coverage", "count", "enrichment"}),
    },
    "fusion_structure": {
        "fusion_id": frozenset({"fusion_id", "fusion", "fusion_name", "name", "id"}),
        "partner": frozenset({"partner", "gene", "gene_name", "side", "partner_gene"}),
        "feature": frozenset({"feature", "domain", "domain_name", "pfam", "name"}),
        "start": frozenset({"start", "begin", "from", "aa_start", "domain_start"}),
        "end": frozenset({"end", "stop", "to", "aa_end", "domain_end"}),
    },
    "gene_arrow_track": {
        "contig": frozenset({"contig", "chr", "chrom", "chromosome", "scaffold", "seqid"}),
        "feature_id": frozenset({"feature_id", "gene_id", "locus_tag", "id", "name", "gene"}),
        "start": frozenset({"start", "begin", "from", "feature_start"}),
        "end": frozenset({"end", "stop", "to", "feature_end"}),
        "strand": frozenset({"strand", "sense", "orientation", "direction"}),
    },
    "gsea_running_score": {
        "gene_set": frozenset({"gene_set", "geneset", "pathway", "term", "set", "id"}),
        "rank": frozenset({"rank", "rank_in_list", "position", "index", "order"}),
        "running_es": frozenset({"running_es", "running_score", "res", "enrichment_score", "es"}),
    },
    "sashimi": {
        "chr": frozenset({"chr", "chrom", "chromosome", "contig", "seqid", "reference"}),
        "start": frozenset({"start", "begin", "donor", "intron_start", "junction_start"}),
        "end": frozenset({"end", "stop", "acceptor", "intron_end", "junction_end"}),
        "count": frozenset({"count", "reads", "n_reads", "unique_reads", "support", "depth"}),
    },
    "contact_map": {
        "chrom1": frozenset({"chrom1", "chr1", "chromosome1", "chrom_1", "chr_1", "chrom_a"}),
        "start1": frozenset({"start1", "start_1", "pos1", "bin1", "bin1_start", "start_a"}),
        "chrom2": frozenset({"chrom2", "chr2", "chromosome2", "chrom_2", "chr_2", "chrom_b"}),
        "start2": frozenset({"start2", "start_2", "pos2", "bin2", "bin2_start", "start_b"}),
        "count": frozenset({"count", "contacts", "value", "score", "balanced", "iced", "n"}),
        "sample": frozenset({"sample", "sample_id", "library", "replicate"}),
        "end1": frozenset({"end1", "end_1", "bin1_end", "end_a"}),
        "end2": frozenset({"end2", "end_2", "bin2_end", "end_b"}),
        "resolution": frozenset({"resolution", "bin_size", "binsize"}),
    },
    "knee_plot": {
        "sample": frozenset({"sample", "sample_id", "library", "run"}),
        "rank": frozenset({"rank", "barcode_rank", "index", "order"}),
        "umi_count": frozenset({"umi_count", "umis", "umi", "total_umi", "counts", "total"}),
        "is_cell": frozenset({"is_cell", "cell", "called", "filtered", "in_filtered"}),
    },
    "damage_profile": {
        "sample": frozenset({"sample", "sample_id", "library", "run"}),
        "end": frozenset({"end", "read_end", "side", "terminus", "strand_end"}),
        "position": frozenset({"position", "pos", "offset", "distance", "cycle"}),
        "base_change": frozenset({"base_change", "change", "substitution", "mutation", "type"}),
        "frequency": frozenset({"frequency", "freq", "rate", "fraction", "value", "damage"}),
    },
    "group_compare": {
        "index": frozenset({"index", "cell_id", "barcode", "cell", "sample_id", "sample", "id"}),
    },
    "transcript_structure": {
        "transcript_id": frozenset(
            {"transcript_id", "transcript", "isoform_id", "isoform", "tx_id"}
        ),
        "gene_id": frozenset({"gene_id", "gene", "gene_name", "symbol"}),
        "chrom": frozenset({"chrom", "chr", "chromosome", "contig", "seqid", "seqname"}),
        "start": frozenset({"start", "begin", "from", "exon_start", "block_start"}),
        "end": frozenset({"end", "stop", "to", "exon_end", "block_end"}),
        "feature": frozenset({"feature", "feature_type", "type", "block", "block_type"}),
        "strand": frozenset({"strand", "sense", "orientation"}),
    },
    "cnv_profile": {
        "sample": frozenset({"sample", "sample_id", "tumour", "tumor", "library", "id"}),
        "chrom": frozenset({"chrom", "chr", "chromosome", "contig", "seqid"}),
        "start": frozenset({"start", "begin", "bin_start", "from", "loc_start"}),
        "end": frozenset({"end", "stop", "bin_end", "to", "loc_end"}),
        "log2": frozenset(
            {"log2", "log2_ratio", "log2ratio", "ratio", "logr", "lrr", "depth_ratio", "seg_mean"}
        ),
    },
    "genome_chord": {
        "chrom_a": frozenset(
            {"chrom_a", "chrom1", "chr1", "chr_a", "left_chrom", "chromosome_1", "chrom_left"}
        ),
        "pos_a": frozenset(
            {"pos_a", "pos1", "start1", "breakpoint1", "left_pos", "pos_left", "start_a"}
        ),
        "chrom_b": frozenset(
            {"chrom_b", "chrom2", "chr2", "chr_b", "right_chrom", "chromosome_2", "chrom_right"}
        ),
        "pos_b": frozenset(
            {"pos_b", "pos2", "start2", "breakpoint2", "right_pos", "pos_right", "start_b"}
        ),
    },
    "record_card": {
        "id": frozenset({"id", "sample", "sample_id", "run_id", "library", "name", "feature_id"}),
        "title": frozenset({"title", "name", "label", "description", "sample_name"}),
    },
    "parallel_coordinates": {
        "sample": frozenset({"sample", "sample_id", "library", "run", "run_id", "id", "name"}),
        "group": frozenset({"group", "condition", "treatment", "batch", "category", "class"}),
    },
}


# Optional roles — validated only if the user has bound a column for them.
_OPTIONAL_ROLES: dict[AdvancedVizKind, dict[str, frozenset[str]]] = {
    "volcano": {
        "label": _STRING,
        "category": _STRING,
    },
    "embedding": {
        "dim_3": _FLOAT,
        "cluster": _STRING,
        "color": _NUMERIC | _STRING,
    },
    "manhattan": {
        "feature": _STRING,
        "effect": _FLOAT,
    },
    # `end` makes a row an interval (peak, coverage bin), `sample` stacks one
    # lane per sample on a shared genome axis, `category` colours the marks by
    # a per-row annotation (gene region, peak caller) instead of by chromosome.
    "genome_view": {
        "feature": _STRING,
        "end": _INT,
        "sample": _STRING,
        "category": _STRING,
    },
    "stacked_taxonomy": {},
    "phylogenetic": {
        "color": _NUMERIC | _STRING,
        "label": _STRING,
    },
    "rarefaction": {
        "iter": _NUMERIC,
        "group": _STRING,
    },
    "da_barplot": {
        "significance": _FLOAT,
        "label": _STRING,
    },
    "enrichment": {
        "source": _STRING,
    },
    "complex_heatmap": {},
    "upset_plot": {},
    "ma": {
        "significance": _FLOAT,
        "label": _STRING,
    },
    "dot_plot": {},
    "lollipop": {
        "effect": _FLOAT,
        # Names the stem. `feature_id` is the lane, not the mark, so a lollipop
        # keyed on a contrast or a chromosome has no way to say which gene a
        # stem is without this.
        "label": _STRING,
    },
    "qq": {
        "feature_id": _STRING,
        "category": _STRING,
    },
    "sunburst": {},
    "oncoplot": {},
    "coverage_track": {
        "end": _INT,
        "sample": _STRING,
        "category": _STRING,
    },
    "sankey": {},
    "pr_benchmark": {
        "support": _NUMERIC,
        "category": _STRING,
    },
    "roc_pr_curve": {
        "threshold": _NUMERIC,
        "group": _STRING,
    },
    "confusion_matrix": {
        "tn": _NUMERIC,
    },
    "metric_ci_bars": {},
    "scatter_xy": {
        "label": _STRING,
        "color": _STRING,
        "size": _NUMERIC,
    },
    "profile": {
        "lower": _FLOAT,
        "upper": _FLOAT,
    },
    "signal_matrix": {
        "group": _STRING,
    },
    "fusion_structure": {
        "breakpoint": _NUMERIC,
        # A retention fraction in [0, 1], but a 0/1 flag is just as common.
        "retained": _NUMERIC,
        "colour_by": _STRING,
    },
    "gene_arrow_track": {
        "class": _STRING,
        "label": _STRING,
        # The neighbourhood window each feature belongs to, when the frame
        # carries one; without it the lane spans the features it holds.
        "region_start": _NUMERIC,
        "region_end": _NUMERIC,
    },
    "gsea_running_score": {
        # `member_col` marks which ranks are set members: the hit rug reads it
        # as a flag, not as a label.
        "member": _BOOLEAN,
        "metric": _FLOAT,
    },
    "sashimi": {
        "sample": _STRING,
        "annotation": _STRING,
    },
    "contact_map": {
        "sample": _STRING,
        "end1": _NUMERIC,
        "end2": _NUMERIC,
        "resolution": _NUMERIC,
    },
    "knee_plot": {
        "is_cell": _BOOLEAN,
    },
    "damage_profile": {},
    "group_compare": {
        "group": _STRING,
    },
    "transcript_structure": {
        "sample": _STRING,
        "gene_name": _STRING,
        "transcript_class": _STRING,
        "expression": _NUMERIC,
    },
    "cnv_profile": {
        "baf": _FLOAT,
        "copy_number": _NUMERIC,
        "segment": _STRING,
        "label": _STRING,
    },
    "genome_chord": {
        "label": _STRING,
        "weight": _NUMERIC,
        "category": _STRING,
        "sample": _STRING,
    },
    "record_card": {
        "title": _STRING,
    },
    "parallel_coordinates": {
        "group": _STRING,
    },
}


# ---------------------------------------------------------------------------
# Graded dtype / name compatibility scoring.
#
# These pure helpers turn the old binary "does column X satisfy role Y?" check
# into a graded score in [0, 1], so the suggester can RANK every viz kind
# instead of filtering down to perfect matches. Both `validate_binding` and
# `suggest_viz_kinds` share them, keeping the backend the single source of
# truth for compatibility (the React builder consumes the scores instead of
# re-deriving them).
# ---------------------------------------------------------------------------

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# A column whose dtype isn't an exact member of a role's accepted set may still
# be *castable* into it. Castable matches score below exact ones so the
# suggester prefers exact dtypes but tolerates close shapes.
_CASTABLE_INT_TO_FLOAT = 0.6
_CASTABLE_CATEGORICAL = 0.8


def _normalize_name(name: str) -> str:
    """Lowercase a column name and collapse separators to ``_`` (snake_case).

    Mirrors the builder's normalisation so ``sample-id`` / ``Sample ID`` /
    ``sample.id`` all align with the snake_case alias sets.
    """
    return _NON_ALNUM_RE.sub("_", name.lower()).strip("_")


def _dtype_score(actual: str, accepted: frozenset[str]) -> float:
    """Graded dtype compatibility: 1.0 exact, castable < 1.0, 0.0 incompatible."""
    if actual in accepted:
        return 1.0
    # Int widens losslessly into a Float role (Int64 → Float64).
    if actual in _INT and accepted <= _FLOAT:
        return _CASTABLE_INT_TO_FLOAT
    # Categorical is interchangeable with String for label/id roles.
    if actual == "Categorical" and accepted & _STRING:
        return _CASTABLE_CATEGORICAL
    return 0.0


def _name_score(col: str, aliases: frozenset[str]) -> float:
    """Fuzzy column-name match against a role's aliases, in [0, 1].

    1.0 = exact alias hit. Otherwise a graded fuzzy score (substring
    containment, shared snake_case tokens, or `difflib` ratio), capped below
    1.0 so a fuzzy hit never outranks an exact one. 0.0 = no name signal.
    """
    norm_aliases = {_normalize_name(a) for a in aliases if a}
    if not norm_aliases:
        return 0.0
    n = _normalize_name(col)
    if n in norm_aliases:
        return 1.0
    n_tokens = {t for t in n.split("_") if t}
    best = 0.0
    for alias in norm_aliases:
        a_tokens = {t for t in alias.split("_") if t}
        shared = n_tokens & a_tokens
        if shared:
            overlap = len(shared) / max(len(n_tokens), len(a_tokens))
            best = max(best, 0.5 + 0.35 * overlap)
        # Substring / fuzzy matching only for aliases long enough to be
        # meaningful. A 1-2 char alias ("p", "x", "fc", "bp", "es") otherwise
        # matches any column that merely *contains* that letter, flooding the
        # picker with false positives (e.g. qq scored ~1.0 on a penguin
        # morphometrics table because "bill_depth_mm" contains "p"). Such short
        # aliases still match a column named exactly that, via the exact-hit and
        # shared-token branches above.
        if len(alias) >= 3:
            # Same guard the other way round: a one-letter column ("a") sits
            # inside half the alias vocabulary.
            if alias in n or (len(n) >= 3 and n in alias):
                best = max(best, 0.85)
            ratio = difflib.SequenceMatcher(None, n, alias).ratio()
            if ratio > 0.8:
                best = max(best, 0.6 + (ratio - 0.8))
    return min(best, 0.9)


def _score_role(
    dc_schema: dict[str, str],
    aliases: frozenset[str],
    accepted: frozenset[str],
) -> tuple[float, list[str]]:
    """Score a single role against the DC schema.

    Returns ``(role_score, candidates)`` where role_score is the best
    column's combined score ``dtype × (0.5 + 0.5 × name)`` and candidates is
    the list of dtype-compatible columns ranked best-first (used by the UI to
    pre-fill the binding dropdown).
    """
    scored: list[tuple[float, str]] = []
    for col, dtype in dc_schema.items():
        d = _dtype_score(dtype, accepted)
        if d == 0.0:
            continue
        scored.append((d * (0.5 + 0.5 * _name_score(col, aliases)), col))
    scored.sort(key=lambda sc: (-sc[0], sc[1]))
    role_score = scored[0][0] if scored else 0.0
    return role_score, [col for _, col in scored]


@dataclass(frozen=True)
class BindingError:
    role: str
    column: str | None
    reason: str  # e.g. "column not in DC", "wrong dtype: got Int64 expected Float64"
    # "error" blocks the render; "warning" is a tolerant heads-up (e.g. a
    # castable dtype mismatch the renderer can coerce) that the editor surfaces
    # without disabling save.
    severity: Literal["error", "warning"] = "error"


def _role_to_config_field(role: str) -> str:
    """Roles map to ``<role>_col`` fields on each VizConfig submodel."""
    return f"{role}_col"


def _dtype_binding_error(
    role: str, col: str, actual: str, accepted: frozenset[str], *, optional: bool
) -> BindingError:
    """Build a dtype-mismatch BindingError, downgrading castable cases to a warning."""
    castable = _dtype_score(actual, accepted) > 0.0
    prefix = "optional column" if optional else "column"
    return BindingError(
        role=role,
        column=col,
        reason=(f"{prefix} '{col}' has dtype {actual!r}, expected one of {sorted(accepted)}"),
        severity="warning" if castable else "error",
    )


def validate_binding(config: VizConfig, dc_schema: dict[str, str]) -> list[BindingError]:
    """Validate that the DC schema satisfies the viz's canonical schema.

    Args:
        config: The viz's per-kind config (e.g. VolcanoConfig).
        dc_schema: Map of column name -> polars dtype name (e.g. {"lfc": "Float64"}).
                   Dtype names are the strings polars produces via ``str(dtype)``.

    Returns:
        List of BindingError (each tagged with ``severity``). A castable dtype
        mismatch (e.g. an Int column for a Float role) is reported as a
        ``warning`` rather than a blocking ``error``. Empty list = valid.
    """
    kind: AdvancedVizKind = config.viz_kind
    errors: list[BindingError] = []

    required = CANONICAL_SCHEMAS[kind]
    optional = _OPTIONAL_ROLES[kind]

    for role, accepted_dtypes in required.items():
        col = getattr(config, _role_to_config_field(role), None)
        if not col:
            errors.append(BindingError(role=role, column=None, reason="role not bound"))
            continue
        if col not in dc_schema:
            errors.append(BindingError(role=role, column=col, reason=f"column '{col}' not in DC"))
            continue
        actual = dc_schema[col]
        if actual not in accepted_dtypes:
            errors.append(_dtype_binding_error(role, col, actual, accepted_dtypes, optional=False))

    for role, accepted_dtypes in optional.items():
        col = getattr(config, _role_to_config_field(role), None)
        if not col:
            continue  # optional + unbound = fine
        if col not in dc_schema:
            errors.append(BindingError(role=role, column=col, reason=f"column '{col}' not in DC"))
            continue
        actual = dc_schema[col]
        if actual not in accepted_dtypes:
            errors.append(_dtype_binding_error(role, col, actual, accepted_dtypes, optional=True))

    return errors


# ---------------------------------------------------------------------------
# Reverse-lookup: "given a DC schema, how well does each viz kind fit?"
#
# Drives the React builder's ranked viz-kind picker (Recommended vs. the rest)
# and the DC card's suggestion chips. Pure functions — no DB, no IO, no DC
# mutation. Testable against any (col → dtype) dict.
#
# Every kind is scored and returned (ranked); nothing is filtered out by
# default, so the builder can present a "suggest but tolerate" picker where the
# user may still pick a low-scoring kind and bind columns manually.
# ---------------------------------------------------------------------------

# Structural gates ported from the builder so the backend stays the single
# source of truth. Kinds whose Pydantic config has a permissive role schema but
# whose renderer needs a wide matrix / many set columns get a structural floor;
# falling short multiplies the score down rather than hiding the kind.
# group_compare reads a wide observation x feature matrix exactly like
# complex_heatmap does, and its only required role is a string row id, so the
# same gate keeps it from claiming every metadata table.
_MIN_FLOAT_COLS: dict[AdvancedVizKind, int] = {"complex_heatmap": 8, "group_compare": 8}
_MIN_INT_COLS: dict[AdvancedVizKind, int] = {"upset_plot": 3}
_MIN_STRING_COLS: dict[AdvancedVizKind, int] = {"sankey": 2}
_KIND_REQUIRES_DC_TYPE: dict[AdvancedVizKind, str] = {"phylogenetic": "phylogeny"}
_EMBEDDING_LIVE_MIN_NUMERIC = 10
# A live embedding is the obvious read only on a wide matrix (an expression or
# abundance table). Between the two floors it stays pickable but unannounced: a
# dozen QC metrics can be projected, but a scatter or parallel axes say more.
_EMBEDDING_LIVE_STRONG_NUMERIC = 30

# Float columns whose name is purely a statistic (DESeq2-style results) — used
# to reject complex_heatmap / sankey, which want a sample matrix / categorical
# flow, not a stats table.
_STAT_LIKE_FLOAT_RE = re.compile(
    r"^(basemean|base_mean|log2foldchange|log2_fold_change|lfcse|lfc_se|stat|pvalue|p_value|"
    r"padj|p_adj|qvalue|q_value|p_?val|fdr|log2fc|lfc|effect_size|significance|nes|es|score)$"
)

# Numeric columns that are coordinates rather than measurements (genomic,
# ordinal or geographic: a latitude/longitude pair belongs on a map). They are
# not axes a parallel-coordinates plot or a generic scatter should propose.
_POSITIONAL_RE = re.compile(
    r"^(start|end|stop|begin|pos|position|bp|chromstart|chromend|"
    r"start_?\d|end_?\d|pos_?\d|rank|index|order|row|row_id|iter|iteration|"
    r"lat|latitude|lon|lng|long|longitude)$"
)

# A String column that names the row: what a scatter labels its points with,
# what a parallel-coordinates line is keyed on, and what a record card shows as
# its heading. Deliberately about the name only: any String column can be an
# id, but these are the ones an author would pick.
_ID_NAME_RE = re.compile(
    r"^(id|name|label|sample|samples|barcode|cell|gene|feature|accession|run|library|"
    r"assembly|bin|contig|taxon|transcript|isoform|peak|region|species|strain|tool|caller)$"
    r"|_(id|name|label|barcode|accession)$|^sample_"
)

# Coordinate pairs: two numeric columns whose names differ only in the axis
# marker (`dim_1`/`dim_2`, `pc1`/`pc2`, `umap_x`/`umap_y`, `x_pos`/`y_pos`).
_PAIR_DIGIT_RE = re.compile(r"^(?P<stem>[a-z][a-z0-9_]*?)_?(?P<axis>[12])$")
_PAIR_SUFFIX_RE = re.compile(r"^(?P<stem>[a-z0-9_]+)_(?P<axis>[xy])$")
_PAIR_PREFIX_RE = re.compile(r"^(?P<axis>[xy])_(?P<stem>[a-z0-9_]+)$")
# Stems that mean the pair is a dimensionality reduction, which `embedding`
# reads better than a plain scatter (it adds colour-by and live recompute).
_EMBEDDING_STEMS = frozenset(
    {"dim", "pc", "pca", "umap", "tsne", "t_sne", "comp", "component", "mds", "lsi", "phate"}
)
# Taxonomic or hierarchy level names: the rank columns a sunburst nests. Its
# only required role is a numeric abundance, which on its own fits any table.
_RANK_NAME_RE = re.compile(
    r"^(domain|superkingdom|kingdom|phylum|class|order|family|genus|species|strain|"
    r"subspecies|rank|level|lineage|taxonomy|taxonomy_lvl|taxon_rank|level_\d+|l\d)$"
)

# Multiplier applied when a structural gate isn't met: the kind stays in the
# ranked list but drops well below the "recommended" threshold.
_GATE_PENALTY = 0.25

# A column name scoring at/above this against a role's aliases is a real name
# match (an exact alias, or an alias that is a whole snake_case part of it).
# Below it the role is satisfied by dtype, or by a partial token overlap, only.
_NAMED_ROLE = 0.85

# Roles that only say which column names the row. Every tabular output has
# one, so a match on them is no evidence for a kind: a knee plot is not argued
# by a `sample` column, only by a barcode rank and a UMI count.
_IDENTITY_ROLES = frozenset({"sample", "sample_id", "feature_id", "id", "index", "label", "series"})

# Score at/above which the builder surfaces a kind under "Recommended".
RECOMMENDED_SCORE = 0.8

# A kind whose distinctive roles are not all matched by name tops out here,
# under the recommended bar, however well its dtypes line up.
_WEAK_CAP = 0.75
_WEAK_FACTOR = 0.85
# A named match resting on a partial alias hit tops out here, under an exact one.
_PARTIAL_NAMED_CAP = 0.95

# Kinds with no required roles (upset_plot, sankey) can only ever be matched on
# the shape of the table, never on what its columns are called. That is enough
# to rank them and keep them pickable, but not enough to advertise them: a flat
# score equal to RECOMMENDED_SCORE meant "has 2 String columns" recommended a
# Sankey on every metadata table there is. Sit them just under the bar instead,
# so a structural-only match is offered but never announced.
_STRUCTURAL_ONLY_SCORE = 0.7

# Shape scores for the generic kinds, which bind columns by shape rather than by
# domain name. A coordinate pair is a strong read; any two measurements plus a
# row label sit at the bar (a scatter is a sound default, never the only one);
# two measurements with nothing to label the points stay just under it.
_SHAPE_PAIR_SCORE = 0.9
_SHAPE_NUMERIC_ID_SCORE = RECOMMENDED_SCORE
_SHAPE_NUMERIC_SCORE = 0.7
# parallel_coordinates' only required role is a string line id, so without a
# floor it would match every table that has a `sample` column. Its point is the
# many-metric read, and below four axes a scatter or a small-multiples grid says
# the same thing more plainly, so a narrow table drops out of "recommended"
# while staying pickable. Counted over numeric measurement columns (Ints
# included: read counts and lengths are exactly the axes a QC table carries),
# not coordinates or statistics. See `_shape_parallel`.
_PARALLEL_MIN_AXES = 4
_PARALLEL_WIDE_AXES = 6

# A record card is the detail half of a master/detail pair, so what makes it
# right is the dashboard, not the columns: another tile on the tab has to select
# rows the card can look up. With that context it is recommended when the
# collection holds the selected column and enough fields to be worth a card;
# without it the card stays pickable under the bar.
_CONTEXT_SCORE = 0.9
_RECORD_CARD_MIN_FIELDS = 4

MatchKind = Literal["named", "shape", "context", "weak"]


@dataclass(frozen=True)
class SuggestionContext:
    """What the builder knows about the dashboard tab the new tile lands on.

    selection_columns: columns emitted by the tab's selection-capable tiles
    (a table with row selection, a lasso scatter). A record card needs one.
    existing_kinds: advanced-viz kinds already on the tab, surfaced as a reason
    only; they do not change the score.
    """

    selection_columns: frozenset[str] = frozenset()
    existing_kinds: frozenset[str] = frozenset()


@dataclass(frozen=True)
class VizSuggestion:
    """How well a viz kind fits a DC schema, plus the matching detail.

    score is 0.0 - 1.0 and exists to rank. It is not a quality measure: what
    the UI shows is `match`, the kind of evidence behind the score:

      - ``named``: every distinctive role has a column named like it.
      - ``shape``: the table has the shape the kind reads (a numeric pair, many
        numeric axes, set-membership columns), whatever the columns are called.
      - ``context``: the dashboard tab makes the kind right (a record card
        following another tile's selection).
      - ``weak``: dtypes line up, names and shape do not argue for it.

    reasons are short, human strings behind the match (e.g. "x/y: numeric pair
    dim_1, dim_2"), shown in the picker's tooltip.

    role_candidates maps each required role → dtype-compatible column names,
    ranked best-first. The UI uses this to pre-fill the binding dropdowns.

    unmet_roles are required roles with no compatible column at all; weak_roles
    have a compatible column but none named like the role.
    """

    viz_kind: AdvancedVizKind
    score: float
    role_candidates: dict[str, list[str]]
    unmet_roles: list[str]
    weak_roles: list[str]
    match: MatchKind = "weak"
    reasons: tuple[str, ...] = ()


def _count_dtypes(dc_schema: dict[str, str], dtypes: frozenset[str]) -> int:
    return sum(1 for d in dc_schema.values() if d in dtypes)


def _is_string(dtype: str) -> bool:
    return dtype in _STRING or dtype == "Categorical"


def _id_columns(dc_schema: dict[str, str]) -> list[str]:
    """String columns whose name says they identify the row."""
    return [
        c for c, d in dc_schema.items() if _is_string(d) and _ID_NAME_RE.search(_normalize_name(c))
    ]


def _measure_columns(dc_schema: dict[str, str]) -> list[str]:
    """Numeric columns that are measurements: not coordinates, not statistics."""
    out: list[str] = []
    for c, d in dc_schema.items():
        if d not in _NUMERIC:
            continue
        n = _normalize_name(c)
        if _POSITIONAL_RE.match(n) or _STAT_LIKE_FLOAT_RE.match(n):
            continue
        out.append(c)
    return out


def _numeric_pairs(dc_schema: dict[str, str]) -> list[tuple[str, str, str]]:
    """Coordinate pairs among the numeric columns, as ``(stem, first, second)``.

    Schema order is kept, so the first pair a table declares comes first.
    """
    firsts: dict[tuple[str, str], str] = {}
    seconds: dict[tuple[str, str], str] = {}
    order: list[tuple[str, str]] = []
    for c, d in dc_schema.items():
        if d not in _NUMERIC:
            continue
        n = _normalize_name(c)
        if n in ("x", "y"):
            key, axis = ("xy", ""), n
        else:
            m = _PAIR_DIGIT_RE.match(n) or _PAIR_SUFFIX_RE.match(n) or _PAIR_PREFIX_RE.match(n)
            if not m:
                continue
            kind = "digit" if m.re is _PAIR_DIGIT_RE else "xy"
            key, axis = (kind, m.group("stem")), m.group("axis")
        if key not in order:
            order.append(key)
        (firsts if axis in ("1", "x") else seconds).setdefault(key, c)
    return [
        (key[1], firsts[key], seconds[key]) for key in order if key in firsts and key in seconds
    ]


def _role_reason(role: str, column: str) -> str:
    """``"effect_size: log2fc"``, or ``"dim_1 column"`` when the names agree."""
    return f"{column} column" if _normalize_name(column) == role else f"{role}: {column}"


def _front(candidates: list[str], first: str) -> list[str]:
    """``candidates`` with ``first`` moved to the front."""
    return [first, *[c for c in candidates if c != first]]


def _gate_reason(
    kind: AdvancedVizKind, dc_schema: dict[str, str], dc_type: str | None
) -> str | None:
    """Why a structural gate held the kind down, or None when every gate passed."""
    min_float = _MIN_FLOAT_COLS.get(kind)
    if min_float is not None:
        float_cols = [c for c, d in dc_schema.items() if d in _FLOAT]
        if len(float_cols) < min_float:
            return (
                f"needs a wide numeric matrix ({min_float}+ float columns, has {len(float_cols)})"
            )
        if all(_STAT_LIKE_FLOAT_RE.match(_normalize_name(c)) for c in float_cols):
            return "the float columns are statistics, not a sample matrix"
    min_int = _MIN_INT_COLS.get(kind)
    if min_int is not None and _count_dtypes(dc_schema, _INT) < min_int:
        return f"needs {min_int}+ integer set-membership columns"
    min_string = _MIN_STRING_COLS.get(kind)
    if min_string is not None:
        if _count_dtypes(dc_schema, _STRING) < min_string:
            return f"needs {min_string}+ categorical columns"
        if any(
            _STAT_LIKE_FLOAT_RE.match(_normalize_name(c))
            for c, d in dc_schema.items()
            if d in _FLOAT
        ):
            return "reads like a statistics table, not a categorical flow"
    required_dc_type = _KIND_REQUIRES_DC_TYPE.get(kind)
    if required_dc_type is not None and dc_type is not None and dc_type != required_dc_type:
        return f"needs a {required_dc_type} data collection"
    return None


def _apply_structural_gates(
    kind: AdvancedVizKind, dc_schema: dict[str, str], score: float, dc_type: str | None
) -> float:
    """Adjust a kind's base score for renderer-level structural requirements."""
    min_float = _MIN_FLOAT_COLS.get(kind)
    if min_float is not None:
        float_cols = [c for c, d in dc_schema.items() if d in _FLOAT]
        if len(float_cols) < min_float:
            score *= _GATE_PENALTY
        elif float_cols and all(_STAT_LIKE_FLOAT_RE.match(_normalize_name(c)) for c in float_cols):
            # Structurally a wide matrix but semantically a stats table.
            score *= _GATE_PENALTY

    min_int = _MIN_INT_COLS.get(kind)
    if min_int is not None:
        # upset_plot has no required roles — derive its score from the count of
        # binary (Int) set-membership columns.
        ints = _count_dtypes(dc_schema, _INT)
        score = (
            _STRUCTURAL_ONLY_SCORE if ints >= min_int else _GATE_PENALTY * min(ints / min_int, 1.0)
        )

    min_string = _MIN_STRING_COLS.get(kind)
    if min_string is not None:
        # sankey has no required roles — needs ≥N categorical columns and no
        # statistic-looking floats (those are results tables, not flows).
        strings = _count_dtypes(dc_schema, _STRING)
        stat_floats = any(
            _STAT_LIKE_FLOAT_RE.match(_normalize_name(c))
            for c, d in dc_schema.items()
            if d in _FLOAT
        )
        score = (
            _STRUCTURAL_ONLY_SCORE if (strings >= min_string and not stat_floats) else _GATE_PENALTY
        )

    required_dc_type = _KIND_REQUIRES_DC_TYPE.get(kind)
    if required_dc_type is not None and dc_type is not None and dc_type != required_dc_type:
        score *= _GATE_PENALTY

    return min(score, 1.0)


@dataclass
class _Draft:
    """A kind's score while the evidence rules refine it."""

    score: float
    match: MatchKind
    reasons: list[str]
    role_candidates: dict[str, list[str]]


def _shape_scatter(dc_schema: dict[str, str], draft: _Draft) -> None:
    """scatter_xy by shape: a coordinate pair, or two measurements plus a label."""
    ids = _id_columns(dc_schema)
    pairs = _numeric_pairs(dc_schema)
    # Statistics are fair axes here (base mean against log2 fold change is an
    # MA plot); coordinates are not.
    measures = [
        c
        for c, d in dc_schema.items()
        if d in _NUMERIC and not _POSITIONAL_RE.match(_normalize_name(c))
    ]
    if pairs:
        _stem, first, second = pairs[0]
        score, reasons = _SHAPE_PAIR_SCORE, [f"x/y: numeric pair {first}, {second}"]
    elif len(measures) >= 2:
        first, second = measures[0], measures[1]
        score = _SHAPE_NUMERIC_ID_SCORE if ids else _SHAPE_NUMERIC_SCORE
        reasons = [f"x/y: {len(measures)} numeric columns, starting with {first}, {second}"]
    else:
        return
    if ids:
        reasons.append(f"points labelled by {ids[0]}")
    if score <= draft.score and draft.match == "named":
        return
    draft.score, draft.match, draft.reasons = score, "shape", reasons
    draft.role_candidates["x"] = _front(draft.role_candidates.get("x", []), first)
    draft.role_candidates["y"] = _front(draft.role_candidates.get("y", []), second)


def _shape_parallel(dc_schema: dict[str, str], draft: _Draft) -> None:
    """parallel_coordinates by shape: a line id and several measurement axes."""
    axes = _measure_columns(dc_schema)
    if not draft.role_candidates.get("sample"):
        draft.score, draft.match = min(draft.score, _GATE_PENALTY), "weak"
        draft.reasons = ["needs a String column to key each line on"]
        return
    line = draft.role_candidates["sample"][0]
    if len(axes) < _PARALLEL_MIN_AXES:
        draft.score *= _GATE_PENALTY
        draft.match = "weak"
        draft.reasons = [f"needs {_PARALLEL_MIN_AXES}+ numeric measurement axes, has {len(axes)}"]
        return
    draft.score = RECOMMENDED_SCORE + (0.05 if len(axes) >= _PARALLEL_WIDE_AXES else 0.0)
    draft.match = "shape"
    draft.reasons = [f"{len(axes)} numeric axes", f"one line per {line}"]


def _shape_profile(dc_schema: dict[str, str], draft: _Draft, named: dict[str, str]) -> None:
    """profile by shape: an ordered, position-like x plus a numeric y per series."""
    if draft.match == "named" or "x" not in named:
        return
    series = draft.role_candidates.get("series") or []
    ys = [c for c in draft.role_candidates.get("y", []) if c != named["x"]]
    if not series or not ys:
        return
    draft.score, draft.match = RECOMMENDED_SCORE, "shape"
    draft.reasons = [f"x: ordered axis {named['x']}", f"y: {ys[0]}", f"one curve per {series[0]}"]
    draft.role_candidates["y"] = _front(draft.role_candidates["y"], ys[0])


def _shape_embedding(dc_schema: dict[str, str], draft: _Draft) -> None:
    """embedding: a reduction pair (dim/PC/UMAP/tSNE), or a wide matrix to project."""
    if draft.match == "named":
        return
    dims = set(draft.role_candidates.get("dim_1", []))
    for stem, first, second in _numeric_pairs(dc_schema):
        if stem in _EMBEDDING_STEMS and first in dims and second in dims:
            draft.score, draft.match = 1.0, "named"
            draft.reasons = [f"dim_1/dim_2: reduction pair {first}, {second}"]
            draft.role_candidates["dim_1"] = _front(draft.role_candidates.get("dim_1", []), first)
            draft.role_candidates["dim_2"] = _front(draft.role_candidates.get("dim_2", []), second)
            return
    if not draft.role_candidates.get("sample_id"):
        return
    n_numeric = _count_dtypes(dc_schema, _NUMERIC)
    if n_numeric >= _EMBEDDING_LIVE_MIN_NUMERIC:
        score = 0.85 if n_numeric >= _EMBEDDING_LIVE_STRONG_NUMERIC else _WEAK_CAP
        if score > draft.score:
            draft.score, draft.match = score, "shape"
            draft.reasons = [f"PCA / UMAP computed live over {n_numeric} numeric columns"]


def _context_record_card(
    dc_schema: dict[str, str], draft: _Draft, context: SuggestionContext | None
) -> None:
    """record_card: recommended only when a tile on the tab selects its rows."""
    draft.match = "weak"
    draft.score = min(draft.score, _STRUCTURAL_ONLY_SCORE)
    if context is None or not context.selection_columns:
        draft.reasons = ["needs a selecting component (a table or a lasso) on this tab"]
        return
    hits = [c for c, d in dc_schema.items() if c in context.selection_columns and _is_string(d)]
    if not hits:
        draft.reasons = ["no selecting component on this tab emits a column of this table"]
        return
    ids = set(_id_columns(dc_schema))
    fields = [c for c in dc_schema if c not in ids and c not in hits]
    draft.role_candidates["id"] = _front(draft.role_candidates.get("id", []), hits[0])
    if len(fields) < _RECORD_CARD_MIN_FIELDS:
        draft.reasons = [
            f"{hits[0]} matches the selection, but only {len(fields)} other columns to show"
        ]
        return
    draft.score, draft.match = _CONTEXT_SCORE, "context"
    draft.reasons = [
        f"id column {hits[0]} matches the selection on this tab",
        f"{len(fields)} descriptive columns to show",
    ]


def _score_kind(
    kind: AdvancedVizKind,
    dc_schema: dict[str, str],
    dc_type: str | None,
    context: SuggestionContext | None = None,
) -> VizSuggestion:
    """Score one viz kind against the DC schema and say what the score rests on."""
    required = CANONICAL_SCHEMAS[kind]
    role_aliases = ROLE_NAMES.get(kind, {})
    role_scores: dict[str, float] = {}
    role_candidates: dict[str, list[str]] = {}
    # Role -> the column that matches it by name, for roles that have one.
    named: dict[str, str] = {}
    for role, accepted in required.items():
        aliases = role_aliases.get(role, frozenset({role}))
        role_scores[role], role_candidates[role] = _score_role(dc_schema, aliases, accepted)
        best = next(
            (c for c in role_candidates[role] if _name_score(c, aliases) >= _NAMED_ROLE), None
        )
        if best is not None:
            named[role] = best

    base = sum(role_scores.values()) / len(required) if required else 0.0

    # Optional-role matches nudge an already-matching kind upward (capped).
    optional = _OPTIONAL_ROLES.get(kind, {})
    if base > 0 and optional:
        opt = sum(
            _score_role(dc_schema, frozenset({role}), accepted)[0]
            for role, accepted in optional.items()
        )
        base = base + 0.1 * (opt / len(optional))

    # Evidence from names: a kind is a named match only when every distinctive
    # (non-identity) role has a column named like it. Otherwise it tops out
    # under the bar, so a vocabulary-rich kind cannot win on dtypes plus a
    # `sample` column.
    distinctive = [r for r in required if r not in _IDENTITY_ROLES]
    draft = _Draft(score=base, match="shape", reasons=[], role_candidates=role_candidates)
    if distinctive:
        missing = [r for r in distinctive if r not in named]
        if not missing:
            draft.match = "named"
            # The identity roles are no evidence either way: a volcano keyed on
            # an oddly named id column is still a volcano.
            draft.score = max(base, sum(role_scores[r] for r in distinctive) / len(distinctive))
            draft.reasons = [_role_reason(r, named[r]) for r in distinctive][:4]
            # An exact alias for every role outranks a partial one ("name" in
            # `gene_name`, "log2" in `log2fc`), so the kind whose vocabulary
            # the table actually speaks comes first.
            if any(
                _name_score(named[r], role_aliases.get(r, frozenset({r}))) < 1.0
                for r in distinctive
            ):
                draft.score = min(draft.score, _PARTIAL_NAMED_CAP)
        else:
            draft.match = "weak"
            draft.score = min(base * _WEAK_FACTOR, _WEAK_CAP)
            draft.reasons = [f"{r}: no column named like it" for r in missing][:3]
            draft.reasons += [_role_reason(r, named[r]) for r in distinctive if r in named][:2]
    elif not required:
        draft.reasons = []
    else:
        role = next(iter(required))
        if role_candidates[role]:
            draft.reasons = [f"{role}: {role_candidates[role][0]}"]
        if kind in _MIN_FLOAT_COLS:
            n_float = _count_dtypes(dc_schema, _FLOAT)
            draft.reasons.append(f"{n_float} float columns as the matrix")

    if kind == "scatter_xy":
        _shape_scatter(dc_schema, draft)
    elif kind == "parallel_coordinates":
        _shape_parallel(dc_schema, draft)
    elif kind == "profile":
        _shape_profile(dc_schema, draft, named)
    elif kind == "embedding":
        _shape_embedding(dc_schema, draft)
    elif kind == "sunburst" and not any(
        _is_string(d) and _RANK_NAME_RE.match(_normalize_name(c)) for c, d in dc_schema.items()
    ):
        draft.score = min(draft.score, _STRUCTURAL_ONLY_SCORE)
        draft.match = "weak"
        draft.reasons = ["no rank columns to nest (kingdom, phylum, ... or level_N)"]

    gated = _apply_structural_gates(kind, dc_schema, draft.score, dc_type)
    if gated < draft.score or (not required and kind in (*_MIN_INT_COLS, *_MIN_STRING_COLS)):
        reason = _gate_reason(kind, dc_schema, dc_type)
        if reason is not None:
            draft.match = "weak"
            draft.reasons = [reason]
        elif not required:
            n = _count_dtypes(dc_schema, _INT if kind in _MIN_INT_COLS else _STRING)
            label = (
                "integer columns read as set membership"
                if kind in _MIN_INT_COLS
                else "categorical columns"
            )
            draft.reasons = [f"{n} {label}"]
    draft.score = gated

    if kind == "record_card":
        _context_record_card(dc_schema, draft, context)

    if draft.match != "weak" and draft.score < 0.5:
        draft.match = "weak"
    if context is not None and kind in context.existing_kinds:
        draft.reasons.append("already used on this tab")

    unmet = [r for r, s in role_scores.items() if s == 0.0]
    weak = [r for r, s in role_scores.items() if s > 0.0 and r not in named]
    return VizSuggestion(
        viz_kind=kind,
        score=round(min(draft.score, 1.0), 4),
        role_candidates=draft.role_candidates,
        unmet_roles=unmet,
        weak_roles=weak,
        match=draft.match,
        reasons=tuple(draft.reasons),
    )


def suggest_viz_kinds(
    dc_schema: dict[str, str],
    min_confidence: float = 0.0,
    dc_type: str | None = None,
    context: SuggestionContext | None = None,
) -> list[VizSuggestion]:
    """Rank every viz kind by how well `dc_schema` fits it.

    Three kinds of evidence feed the score, and each suggestion says which one
    it rests on (`match`) and why (`reasons`):

      - names: a domain kind (volcano, knee plot, sunburst) is a named match
        only when every distinctive role has a column named like it; a partial
        or dtype-only match stays under the recommended bar;
      - shape: the generic kinds read a table by its shape (a coordinate pair
        for scatter_xy, a reduction pair for embedding, several measurement
        axes for parallel_coordinates), and the role-less kinds by their
        structural gates;
      - context: a record card is recommended only when the dashboard tab has
        a tile whose selection it can follow (``context.selection_columns``).

    NO kind is dropped by default: the builder presents a ranked "suggest but
    tolerate" picker.

    Args:
        dc_schema: Map of column name → polars dtype name (the strings polars
            emits via `str(dtype)`).
        min_confidence: Optional score floor. Default 0.0 returns every kind,
            ranked. Raise it (e.g. 0.8) to keep only confident matches.
        dc_type: The DC's `config.type` (e.g. "table", "phylogeny"), used by
            kinds with a hard DC-type requirement. None = unknown (no gate).
        context: What the builder knows about the target dashboard tab. None =
            no dashboard (the DC card, the CLI): context-only kinds stay
            under the bar.

    Returns:
        List of VizSuggestion sorted by score desc, then viz_kind asc.
    """
    suggestions = [_score_kind(kind, dc_schema, dc_type, context) for kind in CANONICAL_SCHEMAS]
    suggestions = [s for s in suggestions if s.score >= min_confidence]
    suggestions.sort(key=lambda s: (-s.score, s.viz_kind))
    return suggestions


# Short human descriptions per role, keyed by role name (roles are reused
# across viz kinds). Surfaced in the builder's per-binding tooltip alongside the
# accepted dtypes. Roles without an entry fall back to an empty description.
_ROLE_DESCRIPTIONS: dict[str, str] = {
    "feature_id": "Identifier for each feature / gene / row (e.g. gene_id, ENSEMBL id).",
    "effect_size": "Magnitude of change, typically log2 fold change.",
    "significance": "Statistical significance — p-value or adjusted p / FDR.",
    "sample_id": "Identifier for each sample / observation.",
    "dim_1": "First embedding coordinate (PC1 / UMAP1 / tSNE1).",
    "dim_2": "Second embedding coordinate (PC2 / UMAP2 / tSNE2).",
    "dim_3": "Optional third embedding coordinate for 3D plots.",
    "chr": "Chromosome / contig name.",
    "chromosome": "Chromosome / contig name.",
    "pos": "Genomic or sequence position (integer).",
    "position": "Genomic or sequence position (integer).",
    "score": "Value plotted on the y-axis (e.g. -log10 p, signal).",
    "taxon": "Taxon / lineage name, or tree tip label.",
    "rank": "Taxonomic rank / level (e.g. Phylum, Genus).",
    "abundance": "Abundance / count / relative frequency.",
    "depth": "Sequencing / sampling depth.",
    "metric": "Diversity or summary metric value.",
    "contrast": "Comparison / contrast label (group vs group).",
    "lfc": "Log2 fold change.",
    "term": "Pathway / GO term / gene-set name.",
    "nes": "Normalised enrichment score.",
    "padj": "Adjusted p-value / FDR.",
    "gene_count": "Number of genes in the set.",
    "index": "Row identifier used as the heatmap index.",
    "avg_log_intensity": "Average log intensity — MA-plot x-axis (e.g. baseMean).",
    "log2_fold_change": "Log2 fold change — MA-plot y-axis.",
    "cluster": "Cluster / cell-type label.",
    "gene": "Gene / feature name.",
    "mean_expression": "Mean expression level (dot colour).",
    "frac_expressing": "Fraction of cells expressing (dot size).",
    "category": "Categorical grouping / annotation.",
    "p_value": "P-value for the QQ distribution.",
    "mutation_type": "Mutation class / variant consequence.",
    "value": "Numeric value plotted (e.g. coverage).",
    "label": "Optional text label for points.",
    "color": "Optional column mapped to point colour.",
    "feature": "Optional feature annotation.",
    "effect": "Optional effect-size column.",
    "iter": "Rarefaction iteration index.",
    "group": "Grouping column for colouring / faceting.",
    "source": "Source / database of the term.",
    "end": "End coordinate of the interval.",
    "start": "Start coordinate of the interval.",
    "sample": "Optional sample column for faceting.",
}

# Per-kind overrides for roles whose meaning is not the one the flat map above
# assumes. Role names are shared across kinds, so `rank` reads as a taxonomic
# level for stacked_taxonomy and as a position in a ranked gene list for GSEA;
# a single description cannot be right for both. Consulted before the flat map.
_KIND_ROLE_DESCRIPTIONS: dict[AdvancedVizKind, dict[str, str]] = {
    "profile": {
        "series": "One curve per distinct value (sample, group, target).",
        "x": "Shared x-axis: distance to a reference point, bin, or length.",
        "y": "Curve height: signal, coverage, or frequency.",
        "lower": "Optional lower bound of the confidence ribbon.",
        "upper": "Optional upper bound of the confidence ribbon.",
    },
    "signal_matrix": {
        "region_id": "One matrix row per region (peak, gene, interval).",
        "position": "Offset from the reference point, one matrix column each.",
        "value": "Signal at that region and offset, drawn as the cell colour.",
    },
    "fusion_structure": {
        "fusion_id": "One small multiple per fusion (e.g. GENE1--GENE2).",
        "partner": "Which partner gene the feature sits on: one lane each.",
        "feature": "Annotated feature drawn along the partner, e.g. a protein domain.",
        "start": "Feature start along the partner.",
        "end": "Feature end along the partner.",
        "breakpoint": "Optional fusion breakpoint, marked on the lane.",
        "retained": "Optional retained fraction of the feature, in [0, 1] or a 0/1 flag.",
        "colour_by": "Optional column driving the feature colour.",
    },
    "gene_arrow_track": {
        "contig": "One lane per contig / scaffold.",
        "feature_id": "Identifier of the gene or CDS drawn as an arrow.",
        "strand": "Arrow direction: '+' points right, '-' points left.",
        "class": "Optional feature class driving the arrow colour.",
        "region_start": "Optional start of the neighbourhood band behind the arrows.",
        "region_end": "Optional end of the neighbourhood band behind the arrows.",
    },
    "gsea_running_score": {
        "gene_set": "Gene set / pathway the running score belongs to.",
        "rank": "Position in the ranked gene list.",
        "running_es": "Running enrichment score at that rank.",
        "member": "Optional flag marking the ranks that are set members.",
        "metric": "Optional ranking metric, drawn as bars under the curve.",
    },
    "sashimi": {
        "start": "Junction donor position.",
        "end": "Junction acceptor position.",
        "count": "Reads supporting the junction, driving the arc width.",
        "annotation": "Optional junction annotation (known / novel, gene).",
    },
    # The flat map reads `feature_id` as "the identifier of each row", which is
    # the one thing it is not here: it is the lane the stems are drawn on, and
    # binding it to something with thousands of levels collapses the panel into
    # a single-value dropdown.
    "lollipop": {
        "feature_id": "One subplot lane per distinct value: the track the stems sit on.",
        "position": "Where each stem stands along the lane's shared x-axis.",
        "category": "Stem and head colour: consequence, direction, class.",
        "effect": "Optional magnitude, drawn as the stem height and the head size.",
        "label": "Optional name for each stem, used in the hover and the top-N labels.",
    },
    "record_card": {
        "id": "Column the incoming selection is matched against: which row the card shows.",
        "title": "Optional column shown as the card's heading.",
    },
    "parallel_coordinates": {
        "sample": "One polyline per distinct value: the line identity, not a facet.",
        "group": "Optional categorical column driving the line colour.",
    },
}


def _role_description(kind: AdvancedVizKind, role: str) -> str:
    """The tooltip for one role of one kind, kind-specific text winning."""
    return _KIND_ROLE_DESCRIPTIONS.get(kind, {}).get(role) or _ROLE_DESCRIPTIONS.get(role, "")


def role_dtype_specs(kind: AdvancedVizKind) -> dict[str, dict[str, object]]:
    """Per-role spec for a viz kind, required first then optional.

    Returns ``{role: {"required": bool, "dtypes": sorted([...]), "description": str}}``.
    Exposed via the `/advanced_viz/kinds` descriptor so the React builder drives
    its binding dropdowns, dtype validation and per-binding tooltips from the
    backend instead of duplicating the dtype tables in TypeScript.
    """
    specs: dict[str, dict[str, object]] = {}
    for role, accepted in CANONICAL_SCHEMAS[kind].items():
        specs[role] = {
            "required": True,
            "dtypes": sorted(accepted),
            "description": _role_description(kind, role),
        }
    for role, accepted in _OPTIONAL_ROLES.get(kind, {}).items():
        specs[role] = {
            "required": False,
            "dtypes": sorted(accepted),
            "description": _role_description(kind, role),
        }
    return specs


__all__ = [
    "BindingError",
    "CANONICAL_SCHEMAS",
    "EmbeddingConfig",
    "ManhattanConfig",
    "RECOMMENDED_SCORE",
    "ROLE_NAMES",
    "StackedTaxonomyConfig",
    "VizSuggestion",
    "VolcanoConfig",
    "role_dtype_specs",
    "suggest_viz_kinds",
    "validate_binding",
]

# ---------------------------------------------------------------------------
# Kind descriptors — what the builder's viz-kind picker shows
# ---------------------------------------------------------------------------

# Lives here rather than in the API route that serves it because two consumers
# need it and only one of them can import FastAPI: `GET /advanced_viz/kinds`
# (the running app) and `depictio dev catalog kinds --json` (the snapshot Tool
# Studio ships, so its picker matches the app's with no backend). It is data,
# not behaviour — label, one-line description, icon, and the "tool" flag for
# the kinds that compute a statistic before plotting it.
KIND_METADATA: dict[AdvancedVizKind, dict[str, Any]] = {
    "phylogenetic": {
        "label": "Phylogenetic tree",
        "description": "Newick tree + tip metadata (Microreact-style): 5 layouts, tip search, subtree highlight.",
        "icon": "tabler:hierarchy-3",
    },
    "scatter_xy": {
        "label": "Scatter (X/Y)",
        "description": "Numeric against numeric, with optional colour, marker size, point labels and a reference line.",
        "icon": "tabler:chart-dots",
    },
    "volcano": {
        "label": "Volcano plot",
        "description": "Effect size vs significance, threshold lines, search & top-N labels.",
        "icon": "tabler:chart-scatter",
    },
    "embedding": {
        "label": "Embedding / clustering",
        "description": (
            "2D/3D sample embedding (PCA / UMAP / t-SNE / PCoA) — accepts a "
            "pre-computed DC (dim_1, dim_2 columns) or runs the reduction "
            "live on a wide sample×feature matrix DC via Celery."
        ),
        "icon": "tabler:atom",
    },
    "manhattan": {
        "label": "Manhattan plot",
        "description": "chr / pos / score scatter — works for true GWAS, peak qvalues, and variant AF.",
        "icon": "tabler:chart-histogram",
        "category": "tool",
    },
    "genome_view": {
        "label": "Genome view",
        "description": (
            "chr / pos / score drawn by GenomeSpy on a chromosome-aware locus axis: "
            "native genome zoom, points, intervals or coverage bars, per-sample lanes, "
            "a gene annotation lane, and a region brush that filters the dashboard."
        ),
        "icon": "tabler:dna-2",
        "category": "tool",
    },
    "stacked_taxonomy": {
        "label": "Stacked taxonomy",
        "description": "Per-sample stacked relative-abundance bar with rank dropdown.",
        "icon": "tabler:chart-pie",
    },
    "rarefaction": {
        "label": "Rarefaction curves",
        "description": "Alpha-diversity vs sequencing depth — one line per sample with ±SE band and group colouring.",
        "icon": "tabler:chart-line",
    },
    "da_barplot": {
        "label": "Differential-abundance bars (tool)",
        "description": (
            'Ranked signed-LFC top-N features for differential abundance — `contrast_view: "all"` '
            "(default) faceted small-multiples, or any specific contrast value for a single-panel drill-in. "
            "Replaces the previous ancombc_differentials kind (auto-migrated)."
        ),
        "icon": "tabler:chart-bar-popular",
        "category": "tool",
    },
    "enrichment": {
        "label": "GSEA / pathway enrichment (tool)",
        "description": "Dot plot: term on y, NES on x, dot size = gene-set size, colour = -log10(padj).",
        "icon": "tabler:chart-dots",
        "category": "tool",
        "legacy": True,
    },
    "complex_heatmap": {
        "label": "ComplexHeatmap (clustered)",
        "description": "Clustered heatmap with dendrograms + annotation tracks. Server-side clustering via plotly-complexheatmap, dispatched as a Celery task.",
        "icon": "tabler:grid-pattern",
    },
    "upset_plot": {
        "label": "UpSet plot",
        "description": "Set-intersection visualisation (alternative to Venn diagrams). Server-side compute via plotly-upset, dispatched as a Celery task.",
        "icon": "tabler:chart-bar-popular",
    },
    "ma": {
        "label": "MA plot",
        "description": "Mean log intensity vs log2 fold change — same hits as a volcano, classic DE / proteomics layout.",
        "icon": "tabler:chart-bubble",  # tabler has no chart-bell; that one rendered blank
        "legacy": True,
    },
    "dot_plot": {
        "label": "Dot plot",
        "description": "scanpy / Seurat marker dot plot: cluster × gene with size = fraction expressing, colour = mean expression.",
        "icon": "tabler:circle-dot",
    },
    "lollipop": {
        "label": "Lollipop / needle plot",
        "description": "Variant tracks along genes: vertical stems coloured by consequence, marker size = effect.",
        "icon": "tabler:chart-arcs",
    },
    "qq": {
        "label": "QQ plot",
        "description": "Quantile-quantile of -log10(p) vs uniform null — standard p-value distribution QC.",
        "icon": "tabler:chart-line",
        "legacy": True,
    },
    "sunburst": {
        "label": "Sunburst",
        "description": "Hierarchical taxonomy / pathway viewer — concentric rings from root to leaf.",
        "icon": "tabler:sun",
    },
    "oncoplot": {
        "label": "Oncoplot",
        "description": "Sample × gene mutation matrix with discrete mutation-type colours and frequency strips.",
        "icon": "tabler:grid-pattern",
    },
    "coverage_track": {
        "label": "Coverage track",
        "description": "Read depth / signal along a coordinate axis. Optional per-sample faceting and categorical annotation lane (gene region, peak class, …).",
        "icon": "tabler:chart-area-line",
    },
    "sankey": {
        "label": "Sankey (categorical flow)",
        "description": "Flow across N ordered categorical levels (e.g. sample → lineage → clade). Server-side aggregation, client-side colour / opacity tweaks.",
        "icon": "tabler:chart-sankey",
    },
    "pr_benchmark": {
        "label": "Precision-recall benchmark",
        "description": "Recall vs precision per callset with F1 iso-contours and y=x diagonal — top-right is best.",
        "icon": "tabler:target-arrow",
    },
    "roc_pr_curve": {
        "label": "ROC / PR curve",
        "description": "Threshold-sweep precision-recall curve with AUC, one line per tool / caller.",
        "icon": "tabler:chart-line",
        "legacy": True,
    },
    "confusion_matrix": {
        "label": "Confusion matrix",
        "description": "TP / FP / FN (/ TN) counts per callset as a compact heatmap; optional row-normalisation.",
        "icon": "tabler:grid-dots",
    },
    "metric_ci_bars": {
        "label": "Metric bars with CI",
        "description": "Precision / recall / F1 bars with 95% confidence-interval whiskers.",
        "icon": "tabler:chart-bar",
    },
    "profile": {
        "label": "Signal profile",
        "description": (
            "Multi-series curve over a shared axis, with optional confidence "
            "ribbons and a reference line: metagene / TSS enrichment, "
            "fragment-length and insert-size distributions."
        ),
        "icon": "tabler:chart-line",
    },
    "signal_matrix": {
        "label": "Signal matrix",
        "description": (
            "One row per region, one column per offset: the heatmap half of a "
            "metagene plot, rows binned by mean rather than truncated."
        ),
        "icon": "tabler:grid-pattern",
    },
    "fusion_structure": {
        "label": "Fusion structure",
        "description": (
            "A gene fusion as its two partners end to end, one lane each, with "
            "protein domains placed along them and the breakpoint marked."
        ),
        "icon": "tabler:arrows-join-2",
    },
    "gene_arrow_track": {
        "label": "Gene arrow track",
        "description": (
            "Strand-aware arrows on a base-pair axis, one lane per contig: "
            "biosynthetic gene clusters, resistance islands, prophage regions."
        ),
        "icon": "tabler:arrow-big-right-lines",
    },
    "gsea_running_score": {
        "label": "GSEA running score",
        "description": (
            "The enrichment-score curve over the ranked list, its hit rug and "
            "the ranked metric, with the leading edge shaded."
        ),
        "icon": "tabler:chart-area-line",
    },
    "sashimi": {
        "label": "Splice junctions",
        "description": (
            "Junction arcs on a base-pair axis, arc width scaled by supporting "
            "reads: splicing evidence per locus."
        ),
        "icon": "tabler:chart-arcs",
    },
    "contact_map": {
        "label": "Contact map",
        "description": (
            "Binned Hi-C style contact matrix, symmetric heatmap with log "
            "colour scale, chromosome selector and optional row/column "
            "balancing."
        ),
        "icon": "tabler:layout-grid",
    },
    "knee_plot": {
        "label": "Knee plot",
        "description": (
            "Barcode-rank curve, UMI count vs rank on log-log axes, one line "
            "per sample, cell-calling cutoff marked."
        ),
        "icon": "tabler:trending-down",
    },
    "damage_profile": {
        "label": "Damage profile",
        "description": (
            "Ancient-DNA misincorporation frequency by position from the read "
            "end, 5p and 3p panels, C>T / G>A substitutions highlighted."
        ),
        "icon": "tabler:dna-2",
    },
    "group_compare": {
        "label": "Group comparison",
        "description": (
            "Differential test between two saved selection groups, computed on "
            "demand: a volcano of the features and the ranked table behind it."
        ),
        "icon": "tabler:arrows-diff",
    },
    "transcript_structure": {
        "label": "Transcript structure",
        "description": (
            "Isoforms of one gene stacked on a base-pair axis, exons as blocks "
            "and introns as lines, novel and known transcripts told apart."
        ),
        "icon": "tabler:layout-rows",
    },
    "cnv_profile": {
        "label": "Copy-number profile",
        "description": (
            "Log2 ratio per bin along the genome with the called segments over "
            "it and, when bound, the B-allele frequency underneath."
        ),
        "icon": "tabler:chart-dots-3",
    },
    "genome_chord": {
        "label": "Genome chord",
        "description": (
            "Chromosomes on a ring, one chord per link between two loci: gene "
            "fusions, translocations, structural variants."
        ),
        "icon": "tabler:circle-dotted",
    },
    "record_card": {
        "label": "Record card",
        "description": (
            "One row of a collection read as labelled fields and links, filled "
            "by the selection another tile emits. The detail half of a "
            "master/detail dashboard."
        ),
        "icon": "tabler:id",
    },
    "parallel_coordinates": {
        "label": "Parallel coordinates",
        "description": (
            "One polyline per sample across N metric axes, each axis brushable. "
            "Reads a many-column QC table as a whole where a scatter would need "
            "one panel per pair."
        ),
        "icon": "tabler:chart-line",
    },
}


#: Kinds that ship without a producer binding them yet.
#:
#: The registry test ``test_every_kind_is_reachable`` asserts that every kind
#: in ``AdvancedVizKind`` is reachable from a catalog ``renders_as`` entry or a
#: shipped dashboard, so a kind cannot be added, forgotten, and then found
#: years later with no way for a user to see it. This set is the audit list of
#: the exceptions, and it is meant to shrink: an entry here is a promise, not a
#: parking space. Retired kinds (``ma``, ``qq``, ``enrichment``,
#: ``roc_pr_curve``) are exempt by a different route, the alias table in
#: ``configs.py``.
INCUBATING: frozenset[str] = frozenset(
    {
        # differentialabundance's pinned prefix publishes no `tables/gsea/`, so
        # no pipeline run produces the ranked list this kind reads and only the
        # showcase's synthetic fixture binds it. Kept and flagged rather than
        # deleted; revisit on a re-pin.
        "gsea_running_score",
    }
)


def kind_descriptors() -> list[dict[str, Any]]:
    """Every advanced-viz kind as the builder's picker consumes it.

    `roles` carries the per-role accepted dtypes (required + optional) so the
    builder drives its binding dropdowns and validation from here rather than
    duplicating the dtype tables in TypeScript. `required_roles` is kept for
    backwards compatibility.
    """
    return [
        {
            "viz_kind": kind,
            "label": meta["label"],
            "description": meta["description"],
            "icon": meta["icon"],
            "required_roles": list(CANONICAL_SCHEMAS[kind].keys()),
            "roles": role_dtype_specs(kind),
            # Entries without an explicit category are pure visualisations.
            "category": meta.get("category", "plot"),
            # True for a kind that survives only so stored dashboards keep
            # loading: it is rewritten into a view of another kind at read
            # time (see `_KIND_ALIASES` in configs.py). Pickers hide these;
            # every other consumer treats an absent flag as False, which is
            # what makes adding it safe for a snapshot read by an older
            # client.
            "legacy": bool(meta.get("legacy", False)),
        }
        for kind, meta in KIND_METADATA.items()
    ]
