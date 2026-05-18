"""Heatmap parameter collection helpers, extracted from depictio.dash.modules.figure_component.utils."""

import json
from typing import Any

# ---------------------------------------------------------------------------
# Heatmap parameter sets
# ---------------------------------------------------------------------------

# Parameters accepted by ComplexHeatmap.from_dataframe()
HEATMAP_FROM_DF_PARAMS: frozenset[str] = frozenset(
    {
        "index_column",
        "value_columns",
        "row_annotations",
        "col_annotations",
        "row_annotation_side",
        "col_annotation_side",
    }
)

# Parameters accepted by ComplexHeatmap.__init__()
HEATMAP_INIT_PARAMS: frozenset[str] = frozenset(
    {
        "cluster_rows",
        "cluster_cols",
        "colorscale",
        "normalize",
        "use_webgl",
        "split_rows_by",
        "cluster_method",
        "cluster_metric",
        "dendro_ratio",
        "name",
        "title",
        "description",
        "width",
        "height",
    }
)

# Combined set of all recognized heatmap parameters
HEATMAP_PARAMS: frozenset[str] = HEATMAP_FROM_DF_PARAMS | HEATMAP_INIT_PARAMS

# Parameters that accept comma-separated list values
HEATMAP_LIST_PARAMS: frozenset[str] = frozenset({"value_columns", "row_annotations"})

# Boolean heatmap parameters
HEATMAP_BOOL_PARAMS: frozenset[str] = frozenset({"cluster_rows", "cluster_cols", "use_webgl"})

# Integer heatmap parameters
HEATMAP_INT_PARAMS: frozenset[str] = frozenset({"width", "height"})

# Float heatmap parameters
HEATMAP_FLOAT_PARAMS: frozenset[str] = frozenset({"dendro_ratio"})


def _parse_heatmap_param(key: str, val: Any) -> Any:
    """Parse a single heatmap parameter value from YAML/JSON string forms.

    Handles JSON-encoded strings, comma-separated lists, booleans, and
    numeric types for ComplexHeatmap parameters.
    """
    if not isinstance(val, str):
        return val

    stripped = val.strip()

    # JSON-encoded dicts/lists (row_annotations, col_annotations, value_columns)
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            pass

    # Comma-separated list params (value_columns, row_annotations)
    if key in HEATMAP_LIST_PARAMS:
        return [s.strip() for s in val.split(",") if s.strip()]

    # Boolean params
    if key in HEATMAP_BOOL_PARAMS:
        return stripped.lower() in ("true", "1", "yes")

    # Float params
    if key in HEATMAP_FLOAT_PARAMS:
        try:
            return float(val)
        except ValueError:
            return None

    # Integer params
    if key in HEATMAP_INT_PARAMS:
        try:
            return int(val)
        except ValueError:
            return None

    return val


def collect_heatmap_kwargs(cleaned_kwargs: dict) -> dict[str, Any]:
    """Filter and parse heatmap-specific parameters from the full kwargs dict.

    Args:
        cleaned_kwargs: Full parameter dictionary (may contain non-heatmap keys)

    Returns:
        Dictionary of parsed parameters suitable for ComplexHeatmap
    """
    heatmap_kwargs: dict[str, Any] = {}
    for k, v in cleaned_kwargs.items():
        if k in HEATMAP_PARAMS and v is not None and v != "":
            parsed = _parse_heatmap_param(k, v)
            if parsed is not None:
                heatmap_kwargs[k] = parsed
    return heatmap_kwargs
