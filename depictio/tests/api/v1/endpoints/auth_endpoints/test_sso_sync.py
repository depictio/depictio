"""Tests for the SSO claim sync and login provisioning (``sso_sync``).

Runs against mongomock-motor (no real MongoDB needed), following the same
``beanie_setup`` pattern as the user_endpoints tests.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import OIDCClaimMapping, OIDCProviderConfig
from depictio.api.v1.endpoints.auth_endpoints import sso_sync
from depictio.api.v1.endpoints.auth_endpoints import utils as sso_utils
from depictio.api.v1.endpoints.auth_endpoints.sso_sync import (
    SSOLoginRejected,
    claim_values,
    first_claim,
    provision_sso_login,
    sync_sso_user,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import GroupBeanie, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

HASHED_PW = "$2b$12$test.hash.not.a.real.password.value"
MODELS = [UserBeanie, GroupBeanie]


def make_provider(**overrides: Any) -> OIDCProviderConfig:
    """A configured provider; ``claims=`` may be a dict or an OIDCClaimMapping."""
    claims = overrides.pop("claims", {})
    if isinstance(claims, dict):
        claims = OIDCClaimMapping(**claims)
    base: dict[str, Any] = {
        "id": "kc",
        "issuer": "https://idp.example.org/realms/example",
        "client_id": "depictio",
        "client_secret": "secret",
    }
    base.update(overrides)
    return OIDCProviderConfig(claims=claims, **base)


async def _create_user(email: str = "sso@example.com", **fields: Any) -> UserBeanie:
    user = UserBeanie(email=email, password=HASHED_PW, is_active=True, is_verified=True, **fields)
    await user.save()
    return user


def _member_ids(group: GroupBeanie) -> set[str]:
    return {str(uid) for uid in group.users_ids}


@pytest.fixture(autouse=True)
def _registration_open(monkeypatch):
    monkeypatch.setattr(settings.auth, "registration_disabled", False)


@pytest.fixture
def spies(monkeypatch):
    """Spies on both pending-claim hooks, in the modules that call them."""
    pi = AsyncMock(return_value=[])
    owner = AsyncMock(return_value=None)
    monkeypatch.setattr(sso_sync, "claim_pending_pi_groups", pi)
    monkeypatch.setattr(sso_sync, "claim_pending_project_ownership_quietly", owner)
    monkeypatch.setattr(sso_utils, "claim_pending_pi_groups", pi)
    monkeypatch.setattr(sso_utils, "claim_pending_project_ownership_quietly", owner)
    return pi, owner


# ------------------------------------------------------
# Claim access helpers
# ------------------------------------------------------


class TestClaimValues:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("lab", ["lab"]),
            (["lab"], ["lab"]),
            ("  lab  ", ["lab"]),
            (["a", " b ", "", "   "], ["a", "b"]),
            ([1, 2.5, "x"], ["1", "2.5", "x"]),
            ([True, False, "x"], ["x"]),
            (True, []),
            (7, ["7"]),
            ([None, {"a": 1}, ["n"], "ok"], ["ok"]),
            ([], []),
            ("", []),
            ("   ", []),
        ],
    )
    def test_normalises_strings_lists_numbers_and_empties(self, raw, expected):
        assert claim_values({"c": raw}, "c") == expected

    def test_absent_or_null_claim_is_none(self):
        assert claim_values({"x": 1}, "c") is None
        assert claim_values({"c": None}, "c") is None
        assert claim_values(None, "c") is None
        assert claim_values({}, "c") is None

    def test_dotted_path_is_followed(self):
        claims = {"realm_access": {"roles": ["admin", "user"]}, "a": {"b": {"c": "deep"}}}
        assert claim_values(claims, "realm_access.roles") == ["admin", "user"]
        assert claim_values(claims, "a.b.c") == ["deep"]
        assert claim_values(claims, "a.b.missing") is None
        assert claim_values(claims, "realm_access.roles.x") is None
        assert claim_values({"a": "scalar"}, "a.b") is None

    def test_literal_dotted_claim_name_wins_over_path(self):
        claims = {"a.b": ["literal"], "a": {"b": ["nested"]}}
        assert claim_values(claims, "a.b") == ["literal"]

    def test_dotted_path_ignores_case(self):
        assert claim_values({"Realm_Access": {"Roles": ["r"]}}, "realm_access.roles") == ["r"]

    def test_first_claim(self):
        assert first_claim({"n": ["", "Jane", "Other"]}, "n") == "Jane"
        assert first_claim({"n": "Jane"}, "n") == "Jane"
        assert first_claim({"n": []}, "n") is None
        assert first_claim({"n": "x"}, None) is None
        assert first_claim({"n": "x"}, "") is None


# ------------------------------------------------------
# Group sync
# ------------------------------------------------------


class TestGroupSync:
    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_creates_missing_sso_groups_and_adds_membership(self):
        provider = make_provider(claims={"groups": "memberOf"})
        user = await _create_user()

        await sync_sso_user(user, {"memberOf": ["Lab Alpha", "  Lab Beta  ", "", "   "]}, provider)

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
        await sync_sso_user(user, {"memberOf": ["Lab Alpha", "Lab Beta"]}, provider)
        assert await GroupBeanie.find({}).count() == 2
        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert len(group.users_ids) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("configured,sent", [("groups", "Groups"), ("Groups", "groups")])
    @beanie_setup(models=MODELS)
    async def test_claim_name_matches_ignoring_case(self, configured, sent):
        provider = make_provider(claims={"groups": configured})
        user = await _create_user()

        await sync_sso_user(user, {sent: ["Lab Alpha"]}, provider)

        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert str(user.id) in _member_ids(group)

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_an_empty_claim_name_is_not_configured(self):
        """Helm passes "" for an unset mapping: it must skip the sync, not wipe groups."""
        provider = make_provider(claims={"groups": ""})
        assert provider.claims.groups is None
        user = await _create_user()
        await GroupBeanie(name="Lab Alpha", sso_managed=True, users_ids=[user.id]).save()

        await sync_sso_user(user, {"groups": ["Other"]}, provider)

        kept = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert kept is not None
        assert str(user.id) in _member_ids(kept)
        assert await GroupBeanie.find_one({"name": "Other"}) is None

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_exact_claim_name_wins_over_a_case_variant(self):
        provider = make_provider(claims={"groups": "groups"})
        user = await _create_user()

        await sync_sso_user(user, {"Groups": ["Wrong"], "groups": ["Right"]}, provider)

        assert await GroupBeanie.find_one({"name": "Right"}) is not None
        assert await GroupBeanie.find_one({"name": "Wrong"}) is None

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_adds_user_to_existing_sso_group(self):
        provider = make_provider(claims={"groups": "memberOf"})
        other_id = PyObjectId()
        await GroupBeanie(name="Lab Alpha", sso_managed=True, users_ids=[other_id]).save()
        user = await _create_user()

        await sync_sso_user(user, {"memberOf": ["Lab Alpha"]}, provider)

        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert _member_ids(group) == {str(other_id), str(user.id)}

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_removes_user_from_stale_sso_groups(self):
        provider = make_provider(claims={"groups": "memberOf"})
        user = await _create_user()
        other_id = PyObjectId()
        await GroupBeanie(
            name="Old Lab",
            sso_managed=True,
            users_ids=[user.id, other_id],
            admin_ids=[user.id],
            pi_id=user.id,
        ).save()

        await sync_sso_user(user, {"memberOf": ["New Lab"]}, provider)

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
    @beanie_setup(models=MODELS)
    async def test_never_touches_manually_created_groups(self):
        provider = make_provider(claims={"groups": "memberOf"})
        user = await _create_user()
        await GroupBeanie(
            name="Manual Team",
            sso_managed=False,
            users_ids=[user.id],
            admin_ids=[user.id],
            pi_id=user.id,
        ).save()

        # 'Manual Team' is NOT in the claim, but sso_managed=False, so it stays.
        await sync_sso_user(user, {"memberOf": ["Lab Alpha"]}, provider)

        group = await GroupBeanie.find_one({"name": "Manual Team"})
        assert group is not None
        assert str(user.id) in _member_ids(group)
        assert str(user.id) in {str(uid) for uid in group.admin_ids}
        assert group.pi_id is not None and str(group.pi_id) == str(user.id)

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_absent_groups_claim_removes_from_all_sso_groups(self):
        provider = make_provider(claims={"groups": "memberOf"})
        user = await _create_user()
        await GroupBeanie(name="Lab Alpha", sso_managed=True, users_ids=[user.id]).save()
        await GroupBeanie(name="Manual Team", sso_managed=False, users_ids=[user.id]).save()

        # Groups mapping configured, but claim absent => treated as empty list.
        await sync_sso_user(user, {"someOtherClaim": ["x"]}, provider)

        sso = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert sso is not None
        assert str(user.id) not in _member_ids(sso)
        kept = await GroupBeanie.find_one({"name": "Manual Team"})
        assert kept is not None
        assert str(user.id) in _member_ids(kept)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "claim_value",
        [
            "lab-a",
            ["lab-a"],
            ["lab-a", "lab-a"],
            [" lab-a ", "", None],
        ],
    )
    @beanie_setup(models=MODELS)
    async def test_string_and_list_group_claims_are_equivalent(self, claim_value):
        provider = make_provider(claims={"groups": "groups"})
        user = await _create_user()

        await sync_sso_user(user, {"groups": claim_value}, provider)

        groups = await GroupBeanie.find({}).to_list()
        assert [g.name for g in groups] == ["lab-a"]
        assert _member_ids(groups[0]) == {str(user.id)}

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_groups_from_a_dotted_path_claim(self):
        provider = make_provider(claims={"groups": "realm_access.roles"})
        user = await _create_user()

        await sync_sso_user(
            user, {"realm_access": {"roles": ["analyst", "offline_access"]}}, provider
        )

        names = {g.name for g in await GroupBeanie.find({}).to_list()}
        assert names == {"analyst", "offline_access"}

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_numbers_bools_and_empties_in_group_lists(self):
        provider = make_provider(claims={"groups": "groups"})
        user = await _create_user()

        await sync_sso_user(user, {"groups": [42, True, False, None, "", "  ", "real"]}, provider)

        names = {g.name for g in await GroupBeanie.find({}).to_list()}
        assert names == {"42", "real"}

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_group_names_are_matched_case_sensitively_but_claims_ignore_case(self):
        """Case-insensitive *claim names* (Groups/groups); group names stay verbatim."""
        provider = make_provider(claims={"groups": "GROUPS"})
        user = await _create_user()

        await sync_sso_user(user, {"groups": ["Lab"]}, provider)

        group = await GroupBeanie.find_one({"name": "Lab"})
        assert group is not None


# ------------------------------------------------------
# Profile sync
# ------------------------------------------------------


class TestProfileSync:
    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_profile_field_mapping(self):
        provider = make_provider(
            claims={"title": "job_title", "display_name": "name", "login": "preferred_username"}
        )
        user = await _create_user()

        await sync_sso_user(
            user,
            {"job_title": ["  Dr.  "], "name": ["Jane Doe"], "preferred_username": ["jdoe"]},
            provider,
        )

        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.title == "Dr."
        assert fetched.display_name == "Jane Doe"
        assert fetched.login == "jdoe"
        assert fetched.sso_provider == "kc"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("as_list", [False, True])
    @beanie_setup(models=MODELS)
    async def test_profile_claims_as_string_or_list_are_identical(self, as_list):
        provider = make_provider(
            claims={"title": "t", "display_name": "n", "login": "u", "email": "mail"}
        )
        user = await _create_user()
        wrap = (lambda v: [v]) if as_list else (lambda v: v)

        await sync_sso_user(
            user, {"t": wrap("Dr."), "n": wrap("Jane Doe"), "u": wrap("jdoe")}, provider
        )

        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert (fetched.title, fetched.display_name, fetched.login) == ("Dr.", "Jane Doe", "jdoe")

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_configured_but_absent_or_empty_values_keep_existing(self):
        provider = make_provider(
            claims={"title": "title", "display_name": "name", "login": "preferred_username"}
        )
        user = await _create_user()
        user.title = "Prof."
        user.display_name = "Old Name"
        await user.save()

        # title absent, name empty-valued, login present.
        await sync_sso_user(user, {"name": ["   "], "preferred_username": ["jdoe"]}, provider)

        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.title == "Prof."
        assert fetched.display_name == "Old Name"
        assert fetched.login == "jdoe"
        assert fetched.sso_provider == "kc"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_dotted_path_profile_claim(self):
        provider = make_provider(claims={"display_name": "profile.full_name"})
        user = await _create_user()

        await sync_sso_user(user, {"profile": {"full_name": "Jane Doe"}}, provider)

        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.display_name == "Jane Doe"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_user_is_saved_once_and_only_when_changed(self, monkeypatch):
        provider = make_provider(claims={"title": "t", "display_name": "n", "login": "u"})
        user = await _create_user()
        saves = []
        original = UserBeanie.save

        async def counting_save(self, *args, **kwargs):
            saves.append(self.email)
            return await original(self, *args, **kwargs)

        monkeypatch.setattr(UserBeanie, "save", counting_save)

        claims = {"t": "Dr.", "n": "Jane Doe", "u": "jdoe"}
        await sync_sso_user(user, claims, provider)
        assert len(saves) == 1  # three fields + sso_provider, one write

        await sync_sso_user(user, claims, provider)
        assert len(saves) == 1  # nothing changed: no write

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_sso_provider_defaults_to_the_provider_id(self):
        user = await _create_user()
        await sync_sso_user(user, {"email": "x@example.com"}, make_provider(id="my-idp"))
        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.sso_provider == "my-idp"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_sso_provider_is_stamped_from_the_configured_name(self):
        user = await _create_user()
        await sync_sso_user(
            user, {"email": "x@example.com"}, make_provider(id="kc", sso_provider="keycloak")
        )
        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.sso_provider == "keycloak"


# ------------------------------------------------------
# No-op behaviour and pending claims
# ------------------------------------------------------


class TestNoOpAndPendingClaims:
    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_no_groups_or_profile_mapping_only_stamps_the_provider(self):
        provider = make_provider()  # default mapping: email + picture only
        user = await _create_user()
        await GroupBeanie(name="Manual Team", users_ids=[user.id]).save()

        await sync_sso_user(
            user, {"memberOf": ["Lab Alpha"], "name": "Jane", "groups": ["g"]}, provider
        )

        assert await GroupBeanie.find({}).count() == 1  # no group created
        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.display_name is None
        assert fetched.title is None
        assert fetched.login is None
        assert fetched.sso_provider == "kc"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty", [None, {}])
    @beanie_setup(models=MODELS)
    async def test_empty_claims_never_wipe_state(self, empty):
        provider = make_provider(claims={"groups": "memberOf", "display_name": "name"})
        user = await _create_user()
        await GroupBeanie(name="Lab Alpha", sso_managed=True, users_ids=[user.id]).save()

        await sync_sso_user(user, empty, provider)

        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert str(user.id) in _member_ids(group)
        fetched = await UserBeanie.find_one(UserBeanie.email == "sso@example.com")
        assert fetched is not None
        assert fetched.sso_provider is None

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_pending_pi_is_claimed_on_the_login_that_asserts_the_group(self):
        provider = make_provider(claims={"groups": "memberOf"})
        user = await _create_user(email="pi@example.com")
        await GroupBeanie(
            name="Lab Alpha", sso_managed=True, pending_pi_email="pi@example.com"
        ).save()

        await sync_sso_user(user, {"memberOf": ["Lab Alpha"]}, provider)

        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert group.pi_id is not None and str(group.pi_id) == str(user.id)
        assert str(user.id) in {str(a) for a in group.admin_ids}
        assert group.pending_pi_email is None

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_pending_pi_on_sso_group_stays_parked_when_not_asserted(self):
        provider = make_provider(claims={"groups": "memberOf"})
        user = await _create_user(email="pi@example.com")
        await GroupBeanie(
            name="Lab Alpha", sso_managed=True, pending_pi_email="pi@example.com"
        ).save()

        await sync_sso_user(user, {"memberOf": ["Other"]}, provider)

        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert group.pi_id is None
        assert group.pending_pi_email == "pi@example.com"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_sync_claims_pending_pi_and_project_ownership(self, spies):
        pi, owner = spies
        user = await _create_user()

        await sync_sso_user(user, {"email": "x@example.com"}, make_provider())

        pi.assert_awaited_once_with(user)
        owner.assert_awaited_once_with(user)

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_empty_claims_skip_the_pending_claims(self, spies):
        pi, owner = spies
        user = await _create_user()

        await sync_sso_user(user, {}, make_provider())

        pi.assert_not_awaited()
        owner.assert_not_awaited()


# ------------------------------------------------------
# provision_sso_login
# ------------------------------------------------------


def _claims(**extra: Any) -> dict[str, Any]:
    return {"sub": "abc", "email": "jane@example.com", "email_verified": True, **extra}


class TestProvisionLogin:
    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_creates_a_verified_user_and_stamps_the_provider(self):
        user, created = await provision_sso_login(make_provider(), _claims())

        assert created is True
        assert user.email == "jane@example.com"
        assert user.is_verified is True
        assert user.is_active is True
        assert user.is_admin is False
        assert user.sso_provider == "kc"
        stored = await UserBeanie.find_one({"email": "jane@example.com"})
        assert stored is not None and stored.sso_provider == "kc"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_new_user_email_is_lowercased(self):
        user, created = await provision_sso_login(
            make_provider(), _claims(email="Jane.Doe@Example.COM")
        )
        assert created is True
        assert user.email == "jane.doe@example.com"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_existing_user_logs_in_and_is_not_duplicated(self):
        existing = await _create_user(email="jane@example.com")

        user, created = await provision_sso_login(make_provider(), _claims())

        assert created is False
        assert user.id == existing.id
        assert await UserBeanie.find({}).count() == 1

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_sso_provider_stamp_uses_configured_name(self):
        user, _ = await provision_sso_login(
            make_provider(id="kc", sso_provider="keycloak"), _claims()
        )
        assert user.sso_provider == "keycloak"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "claims",
        [
            {"sub": "a", "email_verified": True},
            {"sub": "a", "email": "", "email_verified": True},
            {"sub": "a", "email": "   ", "email_verified": True},
            {"sub": "a", "email": [], "email_verified": True},
            {"sub": "a", "email": None, "email_verified": True},
            {"sub": "a", "email": "not-an-email", "email_verified": True},
        ],
    )
    @beanie_setup(models=MODELS)
    async def test_missing_or_unusable_email_is_sso_failed(self, claims):
        with pytest.raises(SSOLoginRejected) as exc:
            await provision_sso_login(make_provider(), claims)
        assert exc.value.code == "sso_failed"
        assert await UserBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "verified",
        [{"email_verified": False}, {"email_verified": "false"}, {}, {"email_verified": 1}],
    )
    @beanie_setup(models=MODELS)
    async def test_unverified_email_is_rejected(self, verified):
        claims = {"sub": "a", "email": "jane@example.com", **verified}
        with pytest.raises(SSOLoginRejected) as exc:
            await provision_sso_login(make_provider(), claims)
        assert exc.value.code == "email_not_verified"
        assert await UserBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_unverified_email_never_matches_an_existing_account(self):
        await _create_user(email="jane@example.com", is_admin=True)
        with pytest.raises(SSOLoginRejected) as exc:
            await provision_sso_login(
                make_provider(), {"sub": "a", "email": "jane@example.com", "email_verified": False}
            )
        assert exc.value.code == "email_not_verified"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("verified", [False, "false", None])
    @beanie_setup(models=MODELS)
    async def test_assume_email_verified_accepts_any_value(self, verified):
        claims = {"sub": "a", "email": "jane@example.com"}
        if verified is not None:
            claims["email_verified"] = verified
        user, created = await provision_sso_login(make_provider(assume_email_verified=True), claims)
        assert created is True
        assert user.email == "jane@example.com"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["true", "True", " TRUE "])
    @beanie_setup(models=MODELS)
    async def test_email_verified_as_a_string_is_accepted(self, value):
        user, created = await provision_sso_login(make_provider(), _claims(email_verified=value))
        assert created is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("wrap", [lambda v: v, lambda v: [v]])
    @beanie_setup(models=MODELS)
    async def test_email_claim_as_string_or_list_gives_the_same_result(self, wrap):
        user, created = await provision_sso_login(
            make_provider(), _claims(email=wrap("jane@example.com"))
        )
        assert created is True
        assert user.email == "jane@example.com"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_email_read_from_a_configured_claim_name(self):
        provider = make_provider(claims={"email": "mail"})
        user, _ = await provision_sso_login(
            provider, {"sub": "a", "mail": ["jane@example.com"], "email_verified": True}
        )
        assert user.email == "jane@example.com"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_registration_disabled_rejects_an_unknown_email(self, monkeypatch):
        monkeypatch.setattr(settings.auth, "registration_disabled", True)

        with pytest.raises(SSOLoginRejected) as exc:
            await provision_sso_login(make_provider(), _claims())

        assert exc.value.code == "registration_disabled"
        assert await UserBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_registration_disabled_still_lets_an_existing_user_in(self, monkeypatch):
        monkeypatch.setattr(settings.auth, "registration_disabled", True)
        existing = await _create_user(email="jane@example.com")

        user, created = await provision_sso_login(make_provider(), _claims())

        assert created is False
        assert user.id == existing.id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("legacy", ["saml", "google", None])
    @beanie_setup(models=MODELS)
    async def test_accounts_from_former_integrations_still_match_by_email(self, legacy):
        existing = await _create_user(email="jane@example.com", sso_provider=legacy)

        user, created = await provision_sso_login(make_provider(), _claims())

        assert created is False
        assert user.id == existing.id
        assert await UserBeanie.find({}).count() == 1
        stored = await UserBeanie.get(existing.id)
        assert stored is not None
        assert stored.sso_provider == "kc"  # re-stamped with the provider now in use

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "claim_email", ["Jane.Doe@example.com", "jane.doe@example.com", "Jane.Doe@Example.com"]
    )
    @beanie_setup(models=MODELS)
    async def test_mixed_case_stored_email_matches_whatever_case_the_idp_sends(self, claim_email):
        # EmailStr keeps the local part's case and lowercases the domain.
        existing = await _create_user(email="Jane.Doe@example.com", sso_provider="saml")
        assert existing.email == "Jane.Doe@example.com"

        user, created = await provision_sso_login(make_provider(), _claims(email=claim_email))

        assert created is False
        assert user.id == existing.id
        assert await UserBeanie.find({}).count() == 1

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_accounts_differing_only_by_case_are_never_guessed(self):
        await _create_user(email="Jane.Doe@example.com")
        await _create_user(email="jane.DOE@example.com")

        with pytest.raises(SSOLoginRejected) as excinfo:
            await provision_sso_login(make_provider(), _claims(email="jane.doe@example.com"))

        assert excinfo.value.code == "sso_failed"
        # Neither account is signed in to, and no third one is created.
        assert await UserBeanie.find({}).count() == 2

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_lowercase_stored_email_matches_a_mixed_case_claim(self):
        existing = await _create_user(email="jane.doe@example.com")

        user, created = await provision_sso_login(
            make_provider(), _claims(email="Jane.Doe@Example.com")
        )

        assert created is False
        assert user.id == existing.id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("existing_user", [False, True])
    @beanie_setup(models=MODELS)
    async def test_pending_claims_fire_for_existing_and_new_users(self, spies, existing_user):
        pi, owner = spies
        if existing_user:
            await _create_user(email="jane@example.com")

        user, created = await provision_sso_login(make_provider(), _claims())

        assert created is (not existing_user)
        assert pi.await_count >= 1
        assert owner.await_count >= 1
        for spy in (pi, owner):
            assert all(call.args[0].id == user.id for call in spy.await_args_list)

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_pending_pi_designation_is_applied_for_a_new_user(self):
        provider = make_provider(claims={"groups": "groups"})
        await GroupBeanie(
            name="Lab Alpha", sso_managed=True, pending_pi_email="jane@example.com"
        ).save()

        user, created = await provision_sso_login(provider, _claims(groups=["Lab Alpha"]))

        assert created is True
        group = await GroupBeanie.find_one({"name": "Lab Alpha"})
        assert group is not None
        assert group.pi_id is not None and str(group.pi_id) == str(user.id)

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_groups_are_synced_from_a_configurable_claim(self):
        provider = make_provider(claims={"groups": "realm_access.roles"})

        user, _ = await provision_sso_login(
            provider, _claims(realm_access={"roles": ["analyst", "viewer"]})
        )

        groups = await GroupBeanie.find({}).to_list()
        assert {g.name for g in groups} == {"analyst", "viewer"}
        assert all(str(user.id) in _member_ids(g) for g in groups)

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_a_failing_sync_does_not_fail_the_login(self, monkeypatch):
        monkeypatch.setattr(sso_sync, "sync_sso_user", AsyncMock(side_effect=RuntimeError("boom")))

        user, created = await provision_sso_login(make_provider(), _claims())

        assert created is True
        assert user.email == "jane@example.com"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_https_picture_sets_the_provider_avatar(self, monkeypatch):
        from depictio.api.v1.services import avatars

        mock = AsyncMock(return_value=True)
        monkeypatch.setattr(avatars, "set_provider_avatar", mock)
        url = "https://idp.example.org/photos/jane.png"

        user, _ = await provision_sso_login(make_provider(), _claims(picture=url))

        mock.assert_awaited_once_with(user.id, provider="kc", url=url)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "picture",
        [
            "http://idp.example.org/photos/jane.png",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "//idp.example.org/x.png",
            "",
            None,
        ],
    )
    @beanie_setup(models=MODELS)
    async def test_non_https_picture_is_ignored(self, monkeypatch, picture):
        from depictio.api.v1.services import avatars

        mock = AsyncMock(return_value=True)
        monkeypatch.setattr(avatars, "set_provider_avatar", mock)

        await provision_sso_login(make_provider(), _claims(picture=picture))

        mock.assert_not_awaited()

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_picture_claim_unset_never_downloads(self, monkeypatch):
        from depictio.api.v1.services import avatars

        mock = AsyncMock(return_value=True)
        monkeypatch.setattr(avatars, "set_provider_avatar", mock)
        provider = make_provider(claims={"picture": None})

        await provision_sso_login(provider, _claims(picture="https://idp.example.org/p.png"))

        mock.assert_not_awaited()

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_avatar_uses_the_configured_sso_provider_name(self, monkeypatch):
        from depictio.api.v1.services import avatars

        mock = AsyncMock(return_value=True)
        monkeypatch.setattr(avatars, "set_provider_avatar", mock)
        provider = make_provider(sso_provider="keycloak", claims={"picture": "avatar_url"})

        user, _ = await provision_sso_login(
            provider, _claims(avatar_url="https://idp.example.org/a.png")
        )

        mock.assert_awaited_once_with(
            user.id, provider="keycloak", url="https://idp.example.org/a.png"
        )
