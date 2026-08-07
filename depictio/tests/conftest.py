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


# beanie >= 2.1.0 calls
#   database.list_collection_names(nameOnly=True, authorizedCollections=True)
# during init_beanie. mongomock-motor forwards **kwargs straight through to
# mongomock's synchronous Database, which accepts neither argument, so every
# test that inits beanie against the mock dies with a TypeError.
#
# Both arguments are no-ops against a mock: authorizedCollections filters the
# result by the connection's privileges (there is no auth here) and nameOnly is
# a server-side projection hint. beanie only wants the collection names, which
# is what the mock returns either way — so dropping them is safe and keeps the
# real driver untouched.
#
# Remove this once mongomock accepts the kwargs; until then it is what lets the
# beanie pin move at all. See mongomock-motor's with_async_methods() wrapper.
from mongomock_motor import AsyncMongoMockDatabase  # noqa: E402

_list_collection_names = AsyncMongoMockDatabase.list_collection_names
_UNSUPPORTED_LIST_COLLECTION_KWARGS = ("authorizedCollections", "nameOnly")


async def _list_collection_names_compat(self, *args, **kwargs):
    for _kwarg in _UNSUPPORTED_LIST_COLLECTION_KWARGS:
        kwargs.pop(_kwarg, None)
    return await _list_collection_names(self, *args, **kwargs)


AsyncMongoMockDatabase.list_collection_names = _list_collection_names_compat
