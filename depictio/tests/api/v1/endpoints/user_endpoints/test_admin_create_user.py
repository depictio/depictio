"""An admin creating an account with a password the person will change."""

from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _create_user_in_db,
    _edit_password,
)
from depictio.api.v1.endpoints.user_endpoints.routes import admin_create_user
from depictio.models.models.users import RequestAdminCreateUser, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

ADMIN = SimpleNamespace(email="admin@example.org", is_admin=True)
MEMBER = SimpleNamespace(email="member@example.org", is_admin=False)


def _payload(**overrides) -> RequestAdminCreateUser:
    data = {"email": "new.person@example.org", "password": "Start-1234"} | overrides
    return RequestAdminCreateUser(**data)


def _standard_mode():
    """Not single-user, not public: the mode the endpoint is for."""
    return (
        patch.object(
            type(settings.auth),
            "is_single_user_mode",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch.object(
            type(settings.auth),
            "is_public_mode",
            new_callable=PropertyMock,
            return_value=False,
        ),
    )


class TestRequestModel:
    def test_a_short_password_is_refused(self):
        with pytest.raises(ValidationError):
            _payload(password="short")

    def test_a_prehashed_password_is_refused(self):
        with pytest.raises(ValidationError):
            _payload(password="$2b$12$" + "a" * 50)

    def test_the_person_must_change_it_by_default(self):
        assert _payload().must_change_password is True


class TestAdminCreateUser:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_creates_the_account_flagged_for_a_password_change(self):
        single, public = _standard_mode()
        with single, public:
            out = await admin_create_user(_payload(display_name="  New Person "), ADMIN)

        assert out["must_change_password"] is True
        stored = await UserBeanie.find_one({"email": "new.person@example.org"})
        assert stored is not None
        assert stored.must_change_password is True
        assert stored.display_name == "New Person"
        assert stored.is_admin is False
        # The password is stored hashed, and it is the one the admin chose.
        assert stored.password.startswith("$2b$")

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_the_email_is_lowercased(self):
        single, public = _standard_mode()
        with single, public:
            await admin_create_user(_payload(email="Mixed.Case@Example.org"), ADMIN)

        assert await UserBeanie.find_one({"email": "mixed.case@example.org"}) is not None

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_a_duplicate_email_is_a_409(self):
        single, public = _standard_mode()
        with single, public:
            await admin_create_user(_payload(), ADMIN)
            with pytest.raises(HTTPException) as exc:
                await admin_create_user(_payload(), ADMIN)

        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_a_non_admin_cannot_create_accounts(self):
        single, public = _standard_mode()
        with single, public, pytest.raises(HTTPException) as exc:
            await admin_create_user(_payload(), MEMBER)

        assert exc.value.status_code == 403
        assert await UserBeanie.find_one({"email": "new.person@example.org"}) is None

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_not_available_in_public_mode(self):
        with (
            patch.object(
                type(settings.auth),
                "is_public_mode",
                new_callable=PropertyMock,
                return_value=True,
            ),
            pytest.raises(HTTPException) as exc,
        ):
            await admin_create_user(_payload(), ADMIN)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_it_works_when_password_login_is_disabled(self):
        # An SSO-only instance still needs its accounts pre-created: the person
        # is matched by email at the first SSO sign-in.
        single, public = _standard_mode()
        with (
            single,
            public,
            patch.object(
                type(settings.auth),
                "is_password_login_disabled",
                new_callable=PropertyMock,
                return_value=True,
            ),
        ):
            out = await admin_create_user(_payload(), ADMIN)

        assert out["success"] is True


class TestChangingThePassword:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_choosing_a_new_password_clears_the_flag(self):
        created = await _create_user_in_db("flagged@example.org", "Start-1234")
        user = created["user"]
        user.must_change_password = True
        await user.save()

        assert await _edit_password(user.id, "$2b$12$" + "b" * 53) is True

        stored = await UserBeanie.get(user.id)
        assert stored is not None
        assert stored.must_change_password is False
