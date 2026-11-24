"""No API response body may carry a user's bcrypt ``password`` hash.

``User`` holds the hash for login and password change, but it must never be
serialized into a response — directly (``GET /auth/me`` and the api-key-gated
``fetch_user`` lookups) or nested (the ``user`` object ``POST /auth/register``
returns). The ``User`` model serializer drops it on every JSON serialization
path; these tests pin that contract over HTTP on an app mirroring production's
``CustomJSONResponse``, and pin the internal side (attribute access,
Python-mode dumps, Beanie persistence) that keeps login and DB saves working.

The hash below is a syntactically bcrypt-shaped placeholder — no real hash is
ever written in this module.
"""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beanie import init_beanie
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from pymongo.asynchronous.database import AsyncDatabase

from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_current_user,
    get_user_or_anonymous,
)
from depictio.api.v1.json_response import CustomJSONResponse
from depictio.models.models.users import TokenBeanie, UserBeanie

FAKE_HASH = "$2b$12$" + "f" * 53

# The profile fields the React viewer reads off /auth/me (see
# ``fetchCurrentUserFull`` in depictio-react-core); they must survive the
# password removal untouched.
PROFILE_FIELDS = (
    "id",
    "email",
    "is_admin",
    "is_anonymous",
    "is_temporary",
    "registration_date",
    "last_login",
    "display_name",
)


@pytest.fixture(autouse=True)
def _beanie_initialized():
    """Beanie document settings must exist before a ``UserBeanie`` is built.

    Every DB-touching helper in the routes under test is patched, so the
    documents are in-memory only; a throwaway mongomock-backed init suffices.
    The setup runs outside any event loop (mongomock is loop-agnostic).
    """
    client = AsyncMongoMockClient()
    asyncio.run(
        init_beanie(
            database=cast(AsyncDatabase, client.test_db),
            document_models=[UserBeanie, TokenBeanie],
        )
    )
    yield


def _user(**overrides: Any) -> UserBeanie:
    defaults: dict[str, Any] = {
        "email": "jane.doe@example.org",
        "password": FAKE_HASH,
        "is_admin": True,
        "is_anonymous": False,
        "is_temporary": False,
        "registration_date": "2026-01-01 00:00:00",
        "last_login": "2026-01-01 00:00:00",
    }
    defaults.update(overrides)
    return UserBeanie(**defaults)


def _session_token(user: UserBeanie) -> TokenBeanie:
    return TokenBeanie(
        user_id=user.id,
        access_token="Abcdefgh12345678",
        refresh_token="R3freshToken987654",
        token_lifetime="short-lived",
        expire_datetime=datetime.now() + timedelta(hours=1),
        refresh_expire_datetime=datetime.now() + timedelta(days=1),
        name="jane.doe@example.org_session",
    )


def _assert_no_password(node: Any) -> None:
    """Recursively fail on a ``password`` key anywhere in a JSON payload."""
    if isinstance(node, dict):
        for key, value in node.items():
            assert key != "password", f"leaked the password key under {key!r}"
            _assert_no_password(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_password(item)


@pytest.fixture()
def app() -> FastAPI:
    # Production answers through CustomJSONResponse (default_response_class in
    # depictio/api/main.py); the tests exercise the same serialization path.
    application = FastAPI(default_response_class=CustomJSONResponse)
    application.include_router(user_routes.auth_endpoint_router, prefix="/auth")
    return application


@pytest.fixture()
def client_for(app: FastAPI):
    def factory(user: UserBeanie) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_user_or_anonymous] = lambda: user
        return TestClient(app)

    return factory


# ---------------------------------------------------------------------------
# Model-level contract
# ---------------------------------------------------------------------------


class TestModelSerializer:
    def test_json_mode_dumps_drop_the_hash(self):
        user = _user()
        assert "password" not in user.model_dump(mode="json")
        # Key check, not a substring check: ``must_change_password`` contains
        # the word but is not the hash field.
        _assert_no_password(json.loads(user.model_dump_json()))

    def test_python_mode_and_attribute_keep_it_for_internal_use(self):
        user = _user()
        # Login and edit_password read the hash off the attribute / a
        # Python-mode dump; only JSON responses must lose it.
        assert user.password == FAKE_HASH
        assert user.model_dump()["password"] == FAKE_HASH

    def test_the_profile_fields_the_viewer_reads_stay(self):
        body = _user().model_dump(mode="json")
        for key in PROFILE_FIELDS:
            assert key in body, f"/auth/me lost the {key!r} field the viewer reads"


class TestBeaniePersistence:
    @pytest.mark.asyncio
    async def test_the_hash_is_still_written_to_the_database(self):
        """The JSON-mode serializer must not touch the Beanie write path.

        Beanie encodes documents by iterating the model's fields itself, so
        the hash round-trips even though JSON serialization drops it.
        """
        user = _user()
        await user.create()

        stored = await UserBeanie.get(user.id)
        assert stored is not None
        assert stored.password == FAKE_HASH


# ---------------------------------------------------------------------------
# HTTP-level contract (routes that return user objects)
# ---------------------------------------------------------------------------


class TestAuthMe:
    def test_no_password_in_the_response(self, client_for):
        response = client_for(_user()).get("/auth/me")

        assert response.status_code == 200
        body = response.json()
        _assert_no_password(body)
        assert FAKE_HASH not in response.text
        assert body["email"] == "jane.doe@example.org"

    def test_the_fields_the_viewer_reads_stay(self, client_for):
        body = client_for(_user()).get("/auth/me").json()
        for key in PROFILE_FIELDS:
            assert key in body, f"/auth/me lost the {key!r} field the viewer reads"


class TestRegister:
    def test_the_returned_user_object_has_no_password(self, app):
        created = _user(email="new.person@example.org")
        mock_settings = MagicMock()
        mock_settings.auth.is_single_user_mode = False
        mock_settings.auth.is_public_mode = False
        mock_settings.auth.registration_disabled = False
        mock_settings.auth.is_password_login_disabled = False

        with (
            patch.object(user_routes, "settings", mock_settings),
            patch.object(user_routes, "enforce_rate_limit"),
            patch.object(
                user_routes,
                "_create_user_in_db",
                AsyncMock(
                    return_value={
                        "success": True,
                        "message": "User created successfully",
                        "user": created,
                    }
                ),
            ),
        ):
            response = TestClient(app).post(
                "/auth/register",
                json={"email": "new.person@example.org", "password": "Start-1234"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        # The user object stays in the payload (existing callers may read it);
        # only its hash must go.
        assert body["user"]["email"] == "new.person@example.org"
        _assert_no_password(body)
        assert FAKE_HASH not in response.text


class TestFetchUserByApiKey:
    """The internal-API-key lookups return full users — still without a hash."""

    def test_from_token(self, app, client_for):
        user = _user()
        with (
            patch.object(user_routes, "_is_valid_internal_api_key", lambda key: True),
            patch.object(
                user_routes, "_async_fetch_user_from_token", new=AsyncMock(return_value=user)
            ),
        ):
            response = client_for(user).get(
                "/auth/fetch_user/from_token",
                params={"token": "test_token"},
                headers={"api-key": "irrelevant"},
            )

        assert response.status_code == 200
        _assert_no_password(response.json())
        assert FAKE_HASH not in response.text

    def test_from_email(self, app, client_for):
        user = _user()
        with (
            patch.object(user_routes, "_is_valid_internal_api_key", lambda key: True),
            patch.object(
                user_routes, "_async_fetch_user_from_email", new=AsyncMock(return_value=user)
            ),
        ):
            response = client_for(user).get(
                "/auth/fetch_user/from_email",
                params={"email": user.email},
                headers={"api-key": "irrelevant"},
            )

        assert response.status_code == 200
        _assert_no_password(response.json())
        assert FAKE_HASH not in response.text

    def test_from_id(self, app, client_for):
        user = _user()
        with (
            patch.object(user_routes, "_is_valid_internal_api_key", lambda key: True),
            patch.object(
                user_routes, "_async_fetch_user_from_id", new=AsyncMock(return_value=user)
            ),
        ):
            response = client_for(user).get(
                "/auth/fetch_user/from_id",
                params={"user_id": str(user.id)},
                headers={"api-key": "irrelevant"},
            )

        assert response.status_code == 200
        _assert_no_password(response.json())
        assert FAKE_HASH not in response.text


class TestLogin:
    def test_valid_credentials_return_a_token_without_a_hash(self, app):
        user = _user()
        mock_settings = MagicMock()
        mock_settings.auth.is_single_user_mode = False
        mock_settings.auth.is_public_mode = False
        mock_settings.auth.is_password_login_disabled = False

        with (
            patch.object(user_routes, "settings", mock_settings),
            patch.object(user_routes, "enforce_rate_limit"),
            patch.object(user_routes, "_check_password", new=AsyncMock(return_value=True)),
            patch.object(
                user_routes, "_async_fetch_user_from_email", new=AsyncMock(return_value=user)
            ),
            patch.object(
                user_routes, "_add_token", new=AsyncMock(return_value=_session_token(user))
            ),
        ):
            response = TestClient(app).post(
                "/auth/login", data={"username": user.email, "password": "Start-1234"}
            )

        assert response.status_code == 200
        body = response.json()
        _assert_no_password(body)
        assert FAKE_HASH not in response.text
        assert body["access_token"] == "Abcdefgh12345678"

    def test_invalid_credentials_still_fail_with_401(self, app):
        user = _user()
        mock_settings = MagicMock()
        mock_settings.auth.is_single_user_mode = False
        mock_settings.auth.is_public_mode = False
        mock_settings.auth.is_password_login_disabled = False

        with (
            patch.object(user_routes, "settings", mock_settings),
            patch.object(user_routes, "enforce_rate_limit"),
            patch.object(user_routes, "_check_password", new=AsyncMock(return_value=False)),
        ):
            response = TestClient(app).post(
                "/auth/login", data={"username": user.email, "password": "wrong"}
            )

        assert response.status_code == 401


class TestUserList:
    def test_the_admin_user_list_has_no_password(self, app, client_for):
        class _FakeFindAll:
            async def to_list(self):
                return [_user(), _user(email="bob@example.org")]

        class _FakeUserBeanie:
            @staticmethod
            def find_all():
                return _FakeFindAll()

        with patch.object(user_routes, "UserBeanie", _FakeUserBeanie):
            response = client_for(_user()).get("/auth/list")

        assert response.status_code == 200
        body = response.json()
        assert {item["email"] for item in body} == {
            "jane.doe@example.org",
            "bob@example.org",
        }
        _assert_no_password(body)
        assert FAKE_HASH not in response.text


class TestMeOptional:
    def test_the_spa_boot_payload_has_no_password(self, app, client_for):
        user = _user()
        with (
            patch.object(
                user_routes, "_async_fetch_user_from_token", new=AsyncMock(return_value=user)
            ),
            patch.object(
                user_routes,
                "avatar_service",
                SimpleNamespace(
                    get_avatar_meta=lambda uid: {}, avatar_updated_at_iso=lambda d: None
                ),
            ),
        ):
            response = client_for(user).get(
                "/auth/me/optional", headers={"Authorization": "Bearer test_token"}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["user"] is not None
        _assert_no_password(body)
        assert FAKE_HASH not in response.text
        assert body["user"]["email"] == "jane.doe@example.org"
