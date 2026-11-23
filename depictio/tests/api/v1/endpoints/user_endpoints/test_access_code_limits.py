"""Public access code: wrong codes are slowed down, a room on one NAT is not.

Every call counted would lock out a classroom that types the right code at
once from one address; only wrong codes count towards the guessing limit.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.user_endpoints import rate_limit
from depictio.api.v1.endpoints.user_endpoints import routes as user_routes


class FakeRedis:
    def __init__(self):
        self.data: dict[str, int] = {}

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def expire(self, key, ttl):
        return True

    def get(self, key):
        return self.data.get(key)


def _request(ip: str):
    request = MagicMock()
    request.headers = {"x-real-ip": ip}
    request.client.host = "10.0.0.2"  # behind the bundled nginx
    return request


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: fake)
    return fake


@pytest.fixture
def public_with_code():
    settings = MagicMock()
    settings.auth.is_public_mode = True
    settings.auth.is_public_access_code_required = True
    settings.auth.verify_public_access_code.side_effect = lambda code: code == "right-code"
    settings.auth.temporary_user_expiry_hours = 1
    settings.auth.temporary_user_expiry_minutes = 0
    with (
        patch.object(user_routes, "settings", settings),
        patch.object(user_routes, "_create_temporary_user", AsyncMock(return_value=MagicMock())),
        patch.object(
            user_routes,
            "_create_temporary_user_session",
            AsyncMock(return_value={"access_token": "t"}),
        ),
    ):
        yield


async def _attempt(ip: str, code: str) -> int:
    try:
        await user_routes.create_temporary_user_public(_request(ip), {"access_code": code})
        return 200
    except HTTPException as exc:
        return exc.status_code


@pytest.mark.asyncio
async def test_a_room_behind_one_address_all_gets_in(redis, public_with_code):
    statuses = [await _attempt("10.1.1.1", "right-code") for _ in range(30)]
    assert statuses == [200] * 30


@pytest.mark.asyncio
async def test_wrong_codes_from_one_address_are_slowed_down(redis, public_with_code):
    statuses = [await _attempt("10.1.1.1", "guess") for _ in range(12)]
    assert statuses[:10] == [403] * 10
    assert statuses[10:] == [429, 429]
    # Even the right code waits out the window from that address...
    assert await _attempt("10.1.1.1", "right-code") == 429
    # ...while the rest of the room is unaffected.
    assert await _attempt("10.1.1.2", "right-code") == 200


@pytest.mark.asyncio
async def test_guesses_spread_over_many_addresses_hit_the_overall_limit(redis, public_with_code):
    for i in range(100):
        assert await _attempt(f"10.2.{i // 250}.{i % 250}", "guess") == 403
    assert await _attempt("10.3.0.1", "guess") == 429


@pytest.mark.asyncio
async def test_without_a_code_no_failure_limit_applies(redis):
    settings = MagicMock()
    settings.auth.is_public_mode = True
    settings.auth.is_public_access_code_required = False
    settings.auth.verify_public_access_code.return_value = True
    with (
        patch.object(user_routes, "settings", settings),
        patch.object(user_routes, "enforce_failure_limit") as failure_limit,
        patch.object(user_routes, "_create_temporary_user", AsyncMock(return_value=MagicMock())),
        patch.object(user_routes, "_create_temporary_user_session", AsyncMock(return_value={})),
    ):
        await user_routes.create_temporary_user_public(_request("10.0.0.1"), {})
    failure_limit.assert_not_called()


def test_failure_limit_fails_open_without_redis(monkeypatch):
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: None)
    rate_limit.enforce_failure_limit(_request("10.0.0.1"), "x", max_per_ip=0, max_overall=0)
    rate_limit.record_failure(_request("10.0.0.1"), "x")
