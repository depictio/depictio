"""The agent-team pipeline: analysts, skeptic, annotator, questioner, reporter.

One run goes through fixed steps:

1. analysts (one per routed topic) explore in parallel and return findings;
   ``evidence.validate`` keeps those backed by their own evidence calls;
2. the skeptic re-checks every finding and gives a verdict
   (confirmed / weakened / refuted);
3. the annotator drafts an annotation for each confirmed finding that is about
   a component; the server writes it (``create_annotation``) with the
   finding's evidence and a deterministic ``dedupe_key``, so a re-run updates
   its earlier proposal instead of duplicating it;
4. the questioner drafts a question for each weakened finding
   (``ask_question``);
5. the reporter writes the summary; the server saves the report
   (``create_report``) with the confirmed and weakened findings.

Agents only call read tools themselves. Writes are made by the pipeline, under
the writing agent's ``ToolContext`` and through ``registry.invoke``, so an
agent can never annotate an unreviewed finding. Progress streams out as SSE
events (see ``agent_runs_routes``); cancellation is checked between steps and
before every LLM turn.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from depictio.api.v1.agents import evidence as evidence_mod
from depictio.api.v1.agents import runs
from depictio.api.v1.agents.budget import BudgetLedger
from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.envelope import fit_to_budget
from depictio.api.v1.agents.profiles import ProfileSet
from depictio.api.v1.agents.router import RouteContext, TeamMember, TeamPlan
from depictio.api.v1.agents.runner import (
    AgentOutcome,
    CancelToken,
    Emit,
    LLMClient,
    Toolbox,
    agent_loop,
    summarise_args,
    summarise_result,
)
from depictio.api.v1.agents.runs import (
    AgentRecord,
    AgentRun,
    RunFinding,
    RunThread,
    ToolCallRecord,
    Verdict,
)
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.ai_endpoints.schemas import AgentFinding
from depictio.models.models.comments import MAX_BODY_CHARS, MAX_LABEL_CHARS
from depictio.models.models.users import TokenScope

SUMMARY_CONTEXT_CHARS = 8_000
FINDINGS_CONTEXT_CHARS = 12_000
EVIDENCE_PREVIEW_CHARS = 600

_EVIDENCE_ITEM = {
    "type": "object",
    "properties": {"call_id": {"type": "string"}, "note": {"type": "string"}},
    "required": ["call_id"],
}
ANALYST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "component_index": {"type": ["string", "null"]},
                    "confidence": {"enum": ["low", "medium", "high"]},
                    "evidence": {"type": "array", "items": _EVIDENCE_ITEM},
                },
                "required": ["title", "detail", "evidence"],
            },
        },
    },
    "required": ["findings"],
}
SKEPTIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "verdict": {"enum": ["confirmed", "weakened", "refuted"]},
                    "reason": {"type": "string"},
                },
                "required": ["finding_id", "verdict", "reason"],
            },
        },
    },
    "required": ["verdicts"],
}
ANNOTATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "annotations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "body": {"type": "string"},
                    "label": {"type": "string"},
                    "shape": {"enum": ["x_range", "y_range", "ref_line", "points", "arrow_note"]},
                    "x0": {},
                    "x1": {},
                    "y0": {"type": "number"},
                    "y1": {"type": "number"},
                    "axis": {"enum": ["x", "y"]},
                    "value": {},
                    "x": {},
                    "y": {},
                    "column": {"type": "string"},
                    "ids": {"type": "array"},
                    "points": {"type": "array"},
                },
                "required": ["finding_id", "body"],
            },
        }
    },
    "required": ["annotations"],
}
QUESTIONER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"finding_id": {"type": "string"}, "body": {"type": "string"}},
                "required": ["finding_id", "body"],
            },
        }
    },
    "required": ["questions"],
}
REPORTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"summary_md": {"type": "string"}},
    "required": ["summary_md"],
}

# Shape fields the annotator may set; everything else is filled by the server.
_SHAPE_FIELDS = ("label", "x0", "x1", "y0", "y1", "axis", "value", "x", "y", "column", "ids")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dedupe_key(question: str, title: str, component_index: str | None, prefix: str = "a") -> str:
    """Stable across re-runs of the same question: the same finding updates its proposal."""
    raw = f"{question.strip().lower()}|{title.strip().lower()}|{component_index or ''}"
    return f"team:{prefix}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def _json(obj: Any, limit: int) -> str:
    value, _ = fit_to_budget(obj, limit)
    return json.dumps(value, default=str, ensure_ascii=False)


@dataclass
class TeamDeps:
    llm: LLMClient
    profiles: ProfileSet
    toolbox: Toolbox = field(default_factory=Toolbox)
    persist: Callable[[AgentRun], None] = runs.save
    max_parallel: int = 3
    token_id: str | None = None


class TeamRun:
    """One run of the pipeline. ``execute`` never raises; it ends with ``run_finished``."""

    def __init__(
        self,
        *,
        run: AgentRun,
        plan: TeamPlan,
        route_ctx: RouteContext,
        user: Any,
        user_scopes: frozenset[TokenScope],
        deps: TeamDeps,
        ledger: BudgetLedger,
        cancel: CancelToken,
    ) -> None:
        self.run = run
        self.plan = plan
        self.route_ctx = route_ctx
        self.user = user
        self.user_scopes = user_scopes
        self.deps = deps
        self.ledger = ledger
        self.cancel = cancel
        self._emit: Emit | None = None
        self.outcomes: dict[str, AgentOutcome] = {}

    # -- plumbing ---------------------------------------------------------------
    async def emit(self, event: str, data: dict[str, Any]) -> None:
        if self._emit is not None:
            await self._emit(event, data)

    async def persist(self) -> None:
        snap = self.ledger.snapshot()
        budget = self.run.budget
        budget.spent_usd = round(snap.spent_usd, 6)
        budget.cost_known = snap.cost_known
        budget.tool_calls = snap.tool_calls
        budget.tokens = snap.tokens
        try:
            await asyncio.to_thread(self.deps.persist, self.run)
        except Exception as exc:  # noqa: BLE001, a failed save must not stop the run
            logger.warning(f"agents: saving run {self.run.id} failed: {exc}")

    def context(self, member: TeamMember) -> ToolContext:
        role = self.deps.profiles.role(member.role)
        scopes = frozenset(s for s in role.scopes if s in self.user_scopes) | {"read"}
        return ToolContext(
            user=self.user,
            scopes=scopes,  # type: ignore[arg-type]
            agent_name=member.agent_id,
            agent_model=self.deps.llm.model,
            run_id=self.run.id,
            token_id=self.deps.token_id,
        )

    def members(self, role: str) -> list[TeamMember]:
        return [m for m in self.plan.team if m.role == role]

    async def _start(self, member: TeamMember) -> AgentRecord:
        record = self.run.agent(member.agent_id)
        record.status = "running"
        record.started_at = _now()
        await self.emit(
            "agent_started",
            {"agent_id": member.agent_id, "role": member.role, "topic": member.topic},
        )
        return record

    async def _finish(self, record: AgentRecord, status: str, summary: str) -> None:
        record.status = status  # type: ignore[assignment]
        record.summary = summary
        record.finished_at = _now()
        # The wire knows ok / budget / error: a skipped agent did its (empty) job.
        wire_status = {"skipped": "ok", "cancelled": "error"}.get(status, status)
        await self.emit(
            "agent_finished",
            {"agent_id": record.agent_id, "status": wire_status, "summary": summary},
        )
        await self.emit("budget", self.ledger.snapshot().event())

    async def _loop(
        self,
        member: TeamMember,
        record: AgentRecord,
        *,
        task: str,
        schema: dict[str, Any],
        reserve: bool = False,
    ) -> AgentOutcome:
        profiles = self.deps.profiles
        outcome = await agent_loop(
            profiles.role(member.role),
            profiles.topic(member.topic),
            self.context(member),
            member.sub_question or self.run.question,
            task=task,
            output_schema=schema,
            llm=self.deps.llm,
            ledger=self.ledger,
            record=record,
            toolbox=self.deps.toolbox,
            emit=self.emit,
            cancel=self.cancel,
            reserve=reserve,
        )
        self.outcomes[member.agent_id] = outcome
        return outcome

    async def _write(
        self, member: TeamMember, record: AgentRecord, tool: str, args: dict[str, Any]
    ) -> dict[str, Any] | None:
        """A write the pipeline makes for ``member``: invoked, recorded and streamed."""
        started = time.perf_counter()
        result = await self.deps.toolbox.invoke(tool, self.context(member), args)
        summary = summarise_result(result)
        record.tool_calls.append(
            ToolCallRecord(
                call_id=result.call_id,
                tool=tool,
                args=summarise_args(args),
                ok=result.ok,
                truncated=result.truncated,
                summary=summary,
                error=result.error,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        )
        await self.emit(
            "tool_call",
            {
                "agent_id": member.agent_id,
                "call_id": result.call_id,
                "tool": tool,
                "args": summarise_args(args),
            },
        )
        await self.emit(
            "tool_result",
            {
                "agent_id": member.agent_id,
                "call_id": result.call_id,
                "ok": result.ok,
                "truncated": result.truncated,
                "summary": summary,
            },
        )
        if not result.ok:
            self.run.warnings.append(f"{member.agent_id}: {tool} failed: {result.error}")
            await self.emit(
                "error", {"detail": f"{tool} failed: {result.error}", "agent_id": member.agent_id}
            )
            return None
        return result.data if isinstance(result.data, dict) else {}

    # -- steps ------------------------------------------------------------------
    def _dashboard_brief(self) -> str:
        return (
            f"Dashboard id: {self.run.dashboard_id}\n"
            "Dashboard structure (component index, type, data collection, key config):\n"
            + _json(self.route_ctx.summary, SUMMARY_CONTEXT_CHARS)
        )

    async def _analyst(self, member: TeamMember, taken: set[str]) -> list[RunFinding]:
        record = await self._start(member)
        outcome = await self._loop(
            member,
            record,
            task=self._dashboard_brief()
            + "\n\nExplore the data and answer with findings backed by your tool calls.",
            schema=ANALYST_SCHEMA,
        )
        findings: list[RunFinding] = []
        if outcome.output is not None:
            findings = evidence_mod.validate(
                outcome.output.get("findings"),
                record.tool_calls,
                agent_id=member.agent_id,
                warnings=self.run.warnings,
                known_components=self.route_ctx.component_indexes or None,
                taken_ids=taken,
            )
        for f in findings:
            await self.emit(
                "finding",
                {
                    "agent_id": f.agent_id,
                    "finding_id": f.finding_id,
                    "title": f.title,
                    "detail": f.detail,
                    "component_index": f.component_index,
                    "confidence": f.confidence,
                    "evidence": [{"call_id": e.call_id, "note": e.note} for e in f.evidence],
                },
            )
        summary = outcome.summary
        if outcome.status != "cancelled":
            summary = f"{summary} ({len(findings)} finding(s) kept)"
        await self._finish(record, outcome.status, summary)
        return findings

    def _findings_brief(self, findings: list[RunFinding], with_verdicts: bool = False) -> str:
        items = []
        for f in findings:
            item: dict[str, Any] = {
                "finding_id": f.finding_id,
                "title": f.title,
                "detail": f.detail,
                "component_index": f.component_index,
                "confidence": f.confidence,
                "evidence": [
                    {
                        "call_id": e.call_id,
                        "query": (e.query or "")[:EVIDENCE_PREVIEW_CHARS],
                        "values": _json(e.values, EVIDENCE_PREVIEW_CHARS),
                    }
                    for e in f.evidence
                ],
            }
            if with_verdicts:
                item["verdict"] = f.verdict
                item["verdict_reason"] = f.verdict_reason
            items.append(item)
        return _json(items, FINDINGS_CONTEXT_CHARS)

    async def _skeptic(self, member: TeamMember) -> None:
        findings = self.run.findings
        record = await self._start(member)
        outcome = await self._loop(
            member,
            record,
            task=(
                f"Dashboard id: {self.run.dashboard_id}\n\nFindings to review:\n"
                + self._findings_brief(findings)
                + "\n\nGive one verdict per finding_id."
            ),
            schema=SKEPTIC_SCHEMA,
        )
        given: dict[str, dict[str, Any]] = {}
        for item in (outcome.output or {}).get("verdicts") or []:
            if isinstance(item, dict) and item.get("verdict") in (
                "confirmed",
                "weakened",
                "refuted",
            ):
                given.setdefault(str(item.get("finding_id")), item)
        for f in findings:
            item = given.get(f.finding_id)
            if item is None:
                verdict, reason = "weakened", "The skeptic gave no verdict on this finding."
            else:
                verdict = item["verdict"]
                reason = str(item.get("reason") or "").strip()[:MAX_BODY_CHARS] or "No reason."
            f.verdict, f.verdict_reason = verdict, reason  # type: ignore[assignment]
            self.run.verdicts.append(
                Verdict(
                    finding_id=f.finding_id,
                    verdict=verdict,  # type: ignore[arg-type]
                    reason=reason,
                    agent_id=member.agent_id,
                )
            )
            await self.emit(
                "verdict",
                {
                    "finding_id": f.finding_id,
                    "verdict": verdict,
                    "reason": reason,
                    "agent_id": member.agent_id,
                },
            )
        await self._finish(record, outcome.status, outcome.summary)

    async def _skip(self, member: TeamMember, why: str) -> None:
        record = await self._start(member)
        await self._finish(record, "skipped", f"Skipped: {why}")

    def _evidence_args(self, f: RunFinding) -> list[dict[str, Any]]:
        return [e.model_dump(exclude_none=True) for e in f.evidence]

    async def _thread_created(
        self, member: TeamMember, data: dict[str, Any], f: RunFinding, kind: str
    ) -> None:
        thread_id = str(data.get("thread_id") or "")
        if not thread_id:
            return
        if thread_id not in self.run.outputs.thread_ids:
            self.run.outputs.thread_ids.append(thread_id)
        if thread_id not in f.thread_ids:
            f.thread_ids.append(thread_id)
        self.run.threads.append(
            RunThread(
                thread_id=thread_id,
                kind=kind,  # type: ignore[arg-type]
                component_index=f.component_index,
                finding_id=f.finding_id,
                agent_id=member.agent_id,
            )
        )
        await self.emit(
            "thread_created",
            {
                "agent_id": member.agent_id,
                "thread_id": thread_id,
                "kind": kind,
                "component_index": f.component_index,
                "finding_id": f.finding_id,
            },
        )

    async def _annotator(self, member: TeamMember) -> None:
        targets = [f for f in self.run.findings if f.verdict == "confirmed" and f.component_index]
        if not targets:
            await self._skip(member, "no confirmed finding on a component.")
            return
        record = await self._start(member)
        outcome = await self._loop(
            member,
            record,
            task=(
                f"Dashboard id: {self.run.dashboard_id}\n\nConfirmed findings to annotate:\n"
                + self._findings_brief(targets)
            ),
            schema=ANNOTATOR_SCHEMA,
        )
        specs: dict[str, dict[str, Any]] = {}
        for item in (outcome.output or {}).get("annotations") or []:
            if isinstance(item, dict) and item.get("finding_id"):
                specs.setdefault(str(item["finding_id"]), item)
        written = 0
        for f in targets:
            if await self.cancel.cancelled():
                break
            spec = specs.get(f.finding_id) or {}
            body = str(spec.get("body") or "").strip() or f"{f.title}. {f.detail}"
            base: dict[str, Any] = {
                "dashboard_id": self.run.dashboard_id,
                "component_index": f.component_index,
                "body": body[:MAX_BODY_CHARS],
                "evidence": self._evidence_args(f),
                "dedupe_key": dedupe_key(self.run.question, f.title, f.component_index),
            }
            args = dict(base)
            if spec.get("shape"):
                args["shape"] = spec["shape"]
                for key in _SHAPE_FIELDS:
                    if spec.get(key) is not None:
                        args[key] = spec[key]
                if isinstance(spec.get("points"), list):
                    args["points"] = spec["points"]
                if isinstance(args.get("label"), str):
                    args["label"] = args["label"][:MAX_LABEL_CHARS]
            data = await self._write(member, record, "create_annotation", args)
            if data is None and "shape" in args:
                # A shape the tool rejects must not cost the finding its comment.
                data = await self._write(member, record, "create_annotation", base)
            if data is not None:
                written += 1
                await self._thread_created(member, data, f, "comment")
        status = outcome.status if outcome.status != "error" else "ok"
        await self._finish(record, status, f"{written} annotation(s) proposed")

    async def _questioner(self, member: TeamMember) -> None:
        targets = [f for f in self.run.findings if f.verdict == "weakened"]
        if not targets:
            await self._skip(member, "no weakened finding to ask about.")
            return
        record = await self._start(member)
        outcome = await self._loop(
            member,
            record,
            task=(
                f"Dashboard id: {self.run.dashboard_id}\n\nWeakened findings (with the "
                "skeptic's reason):\n" + self._findings_brief(targets, with_verdicts=True)
            ),
            schema=QUESTIONER_SCHEMA,
        )
        by_id = {f.finding_id: f for f in targets}
        asked = 0
        seen: set[str] = set()
        for item in (outcome.output or {}).get("questions") or []:
            if await self.cancel.cancelled():
                break
            if not isinstance(item, dict):
                continue
            f = by_id.get(str(item.get("finding_id")))
            body = str(item.get("body") or "").strip()
            if f is None or not body or f.finding_id in seen:
                continue
            seen.add(f.finding_id)
            args: dict[str, Any] = {
                "dashboard_id": self.run.dashboard_id,
                "body": body[:MAX_BODY_CHARS],
                "evidence": self._evidence_args(f),
                "dedupe_key": dedupe_key(self.run.question, f.title, f.component_index, "q"),
            }
            if f.component_index:
                args["component_index"] = f.component_index
            data = await self._write(member, record, "ask_question", args)
            if data is not None:
                asked += 1
                await self._thread_created(member, data, f, "question")
        await self._finish(record, outcome.status, f"{asked} question(s) asked")

    def _fallback_summary(self) -> str:
        lines = [f"**Question:** {self.run.question}", ""]
        for label, verdict in (
            ("Confirmed", "confirmed"),
            ("Weakened", "weakened"),
            ("Refuted", "refuted"),
        ):
            group = [f for f in self.run.findings if f.verdict == verdict]
            if group:
                lines.append(f"**{label}**")
                lines.extend(f"- {f.title}" for f in group)
                lines.append("")
        if not self.run.findings:
            lines.append("No finding could be backed by the data.")
        return "\n".join(lines).strip()

    async def _reporter(self, member: TeamMember) -> None:
        record = await self._start(member)
        outcome = await self._loop(
            member,
            record,
            task=(
                "Findings and verdicts:\n"
                + self._findings_brief(self.run.findings, with_verdicts=True)
                + f"\n\nWarnings of the run: {_json(self.run.warnings[-10:], 2_000)}"
            ),
            schema=REPORTER_SCHEMA,
            reserve=True,
        )
        summary = str((outcome.output or {}).get("summary_md") or "").strip()
        if not summary:
            summary = self._fallback_summary()
        kept = [f for f in self.run.findings if f.verdict in ("confirmed", "weakened")]
        report_findings = [
            AgentFinding(
                title=f.title,
                detail=f.detail,
                component_index=f.component_index,
                confidence=f.confidence if f.verdict == "confirmed" else "low",
                evidence=f.evidence,
                verdict=f.verdict,
                verdict_reason=f.verdict_reason,
            ).model_dump(mode="json", exclude_none=True)
            for f in kept
        ]
        data = await self._write(
            member,
            record,
            "create_report",
            {
                "dashboard_id": self.run.dashboard_id,
                "question": self.run.question[:MAX_BODY_CHARS],
                "summary": summary,
                "findings": report_findings,
            },
        )
        if data is not None and data.get("report_id"):
            self.run.outputs.report_id = str(data["report_id"])
            await self.emit(
                "report_created", {"agent_id": member.agent_id, "report_id": data["report_id"]}
            )
        status = outcome.status if data is not None else "error"
        await self._finish(record, status, "Report written" if data else "Report not written")

    # -- the pipeline -------------------------------------------------------------
    async def _pipeline(self) -> None:
        analysts = self.members("analyst")
        semaphore = asyncio.Semaphore(max(1, self.deps.max_parallel))
        taken: set[str] = set()

        async def bounded(member: TeamMember) -> list[RunFinding]:
            async with semaphore:
                return await self._analyst(member, taken)

        results = await asyncio.gather(*(bounded(m) for m in analysts))
        for found in results:
            self.run.findings.extend(found)
        await self.persist()

        for step, role in (
            (self._skeptic, "skeptic"),
            (self._annotator, "annotator"),
            (self._questioner, "questioner"),
            (self._reporter, "reporter"),
        ):
            if await self.cancel.cancelled():
                return
            for member in self.members(role):
                if role in ("skeptic",) and not self.run.findings:
                    await self._skip(member, "no finding to review.")
                    continue
                await step(member)
            await self.persist()

    def _final_status(self) -> runs.RunStatus:
        analyst_ids = [m.agent_id for m in self.members("analyst")]
        if analyst_ids and all(
            self.outcomes.get(a) is not None and self.outcomes[a].status == "error"
            for a in analyst_ids
        ):
            return "failed"
        if any(o.status == "budget" for o in self.outcomes.values()) or self.ledger.exhausted(
            reserve=True
        ):
            return "budget"
        return "complete"

    async def execute(self, emit: Emit) -> None:
        self._emit = emit
        run = self.run
        await self.persist()
        await self.emit(
            "run_started",
            {
                "run_id": run.id,
                "team": [m.public() for m in self.plan.team],
                "routing": self.plan.routing(),
                "budget": {
                    "limit_usd": run.budget.limit_usd,
                    "max_tool_calls": run.budget.max_tool_calls,
                },
            },
        )
        try:
            await self._pipeline()
            run.status = "cancelled" if await self.cancel.cancelled() else self._final_status()
        except Exception as exc:  # noqa: BLE001, reported as a failed run
            logger.exception(f"agents: run {run.id} failed: {exc}")
            run.status = "failed"
            run.warnings.append(f"Run failed: {exc}"[:300])
            await self.emit("error", {"detail": f"Run failed: {exc}"[:300]})
        run.finished_at = _now()
        for record in run.agents:
            if record.status in ("pending", "running"):
                record.status = "cancelled" if run.status == "cancelled" else "skipped"
        await self.persist()
        await self.emit(
            "run_finished",
            {
                "run_id": run.id,
                "status": run.status,
                "outputs": run.outputs.model_dump(),
            },
        )
        await self.emit("done", {})


def new_run(
    *,
    run_id: str,
    user_id: str,
    dashboard_id: str,
    question: str,
    plan: TeamPlan,
    profiles: ProfileSet,
    model: str,
    ledger: BudgetLedger,
) -> AgentRun:
    """The ``AgentRun`` document of a run about to start, one record per member."""
    agents = []
    for m in plan.team:
        role, topic = profiles.role(m.role), profiles.topic(m.topic)
        agents.append(
            AgentRecord(
                agent_id=m.agent_id,
                role=m.role,
                topic=m.topic,
                role_version=role.version,
                topic_version=topic.version,
                sub_question=m.sub_question,
                reason=m.reason,
            )
        )
    return AgentRun(
        id=run_id,
        user_id=user_id,
        dashboard_id=dashboard_id,
        question=question,
        model=model,
        team=[m.agent_id for m in plan.team],
        routing=plan.routing(),
        agents=agents,
        budget=runs.RunBudget(
            limit_usd=ledger.limit_usd,
            max_tool_calls=ledger.max_tool_calls,
            max_tokens=ledger.max_tokens,
        ),
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
Event = tuple[str, dict[str, Any]]


class RunExecutor(Protocol):
    """Runs a ``TeamRun`` and streams its events. In-process today; Celery later."""

    def events(self, job: TeamRun) -> AsyncIterator[Event]: ...

    def cancel(self, run_id: str) -> bool: ...


class InProcessExecutor:
    """Runs the pipeline as a task of this API process and relays its events.

    If the client goes away mid-run, the run is cancelled at its next check
    rather than left spending in the background.
    """

    _active: dict[str, TeamRun] = {}
    _tasks: set[asyncio.Task[None]] = set()

    def cancel(self, run_id: str) -> bool:
        job = self._active.get(run_id)
        if job is None:
            return False
        job.cancel.cancel()
        return True

    async def events(self, job: TeamRun) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue()

        async def emit(event: str, data: dict[str, Any]) -> None:
            await queue.put((event, data))

        async def main() -> None:
            try:
                await job.execute(emit)
            finally:
                self._active.pop(job.run.id, None)
                await queue.put(None)

        self._active[job.run.id] = job
        task = asyncio.create_task(main())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            if not task.done():
                job.cancel.cancel()


def format_sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()
