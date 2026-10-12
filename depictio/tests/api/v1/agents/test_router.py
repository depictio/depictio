"""Team routing: structural rules (template, catalog, columns), keywords to rank, LLM for ties."""

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


PENGUINS = {
    "species",
    "island",
    "bill_length_mm",
    "bill_depth_mm",
    "flipper_length_mm",
    "body_mass_g",
    "sex",
    "year",
}
IRIS = {"sepal_length", "sepal_width", "petal_length", "petal_width", "species"}
PENGUIN_QUESTION = (
    "Which penguin species differ most in body mass and flipper length, and are there outliers?"
)


def test_column_vocabulary_routes_to_differential_expression():
    # A DESeq2 results table, column names lowercased like build_route_context does.
    deseq2 = {"gene_id", "basemean", "log2foldchange", "lfcse", "stat", "pvalue", "padj"}
    llm = FakeLLM([])
    plan = _route(RouteContext(dashboard_id="d", columns=deseq2), llm=llm)
    assert _topics(plan) == ["differential_expression"] and plan.method == "rules"
    assert plan.scores["differential_expression"] == 4.0  # capped at 4 columns
    assert "columns" in plan.team[0].reason
    assert not llm.calls


def test_edger_columns_route_to_differential_expression():
    edger = {"gene", "logfc", "logcpm", "pvalue", "fdr"}
    assert _topics(_route(RouteContext(dashboard_id="d", columns=edger))) == [
        "differential_expression"
    ]


def test_plain_tables_go_to_general_without_the_llm():
    # The run that routed penguins to differential_expression: no structural
    # signal anywhere, so no LLM call either, whatever the question says.
    for columns in (PENGUINS, IRIS):
        llm = FakeLLM([turn({"topics": ["differential_expression"]})])
        ctx = RouteContext(dashboard_id="d", columns=columns, component_types={"figure", "card"})
        for question in (PENGUIN_QUESTION, "Is there differential expression between species?"):
            plan = _route(ctx, question, llm=llm)
            assert _topics(plan) == ["general"] and plan.method == "rules"
            assert plan.notes
        assert not llm.calls


def test_keywords_alone_never_pick_a_specialist():
    # Keywords of three topics, no structure: general, no tie to break.
    llm = FakeLLM([])
    plan = _route(
        RouteContext(dashboard_id="d"), "coverage of each variant and the diversity", llm=llm
    )
    assert _topics(plan) == ["general"] and not llm.calls
    assert plan.scores["variants"] > 0  # scored, but not a candidate


def test_keywords_and_components_add_to_a_structural_match():
    ctx = RouteContext(
        dashboard_id="d", catalog_modules={"multiqc"}, component_types={"multiqc", "figure"}
    )
    plan = _route(ctx, "Which samples fail QC on duplication?")
    assert _topics(plan)[0] == "qc_multiqc"
    reason = plan.team[0].reason
    assert "catalog multiqc" in reason and "components multiqc" in reason
    assert "question mentions" in reason


def test_keywords_rank_structural_matches():
    ctx = RouteContext(dashboard_id="d", catalog_modules={"qiime2", "ivar"})
    assert _topics(_route(ctx)) == ["microbiome", "variants"]
    llm = FakeLLM([])
    plan = _route(ctx, "Which variant calls stand out?", llm=llm)
    # variants gets the keyword on top of its catalog match and leads the team.
    assert _topics(plan) == ["variants", "microbiome"] and plan.method == "rules"
    assert not llm.calls


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


def test_one_matching_column_is_not_structural():
    ctx = RouteContext(dashboard_id="d", columns={"sepal_length", "species", "genus"})
    plan = _route(ctx)
    assert _topics(plan) == ["general"] and plan.method == "rules"
    assert plan.scores["microbiome"] == 0.0


def test_tie_for_the_last_place_goes_to_the_llm():
    # Three topics each matched by one catalog module: two places, three candidates.
    ctx = RouteContext(dashboard_id="d", catalog_modules={"qiime2", "multiqc", "ivar"})
    llm = FakeLLM([turn({"topics": ["variants", "not-a-topic", "general"]})])
    plan = _route(ctx, llm=llm)
    assert plan.method == "llm" and _topics(plan) == ["variants"]
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "Topics:" in prompt and "differential_expression" not in prompt
    no_llm = _route(ctx)
    assert _topics(no_llm) == ["microbiome", "qc_multiqc"]  # alphabetical tie-break
    assert any("alphabetically" in n for n in no_llm.notes)


def test_unusable_llm_answer_breaks_the_tie_alphabetically():
    ctx = RouteContext(dashboard_id="d", catalog_modules={"qiime2", "multiqc", "ivar"})
    plan = _route(ctx, llm=FakeLLM([turn("no idea")]))
    assert _topics(plan) == ["microbiome", "qc_multiqc"] and plan.method == "rules"


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


def test_team_override_allows_many_analysts_but_one_of_each_support_role():
    plan = _route(
        RouteContext(dashboard_id="d"),
        team=["analyst/general", "analyst/variants", "skeptic/general"],
    )
    assert [m.role for m in plan.team].count("analyst") == 2
    for duplicated in (
        ["analyst/general", "skeptic/general", "skeptic/variants"],
        ["analyst/general", "reporter/general", "reporter/microbiome"],
    ):
        with pytest.raises(ProfileError, match="at most one"):
            _route(RouteContext(dashboard_id="d"), team=duplicated)
