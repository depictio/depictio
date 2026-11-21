"""Regression tests for the authentication hardening pass.

Covers four gaps:
1. Empty / unusable passwords never authenticate (legacy ``bcrypt("")``
   accounts, the anonymous user, pipeline-provisioned users).
2. A leftover anonymous admin is demoted at startup in multi-user mode.
3. ``must_change_password`` gates every authenticated route except the few
   the change-password flow needs (/auth/me, /auth/me/optional, the password
   change itself, logout) — enforced once in ``get_current_user`` plus the
   refresh endpoint.
4. A code-gated public deployment refuses the tokenless anonymous fallback
   unless the request proves the shared access code the same way
   /auth/public/create_temporary_user does.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bcrypt
import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _check_password,
    _create_user_in_db,
    _demote_anonymous_user_admin,
    _hash_password,
    _verify_password,
)
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_current_user,
    get_user_or_anonymous,
)
from depictio.models.models.users import TokenBeanie, UserBeanie
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

CHANGE_ME = "Change your password first."


class _FakeRequest:
    """Minimal stand-in for starlette's Request: a route path and a body."""

    def __init__(self, body: bytes = b"", path: str = "/depictio/api/v1/somewhere"):
        self._body = body
        self.scope = {"route": SimpleNamespace(path=path)}
        self.url = SimpleNamespace(path=path)

    async def body(self) -> bytes:
        return self._body


# ------------------------------------------------------
# 1. Empty and unusable passwords
# ------------------------------------------------------


class TestEmptyAndUnusablePasswords:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_empty_password_never_authenticates(self):
        """A user with a real password still refuses an empty login string."""
        await UserBeanie(
            email="real@example.com", password=_hash_password("real_password")
        ).create()

        assert await _check_password("real@example.com", "") is False
        assert await _check_password("real@example.com", "real_password") is True

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_legacy_empty_hash_account_cannot_sign_in(self):
        """Accounts created with bcrypt("") stored must stay locked out.

        This is the original gap: such an account signed in with an *empty*
        password. The empty-password rule closes it for existing rows too.
        """
        legacy_hash = bcrypt.hashpw(b"", bcrypt.gensalt()).decode("utf-8")
        await UserBeanie(email="legacy@example.com", password=legacy_hash).create()

        assert await _check_password("legacy@example.com", "") is False
        assert await _check_password("legacy@example.com", "not_the_password") is False

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_anonymous_user_never_authenticates_by_password(self):
        """Even a matching password must not sign the anonymous user in."""
        await UserBeanie(
            email="anonymous@depict.io",
            password=_hash_password("some_password"),
            is_anonymous=True,
        ).create()

        assert await _check_password("anonymous@depict.io", "some_password") is False
        assert await _check_password("anonymous@depict.io", "") is False

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_passwordless_creation_stores_an_unusable_hash(self):
        """_create_user_in_db with an empty password must not store bcrypt("")."""
        first = await _create_user_in_db(email="anon1@example.com", password="", is_anonymous=True)
        second = await _create_user_in_db(email="anon2@example.com", password="")

        first_hash = first["user"].password
        second_hash = second["user"].password
        # Still a valid bcrypt hash (the model validator requires it)...
        assert first_hash.startswith("$2b$")
        # ...but of a random secret nobody knows, not of the empty string.
        assert _verify_password(first_hash, "") is False
        assert _verify_password(first_hash, "admin") is False
        assert first_hash != second_hash
        # And no password at all signs in as the account.
        assert await _check_password("anon1@example.com", "") is False
        assert await _check_password("anon1@example.com", "anything") is False

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_provisioned_user_cannot_login_via_the_login_form(self, test_client):
        """End to end: a pipeline-provisioned user cannot POST /auth/login."""
        await _create_user_in_db(email="provisioned@example.com", password="")

        response = test_client.post(
            "/depictio/api/v1/auth/login",
            data={"username": "provisioned@example.com", "password": ""},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        # 401 when the empty password reaches the credential check,
        # 422 when the form layer already refuses the empty field.
        assert response.status_code in (401, 422)

        response = test_client.post(
            "/depictio/api/v1/auth/login",
            data={"username": "provisioned@example.com", "password": "guess"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 401

    def test_verify_password_tolerates_a_non_bcrypt_stored_value(self):
        """A corrupted stored value must not crash the login route."""
        assert _verify_password("not-a-bcrypt-hash", "password") is False


# ------------------------------------------------------
# 2. Leftover anonymous admin demoted at startup
# ------------------------------------------------------


class TestAnonymousAdminDemotion:
    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_demotes_a_leftover_anonymous_admin(self):
        await UserBeanie(
            email="anonymous@depict.io",
            password=_hash_password("x"),
            is_anonymous=True,
            is_admin=True,
        ).create()

        assert await _demote_anonymous_user_admin() is True

        stored = await UserBeanie.find_one({"email": "anonymous@depict.io"})
        assert stored is not None
        assert stored.is_admin is False

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_noop_when_already_non_admin(self):
        await UserBeanie(
            email="anonymous@depict.io",
            password=_hash_password("x"),
            is_anonymous=True,
            is_admin=False,
        ).create()

        assert await _demote_anonymous_user_admin() is False

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie])
    async def test_noop_when_no_anonymous_user(self):
        assert await _demote_anonymous_user_admin() is False

    @pytest.mark.asyncio
    async def test_run_initialization_demotes_in_multi_user_mode(self):
        """The startup path demotes when the instance needs no anonymous user."""
        from depictio.api.v1 import initialization

        admin = SimpleNamespace(id="abc", email="admin@example.com")
        with (
            patch.object(initialization, "settings") as mock_settings,
            patch.object(initialization, "initialize_db", new_callable=AsyncMock) as mock_init,
            patch.object(initialization, "create_bucket"),
            patch.object(initialization, "S3_storage_checks"),
            patch.object(
                initialization, "_create_anonymous_user", new_callable=AsyncMock
            ) as mock_create,
            patch.object(
                initialization, "_demote_anonymous_user_admin", new_callable=AsyncMock
            ) as mock_demote,
            patch("depictio.api.v1.db.initialization_collection"),
        ):
            mock_settings.auth.requires_anonymous_user = False
            mock_settings.auth.is_demo_mode = False
            mock_init.return_value = admin

            await initialization.run_initialization()

            mock_demote.assert_awaited_once()
            mock_create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_initialization_keeps_the_anonymous_user_when_needed(self):
        from depictio.api.v1 import initialization

        admin = SimpleNamespace(id="abc", email="admin@example.com")
        with (
            patch.object(initialization, "settings") as mock_settings,
            patch.object(initialization, "initialize_db", new_callable=AsyncMock) as mock_init,
            patch.object(initialization, "create_bucket"),
            patch.object(initialization, "S3_storage_checks"),
            patch.object(
                initialization, "_create_anonymous_user", new_callable=AsyncMock
            ) as mock_create,
            patch.object(
                initialization, "_demote_anonymous_user_admin", new_callable=AsyncMock
            ) as mock_demote,
            patch("depictio.api.v1.db.initialization_collection"),
        ):
            mock_settings.auth.requires_anonymous_user = True
            mock_init.return_value = admin

            await initialization.run_initialization()

            mock_create.assert_awaited_once()
            mock_demote.assert_not_awaited()


# ------------------------------------------------------
# 3. must_change_password gate
# ------------------------------------------------------


class TestMustChangePasswordGate:
    @staticmethod
    def _flagged_user() -> UserBeanie:
        return UserBeanie(
            email="flagged@example.com",
            password=_hash_password("Start-1234"),
            must_change_password=True,
        )

    async def _current_user_with(self, user, request):
        with patch(
            "depictio.api.v1.endpoints.user_endpoints.routes._async_fetch_user_from_token",
            new_callable=AsyncMock,
            return_value=user,
        ):
            return await get_current_user("some_token", request)

    @pytest.mark.asyncio
    async def test_flagged_user_is_refused_on_an_authenticated_route(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._current_user_with(self._flagged_user(), None)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == CHANGE_ME

    @pytest.mark.asyncio
    async def test_flagged_user_is_refused_on_a_named_route(self):
        request = _FakeRequest(path="/depictio/api/v1/dashboards")
        with pytest.raises(HTTPException) as exc_info:
            await self._current_user_with(self._flagged_user(), request)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == CHANGE_ME

    @pytest.mark.asyncio
    async def test_flagged_user_keeps_the_exempted_routes(self):
        user = self._flagged_user()
        for path in (
            "/depictio/api/v1/auth/me",
            "/depictio/api/v1/auth/me/optional",
            "/depictio/api/v1/auth/edit_password",
        ):
            assert await self._current_user_with(user, _FakeRequest(path=path)) is user

    @pytest.mark.asyncio
    async def test_unflagged_user_is_unchanged(self):
        user = UserBeanie(email="fine@example.com", password=_hash_password("pw"))
        assert await self._current_user_with(user, None) is user

    @pytest.mark.asyncio
    async def test_get_user_or_anonymous_propagates_the_gate(self):
        """The 403 must not be swallowed by the anonymous fallback."""
        with (
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes._async_fetch_user_from_token",
                new_callable=AsyncMock,
                return_value=self._flagged_user(),
            ),
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes.UserBeanie.find_one"
            ) as mock_find,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_user_or_anonymous(
                    token="some_token", request=_FakeRequest(path="/depictio/api/v1/projects")
                )

            assert exc_info.value.status_code == 403
            assert exc_info.value.detail == CHANGE_ME
            # No anonymous fallback lookup happened.
            mock_find.assert_not_called()

    @staticmethod
    def _login(test_client, email, password):
        return test_client.post(
            "/depictio/api/v1/auth/login",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    @pytest.mark.asyncio
    @beanie_setup(models=[UserBeanie, TokenBeanie])
    async def test_full_change_password_flow_over_http(self, test_client):
        """Login succeeds, everything else is 403 until the password is changed."""
        await _create_user_in_db(email="flagged@example.com", password="Start-1234")
        user = await UserBeanie.find_one({"email": "flagged@example.com"})
        user.must_change_password = True
        await user.save()

        # Login itself still succeeds so the UI can show the change form.
        login = self._login(test_client, "flagged@example.com", "Start-1234")
        assert login.status_code == 200
        access_token = login.json()["access_token"]
        refresh_token = login.json()["refresh_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # /auth/me is exempt (the SPA needs the identity to render the form).
        me = test_client.get("/depictio/api/v1/auth/me", headers=headers)
        assert me.status_code == 200

        # Any other authenticated route is refused.
        listing = test_client.get("/depictio/api/v1/auth/list_tokens", headers=headers)
        assert listing.status_code == 403
        assert listing.json()["detail"] == CHANGE_ME

        # So is the token refresh.
        refresh = test_client.post(
            "/depictio/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert refresh.status_code == 403
        assert refresh.json()["detail"] == CHANGE_ME

        # The password change route is exempt and clears the flag.
        change = test_client.post(
            "/depictio/api/v1/auth/edit_password",
            json={"old_password": "Start-1234", "new_password": "My-own-pass-1"},
            headers=headers,
        )
        assert change.status_code == 200
        assert change.json()["success"] is True

        stored = await UserBeanie.find_one({"email": "flagged@example.com"})
        assert stored.must_change_password is False

        # The same token now passes the gate, and refresh works again.
        listing = test_client.get("/depictio/api/v1/auth/list_tokens", headers=headers)
        assert listing.status_code == 200

        refresh = test_client.post(
            "/depictio/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert refresh.status_code == 200


# ------------------------------------------------------
# 4. Public access code gates the anonymous fallback
# ------------------------------------------------------


class TestPublicAccessCodeGate:
    def _settings(self, mock_settings, code_required=True):
        mock_settings.auth.is_public_mode = True
        mock_settings.auth.is_single_user_mode = False
        mock_settings.auth.is_public_access_code_required = code_required
        # Verify exactly the way create_temporary_user does: the shared
        # secret compared against the submitted candidate.
        mock_settings.auth.verify_public_access_code = lambda candidate: candidate == "letmein"

    @pytest.fixture
    def anon_user(self):
        return UserBeanie(
            email="anonymous@depict.io",
            password=_hash_password("x"),
            is_anonymous=True,
        )

    @pytest.mark.asyncio
    async def test_tokenless_fallback_refused_without_proof(self, anon_user):
        with (
            patch("depictio.api.v1.endpoints.user_endpoints.routes.settings") as mock_settings,
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes.UserBeanie.find_one",
                new_callable=AsyncMock,
                return_value=anon_user,
            ) as mock_find,
        ):
            self._settings(mock_settings)

            with pytest.raises(HTTPException) as exc_info:
                await get_user_or_anonymous(token=None, request=_FakeRequest())
            assert exc_info.value.status_code == 401

            with pytest.raises(HTTPException):
                await get_user_or_anonymous(token=None, request=_FakeRequest(body=b""))
            with pytest.raises(HTTPException):
                await get_user_or_anonymous(
                    token=None,
                    request=_FakeRequest(body=b'{"access_code": "wrong"}'),
                )
            # The anonymous lookup never ran.
            mock_find.assert_not_called()

    @pytest.mark.asyncio
    async def test_tokenless_fallback_allows_a_valid_code(self, anon_user):
        with (
            patch("depictio.api.v1.endpoints.user_endpoints.routes.settings") as mock_settings,
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes.UserBeanie.find_one",
                new_callable=AsyncMock,
                return_value=anon_user,
            ),
        ):
            self._settings(mock_settings)

            result = await get_user_or_anonymous(
                token=None,
                request=_FakeRequest(body=b'{"access_code": "letmein"}'),
            )
            assert result is anon_user

    @pytest.mark.asyncio
    async def test_fallback_untouched_when_no_code_is_configured(self, anon_user):
        with (
            patch("depictio.api.v1.endpoints.user_endpoints.routes.settings") as mock_settings,
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes.UserBeanie.find_one",
                new_callable=AsyncMock,
                return_value=anon_user,
            ),
        ):
            self._settings(mock_settings, code_required=False)

            result = await get_user_or_anonymous(token=None, request=_FakeRequest())
            assert result is anon_user

    @pytest.mark.asyncio
    async def test_a_valid_token_bypasses_the_code_check(self, anon_user):
        """A signed-in visitor (temporary user session) is not asked for the code."""
        temp_user = UserBeanie(email="temp@example.com", password=_hash_password("x"))
        with (
            patch("depictio.api.v1.endpoints.user_endpoints.routes.settings") as mock_settings,
            patch(
                "depictio.api.v1.endpoints.user_endpoints.routes._async_fetch_user_from_token",
                new_callable=AsyncMock,
                return_value=temp_user,
            ),
        ):
            self._settings(mock_settings)

            result = await get_user_or_anonymous(token="a_valid_token", request=_FakeRequest())
            assert result is temp_user
