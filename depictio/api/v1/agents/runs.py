"""Persistence of agent-team runs (collection ``ai_agent_runs``).

Same policy as ``ai_analyses``: a run is a derived artifact addressed by its
id, saved while it runs (not only at the end) so a cancelled or crashed run
stays inspectable. A run records its question, team, routing, every agent's
tool calls and findings, the skeptic's verdicts, what it wrote (threads,
report) and what it spent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from depictio.api.v1.endpoints.ai_endpoints.schemas import AgentEvidence

RunStatus = Literal["running", "complete", "cancelled", "failed", "budget"]
AgentStatus = Literal["pending", "running", "ok", "budget", "error", "cancelled", "skipped"]
# "unverified": a finding the skeptic did not review (its budget ran out).
VerdictKind = Literal["confirmed", "weakened", "refuted", "unverified"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collection():
    """Resolved lazily so tests can monkeypatch depictio.api.v1.db."""
    from depictio.api.v1 import db

    return db.ai_agent_runs_collection


class ToolCallRecord(BaseModel):
    """One tool call of one agent. ``values`` keeps a cut of the result for evidence."""

    call_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    truncated: bool = False
    evidence: bool = False
    summary: str = ""
    error: str | None = None
    duration_ms: float = 0.0
    values: Any | None = None
    at: str = Field(default_factory=_now)


class RunFinding(BaseModel):
    """A validated finding of an analyst, with the skeptic's verdict once given."""

    finding_id: str
    agent_id: str
    title: str
    detail: str
    component_index: str | None = None
    confidence: Literal["low", "medium", "high"] = "medium"
    evidence: list[AgentEvidence] = Field(default_factory=list)
    verdict: VerdictKind | None = None
    verdict_reason: str | None = None
    thread_ids: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    finding_id: str
    verdict: VerdictKind
    reason: str
    agent_id: str


class RunThread(BaseModel):
    """A thread the run wrote: an annotation (comment) or a question."""

    thread_id: str
    kind: Literal["comment", "question"]
    component_index: str | None = None
    finding_id: str | None = None
    agent_id: str


class AgentRecord(BaseModel):
    agent_id: str
    role: str
    topic: str
    role_version: int
    topic_version: int
    sub_question: str = ""
    reason: str = ""
    status: AgentStatus = "pending"
    summary: str = ""
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    tokens: int = 0
    cost_usd: float | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RunOutputs(BaseModel):
    thread_ids: list[str] = Field(default_factory=list)
    report_id: str | None = None
    draft_ids: list[str] = Field(default_factory=list)


class RunBudget(BaseModel):
    limit_usd: float
    spent_usd: float = 0.0
    cost_known: bool = False
    max_tool_calls: int
    tool_calls: int = 0
    max_tokens: int
    tokens: int = 0


class AgentRun(BaseModel):
    id: str
    user_id: str
    dashboard_id: str
    question: str
    model: str
    team: list[str] = Field(default_factory=list)
    routing: dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = "running"
    cancel_requested: bool = False
    agents: list[AgentRecord] = Field(default_factory=list)
    findings: list[RunFinding] = Field(default_factory=list)
    verdicts: list[Verdict] = Field(default_factory=list)
    threads: list[RunThread] = Field(default_factory=list)
    outputs: RunOutputs = Field(default_factory=RunOutputs)
    budget: RunBudget
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    finished_at: str | None = None

    def agent(self, agent_id: str) -> AgentRecord:
        for record in self.agents:
            if record.agent_id == agent_id:
                return record
        raise KeyError(agent_id)

    def summary(self) -> dict[str, Any]:
        """The list entry of ``GET /ai/agent-runs``."""
        return {
            "run_id": self.id,
            "dashboard_id": self.dashboard_id,
            "question": self.question,
            "status": self.status,
            "team": self.team,
            "finding_count": len(self.findings),
            "confirmed_count": sum(1 for f in self.findings if f.verdict == "confirmed"),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    def detail(self) -> dict[str, Any]:
        """The body of ``GET /ai/agent-runs/{run_id}``: findings grouped under their agent."""
        agents = []
        for record in self.agents:
            agents.append(
                {
                    "agent_id": record.agent_id,
                    "role": record.role,
                    "topic": record.topic,
                    "role_version": record.role_version,
                    "topic_version": record.topic_version,
                    "status": record.status,
                    "summary": record.summary,
                    "tokens": record.tokens,
                    "cost_usd": record.cost_usd,
                    "started_at": record.started_at,
                    "finished_at": record.finished_at,
                    "tool_calls": [
                        {
                            "call_id": c.call_id,
                            "tool": c.tool,
                            "args": c.args,
                            "ok": c.ok,
                            "truncated": c.truncated,
                            "evidence": c.evidence,
                            "summary": c.summary,
                            "error": c.error,
                            "duration_ms": c.duration_ms,
                        }
                        for c in record.tool_calls
                    ],
                    "findings": [
                        f.model_dump(mode="json")
                        for f in self.findings
                        if f.agent_id == record.agent_id
                    ],
                }
            )
        return {
            "run_id": self.id,
            "dashboard_id": self.dashboard_id,
            "question": self.question,
            "model": self.model,
            "status": self.status,
            "team": self.team,
            "routing": self.routing,
            "agents": agents,
            "verdicts": [v.model_dump(mode="json") for v in self.verdicts],
            "threads": [t.model_dump(mode="json") for t in self.threads],
            "budget": self.budget.model_dump(mode="json"),
            "outputs": self.outputs.model_dump(mode="json"),
            "warnings": self.warnings,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


def new_run_id() -> str:
    return uuid.uuid4().hex


def save(run: AgentRun) -> None:
    """Upsert the run. ``cancel_requested`` is never cleared by a save."""
    doc = run.model_dump(mode="json", exclude={"cancel_requested"})
    _collection().update_one(
        {"id": run.id},
        {"$set": doc, "$setOnInsert": {"cancel_requested": False}},
        upsert=True,
    )


def get(run_id: str) -> AgentRun | None:
    doc = _collection().find_one({"id": run_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return AgentRun.model_validate(doc)


def list_runs(user_id: str, dashboard_id: str | None = None, limit: int = 20) -> list[AgentRun]:
    query: dict[str, Any] = {"user_id": user_id}
    if dashboard_id:
        query["dashboard_id"] = dashboard_id
    out: list[AgentRun] = []
    for doc in _collection().find(query).sort("created_at", -1).limit(limit):
        doc.pop("_id", None)
        try:
            out.append(AgentRun.model_validate(doc))
        except Exception:  # pragma: no cover, a corrupt or older document
            continue
    return out


def request_cancel(run_id: str, *, live: bool) -> bool:
    """Cancel a run. True when it was running.

    ``live``: the run executes in this process, which ends it as ``cancelled``
    at its next check. Otherwise a run still marked running is flagged (so the
    process running it, if any, stops) and marked cancelled right away, as no
    process here will finish it.
    """
    if live:
        _collection().update_one({"id": run_id}, {"$set": {"cancel_requested": True}})
        return True
    result = _collection().update_one(
        {"id": run_id, "status": "running"},
        {"$set": {"cancel_requested": True, "status": "cancelled", "finished_at": _now()}},
    )
    return result.matched_count > 0


ORPHAN_WARNING = "The API process running this run stopped before it finished."


def sweep_orphans() -> int:
    """Mark runs left ``running`` by a previous process as ``failed``. Call at startup."""
    result = _collection().update_many(
        {"status": "running"},
        {
            "$set": {"status": "failed", "finished_at": _now()},
            "$push": {"warnings": ORPHAN_WARNING},
        },
    )
    return result.modified_count


def cancel_requested(run_id: str) -> bool:
    doc = _collection().find_one({"id": run_id}, {"cancel_requested": 1})
    return bool((doc or {}).get("cancel_requested"))
