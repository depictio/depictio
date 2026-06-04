"""Shared pytest fixtures for the Depictio test suite.

Sets safe defaults for the security-hardening env vars introduced in PR1
so existing tests that import ``depictio.api.v1.configs.config`` keep
working without each test having to wire ``DEPICTIO_MINIO_ROOT_PASSWORD``
and ``DEPICTIO_BOOTSTRAP_*`` itself.

Production deployments set these via their .env / Helm Secret; tests
inherit whatever is already in the env, which is empty in CI runners.
"""

from __future__ import annotations

import os

# Defaults applied BEFORE any depictio module imports happen, so the
# Settings() singleton in depictio.api.v1.configs.config doesn't fail-fast
# on a clean CI runner.
_PYTEST_DEFAULTS = {
    "DEPICTIO_CONTEXT": "server",
    # 32-char dev-only password — passes the >=16 length check and isn't on
    # the well-known weak list. Never reuse outside the test suite.
    "DEPICTIO_MINIO_ROOT_PASSWORD": "pytest_minio_password_aaaaaaaaaa",
    "DEPICTIO_BOOTSTRAP_ADMIN_EMAIL": "admin@example.com",
    "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD": "pytest_admin_password_aaaaaaaaaa",
    "DEPICTIO_BOOTSTRAP_SEED_TEST_USER": "true",
    "DEPICTIO_BOOTSTRAP_TEST_USER_PASSWORD": "test_pwd",
}

for _k, _v in _PYTEST_DEFAULTS.items():
    os.environ.setdefault(_k, _v)
