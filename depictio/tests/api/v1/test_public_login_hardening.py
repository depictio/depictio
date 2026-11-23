"""Password sign-in on a public instance: admins only, fail-closed, lockout.

On a public instance the password form faces the whole internet and only exists
so admins can get in (guests get temporary accounts, registration is off). So
there it accepts admins only, refuses to run without its rate limiter, and locks
an account after repeated wrong passwords. Other modes are unchanged.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from depictio.api.v1.configs.settings_models import AuthConfig
from depictio.api.v1.endpoints.user_endpoints import rate_limit
from depictio.api.v1.endpoints.user_endpoints import routes as user_routes

PASSWORD = "the-right-one"


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

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: fake)
    return fake


def _request(ip: str = "203.0.113.7"):
    request = MagicMock()
    request.headers = {"x-real-ip": ip}
    request.client.host = "10.0.0.2"
    return request


async def _login(*, public: bool, is_admin: bool, password: str, email="admin@lab.org"):
    settings = MagicMock()
    settings.auth.is_public_mode = public
    settings.auth.is_single_user_mode = False
    settings.auth.is_password_login_disabled = False
    user = SimpleNamespace(id="u1", email=email, is_admin=is_admin)
    token = SimpleNamespace(logged_in=False)
    with (
        patch.object(user_routes, "settings", settings),
        patch.object(
            user_routes,
            "_check_password",
            AsyncMock(side_effect=lambda _e, p: p == PASSWORD),
        ),
        patch.object(user_routes, "_async_fetch_user_from_email", AsyncMock(return_value=user)),
        patch.object(user_routes, "_add_token", AsyncMock(return_value=token)),
        patch.object(user_routes, "record_login", AsyncMock()),
        patch.object(user_routes, "TokenData", MagicMock()),
    ):
        return await user_routes.login(
            _request(), SimpleNamespace(username=email, password=password)
        )


@pytest.mark.asyncio
async def test_public_mode_admin_signs_in(redis):
    token = await _login(public=True, is_admin=True, password=PASSWORD)
    assert token.logged_in is True


@pytest.mark.asyncio
async def test_public_mode_refuses_a_non_admin_like_a_wrong_password(redis):
    with pytest.raises(HTTPException) as exc:
        await _login(public=True, is_admin=False, password=PASSWORD)
    assert (exc.value.status_code, exc.value.detail) == (401, "Invalid credentials")


@pytest.mark.asyncio
async def test_standard_mode_still_admits_non_admins(redis):
    token = await _login(public=False, is_admin=False, password=PASSWORD)
    assert token.logged_in is True


@pytest.mark.asyncio
async def test_public_mode_fails_closed_without_redis(monkeypatch):
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: None)
    with pytest.raises(HTTPException) as exc:
        await _login(public=True, is_admin=True, password=PASSWORD)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_standard_mode_still_fails_open_without_redis(monkeypatch):
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: None)
    token = await _login(public=False, is_admin=True, password=PASSWORD)
    assert token.logged_in is True


@pytest.mark.asyncio
async def test_account_locks_after_repeated_wrong_passwords(redis):
    for _ in range(rate_limit._LOCKOUT_MAX_FAILURES):
        with pytest.raises(HTTPException) as exc:
            await _login(public=True, is_admin=True, password="wrong")
        assert exc.value.status_code == 401

    # Locked: even the right password is refused, with the same answer.
    with pytest.raises(HTTPException) as exc:
        await _login(public=True, is_admin=True, password=PASSWORD)
    assert (exc.value.status_code, exc.value.detail) == (401, "Invalid credentials")

    # Another account is unaffected.
    token = await _login(public=True, is_admin=True, password=PASSWORD, email="other@lab.org")
    assert token.logged_in is True


@pytest.mark.asyncio
async def test_success_resets_the_failure_count(redis):
    for _ in range(rate_limit._LOCKOUT_MAX_FAILURES - 1):
        with pytest.raises(HTTPException):
            await _login(public=True, is_admin=True, password="wrong")
    await _login(public=True, is_admin=True, password=PASSWORD)
    for _ in range(rate_limit._LOCKOUT_MAX_FAILURES - 1):
        with pytest.raises(HTTPException):
            await _login(public=True, is_admin=True, password="wrong")
    token = await _login(public=True, is_admin=True, password=PASSWORD)
    assert token.logged_in is True


@pytest.mark.asyncio
async def test_lockout_is_not_counted_outside_public_mode(redis):
    for _ in range(rate_limit._LOCKOUT_MAX_FAILURES + 1):
        with pytest.raises(HTTPException):
            await _login(public=False, is_admin=True, password="wrong")
    assert not [key for key in redis.data if "lockout" in key]
    token = await _login(public=False, is_admin=True, password=PASSWORD)
    assert token.logged_in is True


def test_admin_sign_in_link_is_on_by_default_and_can_be_turned_off(monkeypatch):
    monkeypatch.delenv("DEPICTIO_AUTH_PUBLIC_ADMIN_SIGN_IN", raising=False)
    assert AuthConfig().public_admin_sign_in is True
    monkeypatch.setenv("DEPICTIO_AUTH_PUBLIC_ADMIN_SIGN_IN", "false")
    assert AuthConfig().public_admin_sign_in is False
