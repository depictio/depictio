"""Endpoint tests for the review pass over a generated draft: the two
regenerate streams, the review route and the generation history.

Same policy as test_routes_generate.py, whose fixtures this module reuses:
no Mongo, no Delta, no network. The project context builder, the catalog
matcher, the permission checks, the tag resolution and the dashboards
collection are patched at the `dashboard_gen` module boundary, and
`llm_client.completion_with_usage` answers each fill call with the canned
YAML for the tag named in its prompt.

The draft under review is built the way the generator builds one — a lite
envelope through `to_full()` — so its `stored_metadata` carries the real
runtime shape: uuid ids the layout items point at, sections, and the
`ai_source` stamp that names each tile's generation tag.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import yaml
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints import dashboard_gen, generations, llm_client
from depictio.api.v1.endpoints.ai_endpoints.dashboard_plan import normalize_plan, parse_plan
from depictio.api.v1.endpoints.ai_endpoints.dashboard_validate import validate_envelope
from depictio.api.v1.endpoints.ai_endpoints.routes import ai_endpoint_router
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.tests.api.v1.endpoints.ai_endpoints.test_routes_generate import (
    DASHBOARD_ID,
    FAKE_USER,
    IRIS_DC_ID,
    PROJECT_ID,
    TOKENS_PER_CALL,
    WF_IRIS,
    FakeLLM,
    _card,
    _component,
    _FakeProjects,
    _figure,
    _interactive,
    _y,
    iris_context,
    parse_sse,
    project_doc,
)

RUN_ID = "run-1"
WF_ID = "7" * 24
_I = ("iris_table", WF_IRIS)

# The plan the draft was generated from; the run record hands it back so the
# regenerate calls re-use each tile's intent.
PLAN = {
    "title": "Iris overview",
    "subtitle": "Measurements of 150 iris flowers by variety",
    "filter_sections": [{"name": "Cohort", "icon": "mdi:filter-variant"}],
    "grid_sections": [
        {"name": "Cohort", "description": "Headline numbers"},
        {"name": "Measurements", "description": "How they relate"},
    ],
    "components": [
        _component("variety_filter", "Cohort", "interactive", "iris_table"),
        _component("n_flowers", "Cohort", "card", "iris_table"),
        _component(
            "sepal_scatter",
            "Measurements",
            "figure",
            "iris_table",
            intent="how sepal length and width relate",
        ),
        _component("petal_box", "Measurements", "figure", "iris_table"),
    ],
}

# What the draft holds now, in `stored_metadata` order. `petal_box` sits
# under `sepal_scatter` rather than beside it, so a section re-layout is
# visible in the boxes.
DRAFT_COMPONENTS = [
    {
        "tag": "variety_filter",
        "component_type": "interactive",
        "workflow_tag": WF_IRIS,
        "data_collection_tag": "iris_table",
        "title": "variety",
        "interactive_component_type": "MultiSelect",
        "column_name": "variety",
        "column_type": "object",
        "section": "Cohort",
        "layout": {"x": 0, "y": 0, "w": 1, "h": 3},
    },
    {
        "tag": "cohort-header",
        "component_type": "text",
        "title": "Cohort",
        "order": 3,
        "body": "Headline numbers",
        "section": "Cohort",
        "layout": {"x": 0, "y": 0, "w": 8, "h": 1},
    },
    {
        "tag": "n_flowers",
        "component_type": "card",
        "workflow_tag": WF_IRIS,
        "data_collection_tag": "iris_table",
        "title": "count variety",
        "aggregation": "count",
        "column_name": "variety",
        "column_type": "object",
        "section": "Cohort",
        "layout": {"x": 0, "y": 1, "w": 8, "h": 2},
    },
    {
        "tag": "measurements-header",
        "component_type": "text",
        "title": "Measurements",
        "order": 3,
        "body": "How they relate",
        "section": "Measurements",
        "layout": {"x": 0, "y": 0, "w": 8, "h": 1},
    },
    {
        "tag": "sepal_scatter",
        "component_type": "figure",
        "workflow_tag": WF_IRIS,
        "data_collection_tag": "iris_table",
        "title": "scatter",
        "visu_type": "scatter",
        "dict_kwargs": {"x": "sepal.length", "y": "sepal.width"},
        "section": "Measurements",
        "layout": {"x": 0, "y": 1, "w": 8, "h": 5},
    },
    {
        "tag": "petal_box",
        "component_type": "figure",
        "workflow_tag": WF_IRIS,
        "data_collection_tag": "iris_table",
        "title": "box",
        "visu_type": "box",
        "dict_kwargs": {"x": "variety", "y": "petal.length"},
        "section": "Measurements",
        "layout": {"x": 0, "y": 6, "w": 8, "h": 5},
    },
]

# One answer per tag, as the model would re-emit it.
ANSWERS = {
    "variety_filter": [_interactive(*_I, "Select", "variety", "object")],
    "n_flowers": [_card(*_I, "nunique", "variety", "object")],
    "sepal_scatter": [_figure(*_I, "scatter", x="petal.length", y="petal.width", color="variety")],
    "petal_box": [_figure(*_I, "violin", x="variety", y="petal.width")],
}


# ---------------------------------------------------------------------------
# Fixture helpers (plain functions so they can also be driven without pytest)
# ---------------------------------------------------------------------------


def the_plan():
    plan, _ = normalize_plan(parse_plan(PLAN), max_components=16, max_sections=4)
    return plan


def draft_doc(**overrides) -> dict:
    """A persisted AI draft, built the way the generator builds one.

    The lite envelope goes through the real `to_full()`, so every stored
    component carries the uuid its layout item points at and the `ai_source`
    stamp naming its generation tag; the data-bound ones then get the ids
    `_resolve_workflow_tags` would have written.
    """
    components = []
    for component in DRAFT_COMPONENTS:
        component = dict(component)
        component["ai_source"] = {"flow": "generate", "tag": component["tag"]}
        components.append(component)
    lite = validate_envelope(
        {
            "title": "Iris overview",
            "subtitle": PLAN["subtitle"],
            "filter_sections": PLAN["filter_sections"],
            "grid_sections": PLAN["grid_sections"],
            "components": components,
        }
    )
    doc = lite.to_full()
    for stored in doc["stored_metadata"]:
        if stored.get("data_collection_tag"):
            stored["wf_id"] = ObjectId(WF_ID)
            stored["dc_id"] = ObjectId(IRIS_DC_ID)
    doc["dashboard_id"] = ObjectId(DASHBOARD_ID)
    doc["project_id"] = ObjectId(PROJECT_ID)
    doc["permissions"] = {"owners": [], "editors": [], "viewers": []}
    doc["last_saved_ts"] = "2026-01-01 00:00:00"
    doc["ai_generation"] = {
        "status": "draft",
        "model": "m",
        "prompt": "an overview",
        "generated_at": "2026-01-01T00:00:00",
        "run_id": RUN_ID,
        "warnings": [],
        "reviewed": [],
        "dropped": ["petal_hist"],
    }
    doc.update(overrides)
    return doc


def run_record(**overrides) -> generations.GenerationRun:
    run = generations.GenerationRun(
        id=RUN_ID,
        project_id=PROJECT_ID,
        dashboard_id=DASHBOARD_ID,
        prompt="an overview",
        model="m",
        status="complete",
        plan=the_plan().model_dump(mode="json"),
        components=[{"tag": c["tag"], "status": "ok", "attempts": 1} for c in PLAN["components"]],
        created_at="2026-01-01T00:00:00",
    )
    return run.model_copy(update=overrides)


class FakeDashboards:
    """The dashboards collection, applying the `$set` updates it is given."""

    def __init__(self, docs: list[dict]):
        self.docs = list(docs)
        self.updates: list[tuple[dict, dict]] = []

    def find_one(self, query, projection=None):
        oid = query.get("dashboard_id")
        return next((d for d in self.docs if d.get("dashboard_id") == oid), None)

    def find(self, query, projection=None):
        wanted = set((query.get("dashboard_id") or {}).get("$in") or [])
        return [d for d in self.docs if d.get("dashboard_id") in wanted]

    def update_one(self, query, update):
        self.updates.append((query, update))
        doc = self.find_one(query)
        for key, value in (update.get("$set") or {}).items():
            if key.startswith("stored_metadata."):
                doc["stored_metadata"][int(key.split(".", 1)[1])] = value
            elif "." in key:
                head, tail = key.split(".", 1)
                doc.setdefault(head, {})[tail] = value
            else:
                doc[key] = value
        return SimpleNamespace(matched_count=1, modified_count=1)

    @property
    def last_set(self) -> dict:
        return self.updates[-1][1]["$set"]


class RecordingLLM(FakeLLM):
    """`FakeLLM` that also keeps every message list it was handed."""

    def __init__(self, answers: dict[str, list[str]], default: str | None = None):
        super().__init__({}, answers, default=default)
        self.messages: list[list[dict]] = []

    def __call__(self, messages, **kw):
        self.messages.append(messages)
        return super().__call__(messages, **kw)

    def prompt_for(self, tag: str) -> str:
        """The user prompt of the first fill call for `tag`."""
        for messages in self.messages:
            if f"this component's tag: {tag}" in messages[-1]["content"]:
                return messages[-1]["content"]
        raise AssertionError(f"no fill call for '{tag}'")


class Draft:
    """Everything the regenerate flow touches outside the LLM, faked and recorded."""

    def __init__(self, monkeypatch, doc: dict | None = None):
        self.doc = draft_doc() if doc is None else doc
        self.dashboards = FakeDashboards([self.doc])
        self.permission = True
        self.run: generations.GenerationRun | None = run_record()
        self.runs: list[generations.GenerationRun] = []
        self.history_limit: int | None = None

        async def fake_context(project_id, user, dc_ids=None, *, max_collections=6):
            self.context_call = SimpleNamespace(
                project_id=project_id, dc_ids=dc_ids, max_collections=max_collections
            )
            return iris_context(), []

        def fake_resolve(component, project_id):
            self.resolved = component
            if component.get("data_collection_tag"):
                component["wf_id"] = ObjectId(WF_ID)
                component["dc_id"] = ObjectId(IRIS_DC_ID)
                component["dc_config"] = {"data_collection_tag": "iris_table"}

        def fake_list(project_id, limit=20):
            self.history_limit = limit
            return self.runs[:limit]

        monkeypatch.setattr(dashboard_gen, "build_project_data_context", fake_context)
        monkeypatch.setattr(
            dashboard_gen, "compose_offers_for_project", lambda doc: {"modules": []}
        )
        monkeypatch.setattr(dashboard_gen, "dashboards_collection", self.dashboards)
        monkeypatch.setattr(dashboard_gen, "projects_collection", _FakeProjects(project_doc()))
        monkeypatch.setattr(dashboard_gen, "resolve_workflow_tags", fake_resolve)
        monkeypatch.setattr(dashboard_gen, "regenerate_component_fields", lambda component: None)
        monkeypatch.setattr(
            dashboard_gen,
            "check_dashboard_mutation_permission",
            lambda doc, user, perm: self.permission and perm == "editor",
        )
        monkeypatch.setattr(
            dashboard_gen, "check_project_permission", lambda pid, user, perm: self.permission
        )
        monkeypatch.setattr(generations, "get", lambda run_id: self.run)
        monkeypatch.setattr(generations, "list_for_project", fake_list)
        monkeypatch.setattr(settings.ai, "generate_dashboard_enabled", True)
        monkeypatch.setattr(settings.ai, "generate_max_repairs_per_component", 1)
        monkeypatch.setattr(settings.auth, "public_mode", False)
        monkeypatch.setattr(settings.auth, "unauthenticated_mode", False)
        monkeypatch.setattr(settings.auth, "single_user_mode", False)

    # -- reading the draft back --------------------------------------------

    @property
    def stored(self) -> list[dict]:
        return self.doc["stored_metadata"]

    def position_of(self, tag: str) -> int:
        return next(i for i, c in enumerate(self.stored) if dashboard_gen.generation_tag(c) == tag)

    def component(self, tag: str) -> dict:
        return self.stored[self.position_of(tag)]

    def box(self, tag: str) -> dict:
        index = self.component(tag)["index"]
        for key in ("left_panel_layout_data", "right_panel_layout_data"):
            for item in self.doc.get(key) or []:
                if item.get("i") == f"box-{index}":
                    return {k: item[k] for k in ("x", "y", "w", "h")}
        raise AssertionError(f"no layout item for '{tag}'")


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(ai_endpoint_router, prefix="/ai")
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    return TestClient(app)


def regenerate(client, monkeypatch, fake, draft, tag, **body) -> list[tuple[str, dict]]:
    monkeypatch.setattr(llm_client, "completion_with_usage", fake)
    position = draft.position_of(tag)
    r = client.post(
        f"/ai/generated-dashboards/{DASHBOARD_ID}/components/{position}/regenerate", json=body
    )
    assert r.status_code == 200, r.text
    return parse_sse(r.text)


def regenerate_section(client, monkeypatch, fake, section, **body) -> list[tuple[str, dict]]:
    monkeypatch.setattr(llm_client, "completion_with_usage", fake)
    r = client.post(
        f"/ai/generated-dashboards/{DASHBOARD_ID}/sections/{section}/regenerate", json=body
    )
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
def draft(monkeypatch) -> Draft:
    return Draft(monkeypatch)


# ---------------------------------------------------------------------------
# One component
# ---------------------------------------------------------------------------


class TestRegenerateComponent:
    def test_the_tile_is_replaced_in_place(self, client, draft, monkeypatch):
        before = draft.component("sepal_scatter")
        index, section, box = before["index"], before["section"], draft.box("sepal_scatter")
        others = {
            tag: json.dumps(draft.component(tag), default=str)
            for tag in ("variety_filter", "n_flowers", "petal_box", "cohort-header")
        }

        events = regenerate(client, monkeypatch, RecordingLLM(ANSWERS), draft, "sepal_scatter")
        types = [t for t, _ in events]
        assert types[0] == "status"
        assert types[-3:] == ["status", "regenerated", "done"]
        assert types[types.index("component") - 1] == "budget"
        assert "error" not in types

        after = draft.component("sepal_scatter")
        assert after["index"] == index
        assert after["section"] == section
        assert draft.box("sepal_scatter") == box
        assert after["visu_type"] == "scatter"
        assert after["dict_kwargs"] == {
            "x": "petal.length",
            "y": "petal.width",
            "color": "variety",
        }
        assert after["ai_source"]["tag"] == "sepal_scatter"
        # Everything else is byte-for-byte what it was.
        for tag, snapshot in others.items():
            assert json.dumps(draft.component(tag), default=str) == snapshot

    def test_only_that_position_and_the_timestamp_are_written(self, client, draft, monkeypatch):
        position = draft.position_of("sepal_scatter")
        regenerate(client, monkeypatch, RecordingLLM(ANSWERS), draft, "sepal_scatter")
        (query, update) = draft.dashboards.updates[-1]
        assert query == {"dashboard_id": ObjectId(DASHBOARD_ID)}
        assert set(update["$set"]) == {f"stored_metadata.{position}", "last_saved_ts"}
        assert isinstance(update["$set"]["last_saved_ts"], str)
        assert update["$set"]["last_saved_ts"] != "2026-01-01 00:00:00"

    def test_the_events_carry_the_new_component(self, client, draft, monkeypatch):
        position = draft.position_of("sepal_scatter")
        events = regenerate(client, monkeypatch, RecordingLLM(ANSWERS), draft, "sepal_scatter")

        component = _components(events)["sepal_scatter"]
        assert component["status"] == "ok"
        assert component["attempts"] == 1
        assert component["component_type"] == "figure"
        assert component["section"] == "Measurements"

        terminal = _one(events, "regenerated")
        assert terminal["dashboard_id"] == DASHBOARD_ID
        assert terminal["section"] is None
        assert terminal["index"] == position
        assert terminal["tag"] == "sepal_scatter"
        assert terminal["component"]["index"] == draft.component("sepal_scatter")["index"]
        assert terminal["component"]["dict_kwargs"]["x"] == "petal.length"
        assert terminal["components"] == [terminal["component"]]
        # Serialisable end to end: the ids the resolver wrote are strings.
        assert terminal["component"]["dc_id"] == IRIS_DC_ID

    def test_the_budget_event_counts_the_call(self, client, draft, monkeypatch):
        events = regenerate(client, monkeypatch, RecordingLLM(ANSWERS), draft, "sepal_scatter")
        budget = _one(events, "budget")
        assert budget["steps_used"] == 1
        assert budget["tokens_used"] == TOKENS_PER_CALL
        assert budget["max_tokens"] == settings.ai.generate_max_tokens_total

    def test_the_uuid_of_the_tile_addresses_it_too(self, client, draft, monkeypatch):
        monkeypatch.setattr(llm_client, "completion_with_usage", RecordingLLM(ANSWERS))
        index = draft.component("sepal_scatter")["index"]
        r = client.post(
            f"/ai/generated-dashboards/{DASHBOARD_ID}/components/{index}/regenerate", json={}
        )
        assert r.status_code == 200
        assert _components(parse_sse(r.text))["sepal_scatter"]["status"] == "ok"

    def test_the_planned_intent_reaches_the_prompt(self, client, draft, monkeypatch):
        fake = RecordingLLM(ANSWERS)
        regenerate(client, monkeypatch, fake, draft, "sepal_scatter")
        prompt = fake.prompt_for("sepal_scatter")
        assert "how sepal length and width relate" in prompt
        assert 'dashboard: "Iris overview"' in prompt
        assert 'section: "Measurements"' in prompt
        # The other tiles of the draft are named as siblings, this one is not.
        assert "petal_box" in prompt
        assert "already filled in this dashboard: sepal_scatter" not in prompt

    def test_an_instruction_reaches_the_prompt(self, client, draft, monkeypatch):
        fake = RecordingLLM(ANSWERS)
        events = regenerate(
            client,
            monkeypatch,
            fake,
            draft,
            "sepal_scatter",
            instruction="colour it by variety and use the petal columns",
        )
        prompt = fake.prompt_for("sepal_scatter")
        assert "colour it by variety and use the petal columns" in prompt
        assert "how sepal length and width relate" in prompt
        assert _components(events)["sepal_scatter"]["status"] == "ok"
        # The steer becomes the tile's provenance, so the chrome shows it.
        assert (
            draft.component("sepal_scatter")["ai_source"]["prompt"]
            == "colour it by variety and use the petal columns"
        )

    def test_an_instruction_over_500_chars_is_422(self, client, draft):
        r = client.post(
            f"/ai/generated-dashboards/{DASHBOARD_ID}/components/0/regenerate",
            json={"instruction": "x" * 501},
        )
        assert r.status_code == 422

    def test_a_run_that_is_gone_falls_back_to_the_stored_tile(self, client, draft, monkeypatch):
        draft.run = None
        fake = RecordingLLM(ANSWERS)
        events = regenerate(client, monkeypatch, fake, draft, "sepal_scatter")
        # No plan: the intent is rebuilt from the tile's own title.
        prompt = fake.prompt_for("sepal_scatter")
        assert "scatter" in prompt
        assert 'section: "Measurements"' in prompt
        assert _components(events)["sepal_scatter"]["status"] == "ok"
        assert draft.component("sepal_scatter")["dict_kwargs"]["x"] == "petal.length"

    def test_a_repaired_answer_still_lands(self, client, draft, monkeypatch):
        answers = dict(ANSWERS)
        answers["sepal_scatter"] = [
            _figure(*_I, "scatter", x="flipper_length_mm"),
            *ANSWERS["sepal_scatter"],
        ]
        events = regenerate(client, monkeypatch, RecordingLLM(answers), draft, "sepal_scatter")
        component = _components(events)["sepal_scatter"]
        assert component["status"] == "repaired"
        assert component["attempts"] == 2
        assert draft.component("sepal_scatter")["dict_kwargs"]["x"] == "petal.length"

    def test_answers_that_never_validate_leave_the_tile_alone(self, client, draft, monkeypatch):
        before = json.dumps(draft.component("sepal_scatter"), default=str)
        fake = RecordingLLM({}, default=_figure(*_I, "scatter", x="flipper_length_mm"))
        events = regenerate(client, monkeypatch, fake, draft, "sepal_scatter")

        component = _components(events)["sepal_scatter"]
        assert component["status"] == "dropped"
        assert component["attempts"] == 2
        assert "flipper_length_mm" in component["error"]
        types = [t for t, _ in events]
        assert "regenerated" not in types
        assert _one(events, "error")["detail"] == "no component could be regenerated"
        assert types[-1] == "done"
        assert json.dumps(draft.component("sepal_scatter"), default=str) == before
        assert draft.dashboards.updates == []

    def test_an_answer_of_another_type_is_rejected(self, client, draft, monkeypatch):
        fake = RecordingLLM({}, default=_card(*_I, "average", "sepal.length", "float64"))
        events = regenerate(client, monkeypatch, fake, draft, "sepal_scatter")
        component = _components(events)["sepal_scatter"]
        assert component["status"] == "dropped"
        assert "must be 'figure'" in component["error"]
        assert draft.component("sepal_scatter")["visu_type"] == "scatter"

    def test_a_header_is_rewritten_from_the_plan_without_an_llm_call(
        self, client, draft, monkeypatch
    ):
        draft.component("measurements-header")["body"] = "stale"
        fake = RecordingLLM(ANSWERS)
        events = regenerate(client, monkeypatch, fake, draft, "measurements-header")
        assert fake.calls == []
        assert _components(events)["measurements-header"]["status"] == "ok"
        after = draft.component("measurements-header")
        assert after["body"] == "How they relate"
        assert after["title"] == "Measurements"
        # A text tile binds no collection, whatever the draft carried.
        assert not after.get("data_collection_tag")


# ---------------------------------------------------------------------------
# One section
# ---------------------------------------------------------------------------


class TestRegenerateSection:
    def test_every_tile_is_replaced_and_the_boxes_are_re_laid_out(self, client, draft, monkeypatch):
        indices = {
            tag: draft.component(tag)["index"]
            for tag in ("measurements-header", "sepal_scatter", "petal_box")
        }
        events = regenerate_section(client, monkeypatch, RecordingLLM(ANSWERS), "Measurements")

        components = _components(events)
        assert list(components) == ["measurements-header", "sepal_scatter", "petal_box"]
        assert {c["status"] for c in components.values()} == {"ok"}
        assert [t for t, _ in events].count("budget") == 3

        assert draft.component("sepal_scatter")["visu_type"] == "scatter"
        assert draft.component("sepal_scatter")["dict_kwargs"]["color"] == "variety"
        assert draft.component("petal_box")["visu_type"] == "violin"
        assert {tag: draft.component(tag)["index"] for tag in indices} == indices

        # The two figures were stacked full width; the layout pass pairs them
        # under the section header, on section-relative rows.
        assert draft.box("measurements-header") == {"x": 0, "y": 0, "w": 8, "h": 1}
        assert draft.box("sepal_scatter") == {"x": 0, "y": 1, "w": 4, "h": 5}
        assert draft.box("petal_box") == {"x": 4, "y": 1, "w": 4, "h": 5}
        # Nothing outside the section moved.
        assert draft.box("n_flowers") == {"x": 0, "y": 1, "w": 8, "h": 2}
        assert draft.box("variety_filter") == {"x": 0, "y": 0, "w": 1, "h": 3}

    def test_the_terminal_event_lists_the_section(self, client, draft, monkeypatch):
        events = regenerate_section(client, monkeypatch, RecordingLLM(ANSWERS), "Measurements")
        terminal = _one(events, "regenerated")
        assert terminal["section"] == "Measurements"
        assert terminal["index"] is None
        assert terminal["component"] is None
        assert [c["ai_source"]["tag"] for c in terminal["components"]] == [
            "measurements-header",
            "sepal_scatter",
            "petal_box",
        ]
        assert terminal["components"][1]["dict_kwargs"]["x"] == "petal.length"

    def test_the_written_positions_are_the_sections_own(self, client, draft, monkeypatch):
        positions = {
            draft.position_of(t) for t in ("measurements-header", "sepal_scatter", "petal_box")
        }
        regenerate_section(client, monkeypatch, RecordingLLM(ANSWERS), "Measurements")
        written = draft.dashboards.last_set
        assert {int(k.split(".", 1)[1]) for k in written if k.startswith("stored_metadata.")} == (
            positions
        )
        assert "right_panel_layout_data" in written
        assert "left_panel_layout_data" not in written

    def test_one_failing_tile_keeps_its_stored_version(self, client, draft, monkeypatch):
        before = json.dumps(draft.component("petal_box"), default=str)
        answers = dict(ANSWERS)
        answers["petal_box"] = [_figure(*_I, "violin", x="flipper_length_mm")]
        events = regenerate_section(client, monkeypatch, RecordingLLM(answers), "Measurements")

        components = _components(events)
        assert components["sepal_scatter"]["status"] == "ok"
        assert components["petal_box"]["status"] == "dropped"
        assert json.dumps(draft.component("petal_box"), default=str) == before
        assert draft.component("sepal_scatter")["dict_kwargs"]["x"] == "petal.length"
        assert _one(events, "regenerated")["section"] == "Measurements"
        assert [t for t, _ in events][-1] == "done"

    def test_a_filter_section_re_lays_the_left_panel(self, client, draft, monkeypatch):
        regenerate_section(client, monkeypatch, RecordingLLM(ANSWERS), "Cohort")
        written = draft.dashboards.last_set
        assert "left_panel_layout_data" in written
        assert draft.component("variety_filter")["interactive_component_type"] == "Select"
        assert draft.component("n_flowers")["aggregation"] == "nunique"
        assert draft.box("variety_filter") == {"x": 0, "y": 0, "w": 1, "h": 3}
        assert draft.box("cohort-header") == {"x": 0, "y": 0, "w": 8, "h": 1}
        assert draft.box("n_flowers") == {"x": 0, "y": 1, "w": 8, "h": 2}

    def test_an_instruction_reaches_every_tile_of_the_section(self, client, draft, monkeypatch):
        fake = RecordingLLM(ANSWERS)
        regenerate_section(
            client, monkeypatch, fake, "Measurements", instruction="use the petal columns"
        )
        for tag in ("sepal_scatter", "petal_box"):
            assert "use the petal columns" in fake.prompt_for(tag)


# ---------------------------------------------------------------------------
# Review bookkeeping
# ---------------------------------------------------------------------------


def review(client, tag: str, action: str = "keep"):
    return client.post(
        f"/ai/generated-dashboards/{DASHBOARD_ID}/review", json={"tag": tag, "action": action}
    )


class TestReview:
    def test_keep_then_unkeep(self, client, draft):
        r = review(client, "sepal_scatter")
        assert r.status_code == 200
        assert r.json() == {"reviewed": 1, "total": 6}
        assert draft.doc["ai_generation"]["reviewed"] == ["sepal_scatter"]

        assert review(client, "petal_box").json() == {"reviewed": 2, "total": 6}
        assert draft.doc["ai_generation"]["reviewed"] == ["sepal_scatter", "petal_box"]

        # Keeping the same tile twice does not double-count it.
        assert review(client, "petal_box").json() == {"reviewed": 2, "total": 6}

        assert review(client, "sepal_scatter", "unkeep").json() == {"reviewed": 1, "total": 6}
        assert draft.doc["ai_generation"]["reviewed"] == ["petal_box"]

    def test_a_tag_that_is_no_longer_stored_is_dropped(self, client, draft):
        draft.doc["ai_generation"]["reviewed"] = ["sepal_scatter", "deleted_tile"]
        assert review(client, "petal_box").json() == {"reviewed": 2, "total": 6}
        assert draft.doc["ai_generation"]["reviewed"] == ["sepal_scatter", "petal_box"]

    def test_keeping_an_unknown_tag_changes_nothing(self, client, draft):
        assert review(client, "not_a_tile").json() == {"reviewed": 0, "total": 6}
        assert draft.doc["ai_generation"]["reviewed"] == []

    def test_total_counts_only_generated_tiles(self, client, draft):
        draft.stored.append({"index": "hand-made", "component_type": "card", "section": "Cohort"})
        assert review(client, "sepal_scatter").json() == {"reviewed": 1, "total": 6}

    def test_unkeep_after_a_delete_still_answers(self, client, draft):
        draft.doc["ai_generation"]["reviewed"] = ["petal_box"]
        del draft.stored[draft.position_of("petal_box")]
        assert review(client, "petal_box", "unkeep").json() == {"reviewed": 0, "total": 5}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class TestHistory:
    def _runs(self, draft, n: int):
        draft.runs = [
            run_record(
                id=f"run-{i}",
                created_at=f"2026-01-{30 - i:02d}T00:00:00",
                dashboard_id=DASHBOARD_ID if i == 0 else None,
                components=[
                    {"tag": "a", "status": "ok"},
                    {"tag": "b", "status": "repaired"},
                    {"tag": "c", "status": "dropped"},
                    {"tag": "d", "status": "ok"},
                ],
                warnings=[f"warning {i}"],
            )
            for i in range(n)
        ]

    def test_rows_carry_the_counts_and_the_title(self, client, draft):
        self._runs(draft, 3)
        r = client.get(f"/ai/generations/{PROJECT_ID}")
        assert r.status_code == 200
        rows = r.json()["generations"]
        assert [row["id"] for row in rows] == ["run-0", "run-1", "run-2"]
        assert rows[0]["title"] == "Iris overview"
        assert rows[0]["dashboard_id"] == DASHBOARD_ID
        assert rows[1]["title"] is None
        assert (rows[0]["ok"], rows[0]["repaired"], rows[0]["dropped"]) == (2, 1, 1)
        assert rows[0]["prompt"] == "an overview"
        assert rows[0]["status"] == "complete"
        assert rows[0]["warnings"] == ["warning 0"]
        # The history is a list, not a draft: no YAML, no plan.
        assert "yaml" not in rows[0] and "plan" not in rows[0]

    def test_the_limit_is_defaulted_and_capped(self, client, draft):
        self._runs(draft, 3)
        client.get(f"/ai/generations/{PROJECT_ID}")
        assert draft.history_limit == 20
        client.get(f"/ai/generations/{PROJECT_ID}?limit=2")
        assert draft.history_limit == 2
        assert len(client.get(f"/ai/generations/{PROJECT_ID}?limit=2").json()["generations"]) == 2
        client.get(f"/ai/generations/{PROJECT_ID}?limit=500")
        assert draft.history_limit == dashboard_gen.MAX_GENERATION_HISTORY

    def test_permission_and_unknown_project(self, client, draft):
        draft.permission = False
        assert client.get(f"/ai/generations/{PROJECT_ID}").status_code == 403
        draft.permission = True
        assert client.get(f"/ai/generations/{ObjectId()}").status_code == 404
        assert client.get("/ai/generations/not-an-id").status_code == 400


# ---------------------------------------------------------------------------
# Gates (real HTTP codes, before the stream)
# ---------------------------------------------------------------------------


class TestGates:
    def _post(self, client, path: str, **body):
        return client.post(f"/ai/generated-dashboards/{DASHBOARD_ID}/{path}", json=body)

    def test_dashboard_without_ai_generation_is_404(self, client, monkeypatch):
        draft = Draft(monkeypatch, draft_doc(ai_generation=None))
        assert self._post(client, "components/0/regenerate").status_code == 404
        assert self._post(client, "sections/Cohort/regenerate").status_code == 404
        assert self._post(client, "review", tag="n_flowers").status_code == 404
        assert draft.dashboards.updates == []

    def test_unknown_dashboard_is_404_and_a_bad_id_400(self, client, draft):
        r = client.post(f"/ai/generated-dashboards/{ObjectId()}/components/0/regenerate", json={})
        assert r.status_code == 404
        r = client.post("/ai/generated-dashboards/not-an-id/components/0/regenerate", json={})
        assert r.status_code == 400

    def test_non_editor_is_403(self, client, draft, monkeypatch):
        draft.permission = False
        fake = RecordingLLM(ANSWERS)
        monkeypatch.setattr(llm_client, "completion_with_usage", fake)
        assert self._post(client, "components/0/regenerate").status_code == 403
        assert self._post(client, "sections/Cohort/regenerate").status_code == 403
        assert self._post(client, "review", tag="n_flowers").status_code == 403
        assert fake.calls == []
        assert draft.dashboards.updates == []

    def test_a_bad_component_index_is_404(self, client, draft):
        assert self._post(client, "components/99/regenerate").status_code == 404
        assert self._post(client, "components/not-a-tile/regenerate").status_code == 404
        assert self._post(client, "components/-1/regenerate").status_code == 404

    def test_an_unknown_section_is_404(self, client, draft):
        assert self._post(client, "sections/Nowhere/regenerate").status_code == 404

    def test_the_feature_flag_gates_the_regenerates(self, client, draft, monkeypatch):
        monkeypatch.setattr(settings.ai, "generate_dashboard_enabled", False)
        assert self._post(client, "components/0/regenerate").status_code == 404
        assert self._post(client, "sections/Cohort/regenerate").status_code == 404

    def test_public_mode_is_403(self, client, draft, monkeypatch):
        monkeypatch.setattr(settings.auth, "public_mode", True)
        assert self._post(client, "components/0/regenerate").status_code == 403

    def test_gates_run_before_any_llm_call(self, client, draft, monkeypatch):
        fake = RecordingLLM(ANSWERS)
        monkeypatch.setattr(llm_client, "completion_with_usage", fake)
        self._post(client, "sections/Nowhere/regenerate")
        assert fake.calls == []
        assert draft.dashboards.updates == []


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_generation_tag_reads_the_stamp_then_the_tag(self):
        assert dashboard_gen.generation_tag({"ai_source": {"tag": "a"}, "tag": "b"}) == "a"
        assert dashboard_gen.generation_tag({"tag": "b"}) == "b"
        assert dashboard_gen.generation_tag({"ai_source": "junk"}) == ""
        assert dashboard_gen.generation_tag({}) == ""

    def test_ai_source_stamp_leaves_an_empty_prompt_out(self):
        assert dashboard_gen.ai_source_stamp("a") == {"flow": "generate", "tag": "a"}
        assert dashboard_gen.ai_source_stamp("a", "why")["prompt"] == "why"

    def test_planned_for_prefers_the_plan_entry(self):
        plan = the_plan()
        stored = {"component_type": "figure", "title": "scatter", "section": "Measurements"}
        planned = dashboard_gen.planned_for(stored, tag="sepal_scatter", plan=plan)
        assert planned.intent == "how sepal length and width relate"
        assert planned.data_collection_tag == "iris_table"

    def test_planned_for_rebuilds_from_the_tile(self):
        stored = {
            "component_type": "card",
            "title": "count variety",
            "description": "how many rows",
            "section": "Cohort",
            "data_collection_tag": "iris_table",
            "index": "abc",
        }
        planned = dashboard_gen.planned_for(stored, tag="", plan=None)
        assert planned.tag == "abc"
        assert planned.component_type == "card"
        assert planned.intent == "count variety. how many rows"
        assert planned.data_collection_tag == "iris_table"

    def test_target_for_picks_the_fill_mode(self):
        ctx = iris_context().collections[0]
        contexts = {"iris_table": ctx}
        plan = the_plan()
        figure = dashboard_gen.planned_for({}, tag="sepal_scatter", plan=plan)
        target = dashboard_gen.target_for({}, figure, contexts)
        assert (target.mode, target.ctx) == ("llm", ctx)

        text = dashboard_gen.planned_for(
            {"component_type": "text", "title": "T"}, tag="h", plan=None
        )
        assert dashboard_gen.target_for({}, text, contexts).mode == "text"

        viz = dashboard_gen.planned_for(
            {"component_type": "advanced_viz", "title": "V", "viz_kind": "volcano"},
            tag="v",
            plan=None,
        )
        assert dashboard_gen.target_for({}, viz, contexts).mode == "advanced_viz"
        # A collection the project no longer has leaves the target unbound.
        assert dashboard_gen.target_for({}, figure, {}).ctx is None

    def test_locate_component_and_section(self):
        doc = draft_doc()
        assert dashboard_gen.locate_component(doc, "2") == 2
        index = doc["stored_metadata"][4]["index"]
        assert dashboard_gen.locate_component(doc, index) == 4
        with pytest.raises(Exception, match="No component"):
            dashboard_gen.locate_component(doc, "42")
        assert dashboard_gen.locate_section(doc, "Measurements") == [3, 4, 5]
        with pytest.raises(Exception, match="No section"):
            dashboard_gen.locate_section(doc, "Nowhere")

    def test_review_counts_intersects_with_the_document(self):
        doc = draft_doc()
        kept, total = dashboard_gen.review_counts(doc, ["n_flowers", "gone", "n_flowers"])
        assert kept == ["n_flowers"]
        assert total == 6

    def test_bind_standalone_clears_the_bindings(self):
        planned = dashboard_gen.planned_for(
            {"component_type": "text", "title": "T"}, tag="h", plan=None
        )
        component = dashboard_gen.bind_standalone(
            {
                "component_type": "text",
                "title": "T",
                "workflow_tag": WF_IRIS,
                "data_collection_tag": "iris_table",
                "layout": {"x": 0},
                "section": "x",
            },
            planned,
        )
        assert component["tag"] == "h"
        assert component["workflow_tag"] == ""
        assert component["data_collection_tag"] == ""
        assert "layout" not in component and "section" not in component
        with pytest.raises(ValueError, match="must be 'text'"):
            dashboard_gen.bind_standalone({"component_type": "card"}, planned)

    def test_validate_answer_without_a_collection(self):
        planned = dashboard_gen.planned_for(
            {"component_type": "text", "title": "T"}, tag="h", plan=None
        )
        component, error = dashboard_gen.validate_answer(
            _y(component_type="text", title="Cohort", order=3, body="Headline"), planned, None
        )
        assert error is None
        assert component["tag"] == "h"
        assert component["body"] == "Headline"

    def test_fill_intent_appends_the_instruction(self):
        ctx = iris_context().collections[0]
        planned = dashboard_gen.planned_for({}, tag="sepal_scatter", plan=the_plan())
        assert dashboard_gen.fill_intent(planned, ctx, None) == planned.intent
        steered = dashboard_gen.fill_intent(planned, ctx, "  make it a box  ")
        assert steered.startswith(planned.intent)
        assert steered.endswith("make it a box")
        empty = dashboard_gen.planned_for(
            {"component_type": "table", "title": ""}, tag="t", plan=None
        )
        assert "table" in dashboard_gen.fill_intent(empty, ctx, None)

    def test_relayout_section_only_returns_what_changed(self):
        doc = draft_doc()
        components = doc["stored_metadata"]
        layouts = dashboard_gen.relayout_section(components, [3, 4, 5], doc)
        assert list(layouts) == ["right_panel_layout_data"]
        boxes = {item["i"]: item for item in layouts["right_panel_layout_data"]}
        scatter = boxes[f"box-{components[4]['index']}"]
        assert (scatter["x"], scatter["y"], scatter["w"], scatter["h"]) == (0, 1, 4, 5)
        # The untouched sections keep their own boxes.
        card = boxes[f"box-{components[2]['index']}"]
        assert (card["x"], card["y"]) == (0, 1)

    def test_stored_component_keeps_the_id_and_the_section(self, monkeypatch):
        monkeypatch.setattr(dashboard_gen, "resolve_workflow_tags", lambda c, p: None)
        monkeypatch.setattr(dashboard_gen, "regenerate_component_fields", lambda c: None)
        component = yaml.safe_load(_figure(*_I, "violin", x="variety", y="petal.width"))
        component["ai_source"] = {"flow": "generate", "tag": "petal_box"}
        stored = dashboard_gen.stored_component(
            component, project_id=ObjectId(PROJECT_ID), index="keep-me", section="Measurements"
        )
        assert stored["index"] == "keep-me"
        assert stored["section"] == "Measurements"
        assert stored["visu_type"] == "violin"
        assert stored["ai_source"]["tag"] == "petal_box"
        assert "tag" not in stored
