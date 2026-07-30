"""CORS preflight for the export routes.

A cross-origin conditional GET is preflighted, because ``If-None-Match`` is not a
CORS-safelisted request header. The global ``CORSMiddleware`` reads a different
(credentialed, usually empty) allowlist and answers 400, so before
``EmbedPreflightMiddleware`` existed every export response carried an ETag that no
browser could ever send back. The endpoint's whole caching story was unusable from
the one context it is built for.

These mount the real middleware stack in the same order ``api/main.py`` does, since
ordering is the substance of the fix: registered last means consulted first.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.export_endpoints.routes import (
    export_endpoint_router,
    get_embed_user,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User

API_PREFIX = "/depictio/api/v1/export"
DASHBOARD_ID = "507f1f77bcf86cd799439099"
EMBEDDER = "https://lab.example.org"
STRANGER = "https://evil.example.net"


@pytest.fixture
def user() -> User:
    return User(
        id=PyObjectId("507f1f77bcf86cd799439012"),
        email="viewer@example.org",
        password="$2b$12$example.hashed.password.string",
        is_admin=False,
        is_active=True,
        is_verified=True,
    )


@pytest.fixture
def client(user: User):
    """The real middleware order from api/main.py, narrowed to what CORS needs.

    The global CORS allowlist is left empty on purpose: that is the default a
    deployment runs with, and it is what made the preflight fail.
    """
    from depictio.api.main import EmbedPreflightMiddleware

    app = FastAPI()
    app.include_router(export_endpoint_router, prefix=API_PREFIX)
    app.dependency_overrides[get_embed_user] = lambda: user
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )
    # Added last => outermost => sees OPTIONS before the global policy can reject it.
    app.add_middleware(EmbedPreflightMiddleware)

    with patch("depictio.api.v1.services.export.cors.settings") as cors_settings:
        cors_settings.fastapi.embed_allowed_origins = [EMBEDDER]
        yield TestClient(app)


def _preflight(client, origin: str, headers: str = "if-none-match"):
    return client.options(
        f"{API_PREFIX}/dashboards/{DASHBOARD_ID}/components/anything?format=json",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": headers,
        },
    )


class TestEmbedPreflight:
    def test_conditional_get_is_preflight_approved(self, client):
        """The case that was broken: revalidating an export with its own ETag."""
        response = _preflight(client, EMBEDDER)
        assert response.status_code == 204
        assert response.headers["access-control-allow-origin"] == EMBEDDER
        assert "If-None-Match" in response.headers["access-control-allow-headers"]

    def test_etag_is_readable_by_the_page_that_must_echo_it(self, client):
        """Allowing the request header is useless if the response header is hidden."""
        response = _preflight(client, EMBEDDER)
        assert response.headers["access-control-expose-headers"] == "ETag"

    def test_response_varies_on_origin(self, client):
        """The answer is origin-dependent, so a shared cache must not reuse it."""
        assert _preflight(client, EMBEDDER).headers["vary"] == "Origin"

    def test_non_embed_origin_is_not_granted(self, client):
        """Falls through to the global policy, which allows nothing here."""
        response = _preflight(client, STRANGER)
        assert response.status_code != 204
        assert "access-control-allow-origin" not in response.headers

    def test_plain_options_is_not_treated_as_a_preflight(self, client):
        """No Access-Control-Request-Method means this is not a preflight at all."""
        response = client.options(
            f"{API_PREFIX}/dashboards/{DASHBOARD_ID}/components/anything",
            headers={"Origin": EMBEDDER},
        )
        assert response.status_code != 204

    def test_non_export_paths_are_untouched(self, client):
        """The grant is scoped to the export routes, not the whole API."""
        response = client.options(
            "/depictio/api/v1/dashboards/anything",
            headers={
                "Origin": EMBEDDER,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "if-none-match",
            },
        )
        assert "access-control-allow-origin" not in response.headers
