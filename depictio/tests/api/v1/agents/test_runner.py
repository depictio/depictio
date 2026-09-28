"""The agent loop: native tool calls, the JSON fallback, budgets, cancellation."""

import asyncio
import json

from depictio.api.v1.agents.budget import BudgetLedger
from depictio.api.v1.agents.profiles import load_profiles
from depictio.api.v1.agents.runner import CancelToken, agent_loop
from depictio.api.v1.agents.runs import AgentRecord
from depictio.tests.api.v1.agents._fakes import FakeLLM, FakeToolbox, call, ctx, default_tools, turn

FINAL = {"summary": "done", "findings": []}


def _record():
    return AgentRecord(
        agent_id="analyst/general@1",
        role="analyst",
        topic="general",
        role_version=1,
        topic_version=1,
    )


def _ledger(**kw):
    return BudgetLedger(
        max_tool_calls=kw.get("calls", 20),
        limit_usd=kw.get("usd", 1.0),
        max_tokens=kw.get("tokens", 100_000),
    )


def _run(llm, *, role=None, toolbox=None, ledger=None, cancel=None, events=None, scopes=None):
    profiles = load_profiles()
    record = _record()

    async def emit(event, data):
        if events is not None:
            events.append((event, data))

    outcome = asyncio.run(
        agent_loop(
            role or profiles.role("analyst"),
            profiles.topic("general"),
            ctx(scopes),
            "Which species differ?",
            task="Dashboard id: d1",
            output_schema={"type": "object"},
            llm=llm,
            ledger=ledger or _ledger(),
            record=record,
            toolbox=toolbox or FakeToolbox(tools=default_tools()),
            emit=emit,
            cancel=cancel,
        )
    )
    return outcome, record


def test_native_tool_calling():
    llm = FakeLLM(
        [turn(calls=[call("query_data", {"code": "df.mean()", "dc_id": "x"})]), turn(FINAL)]
    )
    events = []
    toolbox = FakeToolbox(tools=default_tools())
    outcome, record = _run(llm, toolbox=toolbox, events=events)

    assert outcome.status == "ok" and outcome.output == FINAL
    # Offered tools: the analyst's, filtered to what the fake registry has.
    offered = {t["function"]["name"] for t in llm.calls[0]["tools"]}
    assert "query_data" in offered and "create_annotation" not in offered
    [rec] = record.tool_calls
    assert rec.tool == "query_data" and rec.ok and rec.evidence and rec.values == {"value": 42.0}
    tool_msg = llm.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "tc1"
    assert json.loads(tool_msg["content"])["call_id"] == rec.call_id
    names = [e for e, _ in events]
    assert names.index("tool_call") < names.index("tool_result")
    assert "budget" in names
    assert record.tokens == 200 and record.cost_usd == 0.002
    # The agent's context carries its name and the run id.
    assert toolbox.invoked[0][1].agent_name == "analyst/general@1"


def test_json_fallback_without_function_calling():
    llm = FakeLLM(
        [
            turn('{"tool": "query_data", "args": {"code": "df.shape"}}'),
            turn("```json\n" + json.dumps({"final": FINAL}) + "\n```"),
        ],
        tools=False,
    )
    toolbox = FakeToolbox(tools=default_tools())
    outcome, record = _run(llm, toolbox=toolbox)
    assert outcome.status == "ok" and outcome.output == FINAL
    assert all(c["tools"] is None for c in llm.calls)
    assert "query_data" in llm.calls[0]["messages"][0]["content"]  # tool catalogue in the prompt
    assert toolbox.calls_to("query_data") == [{"code": "df.shape"}]
    assert llm.calls[1]["messages"][-1]["content"].startswith("Tool result:")


def test_budget_exhaustion_ends_with_one_conclude_call():
    role = load_profiles().role("analyst")
    role = role.model_copy(update={"budget": role.budget.model_copy(update={"max_tool_calls": 1})})
    q = call("query_data", {"code": "df"})
    llm = FakeLLM([turn(calls=[q]), turn(FINAL)])
    toolbox = FakeToolbox(tools=default_tools())
    outcome, _ = _run(llm, role=role, toolbox=toolbox)
    assert outcome.status == "budget" and outcome.output == FINAL
    assert len(toolbox.invoked) == 1
    assert llm.calls[-1]["tool_choice"] == "none"
    assert "budget is used up" in llm.calls[-1]["messages"][-1]["content"]


def test_run_pool_refuses_calls_beyond_the_reporter_reserve():
    # 3 calls in the pool, 2 held back for the reporter: an analyst gets one.
    q = call("query_data", {"code": "df"})
    llm = FakeLLM([turn(calls=[q]), turn(calls=[q]), turn(FINAL)])
    toolbox = FakeToolbox(tools=default_tools())
    ledger = _ledger(calls=3)
    outcome, _ = _run(llm, toolbox=toolbox, ledger=ledger)
    assert len(toolbox.invoked) == 1 and ledger.tool_calls == 1
    assert outcome.status == "budget"
    assert ledger.try_tool_call(reserve=True)  # the reporter still can


def test_cost_ceiling_stops_the_loop():
    llm = FakeLLM([turn(calls=[call("query_data", {"code": "df"})], cost=5.0), turn(FINAL)])
    outcome, _ = _run(llm, ledger=_ledger(usd=0.5))
    assert outcome.status == "budget"
    assert llm.calls[-1]["tool_choice"] == "none"


def test_tool_outside_the_profile_is_refused():
    llm = FakeLLM([turn(calls=[call("create_report", {"dashboard_id": "d"})]), turn(FINAL)])
    toolbox = FakeToolbox(tools=default_tools())
    outcome, record = _run(llm, toolbox=toolbox)
    assert outcome.status == "ok" and not toolbox.invoked and not record.tool_calls
    assert "not available" in llm.calls[1]["messages"][-1]["content"]


def test_invalid_json_gets_one_repair():
    llm = FakeLLM([turn("I think the answer is yes"), turn(FINAL)])
    outcome, _ = _run(llm)
    assert outcome.status == "ok"
    llm = FakeLLM([turn("nope"), turn("still nope")])
    outcome, _ = _run(llm)
    assert outcome.status == "error"


def test_cancel_stops_before_the_next_turn():
    token = CancelToken()
    token.cancel()
    llm = FakeLLM([])
    outcome, _ = _run(llm, cancel=token)
    assert outcome.status == "cancelled" and not llm.calls


def test_llm_failure_is_an_agent_error():
    def boom(messages, tools, choice):
        raise RuntimeError("provider down")

    outcome, _ = _run(FakeLLM(boom))
    assert outcome.status == "error" and "provider down" in outcome.summary
