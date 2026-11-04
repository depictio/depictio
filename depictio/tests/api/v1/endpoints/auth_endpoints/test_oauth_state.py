"""The single-use login state shared between ``/login`` and ``/callback``."""

from datetime import timedelta

import pytest

from depictio.api.v1.endpoints.auth_endpoints.utils import (
    OAUTH_STATE_EXPIRY_MINUTES,
    consume_oauth_state,
    store_oauth_state,
)
from depictio.models.models.oauth_state import OAuthStateBeanie
from depictio.models.timestamps import utc_now_naive
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup


async def _store(**overrides) -> str:
    args = {"provider": "kc", "nonce": "n", "code_verifier": "v", "return_to": "/dashboards"}
    args.update(overrides)
    return await store_oauth_state(**args)


class TestOAuthStateStore:
    """Login and callback are separate requests that may reach different workers,
    so the state lives in shared storage rather than process memory."""

    @pytest.mark.asyncio
    @beanie_setup(models=[OAuthStateBeanie])
    async def test_state_round_trips_everything_the_callback_needs(self):
        state = await _store(provider="kc", nonce="nn", code_verifier="vv", return_to="/x?y=1")

        login = await consume_oauth_state(state)

        assert login is not None
        assert login.state == state
        assert (login.provider, login.nonce, login.code_verifier, login.return_to) == (
            "kc",
            "nn",
            "vv",
            "/x?y=1",
        )

    @pytest.mark.asyncio
    @beanie_setup(models=[OAuthStateBeanie])
    async def test_states_are_unguessable_and_distinct(self):
        states = {await _store() for _ in range(5)}
        assert len(states) == 5
        assert all(len(s) >= 32 for s in states)

    @pytest.mark.asyncio
    @beanie_setup(models=[OAuthStateBeanie])
    async def test_state_is_single_use(self):
        state = await _store()

        assert await consume_oauth_state(state) is not None
        # Replaying the same callback must not authenticate a second time.
        assert await consume_oauth_state(state) is None

    @pytest.mark.asyncio
    @beanie_setup(models=[OAuthStateBeanie])
    async def test_state_expires_after_the_documented_window(self):
        await _store()
        stored = await OAuthStateBeanie.find_one({})
        assert stored is not None
        remaining = stored.expire_datetime - utc_now_naive()
        assert timedelta(minutes=OAUTH_STATE_EXPIRY_MINUTES - 1) < remaining
        assert remaining <= timedelta(minutes=OAUTH_STATE_EXPIRY_MINUTES)

    @pytest.mark.asyncio
    @beanie_setup(models=[OAuthStateBeanie])
    async def test_expired_state_is_rejected_and_burned(self):
        await OAuthStateBeanie(
            state="stale-state",
            expire_datetime=utc_now_naive() - timedelta(minutes=1),
            provider="kc",
            nonce="n",
            code_verifier="v",
        ).insert()

        assert await consume_oauth_state("stale-state") is None
        # Rejected states are consumed too, so they cannot be retried.
        assert await OAuthStateBeanie.find_one({"state": "stale-state"}) is None

    @pytest.mark.asyncio
    @beanie_setup(models=[OAuthStateBeanie])
    async def test_unknown_state_is_rejected(self):
        assert await consume_oauth_state("never-issued") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["", None, 5, ["a"]])
    @beanie_setup(models=[OAuthStateBeanie])
    async def test_empty_or_non_string_state_is_rejected(self, value):
        await _store()
        assert await consume_oauth_state(value) is None  # type: ignore[arg-type]
        assert await OAuthStateBeanie.find({}).count() == 1  # nothing was consumed
