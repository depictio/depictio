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


__all__ = [
    "BindingError",
    "CANONICAL_SCHEMAS",
    "EmbeddingConfig",
    "ManhattanConfig",
    "StackedTaxonomyConfig",
    "VolcanoConfig",
    "validate_binding",
]
