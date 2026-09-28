"""Evidence validation: findings stand only on this run's successful evidence calls."""

from depictio.api.v1.agents.evidence import evidence_calls, validate
from depictio.api.v1.agents.runs import ToolCallRecord

CALLS = [
    ToolCallRecord(
        call_id="c-query",
        tool="query_data",
        args={"code": "df.group_by('species').len()", "dc_id": "dc1"},
        ok=True,
        evidence=True,
        values={"setosa": 50},
    ),
    ToolCallRecord(
        call_id="c-data",
        tool="get_component_data",
        args={"dashboard_id": "d1", "index": "c1"},
        ok=True,
        evidence=True,
        values=12.5,
    ),
    ToolCallRecord(call_id="c-failed", tool="query_data", args={}, ok=False, evidence=False),
    ToolCallRecord(call_id="c-meta", tool="get_dashboard", args={}, ok=True, evidence=False),
]


def _finding(title="Setosa has 50 rows", **kw):
    return {"title": title, "detail": "d", "evidence": [{"call_id": "c-query", "note": "n"}], **kw}


def test_only_successful_evidence_calls_count():
    assert set(evidence_calls(CALLS)) == {"c-query", "c-data"}


def test_valid_finding_gets_server_evidence():
    warnings: list[str] = []
    [f] = validate([_finding()], CALLS, agent_id="a", warnings=warnings)
    [ev] = f.evidence
    assert ev.call_id == "c-query" and ev.note == "n"
    # Query and values come from the call record, not from the model.
    assert ev.query == "df.group_by('species').len()" and ev.values == {"setosa": 50}
    assert not warnings


def test_scalar_values_and_non_query_tools():
    [f] = validate(
        [{"title": "t", "detail": "d", "call_ids": ["c-data"]}], CALLS, agent_id="a", warnings=[]
    )
    assert f.evidence[0].values == {"value": 12.5}
    assert '"tool": "get_component_data"' in f.evidence[0].query


def test_uncited_invented_failed_and_non_evidence_calls_are_rejected():
    warnings: list[str] = []
    raw = [
        {"title": "No citation", "detail": "d"},
        {"title": "Invented", "detail": "d", "evidence": [{"call_id": "made-up"}]},
        {"title": "Failed call", "detail": "d", "evidence": [{"call_id": "c-failed"}]},
        {"title": "Metadata only", "detail": "d", "evidence": [{"call_id": "c-meta"}]},
        {"detail": "no title", "evidence": [{"call_id": "c-query"}]},
        "not a dict",
    ]
    assert validate(raw, CALLS, agent_id="a", warnings=warnings) == []
    assert len(warnings) == 6
    assert any("made-up" in w for w in warnings)


def test_mixed_citations_keep_the_valid_ones():
    warnings: list[str] = []
    raw = _finding(
        evidence=[{"call_id": "c-query"}, {"call_id": "made-up"}, {"call_id": "c-query"}]
    )
    [f] = validate([raw], CALLS, agent_id="a", warnings=warnings)
    assert [e.call_id for e in f.evidence] == ["c-query"]
    assert "ignored citations" in warnings[0]


def test_unknown_component_is_cleared_and_ids_are_stable():
    warnings: list[str] = []
    found = validate(
        [_finding(component_index="gone"), _finding(component_index="c1", confidence="HIGH")],
        CALLS,
        agent_id="a",
        warnings=warnings,
        known_components={"c1"},
    )
    assert found[0].component_index is None and found[1].component_index == "c1"
    assert found[1].confidence == "high"
    assert "not on this dashboard" in warnings[0]
    again = validate([_finding(component_index="c1")], CALLS, agent_id="a", warnings=[])
    assert again[0].finding_id == found[1].finding_id


def test_duplicate_titles_get_distinct_ids():
    taken: set[str] = set()
    found = validate([_finding(), _finding()], CALLS, agent_id="a", warnings=[], taken_ids=taken)
    assert found[0].finding_id != found[1].finding_id and len(taken) == 2


def test_not_a_list():
    warnings: list[str] = []
    assert validate({"title": "x"}, CALLS, agent_id="a", warnings=warnings) == []
    assert warnings
