"""Regression tests for the metadata-only GET /auth/list_tokens response.

The endpoint must never return access_token or refresh_token values: a token
listing that carries the credentials lets any live session read every CLI
token of its user. Callers (React management page, CLI local_stack) only read
id/name/lifetime/expiry fields.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from depictio.api.main import app
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import TokenBeanie, UserBase, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

ACCESS_SECRET = "secret-access-token-value"
REFRESH_SECRET = "secret-refresh-token-value"
USER_ID = "507f1f77bcf86cd799439011"
LIST_URL = "/depictio/api/v1/auth/list_tokens"


def _token() -> TokenBeanie:
    now = datetime.now()
    return TokenBeanie(
        user_id=PyObjectId(USER_ID),
        access_token=ACCESS_SECRET,
        refresh_token=REFRESH_SECRET,
        token_type="bearer",
        token_lifetime="long-lived",
        expire_datetime=now + timedelta(hours=12),
        refresh_expire_datetime=now + timedelta(days=30),
        name="cli-agent-token",
    )


@pytest.fixture
def client():
    """Test client for the full FastAPI app (no lifespan)."""
    return TestClient(app)


@pytest.fixture
def as_user(client):
    """Authenticate requests as a regular user."""
    user = UserBase(id=PyObjectId(USER_ID), email="user@example.com", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.clear()


class TestListTokensMetadataOnly:
    """The listing response carries metadata, never token values."""

    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_listing_has_no_token_values(self, as_user):
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.routes._list_tokens",
            new_callable=AsyncMock,
            return_value=[_token()],
        ):
            response = as_user.get(LIST_URL)

        assert response.status_code == 200, response.text
        # The secrets never reach the wire, under any key.
        assert ACCESS_SECRET not in response.text
        assert REFRESH_SECRET not in response.text
        entry = response.json()[0]
        assert "access_token" not in entry
        assert "refresh_token" not in entry

    @beanie_setup(models=[TokenBeanie, UserBeanie])
    async def test_listing_keeps_the_metadata_callers_read(self, as_user):
        token = _token()
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.routes._list_tokens",
            new_callable=AsyncMock,
            return_value=[token],
        ):
            response = as_user.get(LIST_URL)

        assert response.status_code == 200
        entry = response.json()[0]
        # Both callers read the id as _id (api.ts falls back to id).
        assert entry["_id"] == str(token.id)
        assert entry["name"] == "cli-agent-token"
        assert entry["token_lifetime"] == "long-lived"
        assert entry["token_type"] == "bearer"
        assert entry["user_id"] == USER_ID
        assert entry["logged_in"] is False
        # Datetimes keep the format the UI rendered before the change.
        assert entry["expire_datetime"] == token.expire_datetime.strftime("%Y-%m-%d %H:%M:%S")
        assert entry["refresh_expire_datetime"] == token.refresh_expire_datetime.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        assert entry["created_at"] == token.created_at.strftime("%Y-%m-%d %H:%M:%S")

    @pytest.mark.asyncio
    async def test_lifetime_filter_is_still_forwarded(self, as_user):
        """The CLI asks for long-lived tokens only; the filter must keep working."""
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.routes._list_tokens",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_list:
            response = as_user.get(LIST_URL, params={"token_lifetime": "long-lived"})

        assert response.status_code == 200
        assert response.json() == []
        assert mock_list.call_args.kwargs["token_lifetime"] == "long-lived"
