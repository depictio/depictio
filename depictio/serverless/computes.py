"""Export-time computes shared by both producers (RFC §13, large-compute kinds).

``group_compare`` runs a per-feature test between two groups of rows. A bundle
freezes the comparison its tile OPENS on — what a reader sees first on the live
dashboard — with the server's own ``group_compare_from_frame``; the runtime
hands that result back for that pair only (apiShim ``dispatchGroupCompare``).
Producer A runs it through the Celery task function; producer B, which never
reaches a server, calls the service function on the local Parquet (it imports
only numpy / polars / scipy).
"""

from __future__ import annotations

from typing import Any

#: The renderer's seeded defaults (GroupCompareRenderer), which the Celery
#: task falls back to as well (``_given``).
GROUP_COMPARE_DEFAULTS: dict[str, Any] = {
    "index_col": "index",
    "test": "wilcoxon",
    "log_transform": True,
    "max_features": 2000,
    "min_observations": 3,
    "fdr_threshold": 0.05,
    "log2fc_threshold": 1.0,
    "top_n_labels": 20,
}


def group_compare_opening_pair(
    labels: list[str], default_a: Any, default_b: Any
) -> tuple[str, str] | None:
    """The pair a group_compare tile opens on, from its label values.

    ``configuredGroupPair`` with no saved selection groups (a bundle has none
    at its default state): both configured defaults when they name two
    different values, else the first two values in the order
    ``fetchUniqueValues`` lists them (sorted strings).
    """
    if default_a and default_b and str(default_a) != str(default_b):
        if str(default_a) in labels and str(default_b) in labels:
            return str(default_a), str(default_b)
    return (labels[0], labels[1]) if len(labels) >= 2 else None


def group_compare_settings(config: dict[str, Any]) -> dict[str, Any]:
    """The request's statistic settings from a tile's persisted config."""
    out: dict[str, Any] = {}
    for key, default in GROUP_COMPARE_DEFAULTS.items():
        value = config.get(key)
        out[key] = default if value is None or value == "" else value
    out["log_transform"] = bool(out["log_transform"])
    for key in ("max_features", "min_observations", "top_n_labels"):
        out[key] = int(out[key])
    for key in ("fdr_threshold", "log2fc_threshold"):
        out[key] = float(out[key])
    return out


def selectors(group_col: str, pair: tuple[str, str]) -> dict[str, Any]:
    """The two arms of the request, as the renderer builds them from label values."""
    return {
        "group_a": {"label": pair[0], "column": group_col, "values": [pair[0]]},
        "group_b": {"label": pair[1], "column": group_col, "values": [pair[1]]},
    }


def open_on_frozen_request(config: dict[str, Any], request: dict[str, Any]) -> None:
    """Point a bundled tile's defaults at the frozen pair and run it on mount."""
    config["default_group_a"] = request["group_a"]["label"]
    config["default_group_b"] = request["group_b"]["label"]
    config["auto_run"] = True


def frozen_detail(kind: str, request: dict[str, Any]) -> str:
    pair = f"{request['group_a']['label']} vs {request['group_b']['label']}"
    return (
        f"advanced_viz '{kind}': the opening pair ({pair}) was computed at export with "
        "the server's own function; another pair or filter state needs the live server"
    )
