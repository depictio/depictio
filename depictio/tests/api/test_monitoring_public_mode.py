"""Who may read the monitoring API on a public instance.

A public instance has real admins who sign in, so the Log & Task views must
open for them; the temporary guests it mints, and demo deployments, stay out.
"""

from __future__ import annotations

from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _user(*, admin: bool, temporary: bool = False) -> SimpleNamespace:
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
    monkeypatch.setattr(store, "ingestion_runs_collection", db.ingestion_runs)
    monkeypatch.setattr(store, "cli_agents_collection", db.cli_agents)
    monkeypatch.setattr(settings.monitoring, "enabled", True)
    monkeypatch.setattr(settings.auth, "single_user_mode", False)
    monkeypatch.setattr(settings.auth, "unauthenticated_mode", False)
    monkeypatch.setattr(settings.auth, "public_mode", True)
    monkeypatch.setattr(settings.auth, "demo_mode", False)

    app = FastAPI()
    app.include_router(routes.monitoring_endpoint_router, prefix="/monitoring")
    who = {"user": None}
    app.dependency_overrides[user_routes.get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def get_as(user):
        who["user"] = user
        return client.get("/monitoring/ingestion")

    return SimpleNamespace(get_as=get_as, settings=settings, monkeypatch=monkeypatch)


def test_a_signed_in_admin_reads_monitoring_on_a_public_instance(api):
    assert api.get_as(_user(admin=True)).status_code == 200


def test_a_temporary_guest_does_not(api):
    assert api.get_as(_user(admin=True, temporary=True)).status_code == 403


def test_a_non_admin_does_not(api):
    assert api.get_as(_user(admin=False)).status_code == 403


def test_demo_mode_still_refuses_everyone(api):
    api.monkeypatch.setattr(api.settings.auth, "demo_mode", True)
    assert api.get_as(_user(admin=True)).status_code == 404


def test_single_user_mode_is_always_allowed(api):
    api.monkeypatch.setattr(api.settings.auth, "demo_mode", True)
    api.monkeypatch.setattr(api.settings.auth, "single_user_mode", True)
    assert api.get_as(_user(admin=True)).status_code == 200
