"""First-message WebSocket auth: token in the opening frame, not the URL."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

from depictio.api.v1.endpoints.events_endpoints import routes as events_routes

USER = SimpleNamespace(id="user-1", is_admin=False)


class FakeWebSocket:
    """Minimal WebSocket double: scripted receives, recorded sends."""

    def __init__(self, incoming: list):
        self._incoming = list(incoming)
        self.sent: list = []
        self.accepted = False
        self.close_code: int | None = None
        self.close_reason: str | None = None

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000, reason: str | None = None):
        self.close_code = code
        self.close_reason = reason

    async def receive_json(self):
        if not self._incoming:
            # Silent client: block until the auth timeout cancels us.
            await asyncio.Event().wait()
        item = self._incoming.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def send_json(self, data):
        self.sent.append(data)


@pytest.fixture
def ws_settings(monkeypatch):
    """Isolated settings stand-in: events on, authentication required."""
    settings = SimpleNamespace(
        events=SimpleNamespace(enabled=True, ws_connection_timeout=60),
        auth=SimpleNamespace(requires_anonymous_user=False),
    )
    monkeypatch.setattr(events_routes, "settings", settings)
    return settings


@pytest.fixture
def manager(monkeypatch):
    manager = SimpleNamespace(
        connect=AsyncMock(return_value="client-1"),
        disconnect=AsyncMock(),
        subscribe_to_dashboard=AsyncMock(),
        unsubscribe_from_dashboard=AsyncMock(),
    )
    monkeypatch.setattr(events_routes, "connection_manager", manager)
    return manager


@pytest.fixture
def valid_tokens(monkeypatch):
    """Only the literal "good-token" authenticates."""

    async def resolve(token):
        return USER if token == "good-token" else None

    monkeypatch.setattr(events_routes, "_resolve_websocket_user", resolve)
    return resolve


async def connect(ws, token=None, dashboard_id=None):
    await events_routes.websocket_endpoint(ws, token=token, dashboard_id=dashboard_id)


class TestFirstMessageAuth:
    @pytest.mark.asyncio
    async def test_a_valid_auth_message_connects(self, ws_settings, manager, valid_tokens):
        ws = FakeWebSocket(
            [
                {"type": "auth", "token": "good-token"},
                WebSocketDisconnect(1000),
            ]
        )

        await connect(ws)

        assert ws.accepted
        assert ws.close_code is None
        manager.connect.assert_awaited_once()
        kwargs = manager.connect.call_args.kwargs
        assert kwargs["user_id"] == "user-1"
        assert kwargs["accepted"] is True
        manager.disconnect.assert_awaited_once_with("client-1")

    @pytest.mark.asyncio
    async def test_no_auth_message_within_the_timeout_closes_4401(
        self, ws_settings, manager, valid_tokens, monkeypatch
    ):
        monkeypatch.setattr(events_routes, "WS_AUTH_TIMEOUT_SECONDS", 0.05)
        ws = FakeWebSocket([])

        await connect(ws)

        assert ws.accepted
        assert ws.close_code == 4401
        manager.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_first_message_that_is_not_auth_closes_4401(
        self, ws_settings, manager, valid_tokens
    ):
        ws = FakeWebSocket([{"type": "subscribe", "dashboard_id": "dash-1"}])

        await connect(ws)

        assert ws.close_code == 4401
        manager.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_invalid_token_closes_4401(self, ws_settings, manager, valid_tokens):
        ws = FakeWebSocket(
            [
                {"type": "auth", "token": "expired-token"},
            ]
        )

        await connect(ws)

        assert ws.close_code == 4401
        manager.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_anonymous_mode_connects_without_any_auth_message(
        self, ws_settings, manager, monkeypatch
    ):
        ws_settings.auth.requires_anonymous_user = True
        monkeypatch.setattr(events_routes, "WS_AUTH_TIMEOUT_SECONDS", 0.05)

        class SilentThenGone(FakeWebSocket):
            """Sends nothing within the auth timeout, then disconnects."""

            calls = 0

            async def receive_json(self):
                self.calls += 1
                if self.calls == 1:
                    await asyncio.Event().wait()
                raise WebSocketDisconnect(1000)

        ws = SilentThenGone([])

        await connect(ws)

        assert ws.close_code is None
        manager.connect.assert_awaited_once()
        assert manager.connect.call_args.kwargs["user_id"] is None

    @pytest.mark.asyncio
    async def test_anonymous_mode_still_recognises_a_signed_in_visitor(
        self, ws_settings, manager, valid_tokens
    ):
        """Public / single-user mode: a signed-in visitor's auth message counts,
        or they would lose the events of their private dashboards."""
        ws_settings.auth.requires_anonymous_user = True
        ws = FakeWebSocket([{"type": "auth", "token": "good-token"}, WebSocketDisconnect(1000)])

        await connect(ws)

        assert ws.close_code is None
        assert manager.connect.call_args.kwargs["user_id"] == "user-1"


class TestQueryTokenDeprecated:
    @pytest.mark.asyncio
    async def test_a_query_token_still_connects_with_a_deprecation_warning(
        self, ws_settings, manager, valid_tokens, caplog
    ):
        ws = FakeWebSocket([WebSocketDisconnect(1000)])

        # The depictio logger sits at ERROR in tests; raise it for the block.
        with caplog.at_level(logging.WARNING, logger="depictio"):
            await connect(ws, token="good-token")

        assert ws.close_code is None
        manager.connect.assert_awaited_once()
        assert manager.connect.call_args.kwargs["user_id"] == "user-1"
        assert manager.connect.call_args.kwargs["accepted"] is False

        assert "deprecated" in caplog.text
        # The warning must never echo the token itself.
        assert "good-token" not in caplog.text


class TestSubscribeStillPermissionChecked:
    @pytest.mark.asyncio
    async def test_a_viewer_without_access_cannot_subscribe(
        self, ws_settings, manager, valid_tokens, monkeypatch
    ):
        monkeypatch.setattr(events_routes, "_user_can_access_dashboard", lambda user, d: False)
        ws = FakeWebSocket(
            [
                {"type": "auth", "token": "good-token"},
                {"type": "subscribe", "dashboard_id": "dash-1"},
                WebSocketDisconnect(1000),
            ]
        )

        await connect(ws)

        manager.subscribe_to_dashboard.assert_not_awaited()
        assert any(m.get("type") == "subscribe_denied" for m in ws.sent)

    @pytest.mark.asyncio
    async def test_a_viewer_with_access_subscribes(
        self, ws_settings, manager, valid_tokens, monkeypatch
    ):
        monkeypatch.setattr(events_routes, "_user_can_access_dashboard", lambda user, d: True)
        ws = FakeWebSocket(
            [
                {"type": "auth", "token": "good-token"},
                {"type": "subscribe", "dashboard_id": "dash-1"},
                WebSocketDisconnect(1000),
            ]
        )

        await connect(ws)

        manager.subscribe_to_dashboard.assert_awaited_once_with("client-1", "dash-1")
        assert any(m.get("type") == "subscribed" for m in ws.sent)
