"""The team pipeline end to end with a scripted LLM and fake tools."""

import asyncio
import re
from collections import Counter

from depictio.api.v1.agents.budget import BudgetLedger
from depictio.api.v1.agents.profiles import load_profiles
from depictio.api.v1.agents.registry import ToolResult
from depictio.api.v1.agents.router import RouteContext, route
from depictio.api.v1.agents.runner import CancelToken
from depictio.api.v1.agents.team import TeamDeps, TeamRun, dedupe_key, new_run, shape_args
from depictio.models.models.users import effective_scopes
from depictio.tests.api.v1.agents._fakes import (
    FakeLLM,
    FakeTool,
    FakeToolbox,
    call,
    default_tools,
    role_of,
    turn,
    user,
)

QUESTION = "Which species differ in bill length?"


def team_script():
    """Answers per role: analyst queries once, then reports three findings."""
    seen: Counter[str] = Counter()

    def answer(messages, tools, tool_choice):
        role = role_of(messages)
        seen[role] += 1
        if role == "analyst":
            if seen[role] == 1:
                return turn(calls=[call("query_data", {"code": "df.group_by('species')"})])
            return turn(
                {
                    "summary": "Two differences.",
                    "findings": [
                        {
                            "title": "Gentoo bills are longest",
                            "detail": "Mean 47.5 mm.",
                            "component_index": "c1",
                            "confidence": "high",
                            "evidence": [{"call_id": "call-1", "note": "group means"}],
                        },
                        {
                            "title": "Chinstrap differs from Adelie",
                            "detail": "Means 48.8 vs 38.8.",
                            "component_index": "c2",
                            "evidence": [{"call_id": "call-1"}],
                        },
                        {
                            "title": "Invented claim",
                            "detail": "No call backs this.",
                            "evidence": [{"call_id": "call-999"}],
                        },
                    ],
                }
            )
        if role == "skeptic":
            ids = _finding_ids(messages[-1]["content"])
            return turn(
                {
                    "verdicts": [
                        {"finding_id": ids[0], "verdict": "confirmed", "reason": "Re-checked."},
                        {"finding_id": ids[1], "verdict": "weakened", "reason": "Small n."},
                    ]
                }
            )
        if role == "annotator":
            fid = _finding_ids(messages[-1]["content"])[0]
            return turn(
                {
                    "annotations": [
                        {
                            "finding_id": fid,
                            "body": "Gentoo bills are the longest (47.5 mm).",
                            "shape": "y_range",
                            "y0": 45,
                            "y1": 50,
                        }
                    ]
                }
            )
        if role == "questioner":
            fid = _finding_ids(messages[-1]["content"])[0]
            return turn({"questions": [{"finding_id": fid, "body": "Were juveniles excluded?"}]})
        return turn({"summary_md": "Gentoo bills are the longest."})

    return answer


def _finding_ids(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"f_[0-9a-f]{10}", text)))


def _job(
    llm,
    toolbox,
    *,
    saved=None,
    cancel=None,
    scopes=None,
    question=QUESTION,
    ledger=None,
    summary=None,
):
    profiles = load_profiles()
    route_ctx = RouteContext(
        dashboard_id="d1", component_indexes={"c1", "c2"}, summary=summary or {}
    )
    plan = asyncio.run(route(profiles, route_ctx, question, team=["analyst/general@1"]))
    ledger = ledger or BudgetLedger(max_tool_calls=30, limit_usd=1.0, max_tokens=100_000)
    run = new_run(
        run_id="run-1",
        user_id="u1",
        dashboard_id="d1",
        question=question,
        plan=plan,
        profiles=profiles,
        model=llm.model,
        ledger=ledger,
    )
    saved = saved if saved is not None else []
    return TeamRun(
        run=run,
        plan=plan,
        route_ctx=route_ctx,
        user=user(),
        user_scopes=effective_scopes(scopes),
        deps=TeamDeps(
            llm=llm,
            profiles=profiles,
            toolbox=toolbox,
            persist=lambda r: saved.append(r.model_copy(deep=True)),
        ),
        ledger=ledger,
        cancel=cancel or CancelToken(),
    )


def _execute(job):
    events = []

    async def emit(event, data):
        events.append((event, data))

    asyncio.run(job.execute(emit))
    return events


def test_full_pipeline():
    toolbox = FakeToolbox(tools=default_tools())
    saved = []
    job = _job(FakeLLM(team_script()), toolbox, saved=saved)
    events = _execute(job)
    names = [e for e, _ in events]

    assert names[0] == "run_started" and names[-2:] == ["run_finished", "done"]
    started = dict(events[0][1])
    assert [m["role"] for m in started["team"]] == [
        "analyst",
        "skeptic",
        "annotator",
        "questioner",
        "reporter",
    ]
    assert started["budget"] == {"limit_usd": 1.0, "max_tool_calls": 30}

    # The uncited finding is dropped; two findings, one verdict each.
    findings = [d for e, d in events if e == "finding"]
    assert [f["title"] for f in findings] == [
        "Gentoo bills are longest",
        "Chinstrap differs from Adelie",
    ]
    assert findings[0]["evidence"] == [{"call_id": "call-1", "note": "group means"}]
    verdicts = {d["finding_id"]: d["verdict"] for e, d in events if e == "verdict"}
    assert sorted(verdicts.values()) == ["confirmed", "weakened"]

    # Annotation only for the confirmed finding, with server evidence and a dedupe key.
    [annotation] = toolbox.calls_to("create_annotation")
    assert annotation["component_index"] == "c1" and annotation["shape"] == "y_range"
    assert annotation["evidence"][0]["call_id"] == "call-1"
    assert annotation["evidence"][0]["query"] == "df.group_by('species')"
    assert annotation["dedupe_key"] == dedupe_key(QUESTION, "Gentoo bills are longest", "c1")
    # Question only for the weakened one.
    [question] = toolbox.calls_to("ask_question")
    assert question["component_index"] == "c2" and question["dedupe_key"].startswith("team:q:")

    threads = [d for e, d in events if e == "thread_created"]
    assert [(t["kind"], t["thread_id"]) for t in threads] == [
        ("comment", "t-c1"),
        ("question", "q-c2"),
    ]
    [report] = toolbox.calls_to("create_report")
    assert {f["verdict"] for f in report["findings"]} == {"confirmed", "weakened"}
    weakened = next(f for f in report["findings"] if f["verdict"] == "weakened")
    assert weakened["confidence"] == "low" and weakened["verdict_reason"] == "Small n."
    assert report["summary"] == "Gentoo bills are the longest."
    assert ("report_created", {"agent_id": "reporter/general@1", "report_id": "r1"}) in events

    finished = events[-2][1]
    assert finished["status"] == "complete"
    assert finished["outputs"] == {
        "thread_ids": ["t-c1", "q-c2"],
        "report_id": "r1",
        "draft_ids": [],
    }

    # Writes carry the writing agent's name and the run id; scopes follow the role.
    ctxs = {name: c for name, c, _ in toolbox.invoked}
    assert ctxs["create_annotation"].agent_name == "annotator/general@1"
    assert ctxs["create_annotation"].run_id == "run-1"
    assert "annotate" not in ctxs["query_data"].scopes
    assert "report" in ctxs["create_report"].scopes

    run = saved[-1]
    assert run.status == "complete" and run.finished_at
    assert len(run.findings) == 2 and len(run.verdicts) == 2 and len(run.threads) == 2
    assert any("call-999" in w for w in run.warnings)
    analyst = run.agent("analyst/general@1")
    assert analyst.status == "ok" and analyst.tool_calls[0].evidence
    detail = run.detail()
    assert detail["agents"][0]["findings"][0]["thread_ids"] == ["t-c1"]
    assert detail["budget"]["tool_calls"] == 1


def test_rerun_reuses_dedupe_keys():
    keys = []
    for _ in range(2):
        toolbox = FakeToolbox(tools=default_tools())
        _execute(_job(FakeLLM(team_script()), toolbox))
        keys.append([a["dedupe_key"] for a in toolbox.calls_to("create_annotation")])
    assert keys[0] == keys[1] and keys[0]


def test_rejected_shape_falls_back_to_a_plain_comment():
    tools = default_tools()
    good = tools["create_annotation"].fn

    def picky(args):
        if "shape" in args:
            raise AssertionError("unreachable")
        return good(args)

    tools["create_annotation"].fn = picky
    toolbox = FakeToolbox(tools=tools)
    original = toolbox._invoke

    async def reject_shapes(name, ctx, args):
        if name == "create_annotation" and "shape" in args:
            toolbox.counter += 1
            return ToolResult(ok=False, call_id="bad", error="Invalid annotation")
        return await original(name, ctx, args)

    toolbox.invoke = reject_shapes
    events = _execute(_job(FakeLLM(team_script()), toolbox))
    assert [d["thread_id"] for e, d in events if e == "thread_created"][0] == "t-c1"
    assert any(e == "error" for e, _ in events)


def test_user_without_annotate_scope_gets_no_threads():
    toolbox = FakeToolbox(tools=default_tools())
    events = _execute(_job(FakeLLM(team_script()), toolbox, scopes=["read", "report"]))
    assert not [d for e, d in events if e == "thread_created"]
    assert toolbox.calls_to("create_annotation")  # attempted, refused by scope
    assert ("report_created", {"agent_id": "reporter/general@1", "report_id": "r1"}) in events


def test_no_findings_skips_review_and_still_reports():
    def answer(messages, tools, choice):
        if role_of(messages) == "analyst":
            return turn({"findings": []})
        return turn({"summary_md": "Nothing stood out."})

    toolbox = FakeToolbox(tools=default_tools())
    events = _execute(_job(FakeLLM(answer), toolbox))
    finished = {d["agent_id"]: d for e, d in events if e == "agent_finished"}
    assert finished["skeptic/general@1"]["summary"].startswith("Skipped")
    assert not toolbox.calls_to("create_annotation") and toolbox.calls_to("create_report")
    assert events[-2][1]["status"] == "complete"


def test_cancel_before_start():
    token = CancelToken()
    token.cancel()
    llm = FakeLLM(team_script())
    events = _execute(_job(llm, FakeToolbox(tools=default_tools()), cancel=token))
    assert events[-2][0] == "run_finished" and events[-2][1]["status"] == "cancelled"
    assert not llm.calls


def test_all_analysts_failing_fails_the_run():
    def boom(messages, tools, choice):
        raise RuntimeError("down")

    events = _execute(_job(FakeLLM(boom), FakeToolbox(tools=default_tools())))
    assert events[-2][1]["status"] == "failed"


def test_run_stays_under_the_usd_limit():
    # The run that spent 0.48 of 0.40: analysts kept calling tools. Every call
    # here costs 0.05; the ledger must stop each step before it would overrun.
    def answer(messages, tools, choice):
        role = role_of(messages)
        if role == "analyst":
            if choice == "none":
                return turn(
                    {
                        "findings": [
                            {
                                "title": "Gentoo are heaviest",
                                "detail": "Mean 5076 g.",
                                "component_index": "c1",
                                "evidence": [{"call_id": "call-1"}],
                            }
                        ]
                    },
                    cost=0.05,
                )
            return turn(calls=[call("query_data", {"code": "df.height"})], cost=0.05)
        if role == "skeptic":
            return turn(calls=[call("get_component_data", {"index": "c1"})], cost=0.05)
        return turn({"summary_md": "Gentoo are heaviest.", "questions": []}, cost=0.05)

    ledger = BudgetLedger(max_tool_calls=40, limit_usd=0.40, max_tokens=1_000_000)
    toolbox = FakeToolbox(tools=default_tools())
    job = _job(FakeLLM(answer), toolbox, ledger=ledger)
    events = _execute(job)

    assert ledger.spent_usd <= 0.40
    assert events[-2][1]["status"] == "budget"
    # The analyst concluded with its finding; the reporter used the reserve.
    assert [d["title"] for e, d in events if e == "finding"] == ["Gentoo are heaviest"]
    [report] = toolbox.calls_to("create_report")
    assert report["summary"] == "Gentoo are heaviest."
    budgets = [d for e, d in events if e == "budget"]
    assert all(b["spent_usd"] <= 0.40 for b in budgets)


def test_shape_args_validation():
    assert shape_args({"shape": "ref_line", "axis": "y", "value": 4200.5, "label": "mean"}) == {
        "shape": "ref_line",
        "axis": "y",
        "value": 4200.5,
        "label": "mean",
    }
    assert shape_args({"shape": "y_range", "y0": 50, "y1": 45}) == {
        "shape": "y_range",
        "y0": 45,
        "y1": 50,
    }
    assert shape_args({"shape": "x_range", "x0": "Adelie", "x1": "Gentoo"})["x0"] == "Adelie"
    got = shape_args(
        {"shape": "points", "column": "id", "ids": [3, "p7", None], "points": [{"x": 1}]}
    )
    assert got == {"shape": "points", "column": "id", "ids": [3, "p7"]}
    got = shape_args({"shape": "points", "points": [{"x": 1, "y": 2}, {"x": 3}]})
    assert got == {"shape": "points", "points": [{"x": 1, "y": 2}]}
    # Incomplete, wrongly typed or not drawable: a plain comment instead.
    for bad in (
        {"shape": "ref_line", "axis": "y", "value": "high"},
        {"shape": "ref_line", "value": 3},
        {"shape": "y_range", "y0": 1, "y1": 1},
        {"shape": "y_range", "y0": True, "y1": 2},
        {"shape": "x_range", "x0": 1},
        {"shape": "points", "column": "id", "ids": []},
        {"shape": "arrow_note", "x": 1},
        {"shape": "circle"},
    ):
        assert shape_args(bad) is None, bad
    assert shape_args({"shape": "ref_line", "axis": "y", "value": 3}, "card") is None
    assert shape_args({"shape": "ref_line", "axis": "y", "value": 3}, "figure") is not None


def _annotator_script(annotation):
    base = team_script()

    def answer(messages, tools, choice):
        if role_of(messages) == "annotator":
            fid = _finding_ids(messages[-1]["content"])[0]
            return turn({"annotations": [{"finding_id": fid, **annotation}]})
        return base(messages, tools, choice)

    return answer


def test_annotator_gets_axes_and_draws_a_ref_line():
    summary = {
        "components": [
            {
                "index": "c1",
                "type": "figure",
                "config": {"visu_type": "box", "x": "species", "y": "bill_length_mm"},
            },
            {"index": "c2", "type": "card"},
        ]
    }
    annotation = {
        "body": "Gentoo mean bill length is 47.5 mm.",
        "shape": "ref_line",
        "axis": "y",
        "value": 47.5,
        "label": "Gentoo mean",
        "ids": "not-a-list",
    }
    llm = FakeLLM(_annotator_script(annotation))
    toolbox = FakeToolbox(tools=default_tools())
    _execute(_job(llm, toolbox, summary=summary))
    brief = next(
        c["messages"][-1]["content"] for c in llm.calls if role_of(c["messages"]) == "annotator"
    )
    assert "bill_length_mm" in brief and '"shape_allowed": true' in brief
    [written] = toolbox.calls_to("create_annotation")
    assert written["shape"] == "ref_line" and written["value"] == 47.5
    assert written["label"] == "Gentoo mean" and "ids" not in written


def test_annotator_shape_on_a_card_becomes_a_plain_comment():
    summary = {"components": [{"index": "c1", "type": "card"}]}
    annotation = {"body": "Gentoo: 47.5 mm.", "shape": "ref_line", "axis": "y", "value": 47.5}
    toolbox = FakeToolbox(tools=default_tools())
    saved = []
    _execute(_job(FakeLLM(_annotator_script(annotation)), toolbox, summary=summary, saved=saved))
    [written] = toolbox.calls_to("create_annotation")
    assert "shape" not in written and written["body"] == "Gentoo: 47.5 mm."
    assert any("plain comment" in w for w in saved[-1].warnings)


# -- phase budgets, partial skeptic, unverified findings ----------------------------


def _all_ids(messages) -> list[str]:
    return _finding_ids(" ".join(str(m.get("content") or "") for m in messages))


def _three_findings(cost):
    return turn(
        {
            "findings": [
                {
                    "title": "Gentoo are heaviest",
                    "detail": "Mean 5076 g.",
                    "component_index": "c1",
                    "evidence": [{"call_id": "call-1"}],
                },
                {
                    "title": "Chinstrap flippers are mid-sized",
                    "detail": "Mean 196 mm.",
                    "component_index": "c2",
                    "evidence": [{"call_id": "call-1"}],
                },
                {
                    "title": "Adelie bills are shortest",
                    "detail": "Mean 38.8 mm.",
                    "evidence": [{"call_id": "call-1"}],
                },
            ]
        },
        cost=cost,
    )


def test_skeptic_out_of_budget_concludes_and_the_rest_is_unverified():
    # The skeptic's second call costs more than expected, leaving no room for
    # its conclude call inside its phase: it is forced (the reporter still
    # fits) and judges only the finding it checked. The other two stay
    # unverified: no annotation, no question, reported with low confidence.
    from depictio.api.v1.agents.runner import NUDGE_PROMPT
    from depictio.api.v1.agents.team import SKEPTIC_CONCLUDE, UNVERIFIED_REASON

    skeptic_costs = iter([0.05, 0.09])

    def answer(messages, tools, choice):
        role = role_of(messages)
        if role == "analyst":
            if any(m["role"] == "tool" for m in messages):
                return _three_findings(0.03)
            return turn(calls=[call("query_data", {"code": "df.mean()"})], cost=0.03)
        if role == "skeptic":
            if choice == "none":
                ids = _all_ids(messages)
                return turn(
                    {"verdicts": [{"finding_id": ids[0], "verdict": "confirmed", "reason": "OK."}]},
                    cost=0.03,
                )
            assert not any(m.get("content") == NUDGE_PROMPT for m in messages)
            return turn(calls=[call("query_data", {"code": "df.height"})], cost=next(skeptic_costs))
        if role == "annotator":
            return turn({"annotations": []}, cost=0.02)
        return turn({"summary_md": "Gentoo are heaviest; two claims unverified."}, cost=0.03)

    ledger = BudgetLedger(max_tool_calls=40, limit_usd=0.40, max_tokens=1_000_000)
    toolbox = FakeToolbox(tools=default_tools())
    llm = FakeLLM(answer)
    saved = []
    events = _execute(_job(llm, toolbox, ledger=ledger, saved=saved))

    skeptic_calls = [c for c in llm.calls if role_of(c["messages"]) == "skeptic"]
    assert skeptic_calls[-1]["tool_choice"] == "none"
    assert skeptic_calls[-1]["messages"][-1]["content"] == SKEPTIC_CONCLUDE
    verdicts = [d for e, d in events if e == "verdict"]
    assert [v["verdict"] for v in verdicts] == ["confirmed", "unverified", "unverified"]
    assert all(v["reason"] == UNVERIFIED_REASON for v in verdicts[1:])

    # Only the confirmed finding is annotated; nothing weakened, so no question.
    assert [a["component_index"] for a in toolbox.calls_to("create_annotation")] == ["c1"]
    assert not toolbox.calls_to("ask_question")
    finished = {d["agent_id"]: d for e, d in events if e == "agent_finished"}
    assert finished["questioner/general@1"]["summary"].startswith("Skipped")
    assert "2 of 3 unverified" in finished["skeptic/general@1"]["summary"]

    [report] = toolbox.calls_to("create_report")
    by_verdict = Counter(f["verdict"] for f in report["findings"])
    assert by_verdict == {"confirmed": 1, "unverified": 2}
    assert all(f["confidence"] == "low" for f in report["findings"] if f["verdict"] == "unverified")
    assert ledger.spent_usd <= 0.40
    run = saved[-1]
    assert [f.verdict for f in run.findings] == ["confirmed", "unverified", "unverified"]
    assert [t.finding_id for t in run.threads] == [run.findings[0].finding_id]


def test_fallback_summary_lists_unverified_findings():
    def answer(messages, tools, choice):
        role = role_of(messages)
        if role == "analyst":
            if any(m["role"] == "tool" for m in messages):
                return _three_findings(0.001)
            return turn(calls=[call("query_data", {"code": "df.mean()"})])
        if role == "skeptic":
            return turn({"verdicts": []})
        return turn("not json at all")

    saved = []
    toolbox = FakeToolbox(tools=default_tools())
    _execute(_job(FakeLLM(answer), toolbox, saved=saved))
    [report] = toolbox.calls_to("create_report")
    assert "**Unverified (not reviewed)**" in report["summary"]
    assert "- Adelie bills are shortest" in report["summary"]
    assert {f.verdict for f in saved[-1].findings} == {"unverified"}
    assert not toolbox.calls_to("create_annotation") and not toolbox.calls_to("ask_question")


def test_full_team_at_forty_cents_reaches_every_role():
    # The live Penguins run: a 0.40 limit, about 0.03 per call. Analysts and the
    # skeptic would keep querying; the phase shares stop them in time for every
    # later role to run, and the skeptic answers once nudged.
    from depictio.api.v1.agents.runner import NUDGE_PROMPT
    from depictio.api.v1.agents.team import UNVERIFIED_REASON

    cost = 0.031

    def nudged(messages):
        return any(m.get("content") == NUDGE_PROMPT for m in messages)

    def answer(messages, tools, choice):
        role = role_of(messages)
        if role == "analyst":
            if choice == "none":
                return _three_findings(cost)
            return turn(calls=[call("query_data", {"code": "df.describe()"})], cost=cost)
        if role == "skeptic":
            if choice == "none" or nudged(messages):
                ids = _all_ids(messages)
                return turn(
                    {
                        "verdicts": [
                            {"finding_id": ids[0], "verdict": "confirmed", "reason": "n=124."},
                            {"finding_id": ids[1], "verdict": "weakened", "reason": "n=68."},
                            {"finding_id": ids[2], "verdict": "refuted", "reason": "39.1 mm."},
                        ]
                    },
                    cost=cost,
                )
            return turn(calls=[call("query_data", {"code": "df.height"})], cost=cost)
        if role == "annotator":
            fid = _finding_ids(messages[1]["content"])[0]
            return turn({"annotations": [{"finding_id": fid, "body": "5076 g."}]}, cost=cost)
        if role == "questioner":
            fid = _finding_ids(messages[1]["content"])[0]
            return turn({"questions": [{"finding_id": fid, "body": "Juveniles?"}]}, cost=cost)
        return turn({"summary_md": "Gentoo are heaviest."}, cost=cost)

    ledger = BudgetLedger(max_tool_calls=60, limit_usd=0.40, max_tokens=1_000_000)
    toolbox = FakeToolbox(tools=default_tools())
    llm = FakeLLM(answer)
    events = _execute(_job(llm, toolbox, ledger=ledger))

    started = [d["role"] for e, d in events if e == "agent_started"]
    assert started == ["analyst", "skeptic", "annotator", "questioner", "reporter"]
    finished = {d["agent_id"]: d for e, d in events if e == "agent_finished"}
    assert not any(d["summary"].startswith("Skipped") for d in finished.values())

    verdicts = [d for e, d in events if e == "verdict"]
    assert sorted(v["verdict"] for v in verdicts) == ["confirmed", "refuted", "weakened"]
    assert not any(v["reason"] == UNVERIFIED_REASON for v in verdicts)
    # The skeptic checked something, was nudged, and answered without a conclude call.
    skeptic_calls = [c for c in llm.calls if role_of(c["messages"]) == "skeptic"]
    assert len(skeptic_calls) >= 2 and nudged(skeptic_calls[-1]["messages"])

    assert len(toolbox.calls_to("create_annotation")) == 1
    assert len(toolbox.calls_to("ask_question")) == 1
    assert ("report_created", {"agent_id": "reporter/general@1", "report_id": "r1"}) in events
    # Analysts kept inside their share (0.18), the whole run inside the limit.
    analyst_spend = sum(0.031 for c in llm.calls if role_of(c["messages"]) == "analyst")
    assert analyst_spend <= 0.18 + 1e-9
    assert ledger.spent_usd <= 0.40
    assert all(d["spent_usd"] <= 0.40 for e, d in events if e == "budget")


def _reporter_job(toolbox, verdicts):
    """A job whose run already holds findings with these verdicts, ready for the reporter."""
    from depictio.api.v1.agents.runs import RunFinding
    from depictio.api.v1.endpoints.ai_endpoints.schemas import AgentEvidence

    job = _job(FakeLLM(lambda *a: turn({"summary_md": "x" * 30_000})), toolbox)
    job.run.findings = [
        RunFinding(
            finding_id=f"f_{i:010d}",
            agent_id="analyst/general@1",
            title=f"{verdict} {i}",
            detail="d",
            evidence=[AgentEvidence(call_id="call-1", note="n")],
            verdict=verdict,
        )
        for i, verdict in enumerate(verdicts)
    ]
    return job


def test_reporter_caps_findings_confirmed_first():
    from depictio.api.v1.agents.tools.reports import MAX_FINDINGS, MAX_SUMMARY_CHARS

    # 35 kept findings (plus a refuted one) listed worst first: the cap keeps the best 30.
    verdicts = ["unverified"] * 15 + ["refuted"] + ["weakened"] * 15 + ["confirmed"] * 5
    toolbox = FakeToolbox(tools=default_tools())
    job = _reporter_job(toolbox, verdicts)
    asyncio.run(job._reporter(job.members("reporter")[0]))
    [report] = toolbox.calls_to("create_report")
    kept = [f["verdict"] for f in report["findings"]]
    assert len(kept) == MAX_FINDINGS == 30
    assert kept == ["confirmed"] * 5 + ["weakened"] * 15 + ["unverified"] * 10
    assert len(report["summary"]) <= MAX_SUMMARY_CHARS
    assert any("keeps 30 of 35 findings" in w for w in job.run.warnings)
    assert job.run.outputs.report_id == "r1" and job._final_status() == "complete"


def test_missing_report_fails_the_run():
    tools = default_tools()
    tools["create_report"] = FakeTool(scope="report", fail="findings: too many")
    job = _reporter_job(FakeToolbox(tools=tools), ["confirmed"])
    asyncio.run(job._reporter(job.members("reporter")[0]))
    assert job.run.outputs.report_id is None
    assert job._final_status() == "failed"


def test_client_disconnect_does_not_cancel_the_run():
    from depictio.api.v1.agents.team import InProcessExecutor

    gate = asyncio.Event()
    script = team_script()

    class GatedLLM(FakeLLM):
        async def complete(self, messages, *, tools=None, tool_choice=None):
            await gate.wait()
            return await super().complete(messages, tools=tools, tool_choice=tool_choice)

    saved = []
    job = _job(GatedLLM(script), FakeToolbox(tools=default_tools()), saved=saved)

    async def scenario():
        executor = InProcessExecutor()
        stream = executor.events(job)
        first, _ = await stream.__anext__()
        assert first == "run_started"
        await stream.aclose()  # the client went away mid-run
        tasks = list(InProcessExecutor._tasks)
        assert tasks and not await job.cancel.cancelled()
        gate.set()
        await asyncio.gather(*tasks)
        assert not executor.cancel(job.run.id)  # no longer live once finished

    asyncio.run(scenario())
    assert saved[-1].status == "complete" and saved[-1].outputs.report_id == "r1"
