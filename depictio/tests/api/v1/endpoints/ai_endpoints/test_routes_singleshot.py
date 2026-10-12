"""Endpoint tests for /ai/suggest-figures and /ai/component-from-prompt.

No network, no Mongo, no LLM: `build_data_context` and
`llm_client.completion` are monkeypatched; auth is overridden with a
stub user. The router is mounted on a throwaway app so the tests are
independent of the DEPICTIO_AI_ENABLED gate.
"""

from __future__ import annotations

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


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(ai_endpoint_router, prefix="/ai")
    app.dependency_overrides[get_user_or_anonymous] = lambda: FAKE_USER
    return TestClient(app)


@pytest.fixture()
def data_ctx() -> DataContext:
    return DataContext(
        data_collection_id="6" * 24,
        workflow_id="7" * 24,
        project_name="Iris",
        project_description=None,
        dc_name="iris_table",
        dc_description=None,
        columns=[
            ColumnSummary(name="sepal_length", dtype="Float64", null_pct=0.0, nunique=35),
            ColumnSummary(name="variety", dtype="String", null_pct=0.0, nunique=3),
        ],
        sample_rows=[{"sepal_length": 5.1, "variety": "Setosa"}],
        row_count=150,
        workflow_tag="wf",
        data_collection_tag="dc",
    )


@pytest.fixture()
def patch_context(monkeypatch, data_ctx):
    async def fake_build_data_context(dc_id, user, **kwargs):
        return data_ctx

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_data_context",
        fake_build_data_context,
    )


def _patch_completion(monkeypatch, responses: list[str]) -> list[list[dict]]:
    """completion() pops canned responses in order (repeats the last one).

    Returns the list of message lists each call received, so a test can
    assert on what the prompt contained.
    """
    queue = list(responses)
    calls: list[list[dict]] = []

    def fake_completion(messages, **kwargs):
        calls.append(messages)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(llm_client, "completion", fake_completion)
    return calls


class TestSuggestFigures:
    def test_happy_path_drops_invalid_items(self, client, patch_context, monkeypatch):
        _patch_completion(
            monkeypatch,
            [
                '{"suggestions": ['
                '{"visu_type": "scatter", "dict_kwargs": {"x": "sepal_length", "y": "sepal_length"},'
                ' "title": "S", "explanation": "E"},'
                '{"visu_type": "scatter", "dict_kwargs": {}, "title": "bad", "explanation": "no kwargs"}'
                "]}"
            ],
        )
        r = client.post(
            "/ai/suggest-figures",
            json={"data_collection_id": "6" * 24, "n": 2},
        )
        assert r.status_code == 200
        suggestions = r.json()["suggestions"]
        assert len(suggestions) == 1
        # Server-side synthesized Plotly Express code for display.
        assert suggestions[0]["code"].startswith("fig = px.scatter(")

    def test_invalid_json_is_502(self, client, patch_context, monkeypatch):
        _patch_completion(monkeypatch, ["not json at all"])
        r = client.post(
            "/ai/suggest-figures",
            json={"data_collection_id": "6" * 24, "n": 2},
        )
        assert r.status_code == 502

    def test_all_invalid_suggestions_is_502(self, client, patch_context, monkeypatch):
        _patch_completion(monkeypatch, ['{"suggestions": [{"visu_type": "scatter"}]}'])
        r = client.post(
            "/ai/suggest-figures",
            json={"data_collection_id": "6" * 24, "n": 2},
        )
        assert r.status_code == 502


VALID_CARD_YAML = (
    "component_type: card\n"
    "workflow_tag: wf\n"
    "data_collection_tag: dc\n"
    "aggregation: count\n"
    "column_name: variety\n"
    "column_type: object\n"
    "title: Sample count\n"
)


class TestComponentFromPrompt:
    def test_first_try_valid(self, client, patch_context, monkeypatch):
        _patch_completion(monkeypatch, [VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "count of samples",
                "component_type": "card",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["component_type"] == "card"
        assert payload["validation_attempts"] == 1
        assert payload["parsed"]["aggregation"] == "count"
        assert payload["explanation"] == "Sample count"

    def test_retry_then_valid(self, client, patch_context, monkeypatch):
        invalid = "component_type: card\nworkflow_tag: wf\ndata_collection_tag: dc\n"
        _patch_completion(monkeypatch, [invalid, VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "count of samples",
                "component_type": "card",
            },
        )
        assert r.status_code == 200
        assert r.json()["validation_attempts"] == 2

    def test_exhausted_retries_is_422(self, client, patch_context, monkeypatch):
        _patch_completion(monkeypatch, ["component_type: gizmo\n"])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "??",
                "component_type": "card",
            },
        )
        assert r.status_code == 422

    def test_an_aggregation_the_real_column_cannot_take_is_repaired(
        self, client, patch_context, monkeypatch
    ):
        """The schema check the generator runs, on this route at last.

        The lite model already refuses `average` on a `column_type: object`
        card, so the case only the collection can catch is the one where the
        model declares a type the column does not have: `average` on
        `float64` is a perfectly good card, and `variety` is a String. Before
        this route ran `check_against_schema`, that tile reached the builder
        and failed when it was drawn.
        """
        bad = VALID_CARD_YAML.replace("aggregation: count", "aggregation: average").replace(
            "column_type: object", "column_type: float64"
        )
        calls = _patch_completion(monkeypatch, [bad, VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "average variety",
                "component_type": "card",
            },
        )
        assert r.status_code == 200
        # The repair spends one of the two attempts rather than adding one.
        assert r.json()["validation_attempts"] == 2
        assert r.json()["parsed"]["aggregation"] == "count"
        # And the model was told what was wrong in the schema check's words.
        repair = calls[1][-1]["content"]
        assert "Schema check failed" in repair
        assert "column_type='float64' but 'variety' is stored as 'object'" in repair

    def test_a_tile_the_envelope_refuses_is_repaired_not_a_500(
        self, client, patch_context, monkeypatch
    ):
        """`schema_error` re-validates inside a dashboard, which can itself refuse.

        The tile passed `validate_single` on its own; assembling it into a
        dashboard is stricter and can raise. That is one more thing to hand
        back to the model, not an unhandled error out of the handler.
        """
        raised: list[int] = []

        def refuse_once(component, ctx):
            if not raised:
                raised.append(1)
                raise ValueError("component 0 is not a dashboard component")
            return None

        monkeypatch.setattr(
            "depictio.api.v1.endpoints.ai_endpoints.routes.schema_error", refuse_once
        )
        calls = _patch_completion(monkeypatch, [VALID_CARD_YAML, VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "count of samples",
                "component_type": "card",
            },
        )
        assert r.status_code == 200
        assert r.json()["validation_attempts"] == 2
        assert "ValueError: component 0 is not a dashboard component" in calls[1][-1]["content"]

    def test_a_figure_that_would_draw_nothing_is_repaired(self, client, patch_context, monkeypatch):
        """The substance check: a figure with no bindings validates and draws an empty plot."""
        empty = (
            "component_type: figure\n"
            "workflow_tag: wf\n"
            "data_collection_tag: dc\n"
            "visu_type: scatter\n"
        )
        good = empty + "dict_kwargs:\n  x: sepal_length\n  y: sepal_length\n"
        calls = _patch_completion(monkeypatch, [empty, good])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "scatter",
                "component_type": "figure",
            },
        )
        assert r.status_code == 200
        assert r.json()["validation_attempts"] == 2
        assert "dict_kwargs is empty" in calls[1][-1]["content"]

    def test_a_column_that_is_not_there_exhausts_the_attempts(
        self, client, patch_context, monkeypatch
    ):
        """Both attempts spent on the same bad column ends in 422, not a saved tile."""
        bad = VALID_CARD_YAML.replace("column_name: variety", "column_name: nope")
        _patch_completion(monkeypatch, [bad])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "count of nope",
                "component_type": "card",
            },
        )
        assert r.status_code == 422
        assert "Column 'nope' not found" in r.json()["detail"]

    def test_llm_error_is_502(self, client, patch_context, monkeypatch):
        def boom(messages, **kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(llm_client, "completion", boom)
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "count",
                "component_type": "card",
            },
        )
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# text and advanced_viz: the two types added to component-from-prompt
# ---------------------------------------------------------------------------


VALID_TEXT_YAML = (
    "component_type: text\n"
    "title: Overview\n"
    "order: 2\n"
    "body: A scatter of sepal length next to the sample table.\n"
)

VALID_ADVANCED_VIZ_YAML = (
    "component_type: advanced_viz\n"
    "workflow_tag: wf\n"
    "data_collection_tag: dc\n"
    "title: Volcano\n"
    "viz_kind: volcano\n"
    "config:\n"
    "  viz_kind: volcano\n"
    "  feature_id_col: gene_id\n"
    "  effect_size_col: log2FoldChange\n"
    "  significance_col: padj\n"
)

BAD_ROLE_ADVANCED_VIZ_YAML = (
    "component_type: advanced_viz\n"
    "workflow_tag: wf\n"
    "data_collection_tag: dc\n"
    "viz_kind: volcano\n"
    "config:\n"
    "  viz_kind: volcano\n"
    "  foo_col: gene_id\n"
)


@pytest.fixture()
def de_ctx() -> DataContext:
    return DataContext(
        data_collection_id="6" * 24,
        workflow_id="7" * 24,
        project_name="DE",
        project_description=None,
        dc_name="de_results",
        dc_description=None,
        columns=[
            ColumnSummary(name="gene_id", dtype="String", null_pct=0.0, nunique=100),
            ColumnSummary(name="log2FoldChange", dtype="Float64", null_pct=0.0, nunique=100),
            ColumnSummary(name="padj", dtype="Float64", null_pct=0.0, nunique=100),
        ],
        sample_rows=[{"gene_id": "g1", "log2FoldChange": 1.2, "padj": 0.01}],
        row_count=100,
        workflow_tag="wf",
        data_collection_tag="dc",
    )


@pytest.fixture()
def patch_de_context(monkeypatch, de_ctx):
    async def fake_build_data_context(dc_id, user, **kwargs):
        return de_ctx

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_data_context",
        fake_build_data_context,
    )


@pytest.fixture()
def patch_dashboard_context(monkeypatch):
    """Text has no DC: the dashboard summary is the only context it gets."""
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
                    dc_id="6" * 24,
                    title="Sepal scatter",
                )
            ],
        )
        return ctx, "6" * 24

    async def no_data_context(dc_id, user, **kwargs):
        raise AssertionError("build_data_context must not be called for a text component")

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_dashboard_context",
        fake_build_dashboard_context,
    )
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_data_context",
        no_data_context,
    )
    return seen


class TestComponentFromPromptText:
    def test_text_is_prompted_with_the_dashboard_not_a_dc(
        self, client, patch_dashboard_context, monkeypatch
    ):
        calls = _patch_completion(monkeypatch, [VALID_TEXT_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "prompt": "introduce this section",
                "component_type": "text",
                "dashboard_id": "5" * 24,
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["component_type"] == "text"
        assert payload["parsed"]["body"].startswith("A scatter")
        assert payload["parsed"]["order"] == 2
        assert payload["explanation"] == "Overview"
        assert patch_dashboard_context["dashboard_id"] == "5" * 24
        system = calls[0][0]["content"]
        assert "Sepal scatter" in system
        assert "DATASET SCHEMA" not in system

    def test_text_without_dashboard_id_still_works(
        self, client, patch_dashboard_context, monkeypatch
    ):
        calls = _patch_completion(monkeypatch, [VALID_TEXT_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={"prompt": "introduce this section", "component_type": "text"},
        )
        assert r.status_code == 200
        assert "dashboard_id" not in patch_dashboard_context
        assert "(no dashboard context available)" in calls[0][0]["content"]

    def test_data_bound_type_without_dc_or_dashboard_is_422(
        self, client, patch_context, monkeypatch
    ):
        """No DC and no dashboard to route from: nothing the server can do."""
        _patch_completion(monkeypatch, [VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={"prompt": "count of samples", "component_type": "card"},
        )
        assert r.status_code == 422
        assert "dashboard_id" in r.text

    def test_text_pinned_needs_no_inventory(
        self, client, patch_dashboard_context, patch_inventory, monkeypatch
    ):
        _patch_completion(monkeypatch, [VALID_TEXT_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={"prompt": "introduce this section", "component_type": "text"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["routing"] == {"source": "user", "reason": None, "alternatives": []}
        assert payload["data_collection_id"] is None
        assert payload["workflow_id"] is None
        assert patch_inventory == []


# ---------------------------------------------------------------------------
# Routing: the prompt comes first, type and DC are optional pins
# ---------------------------------------------------------------------------

PHYSICAL_ID = "6" * 24
DEMOGRAPHICS_ID = "8" * 24
DASHBOARD_ID = "5" * 24

ROUTER_JSON = (
    '{"component_type": "card", "data_collection_tag": "physical_features",'
    ' "reason": "The prompt asks for one number about body measurements.",'
    ' "alternatives": ["demographics"]}'
)
BAD_TAG_ROUTER_JSON = (
    '{"component_type": "card", "data_collection_tag": "nope",'
    ' "reason": "guess", "alternatives": []}'
)


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
                workflow_id="7" * 24,
                workflow_tag="wf",
                dc_type="table",
                description="Body measurements per penguin",
                columns=[("bill_length_mm", "float64"), ("species", "object")],
                on_dashboard=True,
            ),
            InventoryEntry(
                data_collection_id=DEMOGRAPHICS_ID,
                data_collection_tag="demographics",
                workflow_id="7" * 24,
                workflow_tag="wf",
                dc_type="table",
                description="Island and year per penguin",
                columns=[("island", "object"), ("year", "int64")],
                on_dashboard=False,
            ),
        ],
    )


@pytest.fixture()
def patch_inventory(monkeypatch, inventory) -> list[dict]:
    """Serve the hand-built inventory; record every build call."""
    calls: list[dict] = []

    async def fake_build_project_inventory(dashboard_id, user, *, prioritize=None):
        calls.append({"dashboard_id": dashboard_id, "prioritize": prioritize})
        return inventory

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_project_inventory",
        fake_build_project_inventory,
    )
    return calls


class TestComponentFromPromptRouting:
    def test_fully_pinned_is_not_routed(self, client, patch_context, patch_inventory, monkeypatch):
        calls = _patch_completion(monkeypatch, [VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": PHYSICAL_ID,
                "prompt": "count of samples",
                "component_type": "card",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["routing"] == {"source": "user", "reason": None, "alternatives": []}
        assert payload["component_type"] == "card"
        assert payload["data_collection_id"] == PHYSICAL_ID
        assert payload["workflow_id"] == "7" * 24
        assert patch_inventory == []
        assert len(calls) == 1

    def test_pinned_type_with_one_dashboard_dc_skips_the_router(
        self, client, patch_context, patch_inventory, monkeypatch
    ):
        calls = _patch_completion(monkeypatch, [VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "prompt": "count of samples",
                "component_type": "card",
                "dashboard_id": DASHBOARD_ID,
            },
        )
        assert r.status_code == 200
        payload = r.json()
        # The only LLM call was the generation one.
        assert len(calls) == 1
        assert "DATASET SCHEMA" in calls[0][0]["content"]
        assert payload["routing"]["source"] == "single"
        assert "physical_features" in payload["routing"]["reason"]
        assert payload["routing"]["alternatives"] == []
        assert payload["data_collection_id"] == PHYSICAL_ID
        assert patch_inventory == [{"dashboard_id": DASHBOARD_ID, "prioritize": None}]

    def test_nothing_pinned_routes_type_and_dc(
        self, client, patch_context, patch_inventory, monkeypatch
    ):
        calls = _patch_completion(monkeypatch, [ROUTER_JSON, VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={"prompt": "how many penguins were measured", "dashboard_id": DASHBOARD_ID},
        )
        assert r.status_code == 200
        payload = r.json()
        assert len(calls) == 2
        router_system = calls[0][0]["content"]
        assert "physical_features" in router_system
        assert "demographics" in router_system
        assert "on dashboard" in router_system
        assert calls[0][1]["content"] == "how many penguins were measured"
        assert payload["component_type"] == "card"
        assert payload["data_collection_id"] == PHYSICAL_ID
        assert payload["workflow_id"] == "7" * 24
        routing = payload["routing"]
        assert routing["source"] == "auto"
        assert routing["reason"].startswith("The prompt asks for one number")
        assert routing["alternatives"] == [
            {
                "data_collection_id": DEMOGRAPHICS_ID,
                "data_collection_tag": "demographics",
                "workflow_id": "7" * 24,
                "workflow_tag": "wf",
            }
        ]

    def test_router_is_retried_once_on_an_unknown_tag(
        self, client, patch_context, patch_inventory, monkeypatch
    ):
        calls = _patch_completion(monkeypatch, [BAD_TAG_ROUTER_JSON, ROUTER_JSON, VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={"prompt": "how many penguins", "dashboard_id": DASHBOARD_ID},
        )
        assert r.status_code == 200
        assert len(calls) == 3
        rejection = calls[1][-1]["content"]
        assert "'nope'" in rejection
        assert "physical_features" in rejection
        assert r.json()["routing"]["source"] == "auto"
        assert r.json()["data_collection_id"] == PHYSICAL_ID

    def test_router_exhausted_is_502(self, client, patch_context, patch_inventory, monkeypatch):
        calls = _patch_completion(monkeypatch, [BAD_TAG_ROUTER_JSON])
        r = client.post(
            "/ai/component-from-prompt",
            json={"prompt": "how many penguins", "dashboard_id": DASHBOARD_ID},
        )
        assert r.status_code == 502
        assert "could not choose" in r.json()["detail"]
        assert len(calls) == 2

    def test_pinned_dc_routes_the_type_only(
        self, client, patch_context, patch_inventory, monkeypatch
    ):
        calls = _patch_completion(monkeypatch, [ROUTER_JSON, VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "prompt": "how many penguins",
                "data_collection_id": PHYSICAL_ID,
                "dashboard_id": DASHBOARD_ID,
            },
        )
        assert r.status_code == 200
        assert 'data_collection_tag is fixed to "physical_features"' in calls[0][0]["content"]
        assert patch_inventory == [{"dashboard_id": DASHBOARD_ID, "prioritize": [PHYSICAL_ID]}]
        payload = r.json()
        assert payload["routing"]["source"] == "auto"
        assert payload["component_type"] == "card"
        assert payload["data_collection_id"] == PHYSICAL_ID

    def test_missing_dashboard_id_with_nothing_pinned_is_422(
        self, client, patch_context, patch_inventory, monkeypatch
    ):
        _patch_completion(monkeypatch, [ROUTER_JSON])
        r = client.post("/ai/component-from-prompt", json={"prompt": "how many penguins"})
        assert r.status_code == 422
        assert "dashboard_id" in r.text
        assert patch_inventory == []


class TestComponentFromPromptAdvancedViz:
    def test_validated_end_to_end(self, client, patch_de_context, monkeypatch):
        calls = _patch_completion(monkeypatch, [VALID_ADVANCED_VIZ_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "volcano plot",
                "component_type": "advanced_viz",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["component_type"] == "advanced_viz"
        assert payload["validation_attempts"] == 1
        assert payload["parsed"]["viz_kind"] == "volcano"
        assert payload["parsed"]["config"]["effect_size_col"] == "log2FoldChange"
        # The sheet was ranked against this DC's columns.
        system = calls[0][0]["content"]
        assert "viz_kind: volcano" in system
        assert "config.effect_size_col" in system

    def test_bad_role_is_retried_with_a_field_error(self, client, patch_de_context, monkeypatch):
        calls = _patch_completion(
            monkeypatch, [BAD_ROLE_ADVANCED_VIZ_YAML, VALID_ADVANCED_VIZ_YAML]
        )
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "volcano plot",
                "component_type": "advanced_viz",
            },
        )
        assert r.status_code == 200
        assert r.json()["validation_attempts"] == 2
        retry_observation = calls[1][-1]["content"]
        assert "foo_col" in retry_observation
        assert "untyped dict" not in retry_observation
