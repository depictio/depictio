"""Env defaults so spike scripts can import depictio without a live stack.

Mirrors depictio/tests/conftest.py: the Settings() singleton fails fast on a
clean container unless the security-hardening vars are set. These are
spike-only values — never reuse them elsewhere.

Import this module BEFORE any `depictio.*` import.
"""

from __future__ import annotations

import os

_DEFAULTS = {
    "DEPICTIO_CONTEXT": "server",
    "DEPICTIO_MINIO_ROOT_PASSWORD": "xyspike_minio_password_aaaaaaaaaa",
    "DEPICTIO_BOOTSTRAP_ADMIN_EMAIL": "admin@example.com",
    "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD": "xyspike_admin_password_aaaaaaaaaa",
    "DEPICTIO_BOOTSTRAP_SEED_TEST_USER": "true",
    "DEPICTIO_BOOTSTRAP_TEST_USER_PASSWORD": "test_pwd",
    # Local-filesystem Delta reads (the documented perf-testing escape hatch
    # in deltatables_utils.py) — no MinIO needed.
    "DEPICTIO_USE_LOCAL_FILES": "true",
}

for _k, _v in _DEFAULTS.items():
    os.environ.setdefault(_k, _v)
