"""Every API worker runs the event listener; only one watches MongoDB."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from depictio.api.v1.services import lifespan


@pytest.fixture
def start(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(lifespan.event_service, "start", mock)
    return mock


@pytest.mark.asyncio
async def test_a_worker_that_did_not_initialize_still_listens(monkeypatch, start):
    """Its own WebSocket clients are reachable only through its own listener."""
    monkeypatch.setattr(lifespan.settings.events, "enabled", True)

    await lifespan.start_event_services(should_initialize=False)

    start.assert_awaited_once_with(watch_mongodb=False)


@pytest.mark.asyncio
async def test_the_initializing_worker_also_watches_mongodb(monkeypatch, start):
    monkeypatch.setattr(lifespan.settings.events, "enabled", True)

    await lifespan.start_event_services(should_initialize=True)

    start.assert_awaited_once_with(watch_mongodb=True)


@pytest.mark.asyncio
async def test_nothing_starts_while_events_are_off(monkeypatch, start):
    monkeypatch.setattr(lifespan.settings.events, "enabled", False)

    await lifespan.start_event_services(should_initialize=True)

    start.assert_not_awaited()
