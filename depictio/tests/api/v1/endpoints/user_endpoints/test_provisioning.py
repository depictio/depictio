"""Tests for pipeline provisioning + passwordless magic-link login.

Covers the core functions behind POST /auth/provision_user,
POST /auth/me/magic_link and POST /auth/magic/exchange.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _create_magic_link_ticket,
    _provision_user,
    _redeem_magic_link_ticket,
)
from depictio.models.models.users import (
    MagicLinkTicketBeanie,
    TokenBeanie,
    UserBeanie,
)
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

PROVISION_MODELS = [TokenBeanie, UserBeanie, MagicLinkTicketBeanie]


class TestProvisionUser:
    @pytest.mark.asyncio
    @beanie_setup(models=PROVISION_MODELS)
    async def test_provision_creates_passwordless_user_and_token(self):
        result = await _provision_user("alice@example.com")

        user = result["user"]
        token = result["token"]
        assert isinstance(user, UserBeanie)
        assert user.email == "alice@example.com"
        assert user.is_anonymous is False
        # Passwordless: no usable password, but the stored value is a bcrypt hash.
        assert user.password.startswith("$2b$")
        assert result["created"] is True

        # A long-lived run token is issued and persisted.
        assert isinstance(token, TokenBeanie)
        assert token.token_lifetime == "long-lived"
        assert token.user_id == user.id
        saved = await TokenBeanie.find_one({"user_id": user.id})
        assert saved is not None

    @pytest.mark.asyncio
    @beanie_setup(models=PROVISION_MODELS)
    async def test_provision_is_idempotent(self):
        first = await _provision_user("bob@example.com")
        second = await _provision_user("bob@example.com")

        # Same user is reused; only the first call reports it as created.
        assert first["user"].id == second["user"].id
        assert first["created"] is True
        assert second["created"] is False

        # Exactly one user AND one run token — the token is reused, not piled up.
        users = await UserBeanie.find({"email": "bob@example.com"}).to_list()
        assert len(users) == 1
        tokens = await TokenBeanie.find({"user_id": second["user"].id}).to_list()
        assert len(tokens) == 1
        assert first["token"].access_token == second["token"].access_token


class TestMagicLinkTicket:
    @pytest.mark.asyncio
    @beanie_setup(models=PROVISION_MODELS)
    async def test_create_ticket(self):
        provisioned = await _provision_user("carol@example.com")
        ticket = await _create_magic_link_ticket(provisioned["user"].id, expiry_minutes=15)

        assert ticket.used is False
        assert ticket.ticket  # opaque secret present
        assert ticket.expire_datetime > datetime.now()
        assert ticket.user_id == provisioned["user"].id

    @pytest.mark.asyncio
    @beanie_setup(models=PROVISION_MODELS)
    async def test_redeem_returns_session_and_burns_ticket(self):
        provisioned = await _provision_user("dave@example.com")
        ticket = await _create_magic_link_ticket(provisioned["user"].id, expiry_minutes=15)

        session = await _redeem_magic_link_ticket(ticket.ticket)

        assert session["logged_in"] is True
        assert session["email"] == "dave@example.com"
        assert session["user_id"] == str(provisioned["user"].id)
        assert session["access_token"]
        assert session["refresh_token"]

        # Single-use: the ticket is now burned.
        redeemed = await MagicLinkTicketBeanie.find_one({"ticket": ticket.ticket})
        assert redeemed is not None
        assert redeemed.used is True

    @pytest.mark.asyncio
    @beanie_setup(models=PROVISION_MODELS)
    async def test_redeem_twice_is_rejected(self):
        provisioned = await _provision_user("erin@example.com")
        ticket = await _create_magic_link_ticket(provisioned["user"].id, expiry_minutes=15)

        await _redeem_magic_link_ticket(ticket.ticket)
        with pytest.raises(HTTPException) as exc:
            await _redeem_magic_link_ticket(ticket.ticket)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    @beanie_setup(models=PROVISION_MODELS)
    async def test_redeem_expired_is_rejected(self):
        provisioned = await _provision_user("frank@example.com")
        ticket = await _create_magic_link_ticket(provisioned["user"].id, expiry_minutes=1)

        # Jump past the expiry without moving the wall clock (so the row isn't
        # TTL-reaped from the store) — the redeem path must reject it as expired.
        future = datetime.now() + timedelta(minutes=5)
        with patch("depictio.api.v1.endpoints.user_endpoints.core_functions.datetime") as mock_dt:
            mock_dt.now.return_value = future
            with pytest.raises(HTTPException) as exc:
                await _redeem_magic_link_ticket(ticket.ticket)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    @beanie_setup(models=PROVISION_MODELS)
    async def test_redeem_unknown_ticket_is_rejected(self):
        with pytest.raises(HTTPException) as exc:
            await _redeem_magic_link_ticket("does-not-exist")
        assert exc.value.status_code == 401
