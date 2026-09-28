"""Team routing: rules on template, catalog, columns, components and keywords; LLM fallback."""

import asyncio

import pytest

from depictio.api.v1.agents.profiles import ProfileError, load_profiles
from depictio.api.v1.agents.router import RouteContext, _catalog_refs, route, score_topics
from depictio.tests.api.v1.agents._fakes import FakeLLM, turn


def _route(ctx, question="What stands out?", **kw):
    return asyncio.run(route(load_profiles(), ctx, question, **kw))


def _topics(plan):
    return [m.topic for m in plan.team if m.role == "analyst"]


def test_template_glob_routes_to_microbiome():
    plan = _route(RouteContext(dashboard_id="d", template_id="nf-core/ampliseq/2.16.0"))
    assert plan.method == "rules" and _topics(plan) == ["microbiome"]
    assert "template" in plan.team[0].reason


def test_column_vocabulary_routes_to_differential_expression():
    ctx = RouteContext(dashboard_id="d", columns={"gene_id", "log2foldchange", "padj", "basemean"})
    plan = _route(ctx)
    assert _topics(plan) == ["differential_expression"]
    assert plan.scores["differential_expression"] == 3.0


def test_keywords_and_components():
    ctx = RouteContext(dashboard_id="d", component_types={"multiqc", "figure"})
    plan = _route(ctx, "Which samples fail QC on duplication?")
    assert _topics(plan)[0] == "qc_multiqc"
    reason = plan.team[0].reason
    assert "components multiqc" in reason and "question mentions" in reason


def test_catalog_modules_from_components():
    refs = _catalog_refs({"use": "qiime2/alpha_diversity", "component_type": "advanced_viz"})
    assert refs == {"qiime2/alpha_diversity", "qiime2"}
    assert "multiqc" in _catalog_refs({"component_type": "multiqc"})
    assert "ivar" in _catalog_refs({"catalog_source": {"toolId": "ivar", "use": "ivar/lollipop"}})
    scores = score_topics(load_profiles(), RouteContext(dashboard_id="d", catalog_modules=refs), "")
    assert scores["microbiome"].score == 6.0


def test_two_topics_when_both_score():
    ctx = RouteContext(
        dashboard_id="d",
        template_id="nf-core/ampliseq/2.16.0",
        catalog_modules={"multiqc", "mosdepth", "qiime2"},
    )
    plan = _route(ctx)
    assert _topics(plan) == ["microbiome", "qc_multiqc"]
    roles = [m.role for m in plan.team]
    assert roles == ["analyst", "analyst", "skeptic", "annotator", "questioner", "reporter"]
    # Support roles bind to the first topic; analysts get their own focus.
    assert plan.team[2].agent_id == "skeptic/microbiome@1"
    assert "Your focus" in plan.team[1].sub_question


def test_no_match_without_llm_is_general():
    # One weak signal (a single matching column) is not enough to pick a topic.
    ctx = RouteContext(dashboard_id="d", columns={"sepal_length", "species", "genus"})
    plan = _route(ctx)
    assert _topics(plan) == ["general"] and plan.method == "rules"
    assert plan.notes


def test_no_match_asks_the_llm():
    llm = FakeLLM([turn({"topics": ["variants", "not-a-topic"]})])
    plan = _route(RouteContext(dashboard_id="d"), "anything", llm=llm)
    assert plan.method == "llm" and _topics(plan) == ["variants"]
    assert "Topics:" in llm.calls[0]["messages"][1]["content"]


def test_llm_answer_unusable_falls_back_to_general():
    llm = FakeLLM([turn("no idea")])
    plan = _route(RouteContext(dashboard_id="d"), "anything", llm=llm)
    assert _topics(plan) == ["general"]


def test_tie_for_the_last_place_goes_to_the_llm():
    # Three topics each matched by one keyword: two places, three candidates.
    ctx = RouteContext(dashboard_id="d")
    question = "coverage of each variant and the diversity"
    llm = FakeLLM([turn({"topics": ["variants"]})])
    plan = _route(ctx, question, llm=llm)
    assert plan.method == "llm" and _topics(plan) == ["variants"]
    no_llm = _route(ctx, question)
    assert _topics(no_llm) == ["microbiome", "qc_multiqc"]  # alphabetical tie-break
    assert any("alphabetically" in n for n in no_llm.notes)


def test_team_override():
    plan = _route(
        RouteContext(dashboard_id="d", template_id="nf-core/ampliseq/2"),
        team=["analyst/variants@1", "skeptic/variants"],
    )
    assert plan.method == "fixed"
    assert [m.agent_id for m in plan.team] == [
        "analyst/variants@1",
        "skeptic/variants@1",
        "annotator/variants@1",
        "questioner/variants@1",
        "reporter/variants@1",
    ]
    with pytest.raises(ProfileError):
        _route(RouteContext(dashboard_id="d"), team=["skeptic/general"])
    with pytest.raises(ProfileError):
        _route(RouteContext(dashboard_id="d"), team=["analyst/nope"])
