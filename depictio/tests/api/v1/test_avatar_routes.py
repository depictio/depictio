"""`/auth/me/avatar` routes over HTTP, plus the avatar keys on `/auth/me/optional`.

The auth router is mounted on a bare app with the user dependency replaced, so
only the route logic and the real service (on mongomock) run.
"""

import io
from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.services import avatars


def _png(size=(300, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (20, 120, 200)).save(out, format="PNG")
    return out.getvalue()


def _user(**flags):
    return SimpleNamespace(
        id=ObjectId(),
        email="jane.doe@example.com",
        is_admin=False,
        is_anonymous=False,
        is_temporary=False,
        **flags,
    )


@pytest.fixture()
def world(monkeypatch):
    collection = mongomock.MongoClient()["depictio_test"]["user_avatars"]
    monkeypatch.setattr(avatars, "user_avatars_collection", collection)
    monkeypatch.setattr(settings.auth, "demo_mode", False)

    app = FastAPI()
    app.include_router(user_routes.auth_endpoint_router, prefix="/auth")

    def client_as(user=None):
        app.dependency_overrides.clear()
        if user is not None:
            app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    return SimpleNamespace(client_as=client_as, collection=collection)


def _upload(client, data: bytes, name="me.png", content_type="image/png"):
    return client.put("/auth/me/avatar", files={"file": (name, data, content_type)})


class TestRoundTrip:
    def test_404_when_none(self, world):
        assert world.client_as(_user()).get("/auth/me/avatar").status_code == 404

    def test_upload_get_delete(self, world):
        client = world.client_as(_user())
        response = _upload(client, _png())
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "upload"
        assert body["provider"] is None
        assert body["updated_at"] and "+" not in body["updated_at"]

        got = client.get("/auth/me/avatar")
        assert got.status_code == 200
        assert got.headers["content-type"] == "image/webp"
        assert got.headers["cache-control"] == "private, max-age=300"
        with Image.open(io.BytesIO(got.content)) as image:
            assert image.size == (avatars.AVATAR_SIZE, avatars.AVATAR_SIZE)
        assert got.content != _png()

        deleted = client.delete("/auth/me/avatar")
        assert deleted.status_code == 200
        assert deleted.json() == {"success": True, "removed": True}
        assert client.get("/auth/me/avatar").status_code == 404
        assert client.delete("/auth/me/avatar").json()["removed"] is False

    def test_pictures_are_per_user(self, world):
        _upload(world.client_as(_user()), _png())
        assert world.client_as(_user()).get("/auth/me/avatar").status_code == 404


class TestRejections:
    def test_over_5mb_is_413(self, world):
        too_big = b"\x00" * (avatars.MAX_INPUT_BYTES + 1)
        assert _upload(world.client_as(_user()), too_big).status_code == 413

    def test_not_an_image_is_415(self, world):
        response = _upload(world.client_as(_user()), b"hello", "me.png", "image/png")
        assert response.status_code == 415
        assert "image" in response.json()["detail"].lower()

    def test_anonymous_is_refused(self, world):
        user = _user()
        user.is_anonymous = True
        client = world.client_as(user)
        assert _upload(client, _png()).status_code == 403
        assert client.delete("/auth/me/avatar").status_code == 403

    def test_temporary_is_refused(self, world):
        user = _user()
        user.is_temporary = True
        response = _upload(world.client_as(user), _png())
        assert response.status_code == 403
        assert "temporary" in response.json()["detail"].lower()

    def test_demo_mode_is_refused(self, world, monkeypatch):
        monkeypatch.setattr(settings.auth, "demo_mode", True)
        response = _upload(world.client_as(_user()), _png())
        assert response.status_code == 403
        assert "demo" in response.json()["detail"].lower()

    def test_unauthenticated_is_401(self, world):
        assert world.client_as().get("/auth/me/avatar").status_code == 401


@pytest.mark.asyncio
class TestAuthStatusPayload:
    async def test_payload_carries_avatar_keys(self, world, monkeypatch):
        user = _user()
        avatars.set_uploaded_avatar(user.id, _png())

        async def fake_fetch(token):
            return user

        monkeypatch.setattr(user_routes, "_async_fetch_user_from_token", fake_fetch)
        body = await user_routes.get_current_user_info_optional(token="t")
        assert body["user"]["avatar_updated_at"]
        assert body["user"]["avatar_source"] == "upload"

    async def test_no_picture_is_null(self, world, monkeypatch):
        user = _user()

        async def fake_fetch(token):
            return user

        monkeypatch.setattr(user_routes, "_async_fetch_user_from_token", fake_fetch)
        body = await user_routes.get_current_user_info_optional(token="t")
        assert body["user"]["avatar_updated_at"] is None
