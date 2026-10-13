"""Catalog provenance derived from a ``use:`` handle.

The tile chrome draws its catalog badge from ``stored_metadata.catalog_source``
and from nothing else. A YAML author writes ``use: <tool>/<ref>`` instead, since
that is also the binding that expands into ``viz_kind`` and ``config`` — so a
dashboard built entirely from catalog outputs carried the most precise
provenance available and still claimed none of it.
"""

from __future__ import annotations

import pytest

from depictio.models.components.advanced_viz.catalog import catalog_source_for_use


def test_resolves_a_render_id_handle() -> None:
    source = catalog_source_for_use("ivar/manhattan")

    assert source is not None
    assert source["toolId"] == "ivar"
    assert source["outputId"] == "ivar_variants_long"
    # Round-trips the handle so the popover can show what the YAML actually says.
    assert source["use"] == "ivar/manhattan"
    assert source["toolName"]


def test_resolves_an_output_id_handle() -> None:
    """The second resolution form, for outputs that render more than one kind."""
    source = catalog_source_for_use("qiime2/sunburst_taxonomy")

    assert source is not None
    assert source["toolId"] == "qiime2"
    assert source["outputId"].startswith("qiime2_")


@pytest.mark.parametrize("ref", ["", "no-slash", "nosuchtool/whatever", "ivar/nosuchrender"])
def test_unresolvable_handles_return_none_rather_than_raising(ref: str) -> None:
    """A dashboard that cannot be badged is cosmetic; it must never fail an import."""
    assert catalog_source_for_use(ref) is None


def test_to_full_derives_catalog_source_from_use() -> None:
    from depictio.models.models.dashboards import DashboardDataLite

    dashboard = DashboardDataLite.model_validate(
        {
            "title": "Provenance",
            "components": [
                {
                    "component_type": "advanced_viz",
                    "tag": "adv-manhattan",
                    "index": "adv-manhattan",
                    "workflow_tag": "viralrecon",
                    "data_collection_tag": "variants_long",
                    "use": "ivar/manhattan",
                    "layout": {"x": 0, "y": 0, "w": 8, "h": 8},
                    "title": "Manhattan",
                }
            ],
        }
    )
    stored = dashboard.to_full()["stored_metadata"]
    source = stored[0]["catalog_source"]

    assert source["toolId"] == "ivar"
    assert source["outputId"] == "ivar_variants_long"


def test_an_explicit_catalog_source_is_not_overwritten() -> None:
    from depictio.models.models.dashboards import DashboardDataLite

    declared = {"toolId": "hand", "toolName": "Hand written", "outputId": "hand_output"}
    dashboard = DashboardDataLite.model_validate(
        {
            "title": "Provenance",
            "components": [
                {
                    "component_type": "advanced_viz",
                    "tag": "adv-manhattan",
                    "index": "adv-manhattan",
                    "workflow_tag": "viralrecon",
                    "data_collection_tag": "variants_long",
                    "use": "ivar/manhattan",
                    "catalog_source": declared,
                    "layout": {"x": 0, "y": 0, "w": 8, "h": 8},
                    "title": "Manhattan",
                }
            ],
        }
    )
    stored = dashboard.to_full()["stored_metadata"]

    assert stored[0]["catalog_source"] == declared
