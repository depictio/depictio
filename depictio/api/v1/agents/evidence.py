"""Evidence checks for agent findings.

Generalises ``ai_endpoints.analyses.parse_findings`` from sandbox steps to
tool calls: a finding stands only if it cites the ``call_id`` of at least one
successful, evidence-capable tool call (``evidence=True`` in the registry:
``query_data``, ``get_component_data``) made in this run. The query and the
values of the evidence are copied from the server's own call record, never
taken from the model, so a finding cannot quote numbers no tool returned.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from depictio.api.v1.agents.envelope import fit_to_budget
from depictio.api.v1.agents.runs import RunFinding, ToolCallRecord
from depictio.api.v1.endpoints.ai_endpoints.schemas import AgentEvidence
from depictio.models.models.comments import MAX_BODY_CHARS, MAX_EVIDENCE_ITEMS

MAX_FINDINGS_PER_AGENT = 12
EVIDENCE_VALUES_CHARS = 2_000
_CONFIDENCE = {"low", "medium", "high"}


def call_query(record: ToolCallRecord) -> str | None:
    """What a call computed, in words a reviewer can re-run."""
    if record.tool == "query_data" and isinstance(record.args.get("code"), str):
        return record.args["code"][:MAX_BODY_CHARS]
    text = json.dumps({"tool": record.tool, **record.args}, default=str, sort_keys=True)
    return text[:MAX_BODY_CHARS]


def call_values(record: ToolCallRecord) -> dict[str, Any] | list[Any] | None:
    value = record.values
    if value is None:
        return None
    value, _ = fit_to_budget(value, EVIDENCE_VALUES_CHARS)
    if isinstance(value, (dict, list)):
        return value
    return {"value": value}


def evidence_calls(calls: Iterable[ToolCallRecord]) -> dict[str, ToolCallRecord]:
    """Successful evidence-capable calls by id."""
    return {c.call_id: c for c in calls if c.ok and c.evidence}


def finding_id(agent_id: str, title: str, component_index: str | None) -> str:
    digest = hashlib.sha256(f"{agent_id}|{title}|{component_index or ''}".encode()).hexdigest()
    return f"f_{digest[:10]}"


def _cited(raw: dict[str, Any]) -> list[tuple[str, str | None]]:
    """``(call_id, note)`` pairs from ``evidence`` items or a bare ``call_ids`` list."""
    out: list[tuple[str, str | None]] = []
    for item in raw.get("evidence") or []:
        if isinstance(item, dict) and item.get("call_id"):
            note = item.get("note")
            out.append((str(item["call_id"]), str(note) if note else None))
        elif isinstance(item, str):
            out.append((item, None))
    for call_id in raw.get("call_ids") or []:
        out.append((str(call_id), None))
    return out


def validate(
    raw_findings: Any,
    calls: Iterable[ToolCallRecord],
    *,
    agent_id: str,
    warnings: list[str],
    known_components: set[str] | None = None,
    taken_ids: set[str] | None = None,
) -> list[RunFinding]:
    """Keep the findings backed by this run's evidence calls; explain every drop in ``warnings``.

    Citations of unknown, failed or non-evidence calls are removed; a finding
    left with none is dropped. A ``component_index`` that is not on the
    dashboard is cleared (the finding stays, unanchored).
    """
    if not isinstance(raw_findings, list):
        if raw_findings:
            warnings.append(f"{agent_id}: findings were not a list and were discarded.")
        return []

    valid = evidence_calls(calls)
    taken = taken_ids if taken_ids is not None else set()
    out: list[RunFinding] = []
    for raw in raw_findings[:MAX_FINDINGS_PER_AGENT]:
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            warnings.append(f"{agent_id}: dropped a finding without a title.")
            continue
        title = str(raw["title"]).strip()[:200]
        detail = str(raw.get("detail") or title).strip()[:MAX_BODY_CHARS]

        cited = _cited(raw)
        bad = sorted({cid for cid, _ in cited if cid not in valid})
        evidence: list[AgentEvidence] = []
        seen: set[str] = set()
        for call_id, note in cited:
            record = valid.get(call_id)
            if record is None or call_id in seen:
                continue
            seen.add(call_id)
            evidence.append(
                AgentEvidence(
                    note=(note or title)[:MAX_BODY_CHARS],
                    call_id=call_id,
                    query=call_query(record),
                    values=call_values(record),
                )
            )
        if not evidence:
            reason = f"citing unknown or failed calls {bad}" if bad else "citing no tool call"
            warnings.append(f"{agent_id}: dropped finding {title[:120]!r}, {reason}.")
            continue
        if bad:
            warnings.append(f"{agent_id}: ignored citations {bad} in finding {title[:120]!r}.")

        component = raw.get("component_index")
        component = str(component) if component not in (None, "") else None
        if component is not None and known_components is not None:
            if component not in known_components:
                warnings.append(
                    f"{agent_id}: component {component!r} of finding {title[:120]!r} "
                    "is not on this dashboard; the finding is kept without it."
                )
                component = None

        confidence = str(raw.get("confidence") or "medium").lower()
        fid = finding_id(agent_id, title, component)
        suffix = 2
        while fid in taken:
            fid = f"{finding_id(agent_id, title, component)}_{suffix}"
            suffix += 1
        taken.add(fid)
        out.append(
            RunFinding(
                finding_id=fid,
                agent_id=agent_id,
                title=title,
                detail=detail,
                component_index=component,
                confidence=confidence if confidence in _CONFIDENCE else "medium",  # type: ignore[arg-type]
                evidence=evidence[:MAX_EVIDENCE_ITEMS],
            )
        )
    return out
