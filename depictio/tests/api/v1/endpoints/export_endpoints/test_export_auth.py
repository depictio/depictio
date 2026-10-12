"""An export caller without a token reads public projects only, whatever the auth mode.

The docs promise "public projects without a token, private ones need a bearer
token". Two modes broke that before ``public_only_principal``:

* single-user mode stores the anonymous user as an *admin*, and
  ``check_project_permission`` lets an admin through before it looks at
  ``is_public`` — every project became readable from any allow-listed origin;
* multi-user mode stores no anonymous user at all, so anonymous exports 401'd
  in the deployment shape embeds exist for.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.export_endpoints.routes import (
    get_embed_user,
    public_only_principal,
)

_USER_BEANIE = "depictio.api.v1.endpoints.user_endpoints.routes.UserBeanie"
_PROJECTS = "depictio.api.v1.endpoints.dashboards_endpoints.routes.projects_collection"


def _stored_anonymous(*, is_admin: bool) -> SimpleNamespace:
    return SimpleNamespace(id=ObjectId(), is_admin=is_admin, is_anonymous=True)


def _can_view(user, *, is_public: bool) -> bool:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    project_id = ObjectId()
    project = {"_id": project_id, "is_public": is_public, "permissions": {}}
    with patch(_PROJECTS) as projects:
        projects.find_one.return_value = project
        return check_project_permission(project_id, user, "viewer")


class TestPublicOnlyPrincipal:
    @pytest.mark.asyncio
    async def test_single_user_admin_anonymous_is_not_an_admin_here(self) -> None:
        stored = _stored_anonymous(is_admin=True)
        with patch(f"{_USER_BEANIE}.find_one", new=AsyncMock(return_value=stored)):
            principal = await public_only_principal()

        assert principal.is_admin is False
        assert principal.is_anonymous is True
        assert principal.id == stored.id, "same identity as the stored anonymous user"
        assert _can_view(principal, is_public=True)
        assert not _can_view(principal, is_public=False)

    @pytest.mark.asyncio
    async def test_no_stored_anonymous_user_still_reads_public_projects(self) -> None:
        """Multi-user mode: no 401 for the case embeds exist for."""
        with patch(f"{_USER_BEANIE}.find_one", new=AsyncMock(return_value=None)):
            principal = await public_only_principal()

        assert principal.is_admin is False and principal.is_anonymous is True
        assert _can_view(principal, is_public=True)
        assert not _can_view(principal, is_public=False)


class TestGetEmbedUser:
    @pytest.mark.asyncio
    async def test_a_valid_token_keeps_its_rights(self) -> None:
        admin = SimpleNamespace(id=ObjectId(), is_admin=True, is_anonymous=False)
        with patch(
            "depictio.api.v1.endpoints.export_endpoints.routes.get_current_user",
            new=AsyncMock(return_value=admin),
        ):
            assert await get_embed_user(token="t") is admin

    @pytest.mark.asyncio
    async def test_an_invalid_token_falls_back_to_public_only(self) -> None:
        with (
            patch(
                "depictio.api.v1.endpoints.export_endpoints.routes.get_current_user",
                new=AsyncMock(side_effect=HTTPException(status_code=401)),
            ),
            patch(
                f"{_USER_BEANIE}.find_one",
                new=AsyncMock(return_value=_stored_anonymous(is_admin=True)),
            ),
        ):
            user = await get_embed_user(token="expired")
        assert user.is_admin is False and user.is_anonymous is True


class TestViewerFlags:
    """`/auth/me/optional` tells the viewer whether to draw "Export / embed"."""

    @pytest.mark.asyncio
    async def test_flags_follow_the_settings_and_never_name_an_origin(self, monkeypatch) -> None:
        import json

        from depictio.api.v1.endpoints.user_endpoints import routes as user_routes

        monkeypatch.setattr(user_routes.settings.auth, "single_user_mode", False)
        monkeypatch.setattr(user_routes.settings.fastapi, "embed_enabled", True)
        monkeypatch.setattr(
            user_routes.settings.fastapi, "embed_allowed_origins", ["https://lab.example.org"]
        )
        on = await user_routes.get_current_user_info_optional(token=None)
        assert on["embed_enabled"] is True
        assert on["embed_framing_enabled"] is True
        assert "lab.example.org" not in json.dumps(on, default=str), (
            "this endpoint answers without a token: the flag, never the allowlist"
        )

        monkeypatch.setattr(user_routes.settings.fastapi, "embed_enabled", False)
        monkeypatch.setattr(user_routes.settings.fastapi, "embed_allowed_origins", [])
        off = await user_routes.get_current_user_info_optional(token=None)
        assert off["embed_enabled"] is False
        assert off["embed_framing_enabled"] is False
