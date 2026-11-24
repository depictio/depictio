"""Single-user mode: the owner claims the default admin (email + password).

The zero-config admin is ``admin@example.com`` with a random password nobody
knows. ``POST /auth/me/admin_credentials`` names the credentials the password
form accepts once the instance goes public, on the same account.
"""

from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import SecretStr

from depictio.api.v1 import db_init
from depictio.api.v1.endpoints.user_endpoints import core_functions, rate_limit, routes
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _check_password,
    _create_user_in_db,
    _default_admin,
    _set_default_admin_credentials,
)
from depictio.models.models.users import RequestAdminCredentials, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup


@pytest.fixture
def collections():
    """Projects and dashboards collections, in memory."""
    db = mongomock.MongoClient().db
    with (
        patch("depictio.api.v1.db.projects_collection", db.projects),
        patch("depictio.api.v1.db.dashboards_collection", db.dashboards),
    ):
        yield db


async def _seed_default_admin(**kwargs) -> UserBeanie:
    payload = await _create_user_in_db(
        email="admin@example.com", password="random-unknown-secret", is_admin=True, **kwargs
    )
    return payload["user"]


class TestSetDefaultAdminCredentials:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_first_claim_needs_no_current_password(self, collections):
        admin = await _seed_default_admin()
        assert admin.credentials_claimed is False

        await _set_default_admin_credentials("Me@Lab.org", "my-own-pass-1", None)

        stored = await UserBeanie.get(admin.id)
        assert stored.email == "me@lab.org"
        assert stored.credentials_claimed is True
        assert await _check_password("me@lab.org", "my-own-pass-1") is True

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_later_change_needs_the_current_password(self, collections):
        await _seed_default_admin()
        await _set_default_admin_credentials("me@lab.org", "my-own-pass-1", None)

        for wrong in (None, "", "not-it"):
            with pytest.raises(HTTPException) as exc:
                await _set_default_admin_credentials("me@lab.org", "next-pass-22", wrong)
            assert exc.value.status_code == 400

        await _set_default_admin_credentials("me@lab.org", "next-pass-22", "my-own-pass-1")
        assert await _check_password("me@lab.org", "next-pass-22") is True

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_operator_seeded_admin_is_already_claimed(self, collections):
        """DEPICTIO_BOOTSTRAP_ADMIN_* credentials were chosen: no free claim."""
        await _seed_default_admin(credentials_claimed=True)
        with pytest.raises(HTTPException) as exc:
            await _set_default_admin_credentials("me@lab.org", "my-own-pass-1", None)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_email_of_another_account_is_refused(self, collections):
        await _seed_default_admin()
        await _create_user_in_db(email="taken@lab.org", password="whatever-123")
        with pytest.raises(HTTPException) as exc:
            await _set_default_admin_credentials("taken@lab.org", "my-own-pass-1", None)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_email_collision_ignores_case(self, collections):
        await _seed_default_admin()
        await _create_user_in_db(email="Taken@Lab.org", password="whatever-123")
        with pytest.raises(HTTPException) as exc:
            await _set_default_admin_credentials("taken@lab.org", "my-own-pass-1", None)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_current_password_guesses_lock_the_account(self, collections, monkeypatch):
        """The password the public form accepts costs the same to guess here."""
        fake = FakeRedis()
        monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: fake)
        await _seed_default_admin()
        await _set_default_admin_credentials("me@lab.org", "my-own-pass-1", None)
        for _ in range(rate_limit._LOCKOUT_MAX_FAILURES):
            with pytest.raises(HTTPException):
                await _set_default_admin_credentials("me@lab.org", "next-pass-22", "guess")
        with pytest.raises(HTTPException) as exc:
            await _set_default_admin_credentials("me@lab.org", "next-pass-22", "my-own-pass-1")
        assert exc.value.status_code == 401
        assert await _check_password("me@lab.org", "my-own-pass-1") is True

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_reserved_addresses_are_refused(self, collections):
        await _seed_default_admin()
        for email in ("anonymous@depict.io", "temp_user_x@depictio.temp"):
            with pytest.raises(HTTPException) as exc:
                await _set_default_admin_credentials(email, "my-own-pass-1", None)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_embedded_owner_emails_follow(self, collections):
        admin = await _seed_default_admin()
        other_id = ObjectId()
        owner = {"_id": admin.id, "email": "admin@example.com", "is_admin": True}
        collections.projects.insert_one(
            {"name": "p", "permissions": {"owners": [owner], "viewers": ["*"]}}
        )
        collections.dashboards.insert_one(
            {
                "title": "d",
                "permissions": {
                    "owners": [{"_id": other_id, "email": "x@lab.org"}],
                    "editors": [owner],
                },
            }
        )

        await _set_default_admin_credentials("me@lab.org", "my-own-pass-1", None)

        project = collections.projects.find_one({"name": "p"})
        assert project["permissions"]["owners"][0]["email"] == "me@lab.org"
        assert project["permissions"]["viewers"] == ["*"]
        dashboard = collections.dashboards.find_one({"title": "d"})
        assert dashboard["permissions"]["editors"][0]["email"] == "me@lab.org"
        assert dashboard["permissions"]["owners"][0]["email"] == "x@lab.org"


class FakeRedis:
    def __init__(self):
        self.data: dict[str, int] = {}
        self.ttl: dict[str, int | None] = {}

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def expire(self, key, ttl):
        return True

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = int(value)
        self.ttl[key] = ex
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


def _bootstrap_settings(email="", password="", generated=False):
    return SimpleNamespace(
        bootstrap=SimpleNamespace(
            admin_email=email,
            admin_password=SecretStr(password),
            admin_password_generated=generated,
        )
    )


class TestBackfill:
    """Admins stored before ``credentials_claimed`` existed."""

    @staticmethod
    async def _legacy_admin(email: str) -> UserBeanie:
        payload = await _create_user_in_db(email=email, password="whatever-123", is_admin=True)
        admin = payload["user"]
        await UserBeanie.find_one({"_id": admin.id}).update({"$unset": {"credentials_claimed": ""}})
        return await UserBeanie.get(admin.id)

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    @pytest.mark.parametrize(
        ("email", "settings", "claimed"),
        [
            ("admin@example.com", _bootstrap_settings(), False),
            ("admin@example.com", _bootstrap_settings("admin@example.com", "x", True), False),
            ("admin@example.com", _bootstrap_settings("admin@example.com", "chosen"), True),
            ("owner@lab.org", _bootstrap_settings(), True),
        ],
    )
    async def test_only_the_zero_config_admin_stays_claimable(self, email, settings, claimed):
        admin = await self._legacy_admin(email)
        with patch.object(db_init, "settings", settings):
            await db_init._backfill_credentials_claimed(admin)
        assert (await UserBeanie.get(admin.id)).credentials_claimed is claimed

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_a_stored_value_is_kept(self):
        admin = await _seed_default_admin(credentials_claimed=False)
        admin.email = "owner@lab.org"
        await admin.save()
        with patch.object(db_init, "settings", _bootstrap_settings()):
            await db_init._backfill_credentials_claimed(admin)
        assert (await UserBeanie.get(admin.id)).credentials_claimed is False


class TestDefaultAdmin:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_oldest_admin_wins(self):
        """A second admin never becomes the single-user identity by accident."""
        seeded = await _create_user_in_db(
            id=ObjectId("67658ba033c8b59ad489d7c7"),
            email="admin@example.com",
            password="x-secret-123",
            is_admin=True,
        )
        await _create_user_in_db(email="later@lab.org", password="x-secret-123", is_admin=True)
        assert (await _default_admin()).id == seeded["user"].id


class TestRoute:
    @staticmethod
    def _call(user, *, single_user=True):
        body = RequestAdminCredentials(email="me@lab.org", new_password="my-own-pass-1")
        mock_settings = SimpleNamespace(auth=SimpleNamespace(is_single_user_mode=single_user))
        return mock_settings, body

    @pytest.mark.asyncio
    async def test_refused_outside_single_user_mode(self):
        mock_settings, body = self._call(None, single_user=False)
        admin = SimpleNamespace(is_admin=True)
        with patch.object(routes, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc:
                await routes.set_admin_credentials(SimpleNamespace(), body, admin)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_refused_for_a_non_admin(self):
        mock_settings, body = self._call(None)
        with patch.object(routes, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc:
                await routes.set_admin_credentials(
                    SimpleNamespace(), body, SimpleNamespace(is_admin=False)
                )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_claims_in_single_user_mode(self, collections):
        await _seed_default_admin()
        mock_settings, body = self._call(None)
        mock_settings.auth.anonymous_user_email = "anonymous@depict.io"
        with (
            patch.object(routes, "settings", mock_settings),
            patch.object(core_functions, "settings", mock_settings),
            patch.object(routes, "enforce_rate_limit"),
        ):
            result = await routes.set_admin_credentials(
                SimpleNamespace(), body, SimpleNamespace(is_admin=True)
            )
        assert result == {"success": True, "email": "me@lab.org", "credentials_claimed": True}


def test_lockout_key_follows_email_normalisation():
    """A fullwidth domain reaches the same account, so it shares its counter."""
    assert rate_limit._lockout_key("admin@\uff45xample.com") == rate_limit._lockout_key(
        "Admin@example.com"
    )


def test_password_rules():
    with pytest.raises(ValueError):
        RequestAdminCredentials(email="me@lab.org", new_password="short")
    with pytest.raises(ValueError):
        RequestAdminCredentials(email="me@lab.org", new_password="$2b$12$" + "x" * 40)
    with pytest.raises(ValueError):
        RequestAdminCredentials(email="me@lab.org", new_password="\u00e9" * 40)  # 80 bytes
