"""Tests for the SSO attribute sync module (sso_sync.sync_sso_user).

Runs against mongomock-motor (no real MongoDB needed), following the same
init_beanie + AsyncMongoMockClient pattern as the user_endpoints tests.
"""

from typing import cast

import pytest
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient
from pymongo.asynchronous.database import AsyncDatabase

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.auth_endpoints.sso_sync import sync_sso_user
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import GroupBeanie, UserBeanie

HASHED_PW = "$2b$12$test.hash.not.a.real.password.value"


@pytest.fixture(autouse=True)
def _reset_saml_attribute_settings(monkeypatch):
    """Isolate each test from env-provided SAML attribute mappings."""
    monkeypatch.setattr(settings.auth, "saml_attribute_groups", None)
    monkeypatch.setattr(settings.auth, "saml_attribute_title", None)
    monkeypatch.setattr(settings.auth, "saml_attribute_display_name", None)
    monkeypatch.setattr(settings.auth, "saml_attribute_login", None)


async def _setup_db() -> None:
    client = AsyncMongoMockClient()
    await init_beanie(
        database=cast(AsyncDatabase, client.test_db),
        document_models=[UserBeanie, GroupBeanie],
    )


async def _create_user(email: str = "sso@example.com") -> UserBeanie:
    user = UserBeanie(email=email, password=HASHED_PW, is_active=True, is_verified=True)
    await user.save()
    return user


def _member_ids(group: GroupBeanie) -> set[str]:
    return {str(uid) for uid in group.users_ids}


# ------------------------------------------------------
# Group sync
# ------------------------------------------------------


class TestGroupSync:
    @pytest.mark.asyncio
    async def test_creates_missing_sso_groups_and_adds_membership(self, monkeypatch):
        await _setup_db()
        monkeypatch.setattr(settings.auth, "saml_attribute_groups", "memberOf")
        user = await _create_user()

        await sync_sso_user(user, {"memberOf": ["Lab Alpha", "  Lab Beta  ", "", "   "]})

        for name in ("Lab Alpha", "Lab Beta"):
            group = await GroupBeanie.find_one({"name": name})
            assert group is not None, f"group '{name}' should have been created"
            assert group.sso_managed is True
            assert group.admin_ids == []
            assert group.pi_id is None
            assert str(user.id) in _member_ids(group)

        # Empty/whitespace values are dropped.
        assert await GroupBeanie.find({}).count() == 2

        # Idempotent: a second login with the same assertion changes nothing.
        await sync_sso_user(user, {"memberOf": ["Lab Alpha", "Lab Beta"]})
        assert await GroupBeanie.find({}).count() == 2
        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert len(group.users_ids) == 1

    @pytest.mark.asyncio
    async def test_adds_user_to_existing_sso_group(self, monkeypatch):
        await _setup_db()
        monkeypatch.setattr(settings.auth, "saml_attribute_groups", "memberOf")
        other_id = PyObjectId()
        existing = GroupBeanie(name="Lab Alpha", sso_managed=True, users_ids=[other_id])
        await existing.save()
        user = await _create_user()

        await sync_sso_user(user, {"memberOf": ["Lab Alpha"]})

        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert _member_ids(group) == {str(other_id), str(user.id)}

    @pytest.mark.asyncio
    async def test_removes_user_from_stale_sso_groups(self, monkeypatch):
        await _setup_db()
        monkeypatch.setattr(settings.auth, "saml_attribute_groups", "memberOf")
        user = await _create_user()
        other_id = PyObjectId()
        stale = GroupBeanie(
            name="Old Lab",
            sso_managed=True,
            users_ids=[user.id, other_id],
            admin_ids=[user.id],
            pi_id=user.id,
        )
        await stale.save()

        await sync_sso_user(user, {"memberOf": ["New Lab"]})

        old = await GroupBeanie.find_one({"name": "Old Lab"})
        assert old is not None
        assert str(user.id) not in _member_ids(old)
        assert str(user.id) not in {str(uid) for uid in old.admin_ids}
        assert old.pi_id is None
        # Other members are untouched.
        assert str(other_id) in _member_ids(old)

        new = await GroupBeanie.find_one({"name": "New Lab"})
        assert new is not None
        assert str(user.id) in _member_ids(new)

    @pytest.mark.asyncio
    async def test_never_touches_manually_created_groups(self, monkeypatch):
        await _setup_db()
        monkeypatch.setattr(settings.auth, "saml_attribute_groups", "memberOf")
        user = await _create_user()
        manual = GroupBeanie(
            name="Manual Team",
            sso_managed=False,
            users_ids=[user.id],
            admin_ids=[user.id],
            pi_id=user.id,
        )
        await manual.save()

        # 'Manual Team' is NOT in the assertion — but sso_managed=False, so it stays.
        await sync_sso_user(user, {"memberOf": ["Lab Alpha"]})

        group = await GroupBeanie.find_one({"name": "Manual Team"})
        assert group is not None
        assert str(user.id) in _member_ids(group)
        assert str(user.id) in {str(uid) for uid in group.admin_ids}
        assert group.pi_id is not None and str(group.pi_id) == str(user.id)

    @pytest.mark.asyncio
    async def test_absent_groups_attribute_removes_from_all_sso_groups(self, monkeypatch):
        await _setup_db()
        monkeypatch.setattr(settings.auth, "saml_attribute_groups", "memberOf")
        user = await _create_user()
        sso_group = GroupBeanie(name="Lab Alpha", sso_managed=True, users_ids=[user.id])
        await sso_group.save()
        manual = GroupBeanie(name="Manual Team", sso_managed=False, users_ids=[user.id])
        await manual.save()

        # Groups mapping configured, but attribute absent => treated as empty list.
        await sync_sso_user(user, {"someOtherAttr": ["x"]})

        sso = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert sso is not None
        assert str(user.id) not in _member_ids(sso)
        # Manual group membership survives.
        kept = await GroupBeanie.find_one({"name": "Manual Team"})
        assert kept is not None
        assert str(user.id) in _member_ids(kept)


# ------------------------------------------------------
# Profile sync
# ------------------------------------------------------


class TestProfileSync:
    @pytest.mark.asyncio
    async def test_profile_field_mapping(self, monkeypatch):
        await _setup_db()
        monkeypatch.setattr(settings.auth, "saml_attribute_title", "urn:oid:title")
        monkeypatch.setattr(settings.auth, "saml_attribute_display_name", "displayName")
        monkeypatch.setattr(settings.auth, "saml_attribute_login", "uid")
        user = await _create_user()

        await sync_sso_user(
            user,
            {
                "urn:oid:title": ["  Dr.  "],
                "displayName": ["Jane Doe"],
                "uid": ["jdoe"],
            },
        )

        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.title == "Dr."
        assert fetched.display_name == "Jane Doe"
        assert fetched.login == "jdoe"
        assert fetched.sso_provider == "saml"

    @pytest.mark.asyncio
    async def test_configured_but_absent_or_empty_values_keep_existing(self, monkeypatch):
        await _setup_db()
        monkeypatch.setattr(settings.auth, "saml_attribute_title", "urn:oid:title")
        monkeypatch.setattr(settings.auth, "saml_attribute_display_name", "displayName")
        monkeypatch.setattr(settings.auth, "saml_attribute_login", "uid")
        user = await _create_user()
        user.title = "Prof."
        user.display_name = "Old Name"
        await user.save()

        # title absent, displayName empty-valued, uid present.
        await sync_sso_user(user, {"displayName": ["   "], "uid": ["jdoe"]})

        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.title == "Prof."
        assert fetched.display_name == "Old Name"
        assert fetched.login == "jdoe"
        assert fetched.sso_provider == "saml"


# ------------------------------------------------------
# No-op behaviour
# ------------------------------------------------------


class TestNoOp:
    @pytest.mark.asyncio
    async def test_noop_when_settings_unset(self):
        await _setup_db()
        user = await _create_user()
        manual = GroupBeanie(name="Manual Team", users_ids=[user.id])
        await manual.save()

        await sync_sso_user(user, {"memberOf": ["Lab Alpha"], "displayName": ["Jane"]})

        # No groups created, memberships untouched, profile untouched.
        assert await GroupBeanie.find({}).count() == 1
        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.display_name is None
        assert fetched.title is None
        assert fetched.login is None
        assert fetched.sso_provider is None

    @pytest.mark.asyncio
    async def test_noop_when_attributes_none_or_empty(self, monkeypatch):
        await _setup_db()
        monkeypatch.setattr(settings.auth, "saml_attribute_groups", "memberOf")
        monkeypatch.setattr(settings.auth, "saml_attribute_display_name", "displayName")
        user = await _create_user()
        sso_group = GroupBeanie(name="Lab Alpha", sso_managed=True, users_ids=[user.id])
        await sso_group.save()

        # A None/empty attribute payload never wipes state — even sso_managed
        # group membership survives (unlike a present-but-groupless assertion).
        await sync_sso_user(user, None)
        await sync_sso_user(user, {})

        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert str(user.id) in _member_ids(group)
        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.sso_provider is None
