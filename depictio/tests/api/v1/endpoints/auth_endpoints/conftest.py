"""Fixtures of the SSO tests: caches reset, ``httpx`` replaced by a fake provider."""

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from depictio.api.v1.endpoints.auth_endpoints import oidc
from depictio.tests.api.v1.endpoints.auth_endpoints.fake_idp import FakeIdP


@pytest.fixture(autouse=True)
def _clean_oidc_caches():
    oidc.clear_caches()
    yield
    oidc.clear_caches()


@pytest.fixture
def idp(monkeypatch) -> FakeIdP:
    """A fake provider wired in place of ``httpx.AsyncClient`` in ``oidc``."""
    fake = FakeIdP()
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(fake.handle)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(
        oidc, "httpx", SimpleNamespace(AsyncClient=factory, BasicAuth=httpx.BasicAuth)
    )
    return fake
