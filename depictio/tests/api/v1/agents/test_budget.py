"""The run ledger anticipates the next LLM call, per role, and keeps the reporter's reserve."""

from types import SimpleNamespace

from depictio.api.v1.agents.budget import BudgetLedger
from depictio.tests.api.v1.agents._fakes import FakeLLM, FakeToolbox, call, default_tools, turn
from depictio.tests.api.v1.agents.test_runner import _run


def _usage(cost, tokens=100):
    return SimpleNamespace(total_tokens=tokens, cost_usd=cost)


def _ledger(usd=0.40, tokens=1_000_000):
    # 15% reserve: everyone but the reporter stops at 0.34.
    return BudgetLedger(max_tool_calls=100, limit_usd=usd, max_tokens=tokens)


def test_nothing_is_expected_before_the_first_call():
    ledger = _ledger()
    assert ledger.expected_cost("analyst") == 0.0
    assert ledger.can_think(role="analyst", turns=2)


def test_next_call_is_expected_to_cost_the_role_maximum():
    ledger = _ledger()
    ledger.record_llm(_usage(0.02), None, role="analyst")
    ledger.record_llm(_usage(0.08), None, role="analyst")
    assert ledger.expected_cost("analyst") == 0.08
    # 0.10 spent: two more 0.08 calls (0.26) fit under 0.34.
    assert ledger.can_think(role="analyst", turns=2)
    ledger.record_llm(_usage(0.08), None, role="analyst")  # 0.18
    ledger.record_llm(_usage(0.08), None, role="analyst")  # 0.26
    # One more (0.34) still fits, two more (0.42) do not.
    assert ledger.can_think(role="analyst", turns=1)
    assert not ledger.can_think(role="analyst", turns=2)
    ledger.record_llm(_usage(0.05), None, role="analyst")  # 0.31
    assert not ledger.can_think(role="analyst", turns=1)  # 0.39 > 0.34
    # The reporter may use the reserve: 0.31 + 0.08 fits the whole 0.40.
    assert ledger.can_think(reserve=True, role="analyst", turns=1)


def test_unseen_role_expects_the_run_maximum():
    ledger = _ledger()
    ledger.record_llm(_usage(0.12), None, role="analyst")
    ledger.record_llm(_usage(0.02), None, role="skeptic")
    assert ledger.expected_cost("skeptic") == 0.02
    assert ledger.expected_cost("reporter") == 0.12
    ledger.record_llm(_usage(0.12), None, role="analyst")  # 0.26
    assert ledger.can_think(role="skeptic", turns=2)  # 0.30
    assert not ledger.can_think(role="annotator", turns=1)  # 0.38 > 0.34
    assert ledger.can_think(reserve=True, role="reporter")  # 0.38 <= 0.40


def test_token_ceiling_is_anticipated_too():
    ledger = _ledger(tokens=1_000)  # 850 without the reserve
    ledger.record_llm(_usage(None, tokens=450), None, role="analyst")
    assert not ledger.cost_known  # unknown cost: only tokens bound the run
    assert not ledger.can_think(role="analyst", turns=1)  # 900 > 850
    assert ledger.can_think(reserve=True, role="analyst", turns=1)  # 900 <= 1000


def test_agent_stops_before_the_step_that_would_overrun():
    # Every turn costs 0.10 and asks for a tool: the loop must leave room for its
    # conclude call and stop under the non-reserve limit (0.34).
    def answer(messages, tools, choice):
        if choice == "none":
            return turn({"findings": []}, cost=0.10)
        return turn(calls=[call("query_data", {"code": "df.height"})], cost=0.10)

    ledger = _ledger()
    llm = FakeLLM(answer)
    outcome, record = _run(llm, ledger=ledger, toolbox=FakeToolbox(tools=default_tools()))
    assert outcome.status == "budget" and outcome.output == {"findings": []}
    assert len(llm.calls) == 3 and llm.calls[-1]["tool_choice"] == "none"
    assert round(ledger.spent_usd, 6) == 0.30 <= 0.34
    assert round(record.cost_usd or 0, 6) == 0.30


def test_no_conclude_call_when_it_cannot_fit():
    ledger = _ledger()
    ledger.record_llm(_usage(0.30), None, role="analyst")
    llm = FakeLLM([])
    outcome, _ = _run(llm, ledger=ledger)
    assert outcome.status == "budget" and outcome.output is None
    assert not llm.calls


# -- phases ----------------------------------------------------------------------
# At 0.40: analysts up to 0.18, skeptic up to 0.28, writers up to 0.34, reporter 0.40.


def test_each_phase_stops_at_its_cumulative_share():
    ledger = _ledger()
    for _ in range(4):
        ledger.record_llm(_usage(0.04), None, role="analyst")  # 0.16
    assert not ledger.can_think(phase="analysts", role="analyst")  # 0.20 > 0.18
    assert ledger.can_think(phase="skeptic", role="skeptic")  # 0.20 <= 0.28
    assert not ledger.can_think(phase="skeptic", role="skeptic", turns=4)  # 0.32 > 0.28
    ledger.record_llm(_usage(0.04), None, role="analyst")  # 0.20: past the analysts' share
    assert not ledger.try_tool_call(phase="analysts")
    assert ledger.try_tool_call(phase="skeptic")


def test_unused_allowance_rolls_forward():
    ledger = _ledger()
    ledger.record_llm(_usage(0.04), None, role="analyst")  # analysts used 0.04 of 0.18
    # The skeptic's own share is 0.10 (2 calls of 0.04); with what the analysts
    # left it may make 6 (0.28).
    assert ledger.can_think(phase="skeptic", role="skeptic", turns=5)
    assert not ledger.can_think(phase="skeptic", role="skeptic", turns=7)
    # A later phase never takes the reporter's share.
    for _ in range(6):
        ledger.record_llm(_usage(0.04), None, role="annotator")  # 0.28
    assert not ledger.can_think(phase="writers", role="annotator", turns=2)  # 0.36 > 0.34
    assert ledger.can_think(phase="reporter", role="reporter", turns=2)  # 0.36 <= 0.40
    assert ledger.can_think(reserve=True, role="reporter", turns=2)


def test_forced_answer_borrows_from_later_phases_but_not_the_reporter():
    ledger = _ledger()
    for _ in range(7):
        ledger.record_llm(_usage(0.04), None, role="skeptic")  # 0.28
    assert not ledger.can_think(phase="skeptic", role="skeptic")  # 0.32 > 0.28
    assert ledger.can_force(role="skeptic", then="reporter")  # 0.28 + 0.04 + 0.04
    ledger.record_llm(_usage(0.04), None, role="skeptic")  # 0.32
    ledger.record_llm(_usage(0.04), None, role="skeptic")  # 0.36
    assert not ledger.can_force(role="skeptic", then="reporter")  # 0.44 > 0.40


def test_analyst_is_nudged_then_concludes_inside_its_phase():
    import asyncio

    from depictio.api.v1.agents.profiles import load_profiles
    from depictio.api.v1.agents.runner import NUDGE_PROMPT, agent_loop
    from depictio.tests.api.v1.agents._fakes import ctx
    from depictio.tests.api.v1.agents.test_runner import _record

    def answer(messages, tools, choice):
        if choice == "none":
            return turn({"findings": []}, cost=0.035)
        return turn(calls=[call("query_data", {"code": "df.height"})], cost=0.035)

    ledger = _ledger()
    llm = FakeLLM(answer)
    profiles = load_profiles()
    outcome = asyncio.run(
        agent_loop(
            profiles.role("analyst"),
            profiles.topic("general"),
            ctx(),
            "Which species differ?",
            task="Dashboard id: d1",
            output_schema={"type": "object"},
            llm=llm,
            ledger=ledger,
            record=_record(),
            toolbox=FakeToolbox(tools=default_tools()),
            phase="analysts",
        )
    )
    # Four tool turns (the last one after the nudge), then the conclude call.
    assert outcome.status == "budget" and outcome.output == {"findings": []}
    assert len(llm.calls) == 5 and llm.calls[-1]["tool_choice"] == "none"
    assert ledger.spent_usd <= 0.18
    nudges = [m for m in llm.calls[-1]["messages"] if m.get("content") == NUDGE_PROMPT]
    assert len(nudges) == 1
    assert not any(m.get("content") == NUDGE_PROMPT for m in llm.calls[2]["messages"])
    assert any(m.get("content") == NUDGE_PROMPT for m in llm.calls[3]["messages"])
