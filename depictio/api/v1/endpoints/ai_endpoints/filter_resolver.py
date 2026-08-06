"""Resolve LLM filter proposals into client-applicable filters.

Three proposal kinds come out of the analyze / resolve-filters prompts:

- ``set_widget`` — set an existing interactive component's value. Verified
  against the dashboard's interactive inventory so the LLM cannot target a
  component that does not exist.
- ``filter_expr`` — a Polars expression string. Gated through
  ``validate_filter_expr`` (the same sandbox the CLI-authored components
  use) before it ever reaches a client.
- ``threshold`` — a percentile request ("top 3% of X"). The quantile is
  computed here, server-side, on the delta table with the user's active
  filters applied, and substituted into a concrete comparison. This keeps
  the filter-expression allowlist free of quantile/rank primitives, at the
  disclosed cost of a point-in-time threshold.

Every failure downgrades to a warning string rather than an exception so
one bad proposal never voids the rest.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from bson import ObjectId

from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.api.v1.endpoints.ai_endpoints.context import DashboardContext
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    FilterProposal,
    ResolvedFilter,
    ThresholdSpec,
)
from depictio.models.components.filter_expr import validate_filter_expr

logger = logging.getLogger(__name__)

# Column names are interpolated into `col('<name>')` — refuse anything that
# could escape the single-quoted string. Delta column names in practice are
# word characters plus a few separators.
_SAFE_COLUMN = re.compile(r"^[\w .\-/%()+]+$")


def _describe_threshold(spec: ThresholdSpec, value: float) -> str:
    if spec.op in (">=", ">"):
        pct = (1.0 - spec.q) * 100.0
        side = "top"
    else:
        pct = spec.q * 100.0
        side = "bottom"
    return f"{side} {pct:.3g}% of {spec.column} ⇒ {spec.column} {spec.op} {value:.6g}"


def resolve_threshold(
    spec: ThresholdSpec,
    *,
    workflow_id: str,
    data_collection_id: str,
    active_filters: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Compute the concrete (filter_expr, description) for a ThresholdSpec.

    Raises ValueError with an LLM/user-readable message on any failure
    (unknown column, non-numeric column, empty data).
    """
    if not _SAFE_COLUMN.match(spec.column):
        raise ValueError(f"unsupported column name for threshold: {spec.column!r}")

    df = load_deltatable_lite(
        workflow_id=ObjectId(workflow_id),
        data_collection_id=ObjectId(data_collection_id),
        metadata=active_filters or None,
        select_columns=[spec.column],
    )
    if df is None or df.height == 0:
        raise ValueError("no rows available to compute the threshold on")
    if spec.column not in df.columns:
        raise ValueError(f"column {spec.column!r} not found in the data collection")

    series = df.get_column(spec.column)
    try:
        value = series.quantile(spec.q, interpolation="nearest")
    except Exception as e:  # noqa: BLE001 — non-numeric columns etc.
        raise ValueError(f"cannot compute quantile on {spec.column!r}: {e}") from e
    if value is None:
        raise ValueError(f"quantile of {spec.column!r} is undefined (all nulls?)")

    expr = f"col('{spec.column}') {spec.op} {float(value)!r}"
    # Belt and braces: the synthesized expression must itself pass the
    # sandbox validator before we hand it to any client.
    validate_filter_expr(expr)
    return expr, _describe_threshold(spec, float(value))


def resolve_proposals(
    proposals: list[FilterProposal],
    *,
    dashboard_ctx: DashboardContext,
    workflow_id: str | None,
    data_collection_id: str | None,
    active_filters: list[dict[str, Any]] | None = None,
) -> tuple[list[ResolvedFilter], list[str]]:
    """Validate/resolve proposals; return (resolved, warnings)."""
    resolved: list[ResolvedFilter] = []
    warnings: list[str] = []
    widget_ids = {f.component_id for f in dashboard_ctx.filters if f.component_id}

    for proposal in proposals:
        if proposal.kind == "set_widget":
            if not proposal.component_id:
                warnings.append("set_widget proposal without component_id — skipped")
                continue
            if proposal.component_id not in widget_ids:
                warnings.append(
                    f"set_widget targets unknown component {proposal.component_id!r} — skipped"
                )
                continue
            resolved.append(
                ResolvedFilter(
                    kind="set_widget",
                    component_id=proposal.component_id,
                    value=proposal.value,
                    dc_id=data_collection_id,
                    description=proposal.reason,
                )
            )

        elif proposal.kind == "filter_expr":
            if not proposal.filter_expr:
                warnings.append("filter_expr proposal without an expression — skipped")
                continue
            try:
                validate_filter_expr(proposal.filter_expr)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"invalid filter_expr {proposal.filter_expr!r}: {e}")
                continue
            resolved.append(
                ResolvedFilter(
                    kind="filter_expr",
                    filter_expr=proposal.filter_expr,
                    dc_id=data_collection_id,
                    description=proposal.reason,
                )
            )

        elif proposal.kind == "threshold":
            if proposal.threshold is None:
                warnings.append("threshold proposal without a threshold spec — skipped")
                continue
            if not workflow_id or not data_collection_id:
                warnings.append("threshold proposal but no data collection in scope — skipped")
                continue
            try:
                expr, description = resolve_threshold(
                    proposal.threshold,
                    workflow_id=workflow_id,
                    data_collection_id=data_collection_id,
                    active_filters=active_filters,
                )
            except Exception as e:  # noqa: BLE001
                warnings.append(f"threshold on {proposal.threshold.column!r} failed: {e}")
                continue
            if proposal.reason:
                description = f"{description} ({proposal.reason})"
            resolved.append(
                ResolvedFilter(
                    kind="filter_expr",
                    filter_expr=expr,
                    dc_id=data_collection_id,
                    description=description,
                )
            )

    for warning in warnings:
        logger.warning("filter_resolver: %s", warning)
    return resolved, warnings
