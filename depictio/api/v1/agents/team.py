"""The agent-team pipeline: analysts, skeptic, annotator, questioner, reporter.

One run goes through fixed steps:

1. analysts (one per routed topic) explore in parallel and return findings;
   ``evidence.validate`` keeps those backed by their own evidence calls;
2. the skeptic re-checks the findings, given in one compact batch, and
   gives a verdict (confirmed / weakened / refuted); when its budget runs out
   it still answers for what it checked, and a finding it never judged is
   ``unverified``;
3. the annotator drafts an annotation for each confirmed finding that is about
   a component; the server writes it (``create_annotation``) with the
   finding's evidence and a deterministic ``dedupe_key``, so a re-run updates
   its earlier proposal instead of duplicating it;
4. the questioner drafts a question for each weakened finding
   (``ask_question``);
5. the reporter writes the summary; the server saves the report
   (``create_report``) with the confirmed, weakened and unverified findings.

Each step spends from its own phase of the run's budget (``budget.PHASES``);
what a step leaves unused rolls forward to the later ones.

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
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from depictio.api.v1.agents import evidence as evidence_mod
from depictio.api.v1.agents import runs
from depictio.api.v1.agents.budget import BudgetLedger, phase_of
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
from depictio.api.v1.agents.tools.reports import MAX_FINDINGS as REPORT_MAX_FINDINGS
from depictio.api.v1.agents.tools.reports import MAX_SUMMARY_CHARS as REPORT_MAX_SUMMARY_CHARS
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.ai_endpoints.schemas import AgentFinding
from depictio.models.models.comments import MAX_BODY_CHARS, MAX_LABEL_CHARS
from depictio.models.models.users import TokenScope

SUMMARY_CONTEXT_CHARS = 8_000
FINDINGS_CONTEXT_CHARS = 12_000
EVIDENCE_PREVIEW_CHARS = 600
# The skeptic gets every finding in one batch: shorter evidence previews.
SKEPTIC_EVIDENCE_CHARS = 300
SKEPTIC_TASK = (
    "Review all these findings in this one pass. Most can be judged from the cited "
    "evidence values; re-run a query only for a claim that needs it, and keep such checks "
    "few. Answer with one JSON object holding a verdict for every finding_id."
)
SKEPTIC_CONCLUDE = (
    "Your budget is used up. Do not call any tool. Reply now with the verdicts JSON: a "
    "verdict for every finding you checked or can judge from the evidence in the brief and "
    "the tool results you have. Leave out a finding you could not judge."
)
UNVERIFIED_REASON = "The skeptic did not review this finding before the budget ran out."
ANNOTATOR_RETRY = (
    "These shapes could not be drawn (the error of each is given). Reply with the "
    "annotations JSON again for these finding_ids only, each with a fixed shape. Prefer "
    "shapes that are always drawable: ref_line, y_range / x_range, or points by "
    "coordinate (points [{x, y}]). Leave the shape out only if you cannot place it."
)

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

# Component types a shape can be drawn on; others (cards, tables...) get a plain comment.
SHAPE_COMPONENT_TYPES = frozenset({"figure", "advanced_viz", "multiqc"})
MAX_SHAPE_IDS = 200
# Config keys that say what a component's axes show, for the annotator's brief.
_AXIS_KEYS = ("visu_type", "viz_kind", "x", "y", "color", "config", "selected_plot")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_coord(value: Any) -> bool:
    """A data coordinate: a number, or a category name on a categorical axis."""
    return _is_number(value) or (isinstance(value, str) and bool(value.strip()))


def _ordered(a: Any, b: Any) -> tuple[Any, Any]:
    if _is_number(a) and _is_number(b) and a > b:
        return b, a
    return a, b


def check_shape(spec: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The ``create_annotation`` shape fields of an annotator proposal, or why not.

    Returns ``(fields, None)`` for a complete, well-typed shape, else
    ``(None, reason)`` with what the shape is missing, for the annotator's retry.
    """
    shape = spec.get("shape")
    out: dict[str, Any]
    if shape == "x_range":
        x0, x1 = spec.get("x0"), spec.get("x1")
        if not (_is_coord(x0) and _is_coord(x1)) or x0 == x1:
            return None, "x_range needs x0 and x1: two different numbers or category names."
        x0, x1 = _ordered(x0, x1)
        out = {"shape": shape, "x0": x0, "x1": x1}
    elif shape == "y_range":
        y0, y1 = spec.get("y0"), spec.get("y1")
        if not (_is_number(y0) and _is_number(y1)) or y0 == y1:
            return None, "y_range needs y0 and y1: two different numbers."
        y0, y1 = _ordered(y0, y1)
        out = {"shape": shape, "y0": y0, "y1": y1}
    elif shape == "ref_line":
        axis, value = spec.get("axis"), spec.get("value")
        if axis not in ("x", "y") or not _is_coord(value):
            return None, "ref_line needs axis ('x' or 'y') and a value."
        if axis == "y" and not _is_number(value):
            return None, "ref_line on the y axis needs a numeric value."
        out = {"shape": shape, "axis": axis, "value": value}
    elif shape == "arrow_note":
        x, y = spec.get("x"), spec.get("y")
        if not (_is_coord(x) and _is_coord(y)):
            return None, "arrow_note needs x and y coordinates."
        out = {"shape": shape, "x": x, "y": y}
    elif shape == "points":
        out = {"shape": shape}
        column, ids = spec.get("column"), spec.get("ids")
        if isinstance(column, str) and column.strip() and isinstance(ids, list):
            kept = [i for i in ids if _is_coord(i)][:MAX_SHAPE_IDS]
            if kept:
                out["column"], out["ids"] = column.strip(), kept
        points = spec.get("points")
        if isinstance(points, list):
            coords = [
                {"x": pt["x"], "y": pt["y"]}
                for pt in points
                if isinstance(pt, dict) and _is_coord(pt.get("x")) and _is_coord(pt.get("y"))
            ][:MAX_SHAPE_IDS]
            if coords:
                out["points"] = coords
        if "ids" not in out and "points" not in out:
            return None, "points needs points [{x, y}] with both coordinates (or column and ids)."
    else:
        return None, (
            f"Unknown shape {shape!r}: use ref_line, y_range, x_range, points or arrow_note."
        )
    label = spec.get("label")
    if isinstance(label, str) and label.strip():
        out["label"] = label.strip()[:MAX_LABEL_CHARS]
    return out, None


def shape_allowed(component_type: str | None) -> bool:
    """Whether a shape can be drawn on a component of this type (unknown: yes)."""
    return not component_type or component_type.lower() in SHAPE_COMPONENT_TYPES


def shape_args(spec: dict[str, Any], component_type: str | None = None) -> dict[str, Any] | None:
    """``check_shape``'s fields, or None when incomplete or not drawable on the component."""
    if not shape_allowed(component_type):
        return None
    return check_shape(spec)[0]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _specs_by_finding(output: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The annotator's proposals by finding id, the first one of each."""
    specs: dict[str, dict[str, Any]] = {}
    for item in (output or {}).get("annotations") or []:
        if isinstance(item, dict) and item.get("finding_id"):
            specs.setdefault(str(item["finding_id"]), item)
    return specs


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

    async def _finish(
        self,
        record: AgentRecord,
        status: str,
        summary: str,
        counts: dict[str, int] | None = None,
    ) -> None:
        record.status = status  # type: ignore[assignment]
        record.summary = summary
        record.counts = dict(counts or {})
        record.finished_at = _now()
        # The wire knows ok / budget / error: a skipped agent did its (empty) job.
        wire_status = {"skipped": "ok", "cancelled": "error"}.get(status, status)
        await self.emit(
            "agent_finished",
            {
                "agent_id": record.agent_id,
                "status": wire_status,
                "summary": summary,
                "counts": record.counts,
            },
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
        conclude_prompt: str | None = None,
        force_conclude_for: str | None = None,
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
            phase=phase_of(member.role),
            conclude_prompt=conclude_prompt,
            force_conclude_for=force_conclude_for,
        )
        self.outcomes[member.agent_id] = outcome
        return outcome

    async def _write(
        self,
        member: TeamMember,
        record: AgentRecord,
        tool: str,
        args: dict[str, Any],
        *,
        errors: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """A write the pipeline makes for ``member``: invoked, recorded and streamed.

        A failure is a run warning and an ``error`` event, unless ``errors`` is
        given: then its message is appended there for the caller to retry.
        """
        started = time.perf_counter()
        result = await self.deps.toolbox.invoke(tool, self.context(member), args)
        summary = summarise_result(result, args)
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
            if errors is not None:
                errors.append(str(result.error or "failed"))
                return None
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
        await self._finish(record, outcome.status, outcome.summary, {"findings": len(findings)})
        return findings

    def _findings_brief(
        self,
        findings: list[RunFinding],
        with_verdicts: bool = False,
        preview: int = EVIDENCE_PREVIEW_CHARS,
    ) -> str:
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
                        "query": (e.query or "")[:preview],
                        "values": _json(e.values, preview),
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
                + self._findings_brief(findings, preview=SKEPTIC_EVIDENCE_CHARS)
                + "\n\n"
                + SKEPTIC_TASK
            ),
            schema=SKEPTIC_SCHEMA,
            conclude_prompt=SKEPTIC_CONCLUDE,
            # Verdicts gate every later step: answer past the phase if the reporter still fits.
            force_conclude_for="reporter",
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
                verdict, reason = "unverified", UNVERIFIED_REASON
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
        counts = Counter(str(f.verdict) for f in findings)
        summary = outcome.summary
        if counts["unverified"]:
            summary = f"{summary} ({counts['unverified']} of {len(findings)} unverified)"
        await self._finish(record, outcome.status, summary, dict(counts))

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

    def _components_by_index(self) -> dict[str, dict[str, Any]]:
        return {
            str(c.get("index")): c
            for c in self.route_ctx.summary.get("components") or []
            if isinstance(c, dict) and c.get("index") is not None
        }

    def _axes_brief(self, targets: list[RunFinding]) -> str:
        """Type and axis columns of the components the findings are about."""
        by_index = self._components_by_index()
        items = []
        for index in dict.fromkeys(f.component_index for f in targets if f.component_index):
            comp = by_index.get(str(index))
            if comp is None:
                continue
            config = comp.get("config") or {}
            item: dict[str, Any] = {"component_index": index, "type": comp.get("type")}
            item.update({k: config[k] for k in _AXIS_KEYS if k in config})
            item["shape_allowed"] = str(comp.get("type") or "").lower() in SHAPE_COMPONENT_TYPES
            # Rows can be marked by id only through the component's selection column.
            item["points_by_id_column"] = config.get("selection_column")
            items.append(item)
        return _json(items, SUMMARY_CONTEXT_CHARS) if items else "[]"

    async def _annotator(self, member: TeamMember) -> None:
        targets = [f for f in self.run.findings if f.verdict == "confirmed" and f.component_index]
        if not targets:
            await self._skip(member, "no confirmed finding on a component.")
            return
        record = await self._start(member)
        outcome = await self._loop(
            member, record, task=self._annotator_task(targets), schema=ANNOTATOR_SCHEMA
        )
        types = {i: str(c.get("type") or "") for i, c in self._components_by_index().items()}
        specs = _specs_by_finding(outcome.output)
        drawn: dict[str, bool] = {}
        retry: dict[str, str] = {}
        # Without the annotate scope every write is refused: no retry to spend on.
        can_retry = self.context(member).has("annotate")
        for f in targets:
            if await self.cancel.cancelled():
                break
            spec = specs.get(f.finding_id) or {}
            result = await self._annotate(member, record, f, spec, types, final=not can_retry)
            if isinstance(result, str):
                retry[f.finding_id] = result
            elif result is not None:
                drawn[f.finding_id] = result
        if retry and not await self.cancel.cancelled():
            # One more turn to fix the shapes, told what was wrong with each.
            again = [f for f in targets if f.finding_id in retry]
            problems = [
                {
                    "finding_id": f.finding_id,
                    "sent": specs.get(f.finding_id),
                    "error": retry[f.finding_id],
                }
                for f in again
            ]
            fixed = await self._loop(
                member,
                record,
                task=self._annotator_task(again)
                + "\n\nShapes that failed:\n"
                + _json(problems, SUMMARY_CONTEXT_CHARS)
                + "\n\n"
                + ANNOTATOR_RETRY,
                schema=ANNOTATOR_SCHEMA,
            )
            respecs = _specs_by_finding(fixed.output)
            for f in again:
                if await self.cancel.cancelled():
                    break
                spec = respecs.get(f.finding_id) or specs.get(f.finding_id) or {}
                result = await self._annotate(member, record, f, spec, types, final=True)
                if isinstance(result, bool):
                    drawn[f.finding_id] = result
        shapes = sum(drawn.values())
        comments = len(drawn) - shapes
        status = outcome.status if outcome.status != "error" else "ok"
        await self._finish(
            record,
            status,
            f"{_plural(shapes, 'annotation')} and {_plural(comments, 'plain comment')} proposed",
            {"annotations": shapes, "comments": comments},
        )

    def _annotator_task(self, targets: list[RunFinding]) -> str:
        return (
            f"Dashboard id: {self.run.dashboard_id}\n\nComponents of these findings "
            "(type and the columns on their axes):\n"
            + self._axes_brief(targets)
            + "\n\nConfirmed findings to annotate:\n"
            + self._findings_brief(targets)
        )

    async def _annotate(
        self,
        member: TeamMember,
        record: AgentRecord,
        f: RunFinding,
        spec: dict[str, Any],
        types: dict[str, str],
        *,
        final: bool,
    ) -> bool | str | None:
        """Write the annotation of ``f``: True with a shape, False as a plain comment.

        A shape the annotator meant but got wrong (or the tool rejected) is
        returned as its error string when not ``final``, for one retry; on the
        final attempt it degrades to a plain comment with a run warning. None
        when nothing could be written.
        """
        body = str(spec.get("body") or "").strip() or f"{f.title}. {f.detail}"
        base: dict[str, Any] = {
            "dashboard_id": self.run.dashboard_id,
            "component_index": f.component_index,
            "body": body[:MAX_BODY_CHARS],
            "evidence": self._evidence_args(f),
            "dedupe_key": dedupe_key(self.run.question, f.title, f.component_index),
        }
        problem: str | None = None
        if spec.get("shape"):
            comp_type = types.get(str(f.component_index)) or None
            if not shape_allowed(comp_type):
                self.run.warnings.append(
                    f"{member.agent_id}: a {comp_type} ({f.component_index}) cannot hold a "
                    f"shape; {spec.get('shape')!r} written as a plain comment."
                )
            else:
                shape, problem = check_shape(spec)
                if shape is not None:
                    errors: list[str] = []
                    data = await self._write(
                        member, record, "create_annotation", {**base, **shape}, errors=errors
                    )
                    if data is not None:
                        await self._thread_created(member, data, f, "comment")
                        return True
                    problem = errors[0] if errors else "rejected"
                if not final:
                    return problem
                self.run.warnings.append(
                    f"{member.agent_id}: shape {spec.get('shape')!r} on {f.component_index} "
                    f"could not be drawn ({problem}); written as a plain comment."
                )
        data = await self._write(member, record, "create_annotation", base)
        if data is None:
            return None
        await self._thread_created(member, data, f, "comment")
        return False

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
        await self._finish(
            record, outcome.status, f"{_plural(asked, 'question')} asked", {"questions": asked}
        )

    def _fallback_summary(self) -> str:
        lines = [f"**Question:** {self.run.question}", ""]
        for label, verdict in (
            ("Confirmed", "confirmed"),
            ("Weakened", "weakened"),
            ("Refuted", "refuted"),
            ("Unverified (not reviewed)", "unverified"),
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
                "Findings and verdicts (unverified: the skeptic did not review it, so "
                "report it as unverified, with low confidence):\n"
                + self._findings_brief(self.run.findings, with_verdicts=True)
                + f"\n\nWarnings of the run: {_json(self.run.warnings[-10:], 2_000)}"
            ),
            schema=REPORTER_SCHEMA,
            reserve=True,
        )
        summary = str((outcome.output or {}).get("summary_md") or "").strip()
        if not summary:
            summary = self._fallback_summary()
        if len(summary) > REPORT_MAX_SUMMARY_CHARS:
            summary = summary[: REPORT_MAX_SUMMARY_CHARS - 1].rstrip() + "\u2026"
        rank = {"confirmed": 0, "weakened": 1, "unverified": 2}
        kept = sorted(
            (f for f in self.run.findings if f.verdict in rank),
            key=lambda f: rank[f.verdict or ""],
        )
        if len(kept) > REPORT_MAX_FINDINGS:
            self.run.warnings.append(
                f"{member.agent_id}: the report keeps {REPORT_MAX_FINDINGS} of "
                f"{len(kept)} findings (confirmed first, then weakened, then unverified)."
            )
            kept = kept[:REPORT_MAX_FINDINGS]
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
        # Agents stopping at their phase share is expected; the run only counts
        # as cut short when that cost it a report or a verdict.
        cut_short = self.run.outputs.report_id is None or any(
            f.verdict == "unverified" for f in self.run.findings
        )
        stopped = any(o.status == "budget" for o in self.outcomes.values())
        if cut_short and (stopped or self.ledger.exhausted(reserve=True)):
            return "budget"
        if self.members("reporter") and self.run.outputs.report_id is None:
            # The report is the run's deliverable: without it the run did not complete.
            return "failed"
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

    The run is detached from the stream: if the client goes away mid-run, the
    run goes on to its end (bounded by its budget ledger) and stays readable
    through ``GET /ai/agent-runs/{run_id}``. Only an explicit cancel stops it.
    The class-level registries keep each live task referenced until it ends.
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
        listening = True

        async def emit(event: str, data: dict[str, Any]) -> None:
            if listening:
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
            # The client left: stop queueing events nobody reads, keep the run going.
            listening = False


def format_sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()
