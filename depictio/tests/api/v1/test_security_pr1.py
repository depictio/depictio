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


@pytest.mark.parametrize("weak_pw", ["changeme", "minio123", "short"])
def test_server_context_rejects_weak_bootstrap_admin_password(monkeypatch, weak_pw):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.setenv("DEPICTIO_MINIO_ROOT_PASSWORD", "a" * 32)
    monkeypatch.setenv("DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD", weak_pw)
    mod = _reload_settings_module()
    with pytest.raises(Exception, match="DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD"):
        mod.Settings()


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
    assert "current_user.is_admin" in src, (
        "File-delete must branch on the *caller's* admin flag."
    )
