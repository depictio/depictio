"""Regression tests for the public/demo-mode deployment fixes.

Covers two behaviors that regressed/were tightened after the #779 security work:

1. Reference dashboards must be seeded ``is_public=True`` ONLY when the server runs
   in public/demo mode, and stay private on standard deployments (preserving the
   #779 lockdown). See ``create_dashboard_from_json`` in ``db_init``.
2. A temporary (public/demo) user's TTL must slide forward on every token refresh so
   an active visitor is authorized for the duration of their session and never lapses
   back to the anonymous fallback identity mid-session. See
   ``_rearm_temporary_user_expiry`` in the user endpoints routes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from depictio.models.models.base import PyObjectId

REPO_ROOT = Path(__file__).resolve().parents[4]
IRIS_SEED = REPO_ROOT / "depictio" / "projects" / "init" / "iris" / ".db_seeds" / "dashboard.json"


# ---------------------------------------------------------------------------
# Regression A — reference dashboards public only in public/demo mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("is_public_mode", [True, False])
@pytest.mark.asyncio
async def test_reference_dashboard_is_public_follows_public_mode(is_public_mode: bool) -> None:
    """``create_dashboard_from_json`` seeds ``is_public`` from ``is_public_mode``.

    The bundled seed JSON ships ``is_public=True``, but the create path must override
    it to mirror the server's auth mode: public in public/demo deployments, private
    everywhere else.
    """
    from depictio.api.v1 import db_init

    admin_user = MagicMock()
    admin_user.id = PyObjectId()
    admin_user.email = "admin@example.com"

    mock_collection = MagicMock()
    mock_collection.find_one.return_value = None  # force the create branch

    captured: dict = {}

    async def fake_save_dashboard(dashboard_id, data, current_user):  # noqa: ANN001
        captured["data"] = data
        return {"success": True}

    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = is_public_mode

    with (
        patch("depictio.api.v1.db.dashboards_collection", mock_collection),
        patch.object(db_init, "save_dashboard", side_effect=fake_save_dashboard),
        patch.object(db_init, "settings", mock_settings),
    ):
        await db_init.create_dashboard_from_json(admin_user, str(IRIS_SEED), static_dc_id="")

    assert captured["data"].is_public is is_public_mode


# ---------------------------------------------------------------------------
# Regression B — sliding expiration keeps active temp users authorized
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rearm_temporary_user_expiry_extends_temp_user() -> None:
    """A temporary user's ``expiration_time`` is pushed forward and the record saved."""
    from depictio.api.v1.endpoints.user_endpoints import routes

    mock_settings = MagicMock()
    mock_settings.auth.temporary_user_expiry_hours = 2
    mock_settings.auth.temporary_user_expiry_minutes = 0

    user = MagicMock()
    user.is_temporary = True
    user.save = AsyncMock()

    before = datetime.now()
    with patch.object(routes, "settings", mock_settings):
        await routes._rearm_temporary_user_expiry(user)

    user.save.assert_awaited_once()
    # Re-armed roughly 2h out — well beyond the original 1h demo window.
    assert user.expiration_time > before + timedelta(hours=1, minutes=30)


@pytest.mark.asyncio
async def test_rearm_temporary_user_expiry_skips_regular_and_missing_user() -> None:
    """Non-temporary users (and ``None``) are left untouched."""
    from depictio.api.v1.endpoints.user_endpoints import routes

    regular = MagicMock()
    regular.is_temporary = False
    regular.save = AsyncMock()

    await routes._rearm_temporary_user_expiry(regular)
    regular.save.assert_not_awaited()

    # No user resolved (revoked token edge case) is a safe no-op.
    await routes._rearm_temporary_user_expiry(None)
