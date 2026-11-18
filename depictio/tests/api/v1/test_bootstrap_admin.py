"""First-boot admin seeding (`_bootstrap_admin_and_test_user`) per auth mode."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from depictio.api.v1 import db_init


def _settings(*, single_user: bool, public: bool, email: str = "", password: str = ""):
    mock_settings = MagicMock()
    mock_settings.bootstrap.admin_email = email
    mock_settings.bootstrap.admin_password.get_secret_value.return_value = password
    mock_settings.bootstrap.seed_test_user = False
    mock_settings.auth.is_single_user_mode = single_user
    mock_settings.auth.is_public_mode = public
    mock_settings.auth.is_password_login_disabled = False
    return mock_settings


def _patches(mock_settings, create_user):
    return (
        patch.object(db_init, "settings", mock_settings),
        patch.object(db_init.UserBeanie, "find_one", AsyncMock(return_value=None)),
        patch.object(db_init, "_create_user_in_db", create_user),
        patch.object(db_init, "_resolve_existing_admin_token", AsyncMock(return_value={"t": 1})),
    )


@pytest.mark.asyncio
async def test_public_mode_seeds_default_admin_without_bootstrap_env():
    """A fresh public-mode instance (a SciLifeLab Serve app created public) has no
    admin and no DEPICTIO_BOOTSTRAP_ADMIN_*: it must seed a local admin, as
    single-user mode does, rather than fail startup."""
    admin = MagicMock(email="admin@example.com")
    create_user = AsyncMock(return_value={"success": True, "user": admin})
    p1, p2, p3, p4 = _patches(_settings(single_user=False, public=True), create_user)
    with p1, p2, p3, p4:
        admin_user, _ = await db_init._bootstrap_admin_and_test_user()

    assert admin_user is admin
    kwargs = create_user.await_args.kwargs
    assert kwargs["is_admin"] is True
    assert kwargs["email"] == "admin@example.com"
    # Random, never a known default.
    assert len(kwargs["password"]) >= 32


@pytest.mark.asyncio
async def test_public_mode_prefers_bootstrap_env_when_set():
    admin = MagicMock(email="owner@lab.org")
    create_user = AsyncMock(return_value={"success": True, "user": admin})
    mock_settings = _settings(
        single_user=False, public=True, email="owner@lab.org", password="p" * 20
    )
    p1, p2, p3, p4 = _patches(mock_settings, create_user)
    with p1, p2, p3, p4:
        await db_init._bootstrap_admin_and_test_user()

    kwargs = create_user.await_args.kwargs
    assert kwargs["email"] == "owner@lab.org"
    assert kwargs["password"] == "p" * 20


@pytest.mark.asyncio
async def test_private_multi_user_mode_still_fails_fast():
    """Without public or single-user mode, an instance with no declared admin
    must keep refusing to start: someone has to be able to log in."""
    create_user = AsyncMock()
    p1, p2, p3, p4 = _patches(_settings(single_user=False, public=False), create_user)
    with p1, p2, p3, p4, pytest.raises(RuntimeError, match="No admin user exists"):
        await db_init._bootstrap_admin_and_test_user()
    create_user.assert_not_awaited()
