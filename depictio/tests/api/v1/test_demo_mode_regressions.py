"""Regression tests for the public/demo-mode deployment fixes.

Covers behaviors tightened after the #779 security work:

1. Dashboard visibility is project-driven: the seeding path defers to
   ``save_dashboard``, whose insert branch stamps ``is_public`` from the parent
   project — reference dashboards follow their (public) reference project.
   Anonymous exposure is governed by the auth mode (public mode), not by
   hiding the flag. See ``create_dashboard_from_json`` in ``db_init`` and the
   insert branch of ``save_dashboard``.
2. A temporary (public/demo) user's TTL must slide forward on every token refresh so
   an active visitor is authorized for the duration of their session and never lapses
   back to the anonymous fallback identity mid-session. See
   ``_rearm_temporary_user_expiry`` in the user endpoints routes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from depictio.models.models.base import PyObjectId

REPO_ROOT = Path(__file__).resolve().parents[4]
IRIS_SEED = REPO_ROOT / "depictio" / "projects" / "init" / "iris" / ".db_seeds" / "dashboard.json"


# ---------------------------------------------------------------------------
# Regression A — dashboard visibility is project-driven, whatever the mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("is_public_mode", [True, False])
@pytest.mark.asyncio
async def test_reference_dashboard_seeding_defers_visibility_to_save(
    is_public_mode: bool,
) -> None:
    """``create_dashboard_from_json`` no longer overrides ``is_public``.

    Visibility is project-driven: the insert branch of ``save_dashboard`` stamps
    the flag from the parent project, so the seeding path must pass the data
    through untouched — identically in public and standard mode.
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

    # Whatever the auth mode, the seeding path passes the seed JSON's value
    # through unchanged — the authoritative value is stamped from the parent
    # project by save_dashboard's insert branch (and converged at startup by
    # reconcile_dashboard_visibility), so the seed's own flag is incidental and
    # must not be read as an assertion about the deployed visibility.
    seeded_is_public = json.loads(IRIS_SEED.read_text())["is_public"]
    assert captured["data"].is_public is seeded_is_public


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


# ---------------------------------------------------------------------------
# Regression C — project export usable by public/demo-mode (non-admin) visitors
# ---------------------------------------------------------------------------


def _export_request(**overrides):
    """Build a MigrateExportRequest with sensible UI-flow defaults."""
    from depictio.api.v1.endpoints.migrate_endpoints.routes import MigrateExportRequest

    params = {"project_id": str(PyObjectId()), "mode": "all"}
    params.update(overrides)
    return MigrateExportRequest(**params)


def _user(is_admin: bool):
    user = MagicMock()
    user.id = PyObjectId()
    user.is_admin = is_admin
    return user


@pytest.mark.asyncio
async def test_export_blocked_for_non_admin_on_standard_instance() -> None:
    """On a standard (non-public) deployment, export stays admin-only."""
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.migrate_endpoints import routes

    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = False

    with patch.object(routes, "settings", mock_settings):
        with pytest.raises(HTTPException) as exc_info:
            await routes.export_project(_export_request(), current_user=_user(is_admin=False))

    assert exc_info.value.status_code == 403
    assert "administrators" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_export_rejects_non_admin_target_s3_config_in_public_mode() -> None:
    """Public-mode visitors may export, but never via the server-to-server S3
    copy path (an exfiltration vector) — only the in-ZIP bundling UI flow."""
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.migrate_endpoints import routes

    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = True

    with patch.object(routes, "settings", mock_settings):
        with pytest.raises(HTTPException) as exc_info:
            await routes.export_project(
                _export_request(target_s3_config={"endpoint_url": "http://evil:9000"}),
                current_user=_user(is_admin=False),
            )

    assert exc_info.value.status_code == 403
    assert "target s3" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_export_in_public_mode_scopes_query_to_readable_projects() -> None:
    """A non-admin public-mode caller clears the admin gate and the project
    lookup is permission-scoped: the Mongo query carries the owner/editor/viewer
    /``is_public`` ``$or`` filter, so a private project they can't read 404s."""
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.migrate_endpoints import routes

    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = True

    mock_projects = MagicMock()
    mock_projects.find_one.return_value = None  # not readable by this visitor

    visitor = _user(is_admin=False)

    with (
        patch.object(routes, "settings", mock_settings),
        patch.object(routes, "projects_collection", mock_projects),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await routes.export_project(_export_request(), current_user=visitor)

    assert exc_info.value.status_code == 404
    query = mock_projects.find_one.call_args.args[0]
    assert "$or" in query
    assert {"is_public": True} in query["$or"]


@pytest.mark.asyncio
async def test_export_admin_query_is_not_permission_scoped() -> None:
    """Admins keep full reach: the lookup is keyed on the project id alone,
    with no permission ``$or`` filter, in every mode."""
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.migrate_endpoints import routes

    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = False

    mock_projects = MagicMock()
    mock_projects.find_one.return_value = None

    with (
        patch.object(routes, "settings", mock_settings),
        patch.object(routes, "projects_collection", mock_projects),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await routes.export_project(_export_request(), current_user=_user(is_admin=True))

    assert exc_info.value.status_code == 404
    query = mock_projects.find_one.call_args.args[0]
    assert "$or" not in query


# ---------------------------------------------------------------------------
# Regression D: project-mutating manifest routes share create_project's gate
# ---------------------------------------------------------------------------
#
# ``POST /projects/from_manifest`` mirrored ``create_project``'s public/demo-mode
# gate from the start; ``ingest_manifest``, ``refresh_manifest`` and
# ``export_template`` did not, so an auto-minted temp user could pull arbitrary
# remote data into (or export) any project they could edit on a demo instance.


def _manifest_route(name: str):
    """(handler, kwargs, downstream attribute to patch) for each gated route.

    ``dry_run=True`` keeps the token minting out of the picture; the
    downstream helper is patched so passing the gate is observable without a
    database.
    """
    from depictio.api.v1.endpoints.projects_endpoints import routes
    from depictio.api.v1.endpoints.projects_endpoints.export_template import (
        ExportTemplateRequest,
    )
    from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import (
        IngestManifestRequest,
        RefreshManifestRequest,
    )

    project_id = str(PyObjectId())
    if name == "ingest_manifest":
        payload = IngestManifestRequest(
            project_id=project_id, manifest_url="https://example.org/m.json", dry_run=True
        )
        return routes.ingest_manifest, {"payload": payload}, "_ingest_manifest_into_project"
    if name == "refresh_manifest":
        payload = RefreshManifestRequest(project_id=project_id, dry_run=True)
        return routes.refresh_manifest, {"payload": payload}, "_refresh_manifest_in_project"
    payload = ExportTemplateRequest(template_id="lab/tool/1")
    return (
        routes.export_project_template,
        {"project_id": project_id, "payload": payload},
        "build_template_bundle",
    )


_GATED_ROUTES = ["ingest_manifest", "refresh_manifest", "export_template"]


@pytest.mark.parametrize("route", _GATED_ROUTES)
@pytest.mark.asyncio
async def test_manifest_routes_blocked_for_non_admin_in_public_mode(route: str) -> None:
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.projects_endpoints import routes

    handler, kwargs, downstream = _manifest_route(route)
    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = True

    with (
        patch.object(routes, "settings", mock_settings),
        patch.object(routes, downstream) as work,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await handler(current_user=_user(is_admin=False), **kwargs)

    assert exc_info.value.status_code == 403
    assert "public/demo mode" in str(exc_info.value.detail)
    work.assert_not_called()


@pytest.mark.parametrize("route", _GATED_ROUTES)
@pytest.mark.parametrize(
    ("is_public_mode", "is_admin"),
    [(True, True), (False, False)],
    ids=["admin-in-public-mode", "non-admin-on-standard-instance"],
)
@pytest.mark.asyncio
async def test_manifest_routes_pass_the_gate_otherwise(
    route: str, is_public_mode: bool, is_admin: bool
) -> None:
    from depictio.api.v1.endpoints.projects_endpoints import routes

    handler, kwargs, downstream = _manifest_route(route)
    mock_settings = MagicMock()
    mock_settings.auth.is_public_mode = is_public_mode

    with (
        patch.object(routes, "settings", mock_settings),
        patch.object(routes, downstream, return_value={"gate": "passed"}) as work,
        patch.object(routes, "bundle_to_zip", return_value=b"zip"),
    ):
        await handler(current_user=_user(is_admin=is_admin), **kwargs)

    work.assert_called_once()
