"""Regression tests for refresh-token rotation, reuse detection and logout.

/auth/refresh rotates the refresh token on every successful refresh. The
token retired by the last rotation answers only inside a short grace window
(two tabs racing the same refresh) and then only by handing back the pair
the first refresh minted; past the window, presenting it again is reuse of
a consumed credential, which means it leaked — the whole token document
(the session) is deleted. POST /auth/logout deletes the bearer's token
document so a copied localStorage (or a stolen refresh token) cannot revive
a signed-out session.
"""

import hashlib
from datetime import datetime, timedelta

import pytest

from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _add_token,
    _create_user_in_db,
)
from depictio.models.models.users import TokenBeanie, TokenData, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

LOGIN_URL = "/depictio/api/v1/auth/login"
REFRESH_URL = "/depictio/api/v1/auth/refresh"
LOGOUT_URL = "/depictio/api/v1/auth/logout"
ME_URL = "/depictio/api/v1/auth/me"

PASSWORD = "Some-1234-password"


async def _seed_user(email: str = "rotator@example.com") -> UserBeanie:
    """Create a user with a working password and return the Beanie doc."""
    await _create_user_in_db(email=email, password=PASSWORD)
    user = await UserBeanie.find_one({"email": email})
    assert user is not None
    return user


def _login(test_client, email: str):
    return test_client.post(LOGIN_URL, data={"username": email, "password": PASSWORD})


class TestRefreshRotation:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_rotation_returns_a_new_pair_and_retires_the_old_token(self, test_client):
        await _seed_user()
        login = _login(test_client, "rotator@example.com")
        assert login.status_code == 200, login.text
        old_refresh = login.json()["refresh_token"]

        refreshed = test_client.post(REFRESH_URL, json={"refresh_token": old_refresh})
        assert refreshed.status_code == 200, refreshed.text
        body = refreshed.json()
        new_access = body["access_token"]
        new_refresh = body["refresh_token"]
        assert new_refresh
        # The refresh token is one-use, so it must change on every rotation.
        # (The access token may coincide when minted in the same second —
        # same claims, second-granularity exp — which is fine: it is not
        # one-use and both would be equally valid.)
        assert new_refresh != old_refresh
        # The contract the SPA persists: all four fields travel together.
        assert body["refresh_expire_datetime"]
        assert body["expire_datetime"]

        # The retired token is stored hashed only, with its rotation time.
        doc = await TokenBeanie.find_one({"refresh_token": new_refresh})
        assert doc is not None
        assert (
            doc.previous_refresh_token_hash
            == hashlib.sha256(old_refresh.encode("utf-8")).hexdigest()
        )
        assert doc.previous_refresh_rotated_at is not None

        # The new pair authenticates.
        me = test_client.get(ME_URL, headers={"Authorization": f"Bearer {new_access}"})
        assert me.status_code == 200

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_racing_tab_gets_the_current_pair_back_inside_the_grace_window(self, test_client):
        await _seed_user()
        login = _login(test_client, "rotator@example.com")
        old_refresh = login.json()["refresh_token"]

        first = test_client.post(REFRESH_URL, json={"refresh_token": old_refresh})
        assert first.status_code == 200
        new_access = first.json()["access_token"]
        new_refresh = first.json()["refresh_token"]
        new_refresh_expiry = first.json()["refresh_expire_datetime"]

        # A second tab refreshing at once with the same (now retired) token
        # gets the current pair back — no new rotation.
        second = test_client.post(REFRESH_URL, json={"refresh_token": old_refresh})
        assert second.status_code == 200, second.text
        assert second.json()["access_token"] == new_access
        assert second.json()["refresh_token"] == new_refresh
        # Same expiry (storage truncates microseconds, so compare to the second).
        assert abs(
            datetime.fromisoformat(second.json()["refresh_expire_datetime"])
            - datetime.fromisoformat(new_refresh_expiry)
        ) < timedelta(seconds=1)

        # And no extra rotation happened: the stored pair is still current.
        doc = await TokenBeanie.find_one({"refresh_token": new_refresh})
        assert doc is not None
        assert doc.access_token == new_access

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_reuse_past_the_grace_window_deletes_the_session(self, test_client):
        await _seed_user()
        login = _login(test_client, "rotator@example.com")
        old_refresh = login.json()["refresh_token"]

        refreshed = test_client.post(REFRESH_URL, json={"refresh_token": old_refresh})
        assert refreshed.status_code == 200
        new_access = refreshed.json()["access_token"]
        new_refresh = refreshed.json()["refresh_token"]

        # Move the rotation outside the grace window without sleeping.
        doc = await TokenBeanie.find_one({"refresh_token": new_refresh})
        assert doc is not None
        doc.previous_refresh_rotated_at -= timedelta(seconds=31)
        await doc.save()

        reuse = test_client.post(REFRESH_URL, json={"refresh_token": old_refresh})
        assert reuse.status_code == 401

        # Reuse revoked the whole session: the current pair is dead too.
        assert await TokenBeanie.find_one({"refresh_token": new_refresh}) is None
        me = test_client.get(ME_URL, headers={"Authorization": f"Bearer {new_access}"})
        assert me.status_code == 401
        again = test_client.post(REFRESH_URL, json={"refresh_token": new_refresh})
        assert again.status_code == 401

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_unknown_refresh_token_is_rejected_without_side_effects(self, test_client):
        await _seed_user()
        missing = test_client.post(REFRESH_URL, json={"refresh_token": "not-a-real-token"})
        assert missing.status_code == 401
        empty = test_client.post(REFRESH_URL, json={})
        assert empty.status_code == 400

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_long_lived_session_rotates_with_its_own_lifetime(self, test_client):
        user = await _seed_user(email="cli-owner@example.com")
        token = await _add_token(TokenData(name="cli", token_lifetime="long-lived", sub=user.id))
        refreshed = test_client.post(REFRESH_URL, json={"refresh_token": token.refresh_token})
        assert refreshed.status_code == 200, refreshed.text
        # The rotated token inherits the session's own expiry (~1 year + 7 days
        # for long-lived), never a fresh window: rotation does not extend it.
        refresh_expiry = datetime.fromisoformat(refreshed.json()["refresh_expire_datetime"])
        assert refresh_expiry > datetime.now() + timedelta(days=364)
        assert abs(refresh_expiry - token.refresh_expire_datetime) < timedelta(seconds=1)


class TestLogoutRevokesServerSide:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_logout_deletes_the_bearers_session(self, test_client):
        await _seed_user()
        login = _login(test_client, "rotator@example.com")
        assert login.status_code == 200
        access = login.json()["access_token"]
        refresh = login.json()["refresh_token"]
        headers = {"Authorization": f"Bearer {access}"}

        me = test_client.get(ME_URL, headers=headers)
        assert me.status_code == 200

        out = test_client.post(LOGOUT_URL, headers=headers)
        assert out.status_code == 200
        assert out.json()["success"] is True

        # The access token no longer resolves a user...
        me = test_client.get(ME_URL, headers=headers)
        assert me.status_code == 401
        # ...and the refresh token died with the session: no revival.
        refreshed = test_client.post(REFRESH_URL, json={"refresh_token": refresh})
        assert refreshed.status_code == 401

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_logout_without_a_bearer_is_refused(self, test_client):
        await _seed_user()
        out = test_client.post(LOGOUT_URL)
        assert out.status_code == 401


class TestMustChangePasswordStillGatesRefresh:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_flagged_user_refresh_is_refused_without_consuming_the_token(self, test_client):
        user = await _seed_user(email="flagged@example.com")
        user.must_change_password = True
        await user.save()

        login = _login(test_client, "flagged@example.com")
        assert login.status_code == 200
        refresh = login.json()["refresh_token"]

        refused = test_client.post(REFRESH_URL, json={"refresh_token": refresh})
        assert refused.status_code == 403
        assert refused.json()["detail"] == "Change your password first."

        # The refused refresh must not have rotated (consumed) the token.
        user.must_change_password = False
        await user.save()
        ok = test_client.post(REFRESH_URL, json={"refresh_token": refresh})
        assert ok.status_code == 200
        assert ok.json()["refresh_token"] != refresh
