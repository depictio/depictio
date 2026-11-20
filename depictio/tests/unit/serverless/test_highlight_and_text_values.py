"""Highlight tiles take their source's tier; text live values ship like cards.

The ampliseq / viralrecon landing tabs are highlights of figures on other tabs
plus text tiles with `{{name}}` values — both used to be omitted or blank in a
bundle: producer A omitted every highlight ("not supported") and never shipped
the collections a text value reads.
"""

from __future__ import annotations

from depictio.models.models.serverless import ComponentTier, TierReason
from depictio.serverless.producer_a import (
    FamilyTab,
    TierRow,
    classify_stored_component,
    highlight_source,
    resolve_highlight_tiers,
    text_run_params,
    text_value_cards,
)

MAIN = "a" * 24
DIV = "b" * 24


def _tabs():
    main = FamilyTab(
        doc={
            "dashboard_id": MAIN,
            "title": "Overview",
            "stored_metadata": [
                {
                    "index": "hl-1",
                    "component_type": "highlight",
                    "source_tab": "Diversity",
                    "source_component": "Shannon by habitat",
                },
                {
                    "index": "hl-2",
                    "component_type": "highlight",
                    "source_dashboard_id": DIV,
                    "source_component": "alpha-box",
                },
                {
                    "index": "hl-3",
                    "component_type": "highlight",
                    "source_tab": "Nowhere",
                    "source_component": "x",
                },
                {
                    "index": "hl-4",
                    "component_type": "highlight",
                    "source_tab": "Diversity",
                    "source_component": "intro",
                },
            ],
        },
        is_main_tab=True,
    )
    div = FamilyTab(
        doc={
            "dashboard_id": DIV,
            "title": "Diversity",
            "stored_metadata": [
                {"index": "alpha-box", "component_type": "figure", "title": "Shannon by  Habitat"},
                {"index": "intro", "component_type": "text", "title": "intro"},
            ],
        },
        tab_order=1,
    )
    return [main, div]


def test_a_highlight_resolves_inside_the_family_like_the_viewer():
    tabs = _tabs()
    main = tabs[0].components
    assert highlight_source(main[0], tabs)[1]["index"] == "alpha-box"  # by title, spacing ignored
    assert highlight_source(main[1], tabs)[1]["index"] == "alpha-box"  # by tab id + index
    assert highlight_source(main[2], tabs) is None  # no such tab
    assert highlight_source(main[3], tabs) is None  # a text cannot be highlighted


def test_a_highlight_takes_its_sources_settled_tier():
    tabs = _tabs()
    items = [(t, c, str(c["index"])) for t in tabs for c in t.components]
    rows = {}
    for _t, c, cid in items:
        plan = classify_stored_component(c)
        rows[cid] = TierRow(
            component_id=cid,
            title="",
            component_type=c["component_type"],
            tier=plan.tier,
            reason=plan.reason,
            detail=plan.detail,
        )
    rows["alpha-box"].tier = ComponentTier.LIVE
    rows["alpha-box"].reason = None
    resolve_highlight_tiers(items, tabs, rows)
    assert rows["hl-1"].tier is ComponentTier.LIVE
    assert rows["hl-2"].tier is ComponentTier.LIVE
    assert "Diversity" in (rows["hl-1"].detail or "")
    assert (rows["hl-3"].tier, rows["hl-3"].reason) == (
        ComponentTier.OMITTED,
        TierReason.UNSUPPORTED,
    )
    assert rows["hl-4"].tier is ComponentTier.OMITTED


def test_text_values_become_cards_and_params_are_read_from_the_run():
    text = {
        "index": "t1",
        "component_type": "text",
        "body": "Ran with {{param:outdir}} and {{param:unset}}; top {{top}}",
        "values": {
            "top": {
                "dc_id": "d" * 24,
                "wf_id": "w" * 24,
                "column": "Phylum",
                "aggregation": "top",
                "weight": "abund",
            }
        },
    }
    cards = text_value_cards([text, {"index": "c", "component_type": "card"}])
    assert [c["index"] for c in cards] == ["t1::top"]
    assert cards[0]["weight"] == "abund" and cards[0]["dc_id"] == "d" * 24
    project = {
        "template_origin": {
            "run_provenance": [
                {"key": "outdir", "value": "results", "source": "params"},
                {"key": "unset", "value": "null", "source": "params"},
            ]
        }
    }
    assert text_run_params(project, text) == {"outdir": "results", "unset": None}
