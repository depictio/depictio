"""`/utils/server-info` and the admin `/utils/version-check` routes over HTTP.

The router is mounted on a bare app with the auth dependencies replaced, so only
the route logic and the real service (on mongomock) run.
"""

from types import SimpleNamespace

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.utils_endpoints import routes as utils_routes
from depictio.api.v1.services import branding as branding_svc
from depictio.api.v1.services import version_check as vc

LOCKED_DETAIL = "Version check is set by DEPICTIO_VERSION_CHECK_ENABLED."

ADMIN = SimpleNamespace(email="admin@example.com", is_admin=True)
MEMBER = SimpleNamespace(email="member@example.com", is_admin=False)


@pytest.fixture()
def world(monkeypatch):
    collection = mongomock.MongoClient()["depictio_test"]["instance_settings"]
    monkeypatch.setattr(branding_svc, "instance_settings_collection", collection)
    monkeypatch.setattr(settings.version_check, "enabled", None)
    monkeypatch.setattr(settings.auth, "single_user_mode", False)
    vc.invalidate_version_check_cache()

    users = {"admin-token": ADMIN, "member-token": MEMBER}

    async def fake_fetch(token):
        return users.get(token)

    monkeypatch.setattr(utils_routes, "_async_fetch_user_from_token", fake_fetch)

    app = FastAPI()
    app.include_router(utils_routes.utils_endpoint_router, prefix="/utils")

    def client_as(user=None):
        app.dependency_overrides.clear()
        if user is not None:
            app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield SimpleNamespace(client_as=client_as, collection=collection)
    vc.invalidate_version_check_cache()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class TestServerInfo:
    def test_anonymous_gets_links_and_no_version_check(self, world):
        response = world.client_as().get("/utils/server-info")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "online"
        assert body["version"]
        assert body["api_version"].startswith("v")
        assert body["repository_url"] == "https://github.com/depictio/depictio"
        assert body["release_notes_url"] == (
            f"https://github.com/depictio/depictio/releases/tag/v{body['version']}"
        )
        assert body["docs_url"] == "https://depictio.github.io/depictio-docs/"
        assert body["version_check"] is None

    def test_bad_token_is_anonymous_not_401(self, world):
        response = world.client_as().get("/utils/server-info", headers=bearer("nope"))
        assert response.status_code == 200
        assert response.json()["version_check"] is None

    def test_non_admin_gets_no_version_check(self, world):
        response = world.client_as().get("/utils/server-info", headers=bearer("member-token"))
        assert response.json()["version_check"] is None

    def test_admin_gets_the_block(self, world):
        response = world.client_as().get("/utils/server-info", headers=bearer("admin-token"))
        block = response.json()["version_check"]
        assert set(block) == {
            "enabled",
            "locked_by_env",
            "update_available",
            "latest_version",
            "release_url",
            "published_at",
            "checked_at",
            "last_error",
        }
        assert block["enabled"] is True
        assert block["update_available"] is False


class TestAdminRoutes:
    @pytest.mark.parametrize(
        "method,path,kwargs",
        [
            ("get", "/utils/version-check", {}),
            ("put", "/utils/version-check", {"json": {"enabled": False}}),
            ("delete", "/utils/version-check", {}),
            ("post", "/utils/version-check/run", {}),
        ],
    )
    def test_non_admin_is_forbidden(self, world, method, path, kwargs):
        response = getattr(world.client_as(MEMBER), method)(path, **kwargs)
        assert response.status_code == 403

    def test_get_returns_the_admin_view(self, world):
        body = world.client_as(ADMIN).get("/utils/version-check").json()
        assert body["enabled"] is True
        assert body["locked_by_env"] is False
        assert body["env_enabled"] is None
        assert body["repository"] == "depictio/depictio"

    def test_put_then_delete_toggles_the_override(self, world):
        client = world.client_as(ADMIN)
        off = client.put("/utils/version-check", json={"enabled": False}).json()
        assert (off["enabled"], off["override"]) == (False, False)
        cleared = client.delete("/utils/version-check").json()
        assert (cleared["enabled"], cleared["override"]) == (True, None)

    def test_put_rejects_a_non_boolean_body(self, world):
        response = world.client_as(ADMIN).put("/utils/version-check", json={"enabled": "maybe"})
        assert response.status_code == 422

    @pytest.mark.parametrize("forced", [True, False])
    def test_put_and_delete_are_409_when_env_locked(self, world, monkeypatch, forced):
        monkeypatch.setattr(settings.version_check, "enabled", forced)
        client = world.client_as(ADMIN)
        for response in (
            client.put("/utils/version-check", json={"enabled": not forced}),
            client.delete("/utils/version-check"),
        ):
            assert response.status_code == 409
            assert response.json() == {"detail": LOCKED_DETAIL}
        view = client.get("/utils/version-check").json()
        assert view["locked_by_env"] is True
        assert view["env_enabled"] is forced
        assert view["enabled"] is forced

    def test_run_is_409_when_disabled(self, world):
        client = world.client_as(ADMIN)
        client.put("/utils/version-check", json={"enabled": False})
        response = client.post("/utils/version-check/run")
        assert response.status_code == 409
        assert response.json() == {"detail": "Version check is disabled."}

    def test_run_forces_a_check_and_returns_the_view(self, world, monkeypatch):
        calls = []

        async def fake_run(*, force=False):
            calls.append(force)
            return vc.admin_view()

        monkeypatch.setattr(vc, "run_version_check", fake_run)
        response = world.client_as(ADMIN).post("/utils/version-check/run")
        assert response.status_code == 200
        assert calls == [True]
        assert response.json()["enabled"] is True
