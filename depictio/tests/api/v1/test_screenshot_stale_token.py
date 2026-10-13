"""Regression tests for the screenshot session's admin-token selection.

A deployment whose keys volume is recreated against a database that outlives
it (fresh `keys` PVC, retained MongoDB) keeps serving a `default_token` that
no longer verifies. The screenshot service used to hand that token straight
to Playwright: the SPA bootstrapped, read `user: null` from
`/auth/me/optional`, replaced the URL with `/auth`, and the login form was
captured over every dashboard thumbnail.

Two guards are pinned here — pick a token the current keypair actually
signed, and refuse to capture at all once the page has landed on `/auth`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from depictio.api.v1.services import screenshot_service


@pytest.fixture(scope="module")
def keypairs() -> tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]:
    """A "current" keypair and a stale one from a previous keys volume."""
    return (
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
    )


def _sign(private_key: rsa.RSAPrivateKey, **claims) -> str:
    return jwt.encode({"sub": "admin", **claims}, private_key, algorithm="RS256")


def _use_current_key(monkeypatch, current: rsa.RSAPrivateKey) -> None:
    monkeypatch.setattr(screenshot_service, "ALGORITHM", "RS256")
    monkeypatch.setattr(screenshot_service, "get_public_key", lambda _path: current.public_key())


def test_accepts_token_signed_by_current_keypair(monkeypatch, keypairs) -> None:
    current, _stale = keypairs
    _use_current_key(monkeypatch, current)

    assert screenshot_service._signed_by_current_keypair(_sign(current)) is True


def test_rejects_token_signed_by_previous_keypair(monkeypatch, keypairs) -> None:
    current, stale = keypairs
    _use_current_key(monkeypatch, current)

    assert screenshot_service._signed_by_current_keypair(_sign(stale)) is False


def test_accepts_expired_but_authentic_token(monkeypatch, keypairs) -> None:
    """An expired access token is refreshable in the browser — keep it."""
    current, _stale = keypairs
    _use_current_key(monkeypatch, current)

    expired = _sign(current, exp=int((datetime.now() - timedelta(days=1)).timestamp()))
    assert screenshot_service._signed_by_current_keypair(expired) is True


class _FakeToken:
    """Minimal stand-in for a TokenBeanie document."""

    def __init__(self, name: str, access_token: str) -> None:
        self.id = f"id-{name}"
        self.name = name
        self.access_token = access_token
        self.refresh_token = "refresh"
        self.user_id = "6a8c335fc04c657c3a615529"

    def model_dump(self, exclude_none: bool = False) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "user_id": self.user_id,
        }


def _stub_token_store(monkeypatch, tokens: list[_FakeToken]) -> None:
    """Stub UserBeanie/TokenBeanie so the loader runs without MongoDB.

    `find(...).sort(...).to_list()` is reproduced verbatim: the service asks
    for newest-first and the ordering is what makes it prefer a live token
    over the seeded one.
    """

    class _Admin:
        id = "admin-id"

    class _Query:
        def sort(self, _spec):
            return self

        async def to_list(self):
            return tokens

    class _UserBeanie:
        @staticmethod
        async def find_one(_query):
            return _Admin()

    class _TokenBeanie:
        @staticmethod
        def find(_query):
            return _Query()

    monkeypatch.setattr(screenshot_service, "UserBeanie", _UserBeanie)
    monkeypatch.setattr(screenshot_service, "TokenBeanie", _TokenBeanie)


@pytest.mark.asyncio
async def test_skips_stale_token_for_a_verifiable_one(monkeypatch, keypairs) -> None:
    """The stale `default_token` is listed first; the live one must win."""
    current, stale = keypairs
    _use_current_key(monkeypatch, current)
    _stub_token_store(
        monkeypatch,
        [
            _FakeToken("default_token", _sign(stale)),
            _FakeToken("google_oauth_20260824", _sign(current)),
        ],
    )

    token_data = await screenshot_service.get_admin_auth_token()

    assert token_data["name"] == "google_oauth_20260824"
    assert token_data["logged_in"] is True


@pytest.mark.asyncio
async def test_raises_when_every_token_is_stale(monkeypatch, keypairs) -> None:
    current, stale = keypairs
    _use_current_key(monkeypatch, current)
    _stub_token_store(monkeypatch, [_FakeToken("default_token", _sign(stale))])

    with pytest.raises(ValueError, match="re-mint the admin token"):
        await screenshot_service.get_admin_auth_token()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://depictio-viewer:80/auth", True),
        ("http://depictio-viewer:80/auth/google/callback?code=x", True),
        ("http://depictio-viewer:80/dashboard/abc?no-walkthrough=1", False),
        ("http://depictio-viewer:80/dashboards", False),
    ],
)
def test_auth_redirect_detection(url: str, expected: bool) -> None:
    assert screenshot_service._is_auth_redirect(url) is expected
