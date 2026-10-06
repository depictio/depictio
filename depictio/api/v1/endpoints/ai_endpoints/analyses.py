"""Persistence for read-only analysis reports (`ai_analyses` collection).

Same policy as `ai_summaries`: reports are derived artifacts keyed by
dashboard, never written into the dashboard document itself. Unlike
summaries there is no hash cache — every run is its own report, addressed
by id, so an analysis can be reopened after the stream that produced it
is gone.

Findings are validated here, on the way in: `parse_findings` drops any
claim whose `evidence_step_ids` don't resolve to actual executed steps
and reports the drop as a warning. A claim without evidence is not
rendered with a caveat, it is not rendered at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    AnalysisReport,
    BudgetSpent,
    ExecutionStep,
    Finding,
)


def _collection():
    """Resolved lazily so tests can monkeypatch depictio.api.v1.db."""
    from depictio.api.v1.db import ai_analyses_collection

    return ai_analyses_collection


def new_report(dashboard_id: str, prompt: str, model: str) -> AnalysisReport:
    return AnalysisReport(
        id=uuid.uuid4().hex,
        dashboard_id=dashboard_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        prompt=prompt,
        status="running",
    )


def parse_findings(
    payload: Any,
    steps: list[ExecutionStep],
    warnings: list[str],
) -> list[Finding]:
    """Validate the model's findings against the steps that actually ran.

    Two gates, both load-bearing:
    - the Pydantic validator rejects a finding with no evidence ids;
    - the ids must point at steps that exist *and succeeded* — citing a
      failed step as evidence is a claim about data that was never
      produced.
    """
    if not isinstance(payload, list):
        if payload:
            warnings.append("Findings were not a list and were discarded.")
        return []

    valid_ids = {i for i, s in enumerate(steps) if s.status == "success"}
    findings: list[Finding] = []
    for raw in payload:
        try:
            finding = Finding.model_validate(raw)
        except ValidationError:
            claim = (raw or {}).get("claim", "?") if isinstance(raw, dict) else "?"
            warnings.append(f"Dropped a finding without usable evidence: {str(claim)[:120]}")
            continue
        cited = set(finding.evidence_step_ids)
        if not cited <= valid_ids:
            warnings.append(
                f"Dropped a finding citing non-existent or failed steps {sorted(cited - valid_ids)}: "
                f"{finding.claim[:120]}"
            )
            continue
        findings.append(finding)
    return findings


def save(report: AnalysisReport) -> None:
    """Upsert the report; called at start, per step batch, and at the end.

    Persisting the running state (not only the final one) is what makes a
    cancelled or crashed run inspectable afterwards instead of vanished.
    """
    doc = report.model_dump()
    _collection().replace_one({"id": report.id}, doc, upsert=True)


def get(report_id: str) -> AnalysisReport | None:
    doc = _collection().find_one({"id": report_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return AnalysisReport.model_validate(doc)


def latest_for_dashboard(dashboard_id: str, limit: int = 20) -> list[AnalysisReport]:
    docs = _collection().find({"dashboard_id": dashboard_id}).sort("created_at", -1).limit(limit)
    out: list[AnalysisReport] = []
    for doc in docs:
        doc.pop("_id", None)
        try:
            out.append(AnalysisReport.model_validate(doc))
        except ValidationError:  # pragma: no cover — corrupt legacy doc
            continue
    return out


def budget_spent(steps: int, tokens: int, started_at: float, now: float) -> BudgetSpent:
    return BudgetSpent(steps=steps, tokens=tokens, seconds=round(now - started_at, 1))
