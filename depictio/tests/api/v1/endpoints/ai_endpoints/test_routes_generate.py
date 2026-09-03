"""Endpoint tests for /ai/generate-dashboard and the promote route, plus the
pure helpers of `dashboard_gen`.

No Mongo, no Delta, no network: the project context builder, the catalog
matcher, the permission checks, the persistence tail and the run record are
patched at the `dashboard_gen` module boundary (that is where the generator
resolves them), and `llm_client.completion_with_usage` is replaced by a
dispatcher that answers the planning call with a canned plan and every fill
call with the canned YAML for the tag named in its prompt. The SSE body is
parsed with the same reader as test_routes_analyze.py.

Two goldens: iris (one collection, a funnel of MultiSelect + 4 cards,
4 RangeSliders + 2 figures, a table) and a penguins-shaped project (two
collections with a join) where one component is repaired, one is dropped
and the run still lands.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
import yaml
from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints import dashboard_gen, generations, llm_client
from depictio.api.v1.endpoints.ai_endpoints.context import (
    ColumnSummary,
    DataContext,
    JoinSummary,
    ProjectDataContext,
    viz_suggestions_for,
)
from depictio.api.v1.endpoints.ai_endpoints.dashboard_layout import GRID_COLS
from depictio.api.v1.endpoints.ai_endpoints.dashboard_plan import (
    DashboardPlan,
    PlannedComponent,
    SectionSpec,
    normalize_plan,
    parse_plan,
)
from depictio.api.v1.endpoints.ai_endpoints.dashboard_validate import validate_envelope
from depictio.api.v1.endpoints.ai_endpoints.routes import ai_endpoint_router
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

FAKE_USER = SimpleNamespace(id="0" * 24, email="t@example.com", is_admin=False, is_anonymous=False)
PROJECT_ID = "9" * 24
IRIS_DC_ID = "6" * 24
PHYS_DC_ID = "6" * 24
DEMO_DC_ID = "8" * 24
DE_DC_ID = "5" * 24
WF_IRIS = "python/iris_workflow"
WF = "wf"
DASHBOARD_ID = "d" * 24

TOKENS_PER_CALL = 150

# name -> (dtype, distinct)
IRIS = {
    "sepal.length": ("Float64", 35),
    "sepal.width": ("Float64", 23),
    "petal.length": ("Float64", 43),
    "petal.width": ("Float64", 22),
    "variety": ("String", 3),
}
PHYSICAL = {
    "sample_id": ("String", 344),
    "bill_length_mm": ("Float64", 150),
    "species": ("String", 3),
}
DEMOGRAPHICS = {"sample_id": ("String", 344), "island": ("String", 3), "year": ("Int64", 3)}
DE = {"gene_id": ("String", 900), "log2FoldChange": ("Float64", 900), "padj": ("Float64", 900)}


# ---------------------------------------------------------------------------
# Fixture helpers (plain functions so they can also be driven without pytest)
# ---------------------------------------------------------------------------


def _dc(tag: str, dc_id: str, columns: dict, *, workflow_tag: str = WF) -> DataContext:
    return DataContext(
        data_collection_id=dc_id,
        workflow_id="7" * 24,
        project_name="P",
        project_description=None,
        dc_name=tag,
        dc_description=None,
        columns=[
            ColumnSummary(name=n, dtype=d, null_pct=0.0, nunique=k) for n, (d, k) in columns.items()
        ],
        sample_rows=[],
        row_count=150,
        workflow_tag=workflow_tag,
        data_collection_tag=tag,
        dc_type="table",
    )


def iris_context() -> ProjectDataContext:
    return ProjectDataContext(
        project_id=PROJECT_ID,
        project_name="Iris",
        collections=[_dc("iris_table", IRIS_DC_ID, IRIS, workflow_tag=WF_IRIS)],
    )


def penguins_context() -> ProjectDataContext:
    return ProjectDataContext(
        project_id=PROJECT_ID,
        project_name="Penguins",
        collections=[
            _dc("physical", PHYS_DC_ID, PHYSICAL),
            _dc("demographics", DEMO_DC_ID, DEMOGRAPHICS),
        ],
        joins=[JoinSummary(left_dc="physical", right_dc="demographics", on_columns=["sample_id"])],
    )


def de_context() -> DataContext:
    ctx = _dc("de", DE_DC_ID, DE)
    ctx.viz_suggestions = viz_suggestions_for(ctx.columns)
    return ctx


def _y(**fields) -> str:
    return yaml.safe_dump(fields, sort_keys=False)


def _component(tag, section, component_type, dc_tag, intent="show it", **extra) -> dict:
    return {
        "tag": tag,
        "section": section,
        "component_type": component_type,
        "data_collection_tag": dc_tag,
        "intent": intent,
        **extra,
    }


def _interactive(dc_tag, wf, kind, column, column_type) -> str:
    return _y(
        component_type="interactive",
        workflow_tag=wf,
        data_collection_tag=dc_tag,
        title=column,
        interactive_component_type=kind,
        column_name=column,
        column_type=column_type,
    )


def _card(dc_tag, wf, aggregation, column, column_type=None) -> str:
    fields = dict(
        component_type="card",
        workflow_tag=wf,
        data_collection_tag=dc_tag,
        title=f"{aggregation} {column}",
        aggregation=aggregation,
        column_name=column,
    )
    if column_type:
        fields["column_type"] = column_type
    return _y(**fields)


def _figure(dc_tag, wf, visu_type, **kwargs) -> str:
    return _y(
        component_type="figure",
        workflow_tag=wf,
        data_collection_tag=dc_tag,
        title=visu_type,
        visu_type=visu_type,
        dict_kwargs=kwargs,
    )


def _table(dc_tag, wf, columns) -> str:
    return _y(
        component_type="table",
        workflow_tag=wf,
        data_collection_tag=dc_tag,
        title="Rows",
        columns=columns,
        page_size=10,
    )


IRIS_PLAN = {
    "title": "Iris overview",
    "subtitle": "Measurements of 150 iris flowers by variety",
    "filter_sections": [
        {"name": "Cohort", "icon": "mdi:filter-variant", "color": "teal"},
        {"name": "Measurements", "icon": "mdi:ruler", "color": "blue"},
    ],
    "grid_sections": [
        {
            "name": "Cohort",
            "icon": "mdi:counter",
            "color": "teal",
            "description": "Headline numbers",
        },
        {
            "name": "Measurements",
            "icon": "mdi:chart-scatter-plot",
            "description": "How they relate",
        },
        {"name": "Reference", "icon": "mdi:table", "description": "Raw rows"},
    ],
    "components": [
        _component("variety_filter", "Cohort", "interactive", "iris_table"),
        _component("n_flowers", "Cohort", "card", "iris_table"),
        _component("mean_sepal_length", "Cohort", "card", "iris_table"),
        _component("mean_petal_length", "Cohort", "card", "iris_table"),
        _component("n_varieties", "Cohort", "card", "iris_table"),
        _component("sepal_length_range", "Measurements", "interactive", "iris_table"),
        _component("sepal_width_range", "Measurements", "interactive", "iris_table"),
        _component("petal_length_range", "Measurements", "interactive", "iris_table"),
        _component("petal_width_range", "Measurements", "interactive", "iris_table"),
        _component("sepal_scatter", "Measurements", "figure", "iris_table"),
        _component("petal_box", "Measurements", "figure", "iris_table"),
        _component("rows", "Reference", "table", "iris_table"),
    ],
}

_I = ("iris_table", WF_IRIS)
IRIS_ANSWERS = {
    "variety_filter": [_interactive(*_I, "MultiSelect", "variety", "object")],
    "n_flowers": [_card(*_I, "count", "variety", "object")],
    "mean_sepal_length": [_card(*_I, "average", "sepal.length", "float64")],
    "mean_petal_length": [_card(*_I, "average", "petal.length", "float64")],
    "n_varieties": [_card(*_I, "nunique", "variety", "object")],
    "sepal_length_range": [_interactive(*_I, "RangeSlider", "sepal.length", "float64")],
    "sepal_width_range": [_interactive(*_I, "RangeSlider", "sepal.width", "float64")],
    "petal_length_range": [_interactive(*_I, "RangeSlider", "petal.length", "float64")],
    "petal_width_range": [_interactive(*_I, "RangeSlider", "petal.width", "float64")],
    "sepal_scatter": [_figure(*_I, "scatter", x="sepal.length", y="sepal.width", color="variety")],
    "petal_box": [_figure(*_I, "box", x="variety", y="petal.length")],
    "rows": [_table(*_I, list(IRIS))],
}

PENGUINS_PLAN = {
    "title": "Penguins",
    "subtitle": "Body measurements and where they were sampled",
    "filter_sections": [{"name": "Cohort"}],
    "grid_sections": [
        {"name": "Overview", "description": "Numbers"},
        {"name": "Analysis"},
        {"name": "Reference"},
    ],
    "components": [
        _component("species_filter", "Cohort", "interactive", "physical"),
        _component("mean_bill", "Overview", "card", "physical"),
        _component("island_mode", "Overview", "card", "demographics"),
        _component("bad_figure", "Analysis", "figure", "physical"),
        _component("bill_hist", "Analysis", "figure", "physical"),
        _component("rows", "Reference", "table", "demographics"),
    ],
}

_P = ("physical", WF)
_D = ("demographics", WF)
PENGUINS_ANSWERS = {
    "species_filter": [_interactive(*_P, "MultiSelect", "species", "object")],
    "mean_bill": [_card(*_P, "average", "bill_length_mm")],
    # First answer averages a string column (rejected), the second passes.
    "island_mode": [_card(*_D, "average", "island"), _card(*_D, "mode", "island")],
    # Every answer names a column the collection does not have: repairs run out.
    "bad_figure": [_figure(*_P, "histogram", x="flipper_length_mm")],
    "bill_hist": [_figure(*_P, "histogram", x="bill_length_mm", color="species")],
    "rows": [_table(*_D, ["sample_id", "island"])],
}

_TAG_RE = re.compile(r"this component's tag: (\S+)")
_PLAN_MARKER = "You plan a complete Depictio dashboard"


class FakeLLM:
    """Answers the planning call with `plan` and each fill call by the tag in its prompt.

    A tag's answer list is consumed from the front and its last entry
    repeats, so repair rounds beyond the scripted ones keep failing (or
    passing) the same way. `default` answers tags with no script.
    """

    def __init__(self, plan: dict, answers: dict[str, list[str]], default: str | None = None):
        self.plan = plan
        self.answers = {k: list(v) for k, v in answers.items()}
        self.default = default
        self.calls: list[str] = []

    def __call__(self, messages, **kw):
        if _PLAN_MARKER in messages[0]["content"]:
            self.calls.append("plan")
            content = self.plan if isinstance(self.plan, str) else json.dumps(self.plan)
        else:
            tag = _TAG_RE.search(messages[1]["content"]).group(1)
            self.calls.append(tag)
            queue = self.answers.get(tag) or [self.default or ""]
            content = queue.pop(0) if len(queue) > 1 else queue[0]
        return llm_client.Completion(
            content=content,
            usage=llm_client.CompletionUsage(100, 50, TOKENS_PER_CALL),
            cached=False,
        )


class _FakeProjects:
    def __init__(self, doc):
        self.doc = doc

    def find_one(self, query, projection=None):
        return self.doc if self.doc and query.get("_id") == self.doc["_id"] else None


def project_doc() -> dict:
    return {
        "_id": ObjectId(PROJECT_ID),
        "name": "P",
        "workflows": [
            {
                "_id": ObjectId(),
                "data_collections": [
                    {"_id": ObjectId(IRIS_DC_ID), "config": {"type": "table"}},
                    {"_id": ObjectId(DEMO_DC_ID), "config": {"type": "table"}},
                ],
            }
        ],
    }


class Pipeline:
    """Everything the generator touches outside the LLM, faked and recorded."""

    def __init__(self, monkeypatch, ctx: ProjectDataContext):
        self.ctx = ctx
        self.persisted: list[SimpleNamespace] = []
        self.saved_runs: list = []
        self.permission = True
        self.persist_error: HTTPException | None = None
        self.persist_failures = 0
        # The render check: every filled tile is probed, and a tag listed in
        # `probe_errors` answers with that reason instead of None. Faked here
        # like every other collaborator, so no test needs the real probe (it
        # reads the data) to know what the check does with its answer.
        self.probe_errors: dict[str, str] = {}
        self.probed: list[tuple[str, str | None]] = []

        def fake_probe(component, ctx_, user):
            tag = str(component.get("tag") or "")
            self.probed.append((tag, ctx_.data_collection_tag if ctx_ else None))
            return self.probe_errors.get(tag)

        async def fake_context(project_id, user, dc_ids=None, *, max_collections=6):
            self.context_call = SimpleNamespace(
                project_id=project_id, dc_ids=dc_ids, max_collections=max_collections
            )
            return ctx, []

        def fake_persist(lite, project_id, user, *, overwrite=False, extra_fields=None):
            if self.persist_failures > 0:
                self.persist_failures -= 1
                raise HTTPException(status_code=409, detail="exists")
            if self.persist_error is not None:
                raise self.persist_error
            self.persisted.append(
                SimpleNamespace(
                    lite=lite,
                    project_id=project_id,
                    user=user,
                    overwrite=overwrite,
                    extra_fields=extra_fields,
                )
            )
            return {
                "success": True,
                "updated": False,
                "dashboard_id": DASHBOARD_ID,
                "title": lite.title,
                "project_id": str(project_id),
            }

        monkeypatch.setattr(dashboard_gen, "build_project_data_context", fake_context)
        monkeypatch.setattr(
            dashboard_gen, "compose_offers_for_project", lambda doc: {"modules": []}
        )
        monkeypatch.setattr(dashboard_gen, "_persist_lite_dashboard", fake_persist)
        monkeypatch.setattr(dashboard_gen, "probe_component", fake_probe)
        monkeypatch.setattr(dashboard_gen, "projects_collection", _FakeProjects(project_doc()))
        monkeypatch.setattr(
            dashboard_gen, "check_project_permission", lambda pid, user, perm: self.permission
        )
        monkeypatch.setattr(
            generations, "save", lambda run: self.saved_runs.append(run.model_copy(deep=True))
        )
        monkeypatch.setattr(settings.ai, "generate_dashboard_enabled", True)
        monkeypatch.setattr(settings.ai, "generate_max_repairs_per_component", 1)
        monkeypatch.setattr(settings.auth, "public_mode", False)
        monkeypatch.setattr(settings.auth, "unauthenticated_mode", False)
        monkeypatch.setattr(settings.auth, "single_user_mode", False)

    @property
    def last_run(self):
        return self.saved_runs[-1]


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(ai_endpoint_router, prefix="/ai")
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    return TestClient(app)


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        etype = lines[0].removeprefix("event: ").strip()
        data_line = next((ln for ln in lines[1:] if ln.startswith("data: ")), "data: {}")
        events.append((etype, json.loads(data_line.removeprefix("data: "))))
    return events


def generate(client: TestClient, monkeypatch, fake: FakeLLM, **body) -> list[tuple[str, dict]]:
    monkeypatch.setattr(llm_client, "completion_with_usage", fake)
    payload = {"project_id": PROJECT_ID, "prompt": "an overview", **body}
    r = client.post("/ai/generate-dashboard", json=payload)
    assert r.status_code == 200, r.text
    return parse_sse(r.text)


def _components(events) -> dict[str, dict]:
    return {d["tag"]: d for t, d in events if t == "component"}


def _one(events, etype) -> dict:
    return next(d for t, d in events if t == etype)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return make_client()


@pytest.fixture()
def iris(monkeypatch) -> Pipeline:
    return Pipeline(monkeypatch, iris_context())


@pytest.fixture()
def penguins(monkeypatch) -> Pipeline:
    return Pipeline(monkeypatch, penguins_context())


# ---------------------------------------------------------------------------
# Goldens
# ---------------------------------------------------------------------------


class TestIrisGolden:
    def test_event_order_and_every_component_ok(self, client, iris, monkeypatch):
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)
        events = generate(client, monkeypatch, fake)
        types = [t for t, _ in events]

        assert types[0] == "status"
        assert types.index("plan") < types.index("component")
        # A budget event follows the planning call and every fill call.
        assert types[types.index("plan") - 1] == "budget"
        assert types.count("budget") == 1 + 12
        assert types[-2:] == ["dashboard", "done"]
        assert "error" not in types

        components = _components(events)
        assert list(components) == [c["tag"] for c in IRIS_PLAN["components"]]
        assert {c["status"] for c in components.values()} == {"ok"}
        assert all(c["attempts"] == 1 for c in components.values())
        assert fake.calls == ["plan"] + list(components)

    def test_plan_event_is_the_normalised_plan(self, client, iris, monkeypatch):
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        plan = _one(events, "plan")["plan"]
        assert plan["title"] == "Iris overview"
        assert [s["name"] for s in plan["grid_sections"]] == ["Cohort", "Measurements", "Reference"]
        assert [s["name"] for s in plan["filter_sections"]] == ["Cohort", "Measurements"]
        assert len(plan["components"]) == 12

    def test_dashboard_event_and_persisted_draft(self, client, iris, monkeypatch):
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        dashboard = _one(events, "dashboard")
        assert dashboard["dashboard_id"] == DASHBOARD_ID
        assert dashboard["title"] == "Iris overview"
        assert dashboard["project_id"] == PROJECT_ID
        assert dashboard["dropped"] == []
        assert dashboard["warnings"] == []

        (persisted,) = iris.persisted
        assert persisted.overwrite is False
        assert str(persisted.project_id) == PROJECT_ID
        info = persisted.extra_fields["ai_generation"]
        assert info["status"] == "draft"
        assert info["run_id"] == iris.last_run.id
        assert info["prompt"] == "an overview"
        assert info["model"] == llm_client.get_default_model()

        run = iris.last_run
        assert run.status == "complete"
        assert run.dashboard_id == DASHBOARD_ID
        assert run.plan["title"] == "Iris overview"
        assert [c["status"] for c in run.components] == ["ok"] * 12
        assert run.budget_spent.tokens == 13 * TOKENS_PER_CALL
        assert run.yaml == dashboard["yaml"]

    def test_yaml_round_trips_and_lays_out_the_funnel(self, client, iris, monkeypatch):
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        lite_dict = yaml.safe_load(_one(events, "dashboard")["yaml"])
        lite = validate_envelope(lite_dict)
        assert lite.title == "Iris overview"
        assert lite.subtitle == IRIS_PLAN["subtitle"]

        # Every component carries an explicit layout and section; the server
        # added one header text per grid section.
        assert all("layout" in c and c.get("section") for c in lite_dict["components"])
        texts = [c for c in lite_dict["components"] if c["component_type"] == "text"]
        assert [t["section"] for t in texts] == ["Cohort", "Measurements", "Reference"]
        assert texts[0]["title"] == "Cohort" and texts[0]["body"] == "Headline numbers"
        assert all(t["order"] == 3 for t in texts)

        # Full card row: four cards of w=2 on one y.
        cards = [c["layout"] for c in lite_dict["components"] if c["component_type"] == "card"]
        assert [c["w"] for c in cards] == [2, 2, 2, 2]
        assert len({c["y"] for c in cards}) == 1
        assert sum(c["w"] for c in cards) == GRID_COLS

        full = lite.to_full()
        assert len(full["left_panel_layout_data"]) == 5
        assert all(box["w"] <= GRID_COLS for box in full["right_panel_layout_data"])
        assert all(box["x"] + box["w"] <= GRID_COLS for box in full["right_panel_layout_data"])
        assert full["grid_sections"][-1]["collapsed"] is True
        assert full["filter_sections"][0]["icon"] == "mdi:filter-variant"

    def test_persisted_lite_matches_the_streamed_yaml(self, client, iris, monkeypatch):
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        streamed = yaml.safe_load(_one(events, "dashboard")["yaml"])
        (persisted,) = iris.persisted
        assert persisted.lite.title == streamed["title"]
        assert len(persisted.lite.components) == len(streamed["components"])
        assert [c.tag for c in persisted.lite.components] == [
            c["tag"] for c in streamed["components"]
        ]

    def test_requested_collections_and_limits_reach_the_context_builder(
        self, client, iris, monkeypatch
    ):
        monkeypatch.setattr(settings.ai, "generate_max_collections", 3)
        generate(
            client,
            monkeypatch,
            FakeLLM(IRIS_PLAN, IRIS_ANSWERS),
            data_collection_ids=[IRIS_DC_ID],
        )
        assert iris.context_call.project_id == PROJECT_ID
        assert iris.context_call.dc_ids == [IRIS_DC_ID]
        assert iris.context_call.max_collections == 3


class TestPenguinsGolden:
    def test_repair_drop_and_completion(self, client, penguins, monkeypatch):
        fake = FakeLLM(PENGUINS_PLAN, PENGUINS_ANSWERS)
        events = generate(client, monkeypatch, fake)
        components = _components(events)

        assert components["species_filter"]["status"] == "ok"
        assert components["mean_bill"]["status"] == "ok"
        repaired = components["island_mode"]
        assert repaired["status"] == "repaired"
        assert repaired["attempts"] == 2
        assert repaired["error"] is None
        dropped = components["bad_figure"]
        assert dropped["status"] == "dropped"
        assert dropped["attempts"] == 2
        assert "flipper_length_mm" in dropped["error"]
        assert components["bill_hist"]["status"] == "ok"
        assert components["rows"]["status"] == "ok"

        # One repair call for island_mode, two attempts for bad_figure.
        assert fake.calls == [
            "plan",
            "species_filter",
            "mean_bill",
            "island_mode",
            "island_mode",
            "bad_figure",
            "bad_figure",
            "bill_hist",
            "rows",
        ]

        dashboard = _one(events, "dashboard")
        assert dashboard["dropped"] == ["bad_figure"]
        assert any("bad_figure" in w for w in dashboard["warnings"])
        assert [t for t, _ in events][-1] == "done"
        lite_dict = yaml.safe_load(dashboard["yaml"])
        tags = [c["tag"] for c in lite_dict["components"]]
        assert "bad_figure" not in tags
        assert "island_mode" in tags
        assert {
            c["data_collection_tag"]
            for c in lite_dict["components"]
            if c["component_type"] != "text"
        } == {
            "physical",
            "demographics",
        }

    def test_tokens_accumulate_across_budget_events(self, client, penguins, monkeypatch):
        events = generate(client, monkeypatch, FakeLLM(PENGUINS_PLAN, PENGUINS_ANSWERS))
        budgets = [d for t, d in events if t == "budget"]
        assert [b["tokens_used"] for b in budgets] == [
            TOKENS_PER_CALL * n for n in range(1, len(budgets) + 1)
        ]
        assert {
            "steps_used",
            "tokens_used",
            "seconds",
            "max_steps",
            "max_tokens",
            "max_seconds",
        } <= set(budgets[0])
        assert budgets[-1]["steps_used"] == 9
        assert budgets[0]["max_tokens"] == settings.ai.generate_max_tokens_total
        run = penguins.last_run
        assert run.budget_spent.tokens == 9 * TOKENS_PER_CALL
        assert [c["status"] for c in run.components] == [
            "ok",
            "ok",
            "repaired",
            "dropped",
            "ok",
            "ok",
        ]

    def test_column_type_is_filled_from_the_collection(self, client, penguins, monkeypatch):
        events = generate(client, monkeypatch, FakeLLM(PENGUINS_PLAN, PENGUINS_ANSWERS))
        lite_dict = yaml.safe_load(_one(events, "dashboard")["yaml"])
        by_tag = {c["tag"]: c for c in lite_dict["components"]}
        # The canned card answers omit column_type; it comes from the schema.
        assert by_tag["mean_bill"]["column_type"] == "float64"
        assert by_tag["island_mode"]["column_type"] == "object"

    def test_run_is_saved_after_the_plan_and_after_every_component(
        self, client, penguins, monkeypatch
    ):
        generate(client, monkeypatch, FakeLLM(PENGUINS_PLAN, PENGUINS_ANSWERS))
        statuses = [r.status for r in penguins.saved_runs]
        # plan + 6 components + final
        assert len(penguins.saved_runs) == 1 + 6 + 1
        assert statuses[:-1] == ["running"] * 7
        assert statuses[-1] == "complete"
        assert penguins.saved_runs[0].plan is not None
        assert len(penguins.saved_runs[3].components) == 3


# ---------------------------------------------------------------------------
# Budget and failure modes
# ---------------------------------------------------------------------------


class TestBudget:
    def test_token_exhaustion_drops_the_rest_and_still_lands(self, client, iris, monkeypatch):
        # plan (150) + two fills (450): the third fill finds the budget spent.
        monkeypatch.setattr(settings.ai, "generate_max_tokens_total", 3 * TOKENS_PER_CALL)
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)
        events = generate(client, monkeypatch, fake)
        components = _components(events)

        assert fake.calls == ["plan", "variety_filter", "n_flowers"]
        assert components["variety_filter"]["status"] == "ok"
        assert components["n_flowers"]["status"] == "ok"
        rest = [c for tag, c in components.items() if tag not in ("variety_filter", "n_flowers")]
        assert len(rest) == 10
        assert all(c["status"] == "dropped" and c["error"] == "budget" for c in rest)
        assert all(c["attempts"] == 0 for c in rest)

        dashboard = _one(events, "dashboard")
        assert len(dashboard["dropped"]) == 10
        lite_dict = yaml.safe_load(dashboard["yaml"])
        data_bound = [c for c in lite_dict["components"] if c["component_type"] != "text"]
        assert {c["tag"] for c in data_bound} == {"variety_filter", "n_flowers"}
        assert [t for t, _ in events][-1] == "done"
        assert iris.last_run.status == "complete"

    def test_wall_clock_exhaustion_drops_the_rest(self, client, iris, monkeypatch):
        monkeypatch.setattr(settings.ai, "generate_max_wall_clock_s", 60)
        # Start the clock in the past: every fill sees the budget spent.
        real_budget = dashboard_gen.Budget

        class ExpiredBudget(real_budget):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.started -= 3600

        monkeypatch.setattr(dashboard_gen, "Budget", ExpiredBudget)
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)
        events = generate(client, monkeypatch, fake)
        assert fake.calls == ["plan"]
        components = _components(events)
        assert all(c["status"] == "dropped" and c["error"] == "budget" for c in components.values())
        # Nothing data-bound survived: no dashboard.
        types = [t for t, _ in events]
        assert "dashboard" not in types
        assert _one(events, "error")["detail"] == "no component could be generated"
        assert types[-1] == "done"

    def test_cached_completions_are_not_charged(self, client, iris, monkeypatch):
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)

        def cached(messages, **kw):
            completion = fake(messages, **kw)
            return llm_client.Completion(completion.content, completion.usage, cached=True)

        monkeypatch.setattr(llm_client, "completion_with_usage", cached)
        r = client.post("/ai/generate-dashboard", json={"project_id": PROJECT_ID})
        events = parse_sse(r.text)
        budgets = [d for t, d in events if t == "budget"]
        assert all(b["tokens_used"] == 0 for b in budgets)
        assert budgets[-1]["steps_used"] == 13


class TestFailures:
    def test_zero_survivors_is_an_error_event(self, client, iris, monkeypatch):
        fake = FakeLLM(IRIS_PLAN, {}, default="I cannot write that component.")
        events = generate(client, monkeypatch, fake)
        components = _components(events)
        assert len(components) == 12
        assert all(c["status"] == "dropped" and c["attempts"] == 2 for c in components.values())
        types = [t for t, _ in events]
        assert "dashboard" not in types
        assert _one(events, "error")["detail"] == "no component could be generated"
        assert types[-1] == "done"
        assert iris.persisted == []
        assert iris.last_run.status == "failed"

    def test_wrong_component_type_is_repaired_not_relabelled(self, client, iris, monkeypatch):
        answers = dict(IRIS_ANSWERS)
        # A card answer for a planned figure, then the right thing.
        answers["sepal_scatter"] = [
            _card(*_I, "average", "sepal.length", "float64"),
            *IRIS_ANSWERS["sepal_scatter"],
        ]
        fake = FakeLLM(IRIS_PLAN, answers)
        events = generate(client, monkeypatch, fake)
        scatter = _components(events)["sepal_scatter"]
        assert scatter["status"] == "repaired"
        assert scatter["attempts"] == 2
        # The mismatch went back to the model as a repair round, not a relabel.
        assert fake.calls.count("sepal_scatter") == 2
        lite_dict = yaml.safe_load(_one(events, "dashboard")["yaml"])
        figure = next(c for c in lite_dict["components"] if c["tag"] == "sepal_scatter")
        assert figure["visu_type"] == "scatter"
        assert figure["dict_kwargs"]["x"] == "sepal.length"

    def test_invalid_plan_json_is_retried_then_errors(self, client, iris, monkeypatch):
        fake = FakeLLM("this is not json", {})
        events = generate(client, monkeypatch, fake)
        assert fake.calls == ["plan", "plan"]
        types = [t for t, _ in events]
        assert "plan" not in types
        assert types.count("budget") == 2
        assert "did not produce a usable plan" in _one(events, "error")["detail"]
        assert types[-1] == "done"
        assert iris.last_run.status == "failed"

    def test_plan_with_only_unknown_collections_is_retried(self, client, iris, monkeypatch):
        bad_plan = {
            **IRIS_PLAN,
            "components": [_component("ghost", "Reference", "table", "not_a_collection")],
        }
        fake = FakeLLM(bad_plan, {})
        events = generate(client, monkeypatch, fake)
        assert fake.calls == ["plan", "plan"]
        assert "not_a_collection" in _one(events, "error")["detail"]

    def test_unknown_collection_component_is_dropped_before_filling(
        self, client, iris, monkeypatch
    ):
        plan = {
            **IRIS_PLAN,
            "components": [
                *IRIS_PLAN["components"],
                _component("ghost", "Reference", "table", "not_a_collection"),
            ],
        }
        fake = FakeLLM(plan, IRIS_ANSWERS)
        events = generate(client, monkeypatch, fake)
        ghost = _components(events)["ghost"]
        assert ghost["status"] == "dropped"
        assert ghost["attempts"] == 0
        assert "not_a_collection" in ghost["error"]
        assert "ghost" not in fake.calls
        assert _one(events, "dashboard")["dropped"] == ["ghost"]

    def test_llm_failure_during_planning_is_an_error_event(self, client, iris, monkeypatch):
        def boom(messages, **kw):
            raise RuntimeError("provider down")

        monkeypatch.setattr(llm_client, "completion_with_usage", boom)
        r = client.post("/ai/generate-dashboard", json={"project_id": PROJECT_ID})
        assert r.status_code == 200
        events = parse_sse(r.text)
        assert "provider down" in _one(events, "error")["detail"]
        assert [t for t, _ in events][-1] == "done"

    def test_unexpected_exception_is_generic_and_terminates(self, client, iris, monkeypatch):
        def explode(plan, components):
            raise RuntimeError("secret internals")

        monkeypatch.setattr(dashboard_gen, "layout_dashboard", explode)
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        error = _one(events, "error")["detail"]
        assert "secret internals" not in error
        assert "unexpectedly" in error
        assert [t for t, _ in events][-1] == "done"
        assert iris.last_run.status == "failed"

    def test_project_without_table_collections_is_an_error_event(self, client, iris, monkeypatch):
        async def empty(project_id, user, dc_ids=None, *, max_collections=6):
            return ProjectDataContext(project_id=PROJECT_ID, project_name="P", collections=[]), []

        monkeypatch.setattr(dashboard_gen, "build_project_data_context", empty)
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)
        events = generate(client, monkeypatch, fake)
        assert fake.calls == []
        assert "no table data collection" in _one(events, "error")["detail"]


class TestTitles:
    def test_llm_title_collision_gets_a_draft_suffix(self, client, iris, monkeypatch):
        iris.persist_failures = 2
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        dashboard = _one(events, "dashboard")
        assert dashboard["title"] == "Iris overview (AI draft 3)"
        assert iris.persisted[0].lite.title == "Iris overview (AI draft 3)"
        assert yaml.safe_load(dashboard["yaml"])["title"] == "Iris overview (AI draft 3)"
        assert sum("already exists" in w for w in dashboard["warnings"]) == 2

    def test_explicit_title_collision_is_an_error_event(self, client, iris, monkeypatch):
        iris.persist_failures = 1
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS), title="Mine")
        types = [t for t, _ in events]
        assert "dashboard" not in types
        assert _one(events, "error")["detail"] == "title exists"
        assert types[-1] == "done"
        assert iris.last_run.status == "failed"

    def test_explicit_title_is_used_verbatim_and_overwrite_is_passed(
        self, client, iris, monkeypatch
    ):
        events = generate(
            client,
            monkeypatch,
            FakeLLM(IRIS_PLAN, IRIS_ANSWERS),
            title="  My iris  ",
            overwrite=True,
        )
        assert _one(events, "dashboard")["title"] == "My iris"
        assert _one(events, "plan")["plan"]["title"] == "My iris"
        assert iris.persisted[0].overwrite is True

    def test_other_persist_errors_surface_their_detail(self, client, iris, monkeypatch):
        iris.persist_error = HTTPException(status_code=400, detail="Dashboard validation failed: x")
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        assert _one(events, "error")["detail"] == "Dashboard validation failed: x"


# ---------------------------------------------------------------------------
# The render check, between the fill loop and the layout
# ---------------------------------------------------------------------------


class TestRenderCheck:
    def test_every_filled_tile_is_probed_with_its_collection(self, client, iris, monkeypatch):
        generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        probed = dict(iris.probed)
        assert set(probed) == {c["tag"] for c in IRIS_PLAN["components"]}
        # The tile's own collection reaches the probe; text binds none.
        assert set(probed.values()) == {"iris_table"}

    def test_a_tile_that_does_not_render_is_dropped_from_the_draft(self, client, iris, monkeypatch):
        iris.probe_errors["petal_box"] = "duplicate column 'petal.length'"
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        types = [t for t, _ in events]
        assert types[-2:] == ["dashboard", "done"]
        # The fill said ok, the check said dropped: both frames, in that order.
        petal = [d for t, d in events if t == "component" and d["tag"] == "petal_box"]
        assert [d["status"] for d in petal] == ["ok", "dropped"]
        assert petal[-1]["error"] == "render: duplicate column 'petal.length'"
        assert petal[-1]["attempts"] == 0
        # `checking` runs after the last fill and before the layout.
        statuses = [d["message"] for t, d in events if t == "status"]
        assert statuses.index("checking") > statuses.index("filling")
        assert statuses.index("checking") < statuses.index("laying out")

        dashboard = _one(events, "dashboard")
        assert dashboard["dropped"] == ["petal_box"]
        assert "petal_box" not in {
            c["tag"] for c in yaml.safe_load(dashboard["yaml"])["components"]
        }
        assert any("does not render" in w for w in dashboard["warnings"])
        # One entry per planned component: the drop replaces the fill's ok.
        run = iris.last_run
        assert [c["tag"] for c in run.components] == [c["tag"] for c in IRIS_PLAN["components"]]
        assert {c["tag"] for c in run.components if c["status"] == "dropped"} == {"petal_box"}

    def test_a_run_left_with_no_data_bound_tile_ends_in_error(self, client, iris, monkeypatch):
        iris.probe_errors = {c["tag"]: "nope" for c in IRIS_PLAN["components"]}
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        assert "dashboard" not in [t for t, _ in events]
        assert _one(events, "error")["detail"] == "no component could be generated"
        assert iris.last_run.status == "failed"

    def test_a_probe_that_blows_up_keeps_the_tile_and_says_so(self, client, iris, monkeypatch):
        def boom(component, ctx, user):
            raise RuntimeError("the probe module is not there")

        monkeypatch.setattr(dashboard_gen, "probe_component", boom)
        events = generate(client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        dashboard = _one(events, "dashboard")
        assert dashboard["dropped"] == []
        assert sum("could not run" in w for w in dashboard["warnings"]) == 1


# ---------------------------------------------------------------------------
# Two phases: plan_only, then the approved plan
# ---------------------------------------------------------------------------


class TestPlanOnly:
    def test_stops_at_the_plan_and_saves_nothing(self, client, iris, monkeypatch):
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)
        events = generate(client, monkeypatch, fake, plan_only=True)
        types = [t for t, _ in events]

        assert fake.calls == ["plan"]
        assert types[-3:] == ["plan", "budget", "done"]
        assert "component" not in types and "dashboard" not in types
        assert _one(events, "plan")["plan"]["title"] == "Iris overview"
        assert iris.persisted == []
        assert iris.probed == []

        run = iris.last_run
        # Not `complete`: the run stopped at the plan on purpose and saved no
        # dashboard, and the history has to be able to say so.
        assert run.status == "planned"
        assert run.dashboard_id is None
        assert run.yaml == ""
        assert run.plan["title"] == "Iris overview"
        # One planning call, and only that one, is what the caller paid for.
        assert run.budget_spent.tokens == TOKENS_PER_CALL
        assert any("Plan-only" in w for w in run.warnings)

    def test_with_a_plan_is_422_before_the_stream(self, client, iris):
        r = client.post(
            "/ai/generate-dashboard",
            json={"project_id": PROJECT_ID, "plan_only": True, "plan": IRIS_PLAN},
        )
        assert r.status_code == 422


class TestApprovedPlan:
    def test_fills_the_given_plan_without_a_planning_call(self, client, iris, monkeypatch):
        fake = FakeLLM({"title": "never asked"}, IRIS_ANSWERS)
        events = generate(client, monkeypatch, fake, plan=IRIS_PLAN)
        types = [t for t, _ in events]

        assert "plan" not in fake.calls
        assert fake.calls == [c["tag"] for c in IRIS_PLAN["components"]]
        # The panel reads the same budget-then-plan pair in both phases.
        assert types[types.index("plan") - 1] == "budget"
        assert _one(events, "plan")["plan"]["title"] == "Iris overview"
        assert types[-2:] == ["dashboard", "done"]
        assert _one(events, "dashboard")["title"] == "Iris overview"
        assert iris.last_run.status == "complete"
        # Only the fills were charged: the planning call was not made.
        assert iris.last_run.budget_spent.tokens == 12 * TOKENS_PER_CALL

    def test_the_plan_event_is_the_normalised_plan_not_the_one_sent(
        self, client, iris, monkeypatch
    ):
        sent = {
            **IRIS_PLAN,
            "grid_sections": [
                *[
                    {**s, "icon": "not:an-icon", "color": "chartreuse"}
                    if s["name"] == "Reference"
                    else s
                    for s in IRIS_PLAN["grid_sections"]
                ],
                {"name": "Empty", "description": "a section nothing lives in"},
            ],
        }
        events = generate(
            client, monkeypatch, FakeLLM(IRIS_PLAN, IRIS_ANSWERS), plan=sent, title="Pinned"
        )
        plan = _one(events, "plan")["plan"]
        # Normalised exactly as a model answer is: the empty section is gone,
        # the pinned title wins, and no icon or colour outside the allowlists
        # survives into the draft.
        assert [s["name"] for s in plan["grid_sections"]] == ["Cohort", "Measurements", "Reference"]
        assert plan["title"] == "Pinned"
        reference = next(s for s in plan["grid_sections"] if s["name"] == "Reference")
        assert reference["color"] is None
        assert reference["icon"] != "not:an-icon"

    def test_a_plan_naming_a_collection_of_another_project_is_an_error(
        self, client, iris, monkeypatch
    ):
        sent = {
            **IRIS_PLAN,
            "components": [
                *IRIS_PLAN["components"],
                _component("smuggled", "Reference", "table", "someone_elses_dc"),
            ],
        }
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)
        events = generate(client, monkeypatch, fake, plan=sent)
        detail = _one(events, "error")["detail"]
        assert "someone_elses_dc" in detail and "iris_table" in detail
        assert fake.calls == []
        assert iris.persisted == []
        assert [t for t, _ in events][-1] == "done"
        assert iris.last_run.status == "failed"

    def test_a_plan_that_does_not_parse_is_an_error_not_a_500(self, client, iris, monkeypatch):
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)
        events = generate(
            client, monkeypatch, fake, plan={"title": "T", "components": [{"tag": "x"}]}
        )
        types = [t for t, _ in events]
        assert "plan" not in types and "dashboard" not in types
        assert "cannot be used" in _one(events, "error")["detail"]
        assert fake.calls == []
        assert types[-1] == "done"


# ---------------------------------------------------------------------------
# Gates (real HTTP codes, before the stream)
# ---------------------------------------------------------------------------


class TestGates:
    def test_flag_off_is_404(self, client, iris, monkeypatch):
        monkeypatch.setattr(settings.ai, "generate_dashboard_enabled", False)
        r = client.post("/ai/generate-dashboard", json={"project_id": PROJECT_ID})
        assert r.status_code == 404

    def test_public_mode_is_403(self, client, iris, monkeypatch):
        monkeypatch.setattr(settings.auth, "public_mode", True)
        r = client.post("/ai/generate-dashboard", json={"project_id": PROJECT_ID})
        assert r.status_code == 403
        assert "public" in r.json()["detail"]

    def test_anonymous_outside_single_user_mode_is_403(self, iris, monkeypatch):
        app = FastAPI()
        app.include_router(ai_endpoint_router, prefix="/ai")
        anon = SimpleNamespace(id="1" * 24, email="anon@x", is_admin=False, is_anonymous=True)
        app.dependency_overrides[get_current_user] = lambda: anon
        r = TestClient(app).post("/ai/generate-dashboard", json={"project_id": PROJECT_ID})
        assert r.status_code == 403
        monkeypatch.setattr(settings.auth, "single_user_mode", True)
        monkeypatch.setattr(llm_client, "completion_with_usage", FakeLLM(IRIS_PLAN, IRIS_ANSWERS))
        r = TestClient(app).post("/ai/generate-dashboard", json={"project_id": PROJECT_ID})
        assert r.status_code == 200

    def test_non_editor_is_403(self, client, iris):
        iris.permission = False
        r = client.post("/ai/generate-dashboard", json={"project_id": PROJECT_ID})
        assert r.status_code == 403

    def test_unknown_project_is_404_and_bad_id_400(self, client, iris, monkeypatch):
        r = client.post("/ai/generate-dashboard", json={"project_id": str(ObjectId())})
        assert r.status_code == 404
        r = client.post("/ai/generate-dashboard", json={"project_id": "nope"})
        assert r.status_code == 400

    def test_foreign_data_collection_id_is_400(self, client, iris):
        foreign = str(ObjectId())
        r = client.post(
            "/ai/generate-dashboard",
            json={"project_id": PROJECT_ID, "data_collection_ids": [IRIS_DC_ID, foreign]},
        )
        assert r.status_code == 400
        assert foreign in r.json()["detail"]

    def test_gates_run_before_any_llm_call(self, client, iris, monkeypatch):
        fake = FakeLLM(IRIS_PLAN, IRIS_ANSWERS)
        monkeypatch.setattr(llm_client, "completion_with_usage", fake)
        iris.permission = False
        client.post("/ai/generate-dashboard", json={"project_id": PROJECT_ID})
        assert fake.calls == []
        assert iris.saved_runs == []

    def test_prompt_length_is_validated(self, client, iris):
        r = client.post(
            "/ai/generate-dashboard", json={"project_id": PROJECT_ID, "prompt": "x" * 2001}
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Promote
# ---------------------------------------------------------------------------


class _FakeDashboards:
    def __init__(self, doc):
        self.doc = doc
        self.updates: list[tuple[dict, dict]] = []

    def find_one(self, query, projection=None):
        return (
            self.doc if self.doc and query.get("dashboard_id") == self.doc["dashboard_id"] else None
        )

    def update_one(self, query, update):
        self.updates.append((query, update))
        return SimpleNamespace(matched_count=1, modified_count=1)


def _draft_doc(**overrides) -> dict:
    doc = {
        "dashboard_id": ObjectId(DASHBOARD_ID),
        "project_id": ObjectId(PROJECT_ID),
        "permissions": {"owners": [], "editors": [], "viewers": []},
        "ai_generation": {"status": "draft", "model": "m", "generated_at": "t", "run_id": "r"},
    }
    doc.update(overrides)
    return doc


class TestPromote:
    def _wire(self, monkeypatch, doc, permitted=True) -> _FakeDashboards:
        fake = _FakeDashboards(doc)
        monkeypatch.setattr(dashboard_gen, "dashboards_collection", fake)
        monkeypatch.setattr(
            dashboard_gen,
            "check_dashboard_mutation_permission",
            lambda d, user, perm: permitted and perm == "editor",
        )
        return fake

    def test_promote_sets_the_status(self, client, monkeypatch):
        fake = self._wire(monkeypatch, _draft_doc())
        r = client.post(f"/ai/generated-dashboards/{DASHBOARD_ID}/promote")
        assert r.status_code == 200
        assert r.json() == {"dashboard_id": DASHBOARD_ID, "status": "promoted"}
        ((query, update),) = fake.updates
        assert query == {"dashboard_id": ObjectId(DASHBOARD_ID)}
        assert update == {"$set": {"ai_generation.status": "promoted"}}

    def test_missing_dashboard_is_404(self, client, monkeypatch):
        self._wire(monkeypatch, None)
        r = client.post(f"/ai/generated-dashboards/{DASHBOARD_ID}/promote")
        assert r.status_code == 404

    def test_dashboard_without_ai_generation_is_404(self, client, monkeypatch):
        fake = self._wire(monkeypatch, _draft_doc(ai_generation=None))
        r = client.post(f"/ai/generated-dashboards/{DASHBOARD_ID}/promote")
        assert r.status_code == 404
        assert fake.updates == []

    def test_non_editor_is_403(self, client, monkeypatch):
        fake = self._wire(monkeypatch, _draft_doc(), permitted=False)
        r = client.post(f"/ai/generated-dashboards/{DASHBOARD_ID}/promote")
        assert r.status_code == 403
        assert fake.updates == []

    def test_bad_id_is_400(self, client, monkeypatch):
        self._wire(monkeypatch, _draft_doc())
        r = client.post("/ai/generated-dashboards/not-an-id/promote")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _plan(*components: dict, title: str = "Penguins") -> DashboardPlan:
    plan, _ = normalize_plan(
        parse_plan({**PENGUINS_PLAN, "title": title, "components": list(components)}),
        max_components=16,
        max_sections=4,
    )
    return plan


class TestPickTitle:
    def test_requested_wins_and_is_trimmed(self):
        assert dashboard_gen.pick_title("  Mine ", "Plan", draft=3) == "Mine"

    def test_plan_title_gets_a_suffix_from_the_second_draft(self):
        assert dashboard_gen.pick_title(None, "Iris  overview") == "Iris overview"
        assert (
            dashboard_gen.pick_title("", "Iris overview", draft=2) == "Iris overview (AI draft 2)"
        )

    def test_blank_plan_title_falls_back(self):
        assert dashboard_gen.pick_title(None, "   ") == "Generated dashboard"


class TestBudgetTracker:
    def test_charges_uncached_calls_only(self):
        budget = dashboard_gen.Budget(max_tokens=1000, max_seconds=60, max_steps=5)
        budget.charge(llm_client.Completion("x", llm_client.CompletionUsage(1, 1, 400), False))
        budget.charge(llm_client.Completion("x", llm_client.CompletionUsage(1, 1, 400), True))
        assert budget.tokens_used == 400
        assert budget.steps_used == 2
        assert not budget.exhausted()
        budget.charge(llm_client.Completion("x", llm_client.CompletionUsage(1, 1, 600), False))
        assert budget.exhausted()
        event = budget.event()
        assert event["tokens_used"] == 1000
        assert event["max_tokens"] == 1000
        assert event["max_steps"] == 5
        assert budget.spent().tokens == 1000

    def test_wall_clock(self):
        budget = dashboard_gen.Budget(max_tokens=1000, max_seconds=60, max_steps=5)
        budget.started -= 61
        assert budget.exhausted()
        assert budget.event()["seconds"] >= 61

    def test_cost_is_none_until_a_call_reports_one_then_sums_those(self):
        budget = dashboard_gen.Budget(max_tokens=10_000, max_seconds=60, max_steps=5)
        # Nothing reported: None, not 0.0. "No figure" is not "no money".
        budget.charge(llm_client.Completion("x", llm_client.CompletionUsage(1, 1, 100), False))
        assert budget.event()["cost_usd"] is None
        assert budget.spent().cost_usd is None
        budget.charge(
            llm_client.Completion("x", llm_client.CompletionUsage(1, 1, 100, 0.002), False)
        )
        budget.charge(
            llm_client.Completion("x", llm_client.CompletionUsage(1, 1, 100, 0.001), False)
        )
        # A cached call is free, so its cost is not charged either.
        budget.charge(llm_client.Completion("x", llm_client.CompletionUsage(1, 1, 100, 0.5), True))
        assert budget.event()["cost_usd"] == pytest.approx(0.003)
        assert budget.spent().cost_usd == pytest.approx(0.003)


class TestResponseCost:
    """`_response_cost_usd`: the provider's own figure, or None for every reason."""

    def _response(self, hidden):
        return SimpleNamespace(_hidden_params=hidden)

    def test_reads_the_openrouter_header_litellm_parks(self):
        response = self._response(
            {"additional_headers": {"llm_provider-x-litellm-response-cost": 0.00421}}
        )
        assert llm_client._response_cost_usd(response) == pytest.approx(0.00421)

    def test_a_string_is_still_a_number(self):
        response = self._response(
            {"additional_headers": {"llm_provider-x-litellm-response-cost": "0.5"}}
        )
        assert llm_client._response_cost_usd(response) == 0.5

    @pytest.mark.parametrize(
        "hidden",
        [
            {},
            {"additional_headers": {}},
            {"additional_headers": {"llm_provider-x-litellm-response-cost": None}},
            {"additional_headers": {"llm_provider-x-litellm-response-cost": "free"}},
            # `response_cost` is the racing one a logging handler fills in;
            # it is deliberately not read.
            {"response_cost": 0.9},
        ],
    )
    def test_missing_or_unusable_is_none(self, hidden):
        assert llm_client._response_cost_usd(self._response(hidden)) is None

    def test_a_response_without_hidden_params_is_none(self):
        assert llm_client._response_cost_usd(SimpleNamespace()) is None


class TestRoleBindings:
    """`_role_bindings`: one column per required role, never the same twice."""

    def _suggestion(self, **candidates) -> dict:
        return {"role_candidates": {k: list(v) for k, v in candidates.items()}}

    def test_a_column_taken_by_another_role_advances_to_the_next_candidate(self):
        # The ranker offers the same float to depth and metric; binding it
        # twice makes /advanced_viz/data reject a duplicate column.
        suggestion = self._suggestion(
            sample_id=["individual_id", "species"],
            depth=["bill_depth_mm", "bill_length_mm"],
            metric=["bill_depth_mm", "bill_length_mm"],
        )
        bindings, error = dashboard_gen._role_bindings("rarefaction", suggestion)
        assert error is None
        assert bindings == {
            "sample_id_col": "individual_id",
            "depth_col": "bill_depth_mm",
            "metric_col": "bill_length_mm",
        }
        assert len(set(bindings.values())) == len(bindings)

    def test_a_role_with_no_candidate_left_fails_the_binding(self):
        suggestion = self._suggestion(
            sample_id=["individual_id"], depth=["depth"], metric=["depth"]
        )
        bindings, error = dashboard_gen._role_bindings("rarefaction", suggestion)
        assert bindings == {}
        assert "metric" in error and "already bound" in error

    def test_an_empty_candidate_list_still_reports_the_unfilled_role(self):
        suggestion = self._suggestion(sample_id=["s"], depth=["d"], metric=[])
        bindings, error = dashboard_gen._role_bindings("rarefaction", suggestion)
        assert bindings == {}
        assert "no column of the collection fills the role 'metric'" in error


class TestPlanToTargets:
    def test_modes_and_unknown_collections(self):
        de = de_context()
        plan = _plan(
            _component("intro", "Overview", "text", None),
            _component("volcano", "Analysis", "advanced_viz", "de", viz_kind="volcano"),
            _component("offer", "Analysis", "advanced_viz", "de", use="ivar/manhattan"),
            _component("free", "Analysis", "advanced_viz", "de"),
            _component("ghost", "Analysis", "figure", "not_here"),
            _component("hist", "Analysis", "figure", "de"),
        )
        targets, dropped = dashboard_gen.plan_to_targets(plan, {"de": de})
        assert [(t.planned.tag, t.mode) for t in targets] == [
            ("intro", "text"),
            ("volcano", "advanced_viz"),
            ("offer", "advanced_viz"),
            ("free", "llm"),
            ("hist", "llm"),
        ]
        assert targets[0].ctx is None
        assert targets[1].ctx is de
        (ghost,) = dropped
        assert ghost.tag == "ghost" and ghost.status == "dropped" and ghost.attempts == 0
        assert "not_here" in ghost.error and "de" in ghost.error


class TestFillText:
    def test_header_from_the_section(self):
        plan = _plan(_component("intro", "Overview", "text", None))
        text = dashboard_gen.fill_text(plan.components[0], plan, first=False)
        assert text == {
            "tag": "intro",
            "component_type": "text",
            "title": "Overview",
            "order": 3,
            "body": "Numbers",
        }

    def test_first_text_without_description_takes_the_subtitle(self):
        plan = _plan(_component("intro", "Analysis", "text", None))
        first = dashboard_gen.fill_text(plan.components[0], plan, first=True)
        assert first["title"] == "Analysis"
        assert first["body"] == PENGUINS_PLAN["subtitle"]
        later = dashboard_gen.fill_text(plan.components[0], plan, first=False)
        assert later["body"] == ""

    def test_section_headers_are_added_where_the_plan_has_no_text(self):
        plan = _plan(
            _component("intro", "Overview", "text", None),
            _component("mean_bill", "Overview", "card", "physical"),
            _component("hist", "Analysis", "figure", "physical"),
            _component("rows", "Reference", "table", "demographics"),
        )
        components = [
            {"tag": "intro", "component_type": "text", "title": "Overview"},
            {"tag": "mean_bill", "component_type": "card"},
            {"tag": "hist", "component_type": "figure"},
            {"tag": "rows", "component_type": "table"},
        ]
        headers = dashboard_gen.section_headers(plan, components)
        assert [(h["tag"], h["section"], h["title"]) for h in headers] == [
            ("analysis-header", "Analysis", "Analysis"),
            ("reference-header", "Reference", "Reference"),
        ]
        assert all(h["component_type"] == "text" and h["order"] == 3 for h in headers)
        # A section with no surviving tile gets no header.
        headers = dashboard_gen.section_headers(plan, components[:2])
        assert headers == []


class TestFillAdvancedViz:
    def test_ranked_kind_binds_the_first_candidates(self):
        de = de_context()
        planned = PlannedComponent(
            tag="v",
            section="Analysis",
            component_type="advanced_viz",
            data_collection_tag="de",
            viz_kind="volcano",
        )
        component, warnings, error = dashboard_gen.fill_advanced_viz(planned, de)
        assert error is None and warnings == []
        assert component["tag"] == "v"
        assert component["viz_kind"] == "volcano"
        assert component["config"]["feature_id_col"] == "gene_id"
        assert component["config"]["effect_size_col"] == "log2FoldChange"
        assert component["config"]["significance_col"] == "padj"
        assert component["data_collection_tag"] == "de"
        assert component["workflow_tag"] == WF

    def test_use_handle_expands_through_the_catalog(self):
        de = de_context()
        de.catalog_offers = [
            {
                "tool": "ivar",
                "render_id": "manhattan",
                "title": "Manhattan of variants",
                "component_type": "advanced_viz",
                "dc_tag": "de",
                "description": "",
                "viz_kind": "manhattan",
            }
        ]
        planned = PlannedComponent(
            tag="m",
            section="Analysis",
            component_type="advanced_viz",
            data_collection_tag="de",
            use="ivar/manhattan",
        )
        component, warnings, error = dashboard_gen.fill_advanced_viz(planned, de)
        assert error is None and warnings == []
        assert component["use"] == "ivar/manhattan"
        assert component["viz_kind"] == "manhattan"
        assert component["config"]["chr_col"] == "CHROM"
        assert component["title"] == "Manhattan of variants"

    def test_unknown_use_falls_back_to_the_ranked_kind_with_a_warning(self):
        de = de_context()
        planned = PlannedComponent(
            tag="b",
            section="Analysis",
            component_type="advanced_viz",
            data_collection_tag="de",
            use="nope/nothing",
            viz_kind="volcano",
        )
        component, warnings, error = dashboard_gen.fill_advanced_viz(planned, de)
        assert error is None
        assert component["viz_kind"] == "volcano"
        assert "use" not in component
        assert len(warnings) == 1 and "nope/nothing" in warnings[0]

    def test_unknown_use_without_a_kind_is_an_error(self):
        planned = PlannedComponent(
            tag="x",
            section="Analysis",
            component_type="advanced_viz",
            data_collection_tag="de",
            use="nope/nothing",
        )
        component, warnings, error = dashboard_gen.fill_advanced_viz(planned, de_context())
        assert component is None and warnings == []
        assert "nope/nothing" in error

    def test_kind_the_ranker_did_not_recommend_is_an_error(self):
        planned = PlannedComponent(
            tag="k",
            section="Analysis",
            component_type="advanced_viz",
            data_collection_tag="de",
            viz_kind="sunburst",
        )
        component, _, error = dashboard_gen.fill_advanced_viz(planned, de_context())
        assert component is None
        assert "sunburst" in error and "not a recommended kind" in error


class TestOffers:
    COMPOSE = {
        "modules": [
            {
                "tool_id": "ivar",
                "tool_name": "iVar",
                "matches": [
                    {
                        "dc_id": DE_DC_ID,
                        "dc_tag": "de",
                        "output_id": "ivar_variants_long",
                        "name": "Variants",
                        "description": "Long variant table",
                        "renders_as": [
                            {"id": "manhattan", "component": "advanced_viz", "kind": "manhattan"},
                            {"component": "table"},
                            {"component": "advanced_viz", "kind": "oncoplot"},
                            {"id": "manhattan", "component": "advanced_viz", "kind": "manhattan"},
                        ],
                    }
                ],
            }
        ]
    }

    def test_only_advanced_viz_renders_become_offers(self):
        offers = dashboard_gen.offers_by_dc(self.COMPOSE)
        assert list(offers) == [DE_DC_ID]
        assert [(o["tool"], o["render_id"], o["viz_kind"]) for o in offers[DE_DC_ID]] == [
            ("ivar", "manhattan", "manhattan"),
            ("ivar", "variants_long", "oncoplot"),
        ]
        first = offers[DE_DC_ID][0]
        assert first["component_type"] == "advanced_viz"
        assert first["dc_tag"] == "de"
        assert first["description"] == "Long variant table"
        assert first["title"] == "Manhattan plot of Variants"

    def test_attach_fills_each_collection(self):
        de = de_context()
        other = _dc("other", "4" * 24, {"a": ("Int64", 2)})
        ctx = ProjectDataContext(project_id="p", project_name="P", collections=[de, other])
        assert dashboard_gen.attach_catalog_offers(ctx, self.COMPOSE) == 2
        assert [o["render_id"] for o in de.catalog_offers] == ["manhattan", "variants_long"]
        assert other.catalog_offers == []
        assert dashboard_gen.offers_by_dc({"modules": []}) == {}


class TestBindAndValidate:
    def test_bind_pins_tags_and_fills_column_type(self):
        ctx = penguins_context().collections[0]
        planned = PlannedComponent(
            tag="c", section="Overview", component_type="card", data_collection_tag="physical"
        )
        component = {
            "component_type": "card",
            "workflow_tag": "wrong",
            "data_collection_tag": "wrong",
            "aggregation": "average",
            "column_name": "bill_length_mm",
            "section": "x",
            "layout": {"x": 0},
        }
        dashboard_gen.bind_to_collection(component, planned, ctx)
        assert component["tag"] == "c"
        assert component["workflow_tag"] == WF
        assert component["data_collection_tag"] == "physical"
        assert component["column_type"] == "float64"
        assert "section" not in component and "layout" not in component

    def test_bind_rejects_another_type_or_none(self):
        ctx = penguins_context().collections[0]
        planned = PlannedComponent(
            tag="f", section="Analysis", component_type="figure", data_collection_tag="physical"
        )
        with pytest.raises(ValueError, match="must be 'figure'"):
            dashboard_gen.bind_to_collection({"component_type": "card"}, planned, ctx)
        with pytest.raises(ValueError, match="no component_type"):
            dashboard_gen.bind_to_collection({"::": "not a component"}, planned, ctx)

    def test_empty_figure_is_rejected_by_the_substance_check(self):
        ctx = penguins_context().collections[0]
        planned = PlannedComponent(
            tag="f", section="Analysis", component_type="figure", data_collection_tag="physical"
        )
        component, error = dashboard_gen._Generation._validate_answer(
            _y(component_type="figure", title="Empty"), planned, ctx
        )
        assert component is None
        assert "dict_kwargs is empty" in error
        component, error = dashboard_gen._Generation._validate_answer(
            _figure(*_P, "histogram", x="bill_length_mm"), planned, ctx
        )
        assert error is None
        assert component["dict_kwargs"] == {"x": "bill_length_mm"}
        assert component["tag"] == "f"

    def test_schema_error_names_the_field(self):
        ctx = penguins_context().collections[0]
        component = {
            "tag": "f",
            "component_type": "figure",
            "workflow_tag": WF,
            "data_collection_tag": "physical",
            "visu_type": "histogram",
            "dict_kwargs": {"x": "flipper_length_mm"},
        }
        error = dashboard_gen.schema_error(component, ctx)
        assert error.startswith("Schema check failed:")
        assert "dict_kwargs.x" in error and "flipper_length_mm" in error
        component["dict_kwargs"] = {"x": "bill_length_mm"}
        assert dashboard_gen.schema_error(component, ctx) is None

    def test_validate_component_reports_the_validator_message(self):
        validated, error = dashboard_gen.validate_component(
            {"component_type": "card", "aggregation": "average"}
        )
        assert validated is None
        assert "column_name" in error
        validated, error = dashboard_gen.validate_component(
            {"component_type": "text", "title": "T", "order": 3}
        )
        assert error is None and validated["component_type"] == "text"

    def test_offending_tags_from_an_envelope_error(self):
        components = [
            {"tag": "ok", "component_type": "text", "title": "T"},
            {"tag": "bad", "component_type": "card", "aggregation": "average"},
        ]
        try:
            validate_envelope({"title": "X", "components": components})
        except Exception as e:  # noqa: BLE001
            assert dashboard_gen.offending_tags(e, components) == {"bad"}
        else:  # pragma: no cover
            pytest.fail("the envelope should not validate")


class TestGateHelper:
    def test_project_dc_ids_walks_the_workflows(self):
        ids = dashboard_gen._project_dc_ids(project_doc())
        assert ids == {IRIS_DC_ID, DEMO_DC_ID}
        assert (
            dashboard_gen._project_dc_ids({"workflows": ["junk", {"data_collections": ["x"]}]})
            == set()
        )


class TestEnvelope:
    def test_envelope_keeps_the_plan_section_styling_and_adds_headers(self):
        plan = DashboardPlan(
            title="T",
            filter_sections=[SectionSpec(name="Cohort", icon="mdi:filter-variant", color="teal")],
            grid_sections=[SectionSpec(name="Overview", description="d")],
            components=[
                PlannedComponent(
                    tag="f", section="Cohort", component_type="interactive", data_collection_tag="x"
                ),
                PlannedComponent(
                    tag="c", section="Overview", component_type="card", data_collection_tag="x"
                ),
            ],
        )
        gen = SimpleNamespace(
            plan=plan,
            components=[
                {"tag": "f", "component_type": "interactive", "title": "f"},
                {"tag": "c", "component_type": "card", "title": "c"},
            ],
        )
        envelope = dashboard_gen._Generation.envelope(gen, "T")
        assert envelope["filter_sections"] == [
            {"name": "Cohort", "icon": "mdi:filter-variant", "color": "teal"}
        ]
        assert envelope["grid_sections"] == [{"name": "Overview", "description": "d"}]
        assert [c["tag"] for c in envelope["components"]] == ["f", "overview-header", "c"]
        assert "subtitle" not in envelope
