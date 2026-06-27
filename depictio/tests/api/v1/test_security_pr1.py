"""Regression coverage for the PR1 security hardening pass.

Each test pins one of the previously-found CRITICAL/HIGH issues so a future
edit can't silently reopen it:

* MinIO password validator (settings_models.Settings)
* Bootstrap admin password validator
* CORS config — '*' + credentials must raise
* /register must not honour client-supplied is_admin
* IDOR file-delete predicate uses the caller's admin flag, not the file's
"""

from __future__ import annotations

import importlib

import pytest

# ---------------------------------------------------------------------------
# Settings-level fail-fast — context=server only
# ---------------------------------------------------------------------------


def _reload_settings_module():
    """Re-import settings_models so env-var changes are picked up fresh."""
    import depictio.api.v1.configs.settings_models as mod

    return importlib.reload(mod)


@pytest.mark.parametrize(
    "weak_pw",
    ["", "minio", "minio123", "changeme", "admin", "test_pwd", "short"],
)
def test_server_context_rejects_weak_minio_password(monkeypatch, weak_pw):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.setenv("DEPICTIO_MINIO_ROOT_PASSWORD", weak_pw)
    monkeypatch.setenv("DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD", "x" * 32)
    mod = _reload_settings_module()
    with pytest.raises(Exception, match="DEPICTIO_MINIO_ROOT_PASSWORD"):
        mod.Settings()


def test_server_context_accepts_strong_minio_password(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.setenv("DEPICTIO_MINIO_ROOT_PASSWORD", "a" * 32)
    monkeypatch.setenv("DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD", "")
    mod = _reload_settings_module()
    s = mod.Settings()
    # SecretStr keeps the real value out of repr/dump output
    assert "a" * 32 not in repr(s.minio)
    assert s.minio.aws_secret_access_key == "a" * 32


def test_client_context_skips_minio_check(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "client")
    monkeypatch.delenv("DEPICTIO_MINIO_ROOT_PASSWORD", raising=False)
    mod = _reload_settings_module()
    mod.Settings()  # no raise


@pytest.mark.parametrize("weak_pw", ["minio123", "short"])
def test_server_context_rejects_weak_bootstrap_admin_password(monkeypatch, weak_pw):
    """minio123 is in _WEAK_PASSWORDS; passwords < 8 chars are rejected."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "false")
    monkeypatch.setenv("DEPICTIO_MINIO_ROOT_PASSWORD", "a" * 32)
    monkeypatch.setenv("DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD", weak_pw)
    mod = _reload_settings_module()
    with pytest.raises(Exception, match="DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD"):
        mod.Settings()


def test_server_context_allows_changeme_for_admin(monkeypatch):
    """changeme is intentionally allowed for the bootstrap admin (local dev default)."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "false")
    monkeypatch.setenv("DEPICTIO_MINIO_ROOT_PASSWORD", "a" * 32)
    monkeypatch.setenv("DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD", "changeme")
    mod = _reload_settings_module()
    mod.Settings()  # must not raise


# ---------------------------------------------------------------------------
# Mass-assignment guard on /register
# ---------------------------------------------------------------------------


def test_request_user_registration_drops_is_admin():
    """The model must not carry an is_admin field — clients can't self-promote."""
    from depictio.models.models.users import RequestUserRegistration

    req = RequestUserRegistration.model_validate(
        {"email": "u@example.com", "password": "p" * 16, "is_admin": True}
    )
    assert not hasattr(req, "is_admin"), (
        "RequestUserRegistration.is_admin must be removed to prevent self-promotion."
    )


# ---------------------------------------------------------------------------
# IDOR file-delete predicate
# ---------------------------------------------------------------------------


def test_file_delete_query_uses_caller_admin_flag():
    """Non-admin callers can only match files they own; admins match by id only.

    Pure-Python check on the predicate-building branch — we don't need a
    live Mongo, just that the wrong branch isn't taken.
    """
    import ast
    import inspect

    from depictio.api.v1.endpoints.files_endpoints import routes as files_routes

    source = inspect.getsource(files_routes.delete_file)
    tree = ast.parse(source)
    src = ast.unparse(tree)
    # The exploitable predicate from the original bug:
    assert '"permissions.owners.is_admin": True' not in src, (
        "File-delete predicate must NOT key off the file owner's admin flag — "
        "that lets any caller delete files whose owner happens to be admin."
    )
    assert "current_user.is_admin" in src, "File-delete must branch on the *caller's* admin flag."


# ---------------------------------------------------------------------------
# edit_password must await the async old-password check
# ---------------------------------------------------------------------------


def test_edit_password_awaits_old_password_check():
    """``_check_password`` is async — a missing ``await`` makes the call return a
    truthy coroutine, silently bypassing the old-password check. Pin the await.
    """
    import ast
    import inspect

    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes

    tree = ast.parse(inspect.getsource(user_routes.edit_password))

    checked = False
    for node in ast.walk(tree):
        # Find the `not _check_password(...)` predicate and require it be awaited.
        if isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == "_check_password"
        ):
            parents = [a for a in ast.walk(tree) if isinstance(a, ast.Await) and a.value is node]
            assert parents, (
                "edit_password must `await _check_password(...)` — without await the "
                "old-password verification is bypassed entirely."
            )
            checked = True
    assert checked, "Expected edit_password to call _check_password()."


# ---------------------------------------------------------------------------
# PR-B — /advanced_viz/data must gate caller-supplied dc_ids
# ---------------------------------------------------------------------------


def test_advanced_viz_data_calls_dc_access_gate():
    """The data endpoint loads deltatables from caller-supplied ids — pin the
    `_assert_dc_access(...)` gate so it can't be silently dropped."""
    import inspect

    from depictio.api.v1.endpoints.advanced_viz_endpoints import routes as viz_routes

    src = inspect.getsource(viz_routes.fetch_advanced_viz_data)
    assert "_assert_dc_access(" in src, (
        "/advanced_viz/data must assert DC access before loading data — "
        "without it any caller can exfiltrate any data collection by id."
    )


def test_assert_dc_access_denies_non_member():
    """Non-admin callers with no owner/viewer/public match get a 404 (existence-
    hiding); admins skip the membership $or entirely."""
    from unittest.mock import MagicMock, patch

    from bson import ObjectId
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import _assert_dc_access

    dc_id = ObjectId()
    non_admin = MagicMock(is_admin=False, id=ObjectId())
    admin = MagicMock(is_admin=True, id=ObjectId())

    mock_collection = MagicMock()
    with patch("depictio.api.v1.db.projects_collection", mock_collection):
        # Non-member, non-admin: denied with 404 and the query carries the
        # membership $or clause.
        mock_collection.find_one.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _assert_dc_access(dc_id, non_admin)
        assert exc_info.value.status_code == 404  # type: ignore[unresolved-attribute]
        assert "$or" in mock_collection.find_one.call_args[0][0]

        # Admin: membership filter skipped, no raise when the project exists.
        mock_collection.find_one.reset_mock()
        mock_collection.find_one.return_value = {"_id": ObjectId()}
        _assert_dc_access(dc_id, admin)
        assert "$or" not in mock_collection.find_one.call_args[0][0]


# ---------------------------------------------------------------------------
# PR-B — compute cache keys must be user-bound
# ---------------------------------------------------------------------------


def test_compute_cache_key_binds_user_id():
    """Identical payloads from different users must produce different job_ids,
    otherwise user B can read user A's cached compute result."""
    from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import _compute_cache_key

    payload = {"dc_id": "abc", "method": "umap", "params": {"n_neighbors": 15}}
    key_a = _compute_cache_key(payload, "user-a")
    key_b = _compute_cache_key(payload, "user-b")
    assert key_a != key_b, "Cache key must bind user_id — payload-only keys are guessable."
    # Stable for the same user (cache still functions as a cache).
    assert key_a == _compute_cache_key(payload, "user-a")


# ---------------------------------------------------------------------------
# PR-B — /serve/image bucket lock + traversal hardening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_image_rejects_cross_bucket():
    """s3_path pointing at any bucket other than the configured one → 403."""
    from unittest.mock import MagicMock, patch

    from fastapi import HTTPException

    from depictio.api.v1.endpoints.files_endpoints import routes as files_routes

    mock_settings = MagicMock()
    mock_settings.minio.bucket = "depictio-bucket"
    with patch.object(files_routes, "settings", mock_settings):
        with pytest.raises(HTTPException) as exc_info:
            await files_routes.serve_image(s3_path="s3://other-bucket/some/image.png")
        assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    "bad_key",
    [
        "",  # empty
        "../etc/secret.png",  # raw traversal
        "a/../../b.png",  # traversal that survives a naive prefix check
        "/absolute/path.png",  # absolute key
        "a/./b.png",  # non-canonical — rejected post-normalization
        "a//b.png",  # duplicate slash — rejected post-normalization
        "evil.txt",  # unsupported extension
    ],
)
def test_validate_image_path_rejects_traversal(bad_key):
    from depictio.api.v1.endpoints.files_endpoints.routes import _validate_image_path

    assert not _validate_image_path(bad_key)


@pytest.mark.parametrize("good_key", ["dc_id/run/image.png", "shot.JPG", "a/b/c/plot.webp"])
def test_validate_image_path_accepts_canonical_keys(good_key):
    from depictio.api.v1.endpoints.files_endpoints.routes import _validate_image_path

    assert _validate_image_path(good_key)


# ---------------------------------------------------------------------------
# PR-B — update_project_permissions mass-assignment guard
# ---------------------------------------------------------------------------


def test_update_project_permissions_validates_payload():
    """The route must persist schema-validated permissions (with the ≥1-owner
    invariant), never the raw caller-supplied dict."""
    import inspect

    from depictio.api.v1.endpoints.projects_endpoints import routes as project_routes

    src = inspect.getsource(project_routes.add_or_update_permission)
    assert "Permission.model_validate(" in src, (
        "Permissions payload must be validated through the Permission schema."
    )
    assert 'project["permissions"] = validated_permissions.dict()' in src, (
        "Only the validated permissions object may be persisted."
    )
    assert 'project["permissions"] = permission_request.permissions' not in src, (
        "Raw caller-supplied permissions dict must never be written (mass-assignment)."
    )
    assert "not validated_permissions.owners" in src, (
        "A project must keep at least one owner — the emptiness guard is required."
    )


# ---------------------------------------------------------------------------
# PR-B — /register account-enumeration guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_collapses_duplicate_email_to_generic_error():
    """Duplicate-email registration must return the same generic 400 as any
    other failure — 'User already exists' leaks which accounts exist."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import HTTPException

    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
    from depictio.models.models.users import RequestUserRegistration

    registration = RequestUserRegistration(email="dup@example.com", password="p" * 16)
    mock_settings = MagicMock()
    mock_settings.auth.is_single_user_mode = False
    mock_settings.auth.is_public_mode = False
    mock_settings.auth.registration_disabled = False

    with (
        patch.object(user_routes, "settings", mock_settings),
        patch.object(user_routes, "enforce_rate_limit"),
        patch.object(
            user_routes,
            "_create_user_in_db",
            AsyncMock(return_value={"success": False, "message": "User already exists"}),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await user_routes.register(registration, MagicMock())

    assert exc_info.value.status_code == 400  # type: ignore[unresolved-attribute]
    detail = str(exc_info.value.detail)  # type: ignore[unresolved-attribute]
    assert "exist" not in detail.lower(), f"Enumeration leak in register error: {detail!r}"
    assert detail == user_routes._REGISTER_GENERIC_ERROR


@pytest.mark.asyncio
async def test_register_blocked_when_registration_disabled():
    """With DEPICTIO_AUTH_REGISTRATION_DISABLED set, /register must 403 before
    creating any user — only pre-provisioned accounts may log in."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import HTTPException

    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
    from depictio.models.models.users import RequestUserRegistration

    registration = RequestUserRegistration(email="new@example.com", password="p" * 16)
    mock_settings = MagicMock()
    mock_settings.auth.is_single_user_mode = False
    mock_settings.auth.is_public_mode = False
    mock_settings.auth.registration_disabled = True

    create_user = AsyncMock()
    with (
        patch.object(user_routes, "settings", mock_settings),
        patch.object(user_routes, "enforce_rate_limit"),
        patch.object(user_routes, "_create_user_in_db", create_user),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await user_routes.register(registration, MagicMock())

    assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]
    create_user.assert_not_awaited()


# ---------------------------------------------------------------------------
# PR-C — backup restore: backup_id format + path containment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../../../etc/passwd",
        "foo/bar",
        "abc",
        "20250627_12345",  # one digit short
        "20250627_123456.json",
        "",
    ],
)
def test_backup_id_format_rejected(bad_id):
    """backup_id is concatenated into a filename — anything but the canonical
    YYYYMMDD_HHMMSS timestamp must 422 before a path is built."""
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.backup_endpoints.routes import _validate_backup_id

    with pytest.raises(HTTPException) as exc_info:
        _validate_backup_id(bad_id)
    assert exc_info.value.status_code == 422  # type: ignore[unresolved-attribute]


def test_backup_id_canonical_format_accepted(tmp_path):
    from depictio.api.v1.endpoints.backup_endpoints.routes import (
        _resolve_backup_path,
        _validate_backup_id,
    )

    _validate_backup_id("20250627_123456")  # no raise
    resolved = _resolve_backup_path(str(tmp_path), "20250627_123456")
    assert resolved.endswith("depictio_backup_20250627_123456.json")


# ---------------------------------------------------------------------------
# PR-C — migrate /export-project SSRF gate
# ---------------------------------------------------------------------------


def test_export_project_rejects_unlisted_s3_endpoint():
    """Caller-supplied S3 endpoints are rejected unless they match the
    deployment's own MinIO endpoint or the operator allowlist (default empty)."""
    from unittest.mock import MagicMock, patch

    from fastapi import HTTPException

    from depictio.api.v1.endpoints.migrate_endpoints import routes as migrate_routes

    mock_settings = MagicMock()
    mock_settings.minio.endpoint_url = "http://minio:9000"
    mock_settings.backup.migration_allowed_s3_endpoints = ["https://allowed.example.com"]

    with patch.object(migrate_routes, "settings", mock_settings):
        # Arbitrary external endpoint → 403 (SSRF/exfiltration gate).
        with pytest.raises(HTTPException) as exc_info:
            migrate_routes._validate_target_s3_endpoint(
                {"endpoint_url": "http://169.254.169.254/latest/meta-data"}
            )
        assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]

        # Own MinIO endpoint → allowed (self-migration).
        migrate_routes._validate_target_s3_endpoint({"endpoint_url": "http://minio:9000"})

        # Allowlisted endpoint → allowed; near-miss port → 403.
        migrate_routes._validate_target_s3_endpoint({"endpoint_url": "https://allowed.example.com"})
        with pytest.raises(HTTPException) as exc_info:
            migrate_routes._validate_target_s3_endpoint(
                {"endpoint_url": "https://allowed.example.com:9999"}
            )
        assert exc_info.value.status_code == 403  # type: ignore[unresolved-attribute]

        # Missing/malformed endpoint → 400.
        with pytest.raises(HTTPException) as exc_info:
            migrate_routes._validate_target_s3_endpoint({"endpoint_url": ""})
        assert exc_info.value.status_code == 400  # type: ignore[unresolved-attribute]
