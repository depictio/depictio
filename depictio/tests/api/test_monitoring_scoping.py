"""What a non-admin user reads of the tasks, ingestion runs and agents ledgers.

The monitoring read views used to be admin-only. They now open to every real
user on a multi-user instance, scoped to the projects the user can access:
owners and editors read a project's rows in full, plain viewers read a redacted
version, and a stranger sees nothing of it (and a 404, not a 403, on a single
row). Server-wide logs and health stay admin-only.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASE = "/monitoring"


def _user(*, admin: bool = False, temporary: bool = False) -> SimpleNamespace:
    uid = ObjectId()
    return SimpleNamespace(
        id=uid,
        email=f"{uid}@example.org",
        is_admin=admin,
        is_temporary=temporary,
        is_anonymous=False,
    )


@pytest.fixture
def api(monkeypatch):
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.monitoring_endpoints import routes
    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
    from depictio.api.v1.monitoring import store

    db = mongomock.MongoClient().db
    monkeypatch.setattr(store, "task_events_collection", db.task_events)
    monkeypatch.setattr(store, "ingestion_runs_collection", db.ingestion_runs)
    monkeypatch.setattr(store, "cli_agents_collection", db.cli_agents)
    monkeypatch.setattr(routes, "projects_collection", db.projects)
    monkeypatch.setattr(routes, "groups_collection", db.groups)
    monkeypatch.setattr(settings.monitoring, "enabled", True)
    monkeypatch.setattr(settings.auth, "single_user_mode", False)
    monkeypatch.setattr(settings.auth, "unauthenticated_mode", False)
    monkeypatch.setattr(settings.auth, "public_mode", False)
    monkeypatch.setattr(settings.auth, "demo_mode", False)

    owner, editor, viewer, stranger, admin = (
        _user(),
        _user(),
        _user(),
        _user(),
        _user(admin=True),
    )
    mine, other = ObjectId(), ObjectId()
    db.projects.insert_many(
        [
            {
                "_id": mine,
                "is_public": False,
                "permissions": {
                    "owners": [{"_id": owner.id}],
                    "editors": [{"_id": editor.id}],
                    "viewers": [{"_id": viewer.id}],
                },
            },
            {
                "_id": other,
                "is_public": False,
                "permissions": {"owners": [{"_id": ObjectId()}], "editors": [], "viewers": []},
            },
        ]
    )
    now = datetime.now()
    db.task_events.insert_many(
        [
            {
                "task_id": "t-mine",
                "status": "failure",
                "project_id": str(mine),
                "args_repr": "SECRET-ARGS",
                "traceback": "SECRET-TB",
                "logs": ["SECRET-LOG"],
                "worker": "host1",
                "error": "boom",
                "updated_at": now,
            },
            {
                "task_id": "t-other",
                "status": "success",
                "project_id": str(other),
                "updated_at": now,
            },
            {"task_id": "t-none", "status": "success", "updated_at": now},
            {
                "task_id": "t-stranger-own",
                "status": "success",
                "user_id": str(stranger.id),
                "updated_at": now,
            },
        ]
    )
    db.ingestion_runs.insert_many(
        [
            {
                "run_id": "r-mine",
                "status": "success",
                "project_id": str(mine),
                "user_id": str(owner.id),
                "email": "owner@example.org",
                "command_line": "depictio ingest --secret",
                "data_root": "/home/alice/data",
                "started_at": now,
            },
            {
                "run_id": "r-other",
                "status": "success",
                "project_id": str(other),
                "user_id": str(ObjectId()),
                "started_at": now,
            },
        ]
    )
    db.cli_agents.insert_many(
        [
            {
                "agent_id": "a-mine",
                "project_id": str(mine),
                "user_id": str(owner.id),
                "hostname": "login1",
                "heartbeat_at": now,
            },
            {
                "agent_id": "a-other",
                "project_id": str(other),
                "user_id": str(ObjectId()),
                "hostname": "login2",
                "heartbeat_at": now,
            },
        ]
    )

    app = FastAPI()
    app.include_router(routes.monitoring_endpoint_router, prefix=BASE)
    who = {"user": owner}
    app.dependency_overrides[user_routes.get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def as_user(user):
        who["user"] = user
        return client

    return SimpleNamespace(
        as_user=as_user,
        settings=settings,
        monkeypatch=monkeypatch,
        owner=owner,
        editor=editor,
        viewer=viewer,
        stranger=stranger,
        admin=admin,
    )


def _ids(response, key, field):
    assert response.status_code == 200, response.text
    return {row[field] for row in response.json()[key]}


class TestTasks:
    def test_the_owner_sees_the_tasks_of_their_project_only(self, api):
        response = api.as_user(api.owner).get(f"{BASE}/tasks")

        assert _ids(response, "tasks", "task_id") == {"t-mine"}

    def test_a_stranger_sees_none_of_them(self, api):
        response = api.as_user(api.stranger).get(f"{BASE}/tasks")

        # Only the task they queued themselves.
        assert _ids(response, "tasks", "task_id") == {"t-stranger-own"}

    def test_a_stranger_gets_404_on_a_foreign_task(self, api):
        client = api.as_user(api.stranger)

        assert client.get(f"{BASE}/tasks/t-mine").status_code == 404
        assert client.get(f"{BASE}/tasks/t-none").status_code == 404
        assert client.get(f"{BASE}/tasks/t-stranger-own").status_code == 200

    def test_an_editor_reads_the_task_in_full(self, api):
        task = api.as_user(api.editor).get(f"{BASE}/tasks/t-mine").json()

        assert task["traceback"] == "SECRET-TB"
        assert task["args_repr"] == "SECRET-ARGS"
        assert task["logs"] == ["SECRET-LOG"]
        assert "redacted" not in task

    def test_a_viewer_reads_it_redacted(self, api):
        client = api.as_user(api.viewer)

        task = client.get(f"{BASE}/tasks/t-mine").json()
        listed = client.get(f"{BASE}/tasks").json()["tasks"][0]

        for row in (task, listed):
            assert row["redacted"] is True
            assert row["status"] == "failure"
            assert row["error"] == "boom"
            for field in ("traceback", "args_repr", "logs", "worker"):
                assert field not in row

    def test_an_admin_sees_every_task(self, api):
        response = api.as_user(api.admin).get(f"{BASE}/tasks")

        assert _ids(response, "tasks", "task_id") == {
            "t-mine",
            "t-other",
            "t-none",
            "t-stranger-own",
        }


class TestIngestion:
    def test_the_owner_sees_the_runs_of_their_project_in_full(self, api):
        response = api.as_user(api.owner).get(f"{BASE}/ingestion")

        assert _ids(response, "runs", "run_id") == {"r-mine"}
        assert response.json()["runs"][0]["command_line"] == "depictio ingest --secret"

    def test_a_stranger_sees_no_run_and_gets_404_on_a_foreign_one(self, api):
        client = api.as_user(api.stranger)

        assert client.get(f"{BASE}/ingestion").json() == {"runs": []}
        assert client.get(f"{BASE}/ingestion/r-mine").status_code == 404

    def test_a_viewer_reads_the_run_redacted(self, api):
        client = api.as_user(api.viewer)

        run = client.get(f"{BASE}/ingestion/r-mine").json()
        listed = client.get(f"{BASE}/ingestion").json()["runs"][0]

        for row in (run, listed):
            assert row["redacted"] is True
            assert row["status"] == "success"
            for field in ("command_line", "data_root", "email", "user_id"):
                assert field not in row

    def test_a_project_filter_cannot_widen_the_scope(self, api):
        response = api.as_user(api.viewer).get(f"{BASE}/ingestion", params={"project_id": "x"})
        assert response.json() == {"runs": []}

        other = api.as_user(api.viewer).get(f"{BASE}/ingestion", params={"status": "success"})
        assert _ids(other, "runs", "run_id") == {"r-mine"}

    def test_an_admin_sees_every_run(self, api):
        response = api.as_user(api.admin).get(f"{BASE}/ingestion")

        assert _ids(response, "runs", "run_id") == {"r-mine", "r-other"}


class TestAgents:
    def test_scoped_to_the_callers_projects(self, api):
        assert _ids(api.as_user(api.owner).get(f"{BASE}/agents"), "agents", "agent_id") == {
            "a-mine"
        }
        assert api.as_user(api.stranger).get(f"{BASE}/agents").json() == {"agents": []}
        assert _ids(api.as_user(api.admin).get(f"{BASE}/agents"), "agents", "agent_id") == {
            "a-mine",
            "a-other",
        }

    def test_a_viewer_does_not_see_where_the_watcher_runs(self, api):
        agent = api.as_user(api.viewer).get(f"{BASE}/agents").json()["agents"][0]

        assert agent["redacted"] is True
        assert "hostname" not in agent
        assert api.as_user(api.owner).get(f"{BASE}/agents").json()["agents"][0]["hostname"] == (
            "login1"
        )


class TestStillAdminOnly:
    @pytest.mark.parametrize("path", ["/logs", "/logs/level", "/health"])
    def test_server_wide_views_stay_closed_to_non_admins(self, api, path):
        assert api.as_user(api.owner).get(f"{BASE}{path}").status_code == 403

    def test_an_admin_still_reads_the_log_level(self, api):
        assert api.as_user(api.admin).get(f"{BASE}/logs/level").status_code == 200


class TestModes:
    def test_public_mode_refuses_non_admins_and_temporary_guests(self, api):
        api.monkeypatch.setattr(api.settings.auth, "public_mode", True)

        assert api.as_user(api.owner).get(f"{BASE}/tasks").status_code == 403
        assert api.as_user(_user(temporary=True)).get(f"{BASE}/ingestion").status_code == 403
        assert (
            api.as_user(_user(admin=True, temporary=True)).get(f"{BASE}/tasks").status_code == 403
        )
        assert api.as_user(api.admin).get(f"{BASE}/tasks").status_code == 200

    def test_demo_mode_refuses_everyone(self, api):
        api.monkeypatch.setattr(api.settings.auth, "demo_mode", True)

        assert api.as_user(api.owner).get(f"{BASE}/tasks").status_code == 404
        assert api.as_user(api.admin).get(f"{BASE}/ingestion").status_code == 404

    def test_a_temporary_user_is_refused(self, api):
        assert api.as_user(_user(temporary=True)).get(f"{BASE}/tasks").status_code == 403

    def test_single_user_mode_is_always_allowed(self, api):
        api.monkeypatch.setattr(api.settings.auth, "demo_mode", True)
        api.monkeypatch.setattr(api.settings.auth, "public_mode", True)
        api.monkeypatch.setattr(api.settings.auth, "single_user_mode", True)

        assert api.as_user(api.admin).get(f"{BASE}/tasks").status_code == 200


class TestExtractRefs:
    def test_project_id_from_kwargs(self):
        from depictio.api.v1.monitoring.task_signals import _extract_refs

        refs = _extract_refs(
            {"project_id": ObjectId("5f1f1f1f1f1f1f1f1f1f1f1f"), "run_id": "r1"}, ()
        )

        assert refs == {"project_id": "5f1f1f1f1f1f1f1f1f1f1f1f", "run_id": "r1"}

    def test_ids_from_a_dict_first_argument(self):
        from depictio.api.v1.monitoring.task_signals import _extract_refs

        payload = {"project_id": "p1", "run_id": "r1", "dc_id": "d1", "user_id": "u1"}

        assert _extract_refs({}, (payload,)) == payload

    def test_a_user_named_by_a_current_user_entry(self):
        from depictio.api.v1.monitoring.task_signals import _extract_refs

        assert _extract_refs(None, ({"project_id": "p1", "user": {"id": "u9"}},))["user_id"] == "u9"

    def test_nothing_is_invented(self):
        from depictio.api.v1.monitoring.task_signals import _extract_refs

        assert _extract_refs(None, None) == {}
        assert _extract_refs({"other": 1}, ("not-a-dict",)) == {}
        assert _extract_refs({"dashboard_id": "d"}, ()) == {"dashboard_id": "d"}
