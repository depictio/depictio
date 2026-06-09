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
from typing import Literal

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
            if alias in n or n in alias:
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
_MIN_FLOAT_COLS: dict[AdvancedVizKind, int] = {"complex_heatmap": 8}
_MIN_INT_COLS: dict[AdvancedVizKind, int] = {"upset_plot": 3}
_MIN_STRING_COLS: dict[AdvancedVizKind, int] = {"sankey": 2}
_KIND_REQUIRES_DC_TYPE: dict[AdvancedVizKind, str] = {"phylogenetic": "phylogeny"}
_EMBEDDING_LIVE_MIN_NUMERIC = 10

# Float columns whose name is purely a statistic (DESeq2-style results) — used
# to reject complex_heatmap / sankey, which want a sample matrix / categorical
# flow, not a stats table.
_STAT_LIKE_FLOAT_RE = re.compile(
    r"^(basemean|log2foldchange|lfcse|stat|pvalue|padj|qvalue|p_?val|fdr|"
    r"log2fc|effect_size|significance|nes|es|score)$"
)

# Multiplier applied when a structural gate isn't met: the kind stays in the
# ranked list but drops well below the "recommended" threshold.
_GATE_PENALTY = 0.25

# A required role scoring at/above this counts as a strong (name-aware) match;
# below it the role is "weak" (satisfied by dtype/cast only).
_STRONG_ROLE_SCORE = 0.75

# Score at/above which the builder surfaces a kind under "Recommended".
RECOMMENDED_SCORE = 0.8


@dataclass(frozen=True)
class VizSuggestion:
    """How well a viz kind fits a DC schema, plus the matching detail.

    score is 0.0 - 1.0 (graded): a weighted blend of per-role dtype
    compatibility and column-name similarity across the kind's required roles,
    nudged by optional-role matches and structural gates. ~1.0 means every
    required role has a strongly-named, dtype-exact column.

    role_candidates maps each required role → dtype-compatible column names,
    ranked best-first. The UI uses this to pre-fill the binding dropdowns.

    unmet_roles are required roles with no compatible column at all; weak_roles
    are satisfied only by dtype/cast (no strong name match). Both drive the
    builder's inline guidance.
    """

    viz_kind: AdvancedVizKind
    score: float
    role_candidates: dict[str, list[str]]
    unmet_roles: list[str]
    weak_roles: list[str]


def _count_dtypes(dc_schema: dict[str, str], dtypes: frozenset[str]) -> int:
    return sum(1 for d in dc_schema.values() if d in dtypes)


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
        score = 0.8 if ints >= min_int else _GATE_PENALTY * min(ints / min_int, 1.0)

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
        score = 0.8 if (strings >= min_string and not stat_floats) else _GATE_PENALTY

    required_dc_type = _KIND_REQUIRES_DC_TYPE.get(kind)
    if required_dc_type is not None and dc_type is not None and dc_type != required_dc_type:
        score *= _GATE_PENALTY

    return min(score, 1.0)


def _score_kind(
    kind: AdvancedVizKind, dc_schema: dict[str, str], dc_type: str | None
) -> VizSuggestion:
    """Score one viz kind against the DC schema."""
    required = CANONICAL_SCHEMAS[kind]
    role_aliases = ROLE_NAMES.get(kind, {})
    role_scores: dict[str, float] = {}
    role_candidates: dict[str, list[str]] = {}
    for role, accepted in required.items():
        aliases = role_aliases.get(role, frozenset({role}))
        role_scores[role], role_candidates[role] = _score_role(dc_schema, aliases, accepted)

    base = sum(role_scores.values()) / len(required) if required else 0.0

    # Optional-role matches nudge an already-matching kind upward (capped).
    optional = _OPTIONAL_ROLES.get(kind, {})
    if base > 0 and optional:
        opt = sum(
            _score_role(dc_schema, frozenset({role}), accepted)[0]
            for role, accepted in optional.items()
        )
        base = base + 0.1 * (opt / len(optional))

    # Live-compute embedding: a wide numeric matrix with a sample_id column is a
    # valid embedding even without precomputed dim_1/dim_2.
    if kind == "embedding":
        sample_score, _ = _score_role(
            dc_schema, role_aliases.get("sample_id", frozenset({"sample_id"})), _STRING
        )
        if sample_score > 0 and _count_dtypes(dc_schema, _NUMERIC) >= _EMBEDDING_LIVE_MIN_NUMERIC:
            base = max(base, 0.5 + 0.35 * sample_score)

    score = _apply_structural_gates(kind, dc_schema, base, dc_type)

    unmet = [r for r, s in role_scores.items() if s == 0.0]
    weak = [r for r, s in role_scores.items() if 0.0 < s < _STRONG_ROLE_SCORE]
    return VizSuggestion(
        viz_kind=kind,
        score=round(score, 4),
        role_candidates=role_candidates,
        unmet_roles=unmet,
        weak_roles=weak,
    )


def suggest_viz_kinds(
    dc_schema: dict[str, str],
    min_confidence: float = 0.0,
    dc_type: str | None = None,
) -> list[VizSuggestion]:
    """Rank every viz kind by how well `dc_schema` fits it.

    Each kind gets a graded `score` in [0, 1] blending per-role dtype
    compatibility (exact > castable) and column-name similarity (exact alias >
    fuzzy), plus optional-role nudges and structural gates (e.g. heatmap needs
    a wide float matrix, phylogenetic needs a phylogeny-type DC). Unlike the
    old binary matcher, NO kind is dropped by default — the builder presents a
    ranked "suggest but tolerate" picker.

    Args:
        dc_schema: Map of column name → polars dtype name (the strings polars
            emits via `str(dtype)`).
        min_confidence: Optional score floor. Default 0.0 returns every kind,
            ranked. Raise it (e.g. 0.8) to keep only confident matches.
        dc_type: The DC's `config.type` (e.g. "table", "phylogeny"), used by
            kinds with a hard DC-type requirement. None = unknown (no gate).

    Returns:
        List of VizSuggestion sorted by score desc, then viz_kind asc.
    """
    suggestions = [_score_kind(kind, dc_schema, dc_type) for kind in CANONICAL_SCHEMAS]
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
    "sample": "Optional sample column for faceting.",
}


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
            "description": _ROLE_DESCRIPTIONS.get(role, ""),
        }
    for role, accepted in _OPTIONAL_ROLES.get(kind, {}).items():
        specs[role] = {
            "required": False,
            "dtypes": sorted(accepted),
            "description": _ROLE_DESCRIPTIONS.get(role, ""),
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
