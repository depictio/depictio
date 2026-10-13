"""Who may write an ingestion-run record, and what other people see of it.

Run ids are not secret: the project's ingestion history lists them to every
viewer, anonymous ones included on a public project. ``start`` upserted by a
client-supplied ``run_id`` and accepted any ``project_id``, and ``finish`` and
``step`` checked nothing, so any signed-in user could rewrite someone else's
run or file fake runs under any project.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASE = "/monitoring/ingestion"


def _user(*, admin: bool = False) -> SimpleNamespace:
    uid = ObjectId()
    return SimpleNamespace(id=uid, email=f"{uid}@example.org", is_admin=admin, is_anonymous=False)


@pytest.fixture
def api(monkeypatch):
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.monitoring_endpoints import routes
    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
    from depictio.api.v1.monitoring import publish, store

    db = mongomock.MongoClient().db
    monkeypatch.setattr(store, "ingestion_runs_collection", db.ingestion_runs)
    monkeypatch.setattr(store, "cli_agents_collection", db.cli_agents)
    monkeypatch.setattr(dash_routes, "projects_collection", db.projects)
    monkeypatch.setattr(settings.monitoring, "enabled", True)
    monkeypatch.setattr(publish, "publish_ingestion_event", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "allow_step_update", lambda _run_id: True)

    owner, editor, viewer, stranger, admin = (
        _user(),
        _user(),
        _user(),
        _user(),
        _user(admin=True),
    )
    project_id = ObjectId()
    db.projects.insert_one(
        {
            "_id": project_id,
            "is_public": True,
            "permissions": {
                "owners": [{"_id": owner.id}],
                "editors": [{"_id": editor.id}],
                "viewers": [{"_id": viewer.id}],
            },
        }
    )

    app = FastAPI()
    app.include_router(routes.monitoring_endpoint_router, prefix="/monitoring")
    who = {"user": owner}
    app.dependency_overrides[user_routes.get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def as_user(user):
        who["user"] = user
        return client

    return SimpleNamespace(
        as_user=as_user,
        runs=db.ingestion_runs,
        agents=db.cli_agents,
        project_id=str(project_id),
        owner=owner,
        editor=editor,
        viewer=viewer,
        stranger=stranger,
        admin=admin,
    )


def _start(api, user, **body):
    return api.as_user(user).post(f"{BASE}/start", json={"command": "ingest", **body})


def _step(status: str = "running") -> dict:
    return {"step": {"name": "scan", "status": status, "detail": "scanning"}}


class TestStart:
    def test_the_cli_call_without_ids_still_opens_a_run(self, api):
        # What the CLI actually sends: no run_id, no project_id.
        response = _start(api, api.owner)

        assert response.status_code == 200
        run = api.runs.find_one({"run_id": response.json()["run_id"]})
        assert run["user_id"] == str(api.owner.id)

    def test_an_existing_run_of_another_user_is_not_overwritten(self, api):
        run_id = _start(api, api.owner).json()["run_id"]

        response = _start(api, api.stranger, run_id=run_id, project_name="hijacked")

        assert response.status_code == 403
        assert api.runs.find_one({"run_id": run_id})["user_id"] == str(api.owner.id)

    def test_reopening_your_own_run_is_allowed(self, api):
        run_id = _start(api, api.owner).json()["run_id"]

        assert _start(api, api.owner, run_id=run_id).status_code == 200

    @pytest.mark.parametrize("role", ["owner", "editor", "admin"])
    def test_writers_may_file_a_run_under_the_project(self, api, role):
        response = _start(api, getattr(api, role), project_id=api.project_id)

        assert response.status_code == 200

    @pytest.mark.parametrize("role", ["viewer", "stranger"])
    def test_readers_may_not_file_a_run_under_the_project(self, api, role):
        # The project is public, so a stranger can read it; reading is not enough.
        response = _start(api, getattr(api, role), project_id=api.project_id)

        assert response.status_code == 403
        assert api.runs.count_documents({}) == 0

    def test_a_malformed_project_id_is_refused(self, api):
        assert _start(api, api.owner, project_id="not-an-id").status_code == 403


class TestFinishAndStep:
    @pytest.fixture
    def run_id(self, api):
        return _start(api, api.owner).json()["run_id"]

    def test_the_owner_may_report_steps_and_finish(self, api, run_id):
        client = api.as_user(api.owner)

        assert client.post(f"{BASE}/{run_id}/step", json=_step()).status_code == 200
        response = client.post(f"{BASE}/{run_id}/finish", json={"status": "success"})

        assert response.status_code == 200
        assert api.runs.find_one({"run_id": run_id})["status"] == "success"

    def test_another_user_may_not_report_a_step(self, api, run_id):
        response = api.as_user(api.stranger).post(f"{BASE}/{run_id}/step", json=_step())

        assert response.status_code == 403
        assert not api.runs.find_one({"run_id": run_id}).get("steps")

    def test_another_user_may_not_finish_the_run(self, api, run_id):
        response = api.as_user(api.stranger).post(
            f"{BASE}/{run_id}/finish", json={"status": "failed", "error": "forged"}
        )

        assert response.status_code == 403
        assert api.runs.find_one({"run_id": run_id})["status"] == "running"

    def test_an_admin_may_close_a_run(self, api, run_id):
        response = api.as_user(api.admin).post(
            f"{BASE}/{run_id}/finish", json={"status": "interrupted"}
        )

        assert response.status_code == 200

    def test_an_unknown_run_is_404(self, api):
        response = api.as_user(api.owner).post(f"{BASE}/nope/step", json=_step())

        assert response.status_code == 404

    def test_finish_drops_a_project_the_caller_may_not_write(self, api):
        """Start without a project, finish with one: the injection path."""
        run_id = _start(api, api.stranger).json()["run_id"]

        response = api.as_user(api.stranger).post(
            f"{BASE}/{run_id}/finish", json={"status": "success", "project_id": api.project_id}
        )

        assert response.status_code == 200
        assert api.runs.find_one({"run_id": run_id}).get("project_id") is None

    def test_finish_files_the_run_under_a_writable_project(self, api, run_id):
        api.as_user(api.owner).post(
            f"{BASE}/{run_id}/finish", json={"status": "success", "project_id": api.project_id}
        )

        assert api.runs.find_one({"run_id": run_id})["project_id"] == api.project_id


@pytest.fixture
def far_from_utc(monkeypatch: pytest.MonkeyPatch):
    """Run with a local clock 14 hours ahead of UTC."""
    import time

    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_agent_expiry_is_naive_utc(api, far_from_utc):
    """The agents' TTL index is evaluated in UTC.

    Stamped with a local clock, a watcher under ``depictio local up`` west of
    UTC was deleted about a minute after each heartbeat, and here would live
    14 hours past its death.
    """
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.monitoring import store

    before = datetime.now(timezone.utc).replace(tzinfo=None)
    response = api.as_user(api.owner).post(
        "/monitoring/agents/heartbeat", json={"agent_id": "host:1:p"}
    )
    assert response.status_code == 200
    agent_id = response.json()["agent_id"]

    agent = api.agents.find_one({"agent_id": agent_id})
    ttl = max(60, settings.monitoring.agent_ttl_seconds)
    assert abs((agent["heartbeat_at"] - before).total_seconds()) < 60
    assert abs((agent["expires_at"] - before).total_seconds() - ttl) < 60

    store.request_cli_agent_run(agent_id, requested_by="a@example.org")
    requested = api.agents.find_one({"agent_id": agent_id})["run_requested_at"]
    assert abs((requested - before).total_seconds()) < 60
