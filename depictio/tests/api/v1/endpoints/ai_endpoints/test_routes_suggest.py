"""Endpoint tests for /ai/suggest-components.

No network, no Mongo, no LLM: the inventory, dashboard and data-context
builders are patched at the routes module boundary (that is where the
route resolves them), the polars-schema and MultiQC loaders at the
suggest module boundary, and `llm_client.completion` is replaced by a
canned answer. Auth is overridden with a stub user; the router is mounted
on a throwaway app so the tests are independent of the DEPICTIO_AI_ENABLED
gate.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.ai_endpoints import llm_client
from depictio.api.v1.endpoints.ai_endpoints.context import (
    ColumnSummary,
    ComponentSummary,
    DashboardContext,
    DataContext,
    InventoryEntry,
    ProjectInventory,
)
from depictio.api.v1.endpoints.ai_endpoints.routes import ai_endpoint_router
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

FAKE_USER = SimpleNamespace(id="0" * 24, email="t@example.com", is_admin=False)

DASHBOARD_ID = "5" * 24
PHYSICAL_ID = "6" * 24
DEMOGRAPHICS_ID = "8" * 24
WORKFLOW_ID = "7" * 24

# A schema the real advanced_viz ranker recommends kinds for (volcano, qq).
DE_SCHEMA = {"gene_id": "String", "log2FoldChange": "Float64", "padj": "Float64"}
# One it does not.
PLAIN_SCHEMA = {"island": "String", "year": "Int64"}


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(ai_endpoint_router, prefix="/ai")
    app.dependency_overrides[get_user_or_anonymous] = lambda: FAKE_USER
    return TestClient(app)


@pytest.fixture()
def inventory() -> ProjectInventory:
    return ProjectInventory(
        dashboard_id=DASHBOARD_ID,
        project_id="9" * 24,
        project_name="Penguins",
        entries=[
            InventoryEntry(
                data_collection_id=PHYSICAL_ID,
                data_collection_tag="physical_features",
                workflow_id=WORKFLOW_ID,
                workflow_tag="wf",
                dc_type="table",
                description="Body measurements per penguin",
                columns=[("bill_length_mm", "float64"), ("species", "object")],
                on_dashboard=True,
            ),
            InventoryEntry(
                data_collection_id=DEMOGRAPHICS_ID,
                data_collection_tag="demographics",
                workflow_id=WORKFLOW_ID,
                workflow_tag="wf",
                dc_type="table",
                description="Island and year per penguin",
                columns=[("island", "object"), ("year", "int64")],
                on_dashboard=True,
            ),
        ],
    )


@pytest.fixture()
def patch_inventory(monkeypatch, inventory) -> list[dict]:
    calls: list[dict] = []

    async def fake_build_project_inventory(dashboard_id, user, *, prioritize=None):
        calls.append({"dashboard_id": dashboard_id, "prioritize": prioritize})
        return inventory

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_project_inventory",
        fake_build_project_inventory,
    )
    return calls


@pytest.fixture()
def patch_dashboard_context(monkeypatch) -> dict:
    """A figure on physical_features and a table on demographics."""
    seen: dict = {}

    async def fake_build_dashboard_context(dashboard_id, user):
        seen["dashboard_id"] = dashboard_id
        ctx = DashboardContext(
            dashboard_id=dashboard_id,
            figures=[],
            filters=[],
            components=[
                ComponentSummary(
                    component_id="f1",
                    component_type="figure",
                    dc_id=PHYSICAL_ID,
                    title="Bill length scatter",
                ),
                ComponentSummary(
                    component_id="t1",
                    component_type="table",
                    dc_id=DEMOGRAPHICS_ID,
                    title="Demographics table",
                ),
            ],
            dc_ids=[PHYSICAL_ID, DEMOGRAPHICS_ID],
        )
        return ctx, PHYSICAL_ID

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_dashboard_context",
        fake_build_dashboard_context,
    )
    return seen


def _data_ctx(dc_id: str) -> DataContext:
    """The sampled context of one collection.

    Its columns are a superset of the polars schema `patch_schema` serves for
    the same collection, because in production both describe one Delta table:
    `build_data_context` summarises every column of the frame it loads. The
    two fixtures have to agree, or the schema check the suggestion route now
    runs would reject the very bindings the ranker just offered.
    """
    if dc_id == PHYSICAL_ID:
        columns = [
            ColumnSummary(name="bill_length_mm", dtype="Float64", null_pct=0.0, nunique=100),
            ColumnSummary(name="species", dtype="String", null_pct=0.0, nunique=3),
            *(
                ColumnSummary(name=name, dtype=dtype, null_pct=0.0, nunique=100)
                for name, dtype in DE_SCHEMA.items()
            ),
        ]
        sample = [{"bill_length_mm": 39.1, "species": "Adelie"}]
        tag = "physical_features"
    else:
        columns = [
            ColumnSummary(name="island", dtype="String", null_pct=0.0, nunique=3),
            ColumnSummary(name="year", dtype="Int64", null_pct=0.0, nunique=3),
        ]
        sample = [{"island": "Biscoe", "year": 2007}]
        tag = "demographics"
    return DataContext(
        data_collection_id=dc_id,
        workflow_id=WORKFLOW_ID,
        project_name="Penguins",
        project_description=None,
        dc_name=tag,
        dc_description=None,
        columns=columns,
        sample_rows=sample,
        row_count=344,
        workflow_tag="wf",
        data_collection_tag=tag,
        dc_type="table",
    )


@pytest.fixture()
def patch_context(monkeypatch) -> list[str]:
    """Serve a DataContext per collection; record which were loaded."""
    loaded: list[str] = []

    async def fake_build_data_context(dc_id, user, **kwargs):
        loaded.append(dc_id)
        return _data_ctx(dc_id)

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_data_context",
        fake_build_data_context,
    )
    return loaded


@pytest.fixture()
def patch_schema(monkeypatch) -> list[str]:
    """physical_features looks like a DE table to the ranker; demographics does not."""
    asked: list[str] = []

    async def fake_schema(dc_id, user):
        asked.append(dc_id)
        return DE_SCHEMA if dc_id == PHYSICAL_ID else PLAIN_SCHEMA

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.suggest._get_data_collection_polars_schema",
        fake_schema,
    )
    return asked


@pytest.fixture()
def patch_multiqc(monkeypatch):
    def boom(dc_id):
        raise AssertionError("no multiqc collection in this inventory")

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.suggest.fetch_multiqc_builder_options_sync",
        boom,
    )


@pytest.fixture()
def stack(patch_inventory, patch_dashboard_context, patch_context, patch_schema, patch_multiqc):
    """Everything but the LLM."""
    return {
        "inventory": patch_inventory,
        "dashboard": patch_dashboard_context,
        "contexts": patch_context,
        "schemas": patch_schema,
    }


def _patch_completion(monkeypatch, responses: list[str]) -> list[list[dict]]:
    queue = list(responses)
    calls: list[list[dict]] = []

    def fake_completion(messages, **kwargs):
        calls.append(messages)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(llm_client, "completion", fake_completion)
    return calls


def _patch_completion_error(monkeypatch) -> list[list[dict]]:
    calls: list[list[dict]] = []

    def boom(messages, **kwargs):
        calls.append(messages)
        raise RuntimeError("provider down")

    monkeypatch.setattr(llm_client, "completion", boom)
    return calls


def _answer(*items: dict) -> str:
    return json.dumps({"suggestions": list(items)})


CARD_ITEM = {
    "component_type": "card",
    "data_collection_tag": "physical_features",
    "title": "Species count",
    "rationale": "How many species were measured.",
    "component": {"aggregation": "nunique", "column_name": "species", "column_type": "object"},
}
WIDGET_ITEM = {
    "component_type": "interactive",
    "data_collection_tag": "physical_features",
    "title": "Species filter",
    "rationale": "Narrow every tile to one species.",
    "component": {
        "interactive_component_type": "MultiSelect",
        "column_name": "species",
        "column_type": "object",
    },
}
BAD_CARD_ITEM = {
    "component_type": "card",
    "data_collection_tag": "physical_features",
    "title": "Mean species",
    "rationale": "Nonsense: an average of a string column.",
    "component": {"aggregation": "average", "column_name": "species", "column_type": "object"},
}
FIGURE_ITEM = {
    "component_type": "figure",
    "data_collection_tag": "physical_features",
    "title": "Bill length by species",
    "rationale": "Distribution per species.",
    "component": {"visu_type": "box", "dict_kwargs": {"x": "species", "y": "bill_length_mm"}},
}
VOLCANO_ITEM = {
    "component_type": "advanced_viz",
    "data_collection_tag": "physical_features",
    "title": "Volcano of physical_features",
    "rationale": "Effect sizes against adjusted p-values.",
    "component": {
        "viz_kind": "volcano",
        "config": {
            "viz_kind": "volcano",
            "feature_id_col": "gene_id",
            "effect_size_col": "log2FoldChange",
            "significance_col": "padj",
        },
    },
}
VOLCANO_SPACE_LINE = (
    'advanced_viz kind "volcano": config keys feature_id_col=gene_id, '
    "effect_size_col=log2FoldChange, significance_col=padj"
)
TEXT_ITEM = {
    "component_type": "text",
    "data_collection_tag": None,
    "title": "Overview",
    "rationale": "Orients the reader.",
    "component": {"order": 2, "body": "Bill length per species, with the demographics table."},
}


def _post(client: TestClient, **body):
    return client.post("/ai/suggest-components", json={"dashboard_id": DASHBOARD_ID, **body})


class TestAuto:
    def test_merges_ranked_and_llm_items_in_policy_order(self, client, stack, monkeypatch):
        calls = _patch_completion(monkeypatch, [_answer(CARD_ITEM, WIDGET_ITEM, BAD_CARD_ITEM)])
        r = _post(client, n=4)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["warnings"] == []
        items = payload["suggestions"]
        # No slot is reserved for a ranked advanced_viz: the model's items
        # lead and the ranked table fills the room left.
        assert [(s["origin"], s["component_type"]) for s in items] == [
            ("llm", "card"),
            ("llm", "interactive"),
            ("ranked", "table"),
        ]
        assert not [s for s in items if s["component_type"] == "advanced_viz"]
        # Ids resolved from the inventory, not from the model.
        for s in items:
            assert s["data_collection_id"] == PHYSICAL_ID
            assert s["workflow_id"] == WORKFLOW_ID
            assert s["data_collection_tag"] == "physical_features"
            assert s["component"]["workflow_tag"] == "wf"
            assert s["component"]["data_collection_tag"] == "physical_features"
        card = items[0]
        assert card["title"] == "Species count"
        assert card["rationale"] == "How many species were measured."
        assert card["component"]["aggregation"] == "nunique"
        assert card["component"]["title"] == "Species count"
        assert card["code"] is None
        # The table on demographics already exists, so only physical_features gets one.
        table = items[2]
        assert table["component"]["columns"] == ["bill_length_mm", "species"]
        assert table["component"]["page_size"] == 10
        assert table["title"] == "Browse physical_features"
        # One LLM call, prompted with the dashboard and the allowed types
        # (advanced_viz included, table not).
        assert len(calls) == 1
        system = calls[0][0]["content"]
        assert "Bill length scatter" in system
        assert "Demographics table" in system
        assert "ALLOWED COMPONENT TYPES: figure, card, interactive, text, advanced_viz" in system
        assert "CARD:" in system and "INTERACTIVE:" in system and "TEXT:" in system
        assert "ADVANCED_VIZ:" in system
        assert "TABLE:" not in system
        assert "data_collection_tag: physical_features (on dashboard)" in system
        assert "Adelie" in system  # sample rows of the loaded context
        assert "aggregation in {count, mode, nunique}" in system
        assert calls[0][1]["content"] == "Suggest 4 components to add to this dashboard."
        assert stack["inventory"] == [{"dashboard_id": DASHBOARD_ID, "prioritize": None}]
        assert stack["dashboard"]["dashboard_id"] == DASHBOARD_ID
        assert stack["contexts"] == [PHYSICAL_ID, DEMOGRAPHICS_ID]
        assert stack["schemas"] == [PHYSICAL_ID, DEMOGRAPHICS_ID]

    def test_prompt_carries_the_ranked_advanced_viz_space(self, client, stack, monkeypatch):
        calls = _patch_completion(monkeypatch, [_answer(VOLCANO_ITEM, CARD_ITEM)])
        r = _post(client, n=4)
        assert r.status_code == 200, r.text
        system = calls[0][0]["content"]
        # physical_features ranks as a DE table: its kinds are offered with
        # the exact config keys; demographics ranks nothing.
        assert VOLCANO_SPACE_LINE in system
        assert 'advanced_viz kind "qq": config keys p_value_col=padj' in system
        assert "extra keys are rejected" in system
        physical_block, demographics_block = system.split("### data_collection_tag: demographics")
        assert "advanced_viz kind" in physical_block
        assert "advanced_viz kind" not in demographics_block.split("ALLOWED COMPONENT TYPES")[0]
        assert stack["schemas"] == [PHYSICAL_ID, DEMOGRAPHICS_ID]
        # The model took the offer: its advanced_viz validates and is an llm item.
        items = r.json()["suggestions"]
        assert [(s["origin"], s["component_type"]) for s in items] == [
            ("llm", "advanced_viz"),
            ("llm", "card"),
            ("ranked", "table"),
        ]
        volcano = items[0]
        assert volcano["title"] == "Volcano of physical_features"
        assert volcano["data_collection_id"] == PHYSICAL_ID
        assert volcano["component"]["viz_kind"] == "volcano"
        assert volcano["component"]["config"]["effect_size_col"] == "log2FoldChange"
        assert volcano["component"]["config"]["viz_kind"] == "volcano"

    def test_llm_advanced_viz_with_extra_config_key_is_dropped(self, client, stack, monkeypatch):
        bad = {
            **VOLCANO_ITEM,
            "component": {
                "viz_kind": "volcano",
                "config": {**VOLCANO_ITEM["component"]["config"], "depth_col": "padj"},
            },
        }
        _patch_completion(monkeypatch, [_answer(bad, CARD_ITEM)])
        r = _post(client, n=4)
        assert r.status_code == 200, r.text
        assert [s["component_type"] for s in r.json()["suggestions"]] == ["card", "table"]

    def test_llm_advanced_viz_gets_config_viz_kind_filled(self, client, stack, monkeypatch):
        loose = {
            **VOLCANO_ITEM,
            "component": {
                "viz_kind": "volcano",
                "config": {
                    k: v for k, v in VOLCANO_ITEM["component"]["config"].items() if k != "viz_kind"
                },
            },
        }
        _patch_completion(monkeypatch, [_answer(loose)])
        r = _post(client, n=2)
        assert r.status_code == 200, r.text
        volcano = r.json()["suggestions"][0]
        assert volcano["origin"] == "llm"
        assert volcano["component"]["config"]["viz_kind"] == "volcano"

    def test_a_card_on_a_column_that_is_not_there_is_dropped(self, client, stack, monkeypatch):
        """The schema check, on the suggestion route.

        A suggestion has no repair round: an invalid one is dropped the way an
        ungrammatical one already was, and the answer stands on whatever
        survives. `nope` is not a column of physical_features, which only the
        collection can say.
        """
        ghost = {
            **CARD_ITEM,
            "title": "Ghost count",
            "component": {**CARD_ITEM["component"], "column_name": "nope"},
        }
        _patch_completion(monkeypatch, [_answer(ghost, CARD_ITEM)])
        r = _post(client, n=4)
        assert r.status_code == 200, r.text
        titles = [s["title"] for s in r.json()["suggestions"]]
        assert "Ghost count" not in titles
        assert "Species count" in titles

    def test_a_card_whose_declared_type_is_wrong_is_dropped(self, client, stack, monkeypatch):
        """The case the lite model cannot see: a real column, a type it does not have."""
        mistyped = {
            **CARD_ITEM,
            "title": "Mistyped",
            "component": {
                "aggregation": "average",
                "column_name": "species",
                "column_type": "float64",
            },
        }
        _patch_completion(monkeypatch, [_answer(mistyped, CARD_ITEM)])
        r = _post(client, n=4)
        assert r.status_code == 200, r.text
        assert "Mistyped" not in [s["title"] for s in r.json()["suggestions"]]

    def test_figures_get_python_code(self, client, stack, monkeypatch):
        _patch_completion(monkeypatch, [_answer(FIGURE_ITEM)])
        r = _post(client, component_type="figure", n=2)
        assert r.status_code == 200, r.text
        (figure,) = r.json()["suggestions"]
        assert figure["origin"] == "llm"
        assert figure["code"].startswith("fig = px.box(")
        assert figure["component"]["visu_type"] == "box"
        # A pinned LLM type never reads schemas for advanced_viz.
        assert stack["schemas"] == []

    def test_llm_failure_with_ranked_items_is_a_warning(self, client, stack, monkeypatch):
        _patch_completion_error(monkeypatch)
        r = _post(client, n=4)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert len(payload["warnings"]) == 1
        assert payload["warnings"][0].startswith("LLM call failed: provider down")
        assert "ranked suggestions only" in payload["warnings"][0]
        assert {s["origin"] for s in payload["suggestions"]} == {"ranked"}
        # Only the table: a ranked advanced_viz is never surfaced with the type open.
        assert [s["component_type"] for s in payload["suggestions"]] == ["table"]

    def test_invalid_json_with_ranked_items_is_a_warning(self, client, stack, monkeypatch):
        _patch_completion(monkeypatch, ["not json at all"])
        r = _post(client, n=4)
        assert r.status_code == 200, r.text
        assert r.json()["warnings"][0].startswith("LLM returned invalid JSON")

    def test_unknown_tag_and_wrong_type_items_are_dropped(self, client, stack, monkeypatch):
        stray = {**CARD_ITEM, "data_collection_tag": "nope", "title": "Stray"}
        forbidden = {
            **CARD_ITEM,
            "component_type": "table",
            "title": "Not for the model",
            "component": {"columns": ["species"]},
        }
        _patch_completion(monkeypatch, [_answer(stray, forbidden, WIDGET_ITEM)])
        r = _post(client, n=8)
        assert r.status_code == 200, r.text
        llm_titles = [s["title"] for s in r.json()["suggestions"] if s["origin"] == "llm"]
        assert llm_titles == ["Species filter"]

    def test_missing_column_type_is_filled_from_the_inventory(self, client, stack, monkeypatch):
        loose = {
            **BAD_CARD_ITEM,
            "component": {"aggregation": "average", "column_name": "species"},
        }
        _patch_completion(monkeypatch, [_answer(loose, CARD_ITEM)])
        r = _post(client, component_type="card", n=4)
        assert r.status_code == 200, r.text
        # The average-of-a-string card only fails because column_type was filled in.
        assert [s["title"] for s in r.json()["suggestions"]] == ["Species count"]


class TestPinnedType:
    def test_advanced_viz_is_ranked_without_an_llm_call(self, client, stack, monkeypatch):
        calls = _patch_completion(monkeypatch, [_answer(CARD_ITEM)])
        r = _post(client, component_type="advanced_viz", n=4)
        assert r.status_code == 200, r.text
        items = r.json()["suggestions"]
        assert calls == []
        assert stack["contexts"] == []  # no sample rows needed on the ranked path
        assert 1 <= len(items) <= 2
        for s in items:
            assert s["origin"] == "ranked"
            assert s["component_type"] == "advanced_viz"
            assert s["data_collection_id"] == PHYSICAL_ID
            assert s["workflow_id"] == WORKFLOW_ID
            assert s["component"]["config"]["viz_kind"] == s["component"]["viz_kind"]
            assert s["rationale"]
        assert "volcano" in {s["component"]["viz_kind"] for s in items}

    def test_table_is_deterministic(self, client, stack, monkeypatch):
        calls = _patch_completion(monkeypatch, [_answer(CARD_ITEM)])
        r = _post(client, component_type="table", n=4)
        assert r.status_code == 200, r.text
        (table,) = r.json()["suggestions"]
        assert calls == []
        assert table["origin"] == "ranked"
        assert table["data_collection_id"] == PHYSICAL_ID
        assert table["title"] == "Browse physical_features"
        assert table["component"]["component_type"] == "table"
        assert table["component"]["columns"] == ["bill_length_mm", "species"]
        assert table["component"]["page_size"] == 10

    def test_text_has_no_collection(self, client, stack, monkeypatch):
        calls = _patch_completion(monkeypatch, [_answer(TEXT_ITEM)])
        r = _post(client, component_type="text", n=2)
        assert r.status_code == 200, r.text
        (text,) = r.json()["suggestions"]
        assert text["component_type"] == "text"
        assert text["origin"] == "llm"
        assert text["data_collection_id"] is None
        assert text["data_collection_tag"] is None
        assert text["workflow_id"] is None
        assert text["component"]["body"].startswith("Bill length")
        assert text["component"]["order"] == 2
        assert text["component"]["title"] == "Overview"
        assert stack["contexts"] == []
        system = calls[0][0]["content"]
        assert "Bill length scatter" in system
        assert 'Every item has component_type "text"' in system

    def test_no_fitting_collection_is_422(self, client, stack, monkeypatch):
        calls = _patch_completion(monkeypatch, [_answer(CARD_ITEM)])
        r = _post(client, component_type="multiqc")
        assert r.status_code == 422
        assert "multiqc" in r.json()["detail"]
        assert calls == []

    def test_llm_failure_with_nothing_ranked_is_502(self, client, stack, monkeypatch):
        _patch_completion_error(monkeypatch)
        r = _post(client, component_type="card")
        assert r.status_code == 502
        assert "provider down" in r.json()["detail"]

    def test_all_items_invalid_with_nothing_ranked_is_502(self, client, stack, monkeypatch):
        _patch_completion(monkeypatch, [_answer(BAD_CARD_ITEM)])
        r = _post(client, component_type="card")
        assert r.status_code == 502
        assert "validation" in r.json()["detail"]


class TestPinnedCollection:
    def test_unknown_collection_is_404(self, client, stack, monkeypatch):
        _patch_completion(monkeypatch, [_answer(CARD_ITEM)])
        r = _post(client, data_collection_id="1" * 24)
        assert r.status_code == 404
        assert stack["inventory"] == [{"dashboard_id": DASHBOARD_ID, "prioritize": ["1" * 24]}]

    def test_pinned_collection_scopes_everything_to_it(self, client, stack, monkeypatch):
        demo_card = {
            **CARD_ITEM,
            "data_collection_tag": "demographics",
            "title": "Island count",
            "component": {
                "aggregation": "nunique",
                "column_name": "island",
                "column_type": "object",
            },
        }
        calls = _patch_completion(monkeypatch, [_answer(demo_card, CARD_ITEM)])
        r = _post(client, data_collection_id=DEMOGRAPHICS_ID, n=4)
        assert r.status_code == 200, r.text
        items = r.json()["suggestions"]
        # demographics ranks no advanced_viz and already has a table: the
        # only survivor is the model's card on it; the physical_features
        # card names a collection outside the pin and is dropped.
        assert [(s["origin"], s["title"]) for s in items] == [("llm", "Island count")]
        assert items[0]["data_collection_id"] == DEMOGRAPHICS_ID
        system = calls[0][0]["content"]
        assert "data_collection_tag: demographics" in system
        assert "data_collection_tag: physical_features" not in system
        assert 'Every data item uses data_collection_tag "demographics"' in system
        assert stack["contexts"] == [DEMOGRAPHICS_ID]

    def test_pinned_type_the_collection_cannot_back_is_422(self, client, stack, monkeypatch):
        calls = _patch_completion(monkeypatch, [_answer(CARD_ITEM)])
        r = _post(client, data_collection_id=PHYSICAL_ID, component_type="map")
        assert r.status_code == 422
        assert "physical_features" in r.json()["detail"]
        assert calls == []


class TestRequestValidation:
    @pytest.mark.parametrize("n", [0, 9])
    def test_n_is_clamped_by_the_model(self, client, stack, n):
        r = _post(client, n=n)
        assert r.status_code == 422

    def test_dashboard_id_is_required(self, client, stack):
        r = client.post("/ai/suggest-components", json={"n": 2})
        assert r.status_code == 422

    def test_unknown_component_type_is_422(self, client, stack):
        r = _post(client, component_type="gizmo")
        assert r.status_code == 422
