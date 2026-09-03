"""The YAML import route and ``_persist_lite_dashboard`` write the same document.

The persistence tail of ``import_dashboard_from_yaml`` was extracted so the AI
dashboard generator can land a draft through the exact path a CLI import
takes. These tests pin that equivalence on the bundled iris overview
dashboard, plus the two things the helper adds on top: ``extra_fields`` (the
generator's ``ai_generation`` stamp) and the 409 on a title collision.

Mongo is mongomock, patched onto the module attributes the route and its
helper chain read (``dashboards_collection`` / ``projects_collection``), the
way ``test_dashboard_save_timestamps.py`` does. The project document is a
minimal cut of ``depictio/projects/init/iris/project.yaml``: one workflow, one
table DC, so tag resolution and the self-adapting pruning both run for real.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.models.models.dashboards import DashboardData, DashboardDataLite
from depictio.models.models.users import UserBase

REPO_ROOT = Path(__file__).resolve().parents[6]
IRIS_YAML = REPO_ROOT / "depictio" / "projects" / "init" / "iris" / "dashboards" / "overview.yaml"

# Ids and names from depictio/projects/init/iris/project.yaml.
PROJECT_ID = ObjectId("646b0f3c1e4a2d7f8e5b8c9a")
WORKFLOW_ID = ObjectId("646b0f3c1e4a2d7f8e5b8c9b")
DC_ID = ObjectId("646b0f3c1e4a2d7f8e5b8c9c")
PROJECT_NAME = "Iris Dataset Project Data Analysis"

PINNED_NOW = "2026-01-01 10:00:00"

# The route reads three settings: the two auth-mode gates and the viewer URL
# echoed in the payload. `is_public_mode` is a computed property, so the module
# attribute is swapped for a namespace rather than mutated in place.
FAKE_SETTINGS = SimpleNamespace(
    auth=SimpleNamespace(is_public_mode=False, is_single_user_mode=False),
    viewer=SimpleNamespace(external_url="http://viewer.test"),
)

AI_STAMP = {
    "status": "draft",
    "model": "claude-sonnet-4-5",
    "prompt": "An overview of the iris measurements",
    "generated_at": "2026-01-01T10:00:00+00:00",
    # Deliberately not 24 hex chars: `MongoModel.mongo()` turns any
    # ObjectId-looking string into an ObjectId on the way in.
    "run_id": "run-3f9c1a7e",
    "warnings": ["Dropped 1 component: budget"],
}


def _project_doc(owner: UserBase) -> dict:
    return {
        "_id": PROJECT_ID,
        "name": PROJECT_NAME,
        "is_public": False,
        "permissions": {
            "owners": [{"_id": ObjectId(str(owner.id)), "email": owner.email}],
            "editors": [],
            "viewers": [],
        },
        "workflows": [
            {
                "_id": WORKFLOW_ID,
                "name": "iris_workflow",
                "engine": {"name": "python"},
                "data_collections": [
                    {
                        "_id": DC_ID,
                        "data_collection_tag": "iris_table",
                        "description": "Iris dataset in CSV format",
                        "config": {
                            "type": "Table",
                            "metatype": "Metadata",
                            "dc_specific_properties": {"format": "CSV"},
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture
def owner() -> UserBase:
    u = UserBase(id=ObjectId(), email="owner@example.com")
    u.is_anonymous = False
    return u


@pytest.fixture
def iris_yaml() -> str:
    return IRIS_YAML.read_text()


@contextmanager
def _stack(owner: UserBase):
    """A fresh mongomock database holding the iris project, wired into the route module."""
    database = mongomock.MongoClient()["depictio_test"]
    database["projects"].insert_one(_project_doc(owner))
    with (
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(dash_routes, "settings", FAKE_SETTINGS),
        patch.object(dash_routes, "utc_now_str", lambda: PINNED_NOW),
    ):
        yield database


def _pin_uuid4(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic component indices.

    `to_full()` mints one uuid4 per component and `_regenerate_component_indices`
    mints another for every uuid-like index. Both code paths draw from the same
    sequence, so replaying it makes their documents comparable.
    """
    counter = iter(range(1, 10_000))
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(counter)))


def _run_route(owner: UserBase, yaml_text: str, **kwargs):
    """The route as the CLI drives it: project resolved from the YAML's project_tag."""
    return asyncio.run(
        dash_routes.import_dashboard_from_yaml(yaml_content=yaml_text, current_user=owner, **kwargs)
    )


def _persist(owner: UserBase, yaml_text: str, **kwargs):
    # Parse per call: nothing in the tail may depend on a lite object's history.
    return dash_routes._persist_lite_dashboard(
        DashboardDataLite.from_yaml(yaml_text), PROJECT_ID, owner, **kwargs
    )


def _comparable(doc: dict) -> dict:
    """Strip what is minted per call and cannot be pinned from outside.

    `_id` and `dashboard_id` are fresh ObjectIds, `creation_time` derives from
    the latter, and `to_full()` stamps each component with a wall-clock
    `last_updated`. Everything else, resolved ids, layout, permissions,
    timestamps, must match exactly.
    """
    out = dict(doc)
    for key in ("_id", "dashboard_id", "creation_time"):
        assert out.pop(key, None), f"{key} must be set on the stored document"
    out["stored_metadata"] = [
        {k: v for k, v in component.items() if k != "last_updated"}
        for component in out["stored_metadata"]
    ]
    return out


class TestRouteAndHelperAgree:
    def test_same_document_and_payload(self, owner, iris_yaml, monkeypatch):
        with _stack(owner) as via_route:
            _pin_uuid4(monkeypatch)
            route_payload = _run_route(owner, iris_yaml)
            route_doc = via_route["dashboards"].find_one({})

        with _stack(owner) as via_helper:
            _pin_uuid4(monkeypatch)
            helper_payload = _persist(owner, iris_yaml)
            helper_doc = via_helper["dashboards"].find_one({})

        assert route_doc is not None and helper_doc is not None
        assert _comparable(route_doc) == _comparable(helper_doc)

        # Sanity: the helper chain really ran against the project document.
        bound = [c for c in helper_doc["stored_metadata"] if c.get("data_collection_tag")]
        assert bound, "iris overview has data-bound components"
        assert all(str(c["dc_id"]) == str(DC_ID) for c in bound)
        assert all(str(c["wf_id"]) == str(WORKFLOW_ID) for c in bound)
        assert helper_doc["last_saved_ts"] == PINNED_NOW
        assert helper_doc["version"] == 1
        assert helper_doc["is_public"] is False

        # The payloads differ only by the freshly minted id.
        assert route_payload.pop("dashboard_id") != helper_payload.pop("dashboard_id")
        assert route_payload == helper_payload
        assert route_payload == {
            "success": True,
            "updated": False,
            "message": "Dashboard imported successfully",
            "title": "Iris Dataset Analysis",
            "project_id": str(PROJECT_ID),
            "dash_url": "http://viewer.test",
        }

    def test_route_still_runs_its_gates_before_the_tail(self, owner, iris_yaml):
        """The extraction moved persistence only; the permission gate stayed in the route."""
        stranger = UserBase(id=ObjectId(), email="stranger@example.com")
        stranger.is_anonymous = False
        with _stack(owner) as db, pytest.raises(HTTPException) as exc:
            _run_route(stranger, iris_yaml)
        assert exc.value.status_code == 403
        assert db["dashboards"].count_documents({}) == 0


class TestExtraFields:
    def test_ai_generation_lands_on_the_document_and_loads(self, owner, iris_yaml):
        with _stack(owner) as db:
            payload = _persist(owner, iris_yaml, extra_fields={"ai_generation": AI_STAMP})
            doc = db["dashboards"].find_one({"dashboard_id": ObjectId(payload["dashboard_id"])})

        assert doc is not None
        assert doc["ai_generation"] == AI_STAMP

        loaded = DashboardData.from_mongo(doc)
        assert loaded.ai_generation is not None
        assert loaded.ai_generation.status == "draft"
        assert loaded.ai_generation.model_dump() == AI_STAMP

    def test_without_extra_fields_no_stamp_is_written(self, owner, iris_yaml):
        with _stack(owner) as db:
            payload = _persist(owner, iris_yaml)
            doc = db["dashboards"].find_one({"dashboard_id": ObjectId(payload["dashboard_id"])})

        assert doc is not None
        assert doc.get("ai_generation") is None
        assert DashboardData.from_mongo(doc).ai_generation is None

    def test_extra_fields_are_validated_like_the_rest(self, owner, iris_yaml):
        """An unknown key is a 400 from the model, never a stray field in Mongo."""
        with _stack(owner) as db, pytest.raises(HTTPException) as exc:
            _persist(owner, iris_yaml, extra_fields={"not_a_dashboard_field": 1})
        assert exc.value.status_code == 400
        assert db["dashboards"].count_documents({}) == 0

    def test_invalid_stamp_is_a_400(self, owner, iris_yaml):
        with _stack(owner) as db, pytest.raises(HTTPException) as exc:
            _persist(
                owner,
                iris_yaml,
                extra_fields={"ai_generation": {**AI_STAMP, "status": "pending"}},
            )
        assert exc.value.status_code == 400
        assert db["dashboards"].count_documents({}) == 0


class TestTitleCollision:
    def test_second_persist_without_overwrite_is_a_409(self, owner, iris_yaml):
        with _stack(owner) as db:
            _persist(owner, iris_yaml)
            with pytest.raises(HTTPException) as exc:
                _persist(owner, iris_yaml)
            assert exc.value.status_code == 409
            assert db["dashboards"].count_documents({}) == 1

    def test_route_reports_the_same_409(self, owner, iris_yaml):
        with _stack(owner):
            _run_route(owner, iris_yaml)
            with pytest.raises(HTTPException) as exc:
                _run_route(owner, iris_yaml)
        assert exc.value.status_code == 409

    def test_overwrite_replaces_in_place(self, owner, iris_yaml):
        """Same dashboard_id, bumped version, one document. The stamp rides along
        only when passed again: overwrite replaces the whole document."""
        with _stack(owner) as db:
            first = _persist(owner, iris_yaml, extra_fields={"ai_generation": AI_STAMP})
            second = _persist(
                owner, iris_yaml, overwrite=True, extra_fields={"ai_generation": AI_STAMP}
            )
            doc = db["dashboards"].find_one({})
            assert db["dashboards"].count_documents({}) == 1

        assert second["updated"] is True
        assert second["dashboard_id"] == first["dashboard_id"]
        assert doc is not None
        assert doc["version"] == 2
        assert doc["ai_generation"] == AI_STAMP
