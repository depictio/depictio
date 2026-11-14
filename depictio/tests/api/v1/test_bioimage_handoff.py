"""Handing a bioimage store off to a viewer on another origin.

A public project's store reads carry CORS (an anonymous visitor could read
them anyway); a private store is reached through a signed link that names one
store of one DC, reads only, expires and can be revoked. Links are off unless
``DEPICTIO_BIOIMAGE_HANDOFF_ENABLED``. Nothing else ever gets CORS: in
single-user mode the anonymous user reads every project, and a blanket grant
would let any web page read them.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from depictio.api.v1.configs import config as config_module
from depictio.api.v1.configs.settings_models import BioimageConfig
from depictio.api.v1.endpoints.advanced_viz_endpoints import bioimage_handoff
from depictio.tests.api.v1.test_bioimage_endpoint import (
    AUTH,
    DC_ID,
    PREFIX,
    Env,
    key_url,
    make_store,
)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# `path` in a mint answer is relative to the API base, as the SPA's API_BASE is.
API = PREFIX.removesuffix("/advanced_viz")
ON = BioimageConfig(handoff_enabled=True, handoff_ttl_minutes=5)


class FakeRedis:
    def __init__(self):
        self.keys: dict[str, int] = {}

    def exists(self, key):
        return int(key in self.keys)

    def set(self, key, value, ex=None):
        self.keys[key] = ex


@pytest.fixture(autouse=True)
def keys():
    with (
        patch("depictio.api.v1.key_utils.get_private_key", lambda *_: _KEY),
        patch("depictio.api.v1.key_utils.get_public_key", lambda *_: _KEY.public_key()),
        patch.object(config_module, "ALGORITHM", "RS256"),
    ):
        yield


@pytest.fixture
def redis():
    fake = FakeRedis()
    with patch.object(bioimage_handoff, "_redis", lambda: fake):
        yield fake


def _env(tmp_path, **kw):
    env = Env(tmp_path, **kw)
    store = tmp_path / "sample_A.zarr"
    env.register(store if store.exists() else make_store(tmp_path))
    return env


def _mint(client, store="sample_A.zarr"):
    resp = client.post(f"{PREFIX}/bioimage/{DC_ID}/{store}/handoff", headers=AUTH)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestCors:
    def test_a_private_store_read_carries_no_cors(self, tmp_path):
        with _env(tmp_path) as client:
            resp = client.get(key_url("sample_A.zarr", ".zattrs"), headers=AUTH)
        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers

    def test_a_public_store_read_carries_cors_even_on_a_miss(self, tmp_path):
        with _env(tmp_path, public=True) as client:
            hit = client.get(key_url("sample_A.zarr", ".zattrs"), headers=AUTH)
            miss = client.get(key_url("sample_A.zarr", "0/9.9.9"), headers=AUTH)
        assert hit.headers["access-control-allow-origin"] == "*"
        assert "Content-Range" in hit.headers["access-control-expose-headers"]
        # A cross-origin zarr reader must be able to read the 404 as an empty chunk.
        assert miss.status_code == 404
        assert miss.headers["access-control-allow-origin"] == "*"

    def test_status_says_how_a_store_can_be_handed_off(self, tmp_path):
        env = _env(tmp_path, public=True, bioimage=ON)
        with env as client:
            body = client.get(f"{PREFIX}/bioimage/{DC_ID}/handoff", headers=AUTH).json()
        assert body == {"public": True, "links_enabled": True, "ttl_minutes": 5, "remote_urls": {}}


class TestLinks:
    def test_links_are_off_by_default(self, tmp_path):
        with _env(tmp_path) as client:
            resp = client.post(f"{PREFIX}/bioimage/{DC_ID}/sample_A.zarr/handoff", headers=AUTH)
        assert resp.status_code == 404
        assert BioimageConfig().handoff_enabled is False

    def test_a_link_reads_its_store_without_login_and_with_cors(self, tmp_path, redis):
        with _env(tmp_path, bioimage=ON) as client:
            minted = _mint(client)
            resp = client.get(f"{API}{minted['path']}/.zattrs")
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "*"
        assert minted["ttl_s"] == 300

    def test_a_link_reads_no_other_store(self, tmp_path, redis):
        env = _env(tmp_path, bioimage=ON)
        env.register(make_store(tmp_path, "sample_B.zarr"))
        with env as client:
            minted = _mint(client)
            resp = client.get(
                f"{PREFIX}/bioimage/{DC_ID}/t/{minted['token']}/sample_B.zarr/.zattrs"
            )
        assert resp.status_code == 404

    def test_a_link_cannot_write(self, tmp_path, redis):
        with _env(tmp_path, bioimage=ON) as client:
            minted = _mint(client)
            resp = client.put(f"{API}{minted['path']}/.zattrs", content=b"{}")
        assert resp.status_code == 405

    def test_an_expired_link_is_dead(self, tmp_path, redis):
        with _env(tmp_path, bioimage=ON) as client:
            minted = _mint(client)
            claims = jwt.decode(minted["token"], options={"verify_signature": False})
            claims["exp"] = int(time.time()) - 1
            expired = jwt.encode(claims, _KEY, algorithm="RS256")
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/t/{expired}/sample_A.zarr/.zattrs")
        assert resp.status_code == 404

    def test_a_revoked_link_is_dead(self, tmp_path, redis):
        with _env(tmp_path, bioimage=ON) as client:
            minted = _mint(client)
            revoked = client.delete(f"{PREFIX}/bioimage/{DC_ID}/t/{minted['token']}", headers=AUTH)
            resp = client.get(f"{API}{minted['path']}/.zattrs")
        assert revoked.status_code == 200
        assert resp.status_code == 404

    def test_a_link_dies_with_the_switch(self, tmp_path, redis):
        with _env(tmp_path, bioimage=ON) as client:
            minted = _mint(client)
        with _env(tmp_path) as client:
            resp = client.get(f"{API}{minted['path']}/.zattrs")
        assert resp.status_code == 404

    def test_an_access_token_is_not_a_link(self, tmp_path, redis):
        access = jwt.encode(
            {"sub": "u", "exp": int(time.time()) + 60, "jti": "x"}, _KEY, algorithm="RS256"
        )
        with _env(tmp_path, bioimage=ON) as client:
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/t/{access}/sample_A.zarr/.zattrs")
        assert resp.status_code == 404

    def test_no_link_for_a_dc_the_caller_cannot_read(self, tmp_path, redis):
        with _env(tmp_path, bioimage=ON, permitted=False) as client:
            resp = client.post(f"{PREFIX}/bioimage/{DC_ID}/sample_A.zarr/handoff", headers=AUTH)
        assert resp.status_code == 404

    def test_no_link_for_a_store_the_dc_does_not_have(self, tmp_path, redis):
        with _env(tmp_path, bioimage=ON) as client:
            resp = client.post(f"{PREFIX}/bioimage/{DC_ID}/other.zarr/handoff", headers=AUTH)
        assert resp.status_code == 404


class TestPreflight:
    """A viewer's suffix-range read is preflighted; only Range alone is granted here."""

    @staticmethod
    def _client():
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.add_middleware(bioimage_handoff.BioimagePreflightMiddleware)
        return TestClient(app)

    def _preflight(self, headers: str | None, method: str = "GET"):
        h = {"Origin": "https://hms-dbmi.github.io", "Access-Control-Request-Method": method}
        if headers:
            h["Access-Control-Request-Headers"] = headers
        return self._client().options(f"{PREFIX}/bioimage/{DC_ID}/t/tok/s.zarr/0/c/0", headers=h)

    def test_a_range_read_is_granted(self):
        resp = self._preflight("range")
        assert resp.status_code == 204
        assert resp.headers["access-control-allow-origin"] == "*"
        assert resp.headers["access-control-allow-headers"] == "Range"

    @pytest.mark.parametrize(
        ("headers", "method"), [("authorization, range", "GET"), (None, "PUT")]
    )
    def test_anything_else_falls_through(self, headers, method):
        # Not answered here: the bare app has no route, so it is a 405/404.
        assert self._preflight(headers, method).status_code != 204


def test_a_remote_store_is_handed_off_at_its_own_url(tmp_path):
    from depictio.tests.api.v1.test_bioimage_endpoint import REMOTE_ZARR

    env = Env(tmp_path, props={"remote_stores": [REMOTE_ZARR]})
    with env as client:
        body = client.get(f"{PREFIX}/bioimage/{DC_ID}/handoff", headers=AUTH).json()
    assert list(body["remote_urls"].values()) == [REMOTE_ZARR.rstrip("/")]
