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

from dataclasses import dataclass

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

CANONICAL_SCHEMAS: dict[AdvancedVizKind, dict[str, frozenset[str]]] = {
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
# typical short forms). When adding a producer to producers.py whose columns
# map to a viz role, mirror those column names here so the dtype-aware
# suggester surfaces the same viz kind the producer fingerprint does.
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
}


@dataclass(frozen=True)
class BindingError:
    role: str
    column: str | None
    reason: str  # e.g. "column not in DC", "wrong dtype: got Int64 expected Float64"


def _role_to_config_field(role: str) -> str:
    """Roles map to ``<role>_col`` fields on each VizConfig submodel."""
    return f"{role}_col"


def validate_binding(config: VizConfig, dc_schema: dict[str, str]) -> list[BindingError]:
    """Validate that the DC schema satisfies the viz's canonical schema.

    Args:
        config: The viz's per-kind config (e.g. VolcanoConfig).
        dc_schema: Map of column name -> polars dtype name (e.g. {"lfc": "Float64"}).
                   Dtype names are the strings polars produces via ``str(dtype)``.

    Returns:
        List of BindingError. Empty list = valid.
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
            errors.append(
                BindingError(
                    role=role,
                    column=col,
                    reason=(
                        f"column '{col}' has dtype {actual!r}, "
                        f"expected one of {sorted(accepted_dtypes)}"
                    ),
                )
            )

    for role, accepted_dtypes in optional.items():
        col = getattr(config, _role_to_config_field(role), None)
        if not col:
            continue  # optional + unbound = fine
        if col not in dc_schema:
            errors.append(BindingError(role=role, column=col, reason=f"column '{col}' not in DC"))
            continue
        actual = dc_schema[col]
        if actual not in accepted_dtypes:
            errors.append(
                BindingError(
                    role=role,
                    column=col,
                    reason=(
                        f"optional column '{col}' has dtype {actual!r}, "
                        f"expected one of {sorted(accepted_dtypes)}"
                    ),
                )
            )

    return errors


# ---------------------------------------------------------------------------
# Reverse-lookup: "given a DC schema, which viz kinds / producers fit?"
#
# Drives the React DC card "Suggested visualisations" chips and the
# component-creation flow's DC pre-filter. Pure functions — no DB, no IO,
# no DC mutation. Testable against any (col → dtype) dict.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VizSuggestion:
    """A viz kind that a DC could feasibly satisfy plus the matching detail.

    confidence is 0.0 - 1.0 = fraction of required roles satisfied.
    A confidence of 1.0 means every required role has at least one
    candidate column with a compatible dtype.

    role_candidates maps each required role → list of column names whose
    dtype is in the role's accepted set. The UI uses this to pre-fill
    the binding dropdowns at component-creation time.
    """

    viz_kind: AdvancedVizKind
    confidence: float
    role_candidates: dict[str, list[str]]
    producer_name: str | None = None  # populated when a Producer fingerprint matches


def suggest_viz_kinds(
    dc_schema: dict[str, str],
    min_confidence: float = 1.0,
) -> list[VizSuggestion]:
    """Return viz kinds whose required roles can be satisfied by `dc_schema`.

    A role is "satisfied" when the DC has a column whose NAME is in the
    role's `ROLE_NAMES` alias set AND whose dtype is in the role's accepted
    dtype set. Dtype-only matches still appear in `role_candidates` so the
    binding UI can offer them as fallback choices, but they don't count
    toward confidence — otherwise every Numeric+String DC matches every viz.

    Args:
        dc_schema: Map of column name → polars dtype name (the strings
            polars emits via `str(dtype)`).
        min_confidence: Minimum fraction of required roles that must have
            a name+dtype match. Default 1.0 = only return viz kinds where
            every required role has a named candidate. Drop to ~0.7 to
            surface "almost a match" viz kinds in an exploratory UI.

    Returns:
        Sorted (by confidence desc, then viz_kind asc) list of
        VizSuggestion. Empty when nothing fits.
    """
    suggestions: list[VizSuggestion] = []
    for kind, required in CANONICAL_SCHEMAS.items():
        if not required:
            # Schemas with no required roles (sankey, upset_plot) match
            # via producer fingerprints in producers.py instead — the
            # suggestion engine can't say anything useful about them from
            # schema alone.
            continue
        role_aliases = ROLE_NAMES.get(kind, {})
        role_candidates: dict[str, list[str]] = {}
        satisfied = 0
        for role, accepted in required.items():
            dtype_matches = [col for col, dtype in dc_schema.items() if dtype in accepted]
            role_candidates[role] = dtype_matches
            aliases = {a.lower() for a in role_aliases.get(role, frozenset({role}))}
            if any(col.lower() in aliases for col in dtype_matches):
                satisfied += 1
        confidence = satisfied / len(required)
        if confidence >= min_confidence:
            suggestions.append(
                VizSuggestion(viz_kind=kind, confidence=confidence, role_candidates=role_candidates)
            )
    suggestions.sort(key=lambda s: (-s.confidence, s.viz_kind))
    return suggestions


def suggest_producers(dc_schema: dict[str, str]) -> list[tuple[str, float]]:
    """Identify known tool outputs whose required_columns fingerprint matches.

    Producer fingerprints are stricter than viz suggestions — they look at
    actual column NAMES (case-sensitive), not just dtype shapes. When a DC
    matches a producer, we can pre-fill role bindings exactly (via the
    producer's role_mapping) instead of guessing.

    Returns:
        Sorted list of (producer_name, match_ratio). match_ratio = fraction
        of the producer's required_columns present in dc_schema. Only
        producers with match_ratio == 1.0 (full fingerprint match) are
        meaningful — anything less is coincidence.
    """
    # Lazy import to keep schemas.py import-cheap.
    from depictio.models.components.advanced_viz.producers import KNOWN_PRODUCERS

    matches: list[tuple[str, float]] = []
    cols = set(dc_schema.keys())
    for p in KNOWN_PRODUCERS:
        if not p.required_columns:
            continue  # non-tabular producers (e.g. Newick) don't fingerprint
        present = len(p.required_columns & cols)
        ratio = present / len(p.required_columns)
        if ratio == 1.0:
            matches.append((p.name, ratio))
    matches.sort(key=lambda m: (-m[1], m[0]))
    return matches


__all__ = [
    "BindingError",
    "CANONICAL_SCHEMAS",
    "EmbeddingConfig",
    "ManhattanConfig",
    "ROLE_NAMES",
    "StackedTaxonomyConfig",
    "VizSuggestion",
    "VolcanoConfig",
    "suggest_producers",
    "suggest_viz_kinds",
    "validate_binding",
]
