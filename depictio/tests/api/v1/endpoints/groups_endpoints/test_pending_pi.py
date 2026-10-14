"""Tests for deferred P.I. designation (pending_pi.claim_pending_pi_groups).

Runs against mongomock-motor (no real MongoDB needed), following the same
init_beanie + AsyncMongoMockClient pattern as the sso_sync tests.
"""

from typing import cast

import pytest
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient
from pymongo.asynchronous.database import AsyncDatabase

from depictio.api.v1.endpoints.groups_endpoints.pending_pi import claim_pending_pi_groups
from depictio.models.models.users import GroupBeanie, UserBeanie

HASHED_PW = "$2b$12$test.hash.not.a.real.password.value"


async def _setup_db() -> None:
    client = AsyncMongoMockClient()
    await init_beanie(
        database=cast(AsyncDatabase, client.test_db),
        document_models=[UserBeanie, GroupBeanie],
    )


async def _create_user(email: str = "pi@example.org") -> UserBeanie:
    user = UserBeanie(email=email, password=HASHED_PW, is_active=True, is_verified=True)
    await user.save()
    return user


@pytest.mark.asyncio
async def test_claims_group_parked_on_the_users_email():
    await _setup_db()
    group = GroupBeanie(name="Lab Alpha", pending_pi_email="pi@example.org")
    await group.save()

    user = await _create_user()
    claimed = await claim_pending_pi_groups(user)

    assert claimed == ["Lab Alpha"]
    stored = await GroupBeanie.find_one({"name": "Lab Alpha"})
    assert stored is not None
    assert str(stored.pi_id) == str(user.id)
    assert stored.pending_pi_email is None
    assert str(user.id) in {str(uid) for uid in stored.admin_ids}
    assert str(user.id) in {str(uid) for uid in stored.users_ids}


@pytest.mark.asyncio
async def test_claim_is_case_insensitive_on_the_parked_address():
    await _setup_db()
    # The model casefolds on write; a login with different casing still matches.
    group = GroupBeanie(name="Lab Alpha", pending_pi_email="PI@Example.ORG")
    await group.save()

    user = await _create_user("pi@example.org")
    assert await claim_pending_pi_groups(user) == ["Lab Alpha"]


@pytest.mark.asyncio
async def test_other_users_do_not_claim_the_designation():
    await _setup_db()
    group = GroupBeanie(name="Lab Alpha", pending_pi_email="pi@example.org")
    await group.save()

    other = await _create_user("someone.else@example.org")
    assert await claim_pending_pi_groups(other) == []

    stored = await GroupBeanie.find_one({"name": "Lab Alpha"})
    assert stored is not None
    assert stored.pi_id is None
    assert stored.pending_pi_email == "pi@example.org"


@pytest.mark.asyncio
async def test_replaying_a_login_is_a_no_op():
    await _setup_db()
    group = GroupBeanie(name="Lab Alpha", pending_pi_email="pi@example.org")
    await group.save()
    user = await _create_user()

    assert await claim_pending_pi_groups(user) == ["Lab Alpha"]
    assert await claim_pending_pi_groups(user) == []

    stored = await GroupBeanie.find_one({"name": "Lab Alpha"})
    assert stored is not None
    assert len([uid for uid in stored.admin_ids if str(uid) == str(user.id)]) == 1
    assert len([uid for uid in stored.users_ids if str(uid) == str(user.id)]) == 1


@pytest.mark.asyncio
async def test_claims_several_groups_at_once():
    await _setup_db()
    for name in ("Lab Alpha", "Lab Beta"):
        await GroupBeanie(name=name, pending_pi_email="pi@example.org").save()
    await GroupBeanie(name="Lab Gamma").save()

    user = await _create_user()
    assert sorted(await claim_pending_pi_groups(user)) == ["Lab Alpha", "Lab Beta"]

    untouched = await GroupBeanie.find_one({"name": "Lab Gamma"})
    assert untouched is not None
    assert untouched.pi_id is None


@pytest.mark.asyncio
async def test_sso_group_is_left_parked_until_the_idp_asserts_membership():
    """The IdP owns membership of sso_managed groups: promoting a non-member
    here would only be undone by the next assertion."""
    await _setup_db()
    group = GroupBeanie(name="Lab Alpha", sso_managed=True, pending_pi_email="pi@example.org")
    await group.save()

    user = await _create_user()
    assert await claim_pending_pi_groups(user) == []

    stored = await GroupBeanie.find_one({"name": "Lab Alpha"})
    assert stored is not None
    assert stored.pi_id is None
    assert stored.pending_pi_email == "pi@example.org"

    # Once group sync has added them as a member, the next login claims it.
    stored.users_ids.append(user.id)
    await stored.save()
    assert await claim_pending_pi_groups(user) == ["Lab Alpha"]

    claimed = await GroupBeanie.find_one({"name": "Lab Alpha"})
    assert claimed is not None
    assert str(claimed.pi_id) == str(user.id)
    assert claimed.pending_pi_email is None
