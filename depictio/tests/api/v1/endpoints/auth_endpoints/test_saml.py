"""Unit tests for the SAML SSO endpoints (login, ACS callback, metadata).

python3-saml is an optional extra, so ``OneLogin_Saml2_Auth`` is mocked
throughout; tests that need the real library are guarded with importorskip.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.auth_endpoints import state_store
from depictio.api.v1.endpoints.auth_endpoints.saml_utils import (
    get_acs_url,
    resolve_email,
    safe_relay_path,
)

_SAML_SETTINGS = {
    "saml_enabled": True,
    "saml_idp_entity_id": "https://sso.example.org/realms/myrealm",
    "saml_idp_sso_url": "https://sso.example.org/realms/myrealm/protocol/saml",
    "saml_idp_cert": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
    "saml_sp_entity_id": "https://api.example.org/depictio",
}


def _configure_saml(**overrides):
    """Patch the real (shared) settings.auth SAML fields for one test."""
    from contextlib import ExitStack

    stack = ExitStack()
    for field, value in {**_SAML_SETTINGS, **overrides}.items():
        stack.enter_context(patch.object(settings.auth, field, value))
    return stack


@pytest.fixture
def client():
    app = FastAPI()
    from depictio.api.v1.endpoints.auth_endpoints.saml_routes import saml_router

    app.include_router(saml_router, prefix="/auth/saml")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state_store():
    state_store._local_states.clear()
    yield
    state_store._local_states.clear()


@pytest.fixture(autouse=True)
def _no_redis():
    with patch(
        "depictio.api.v1.endpoints.auth_endpoints.state_store.get_shared_redis_client",
        return_value=None,
    ):
        yield


def _mock_auth(request_id="ONELOGIN_id_1", nameid="user@example.org", errors=None, attributes=None):
    auth = MagicMock()
    auth.login.return_value = "https://sso.example.org/sso?SAMLRequest=xyz"
    auth.get_last_request_id.return_value = request_id
    auth.process_response.return_value = None
    auth.get_errors.return_value = errors or []
    auth.get_last_error_reason.return_value = "reason"
    auth.get_attributes.return_value = attributes or {}
    auth.get_nameid.return_value = nameid
    return auth


class TestSamlLogin:
    def test_login_disabled_returns_403(self, client):
        with patch.object(settings.auth, "saml_enabled", False):
            assert client.get("/auth/saml/login").status_code == 403

    def test_login_enabled_but_unconfigured_returns_500(self, client):
        with _configure_saml(saml_idp_sso_url=None):
            assert client.get("/auth/saml/login").status_code == 500

    def test_login_redirects_to_idp_and_stores_request_id(self, client):
        auth = _mock_auth()
        with (
            _configure_saml(),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.init_saml_auth",
                new=AsyncMock(return_value=auth),
            ),
        ):
            response = client.get("/auth/saml/login", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "https://sso.example.org/sso?SAMLRequest=xyz"
        auth.login.assert_called_once_with(return_to="/dashboards")
        assert state_store.consume_auth_state("saml", "ONELOGIN_id_1") == "/dashboards"

    @pytest.mark.parametrize("evil_next", ["//evil.com", "https://evil.com", "javascript:alert(1)"])
    def test_login_rejects_non_relative_next(self, client, evil_next):
        auth = _mock_auth()
        with (
            _configure_saml(),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.init_saml_auth",
                new=AsyncMock(return_value=auth),
            ),
        ):
            client.get("/auth/saml/login", params={"next": evil_next}, follow_redirects=False)

        auth.login.assert_called_once_with(return_to="/dashboards")

    def test_login_preserves_safe_next(self, client):
        auth = _mock_auth()
        with (
            _configure_saml(),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.init_saml_auth",
                new=AsyncMock(return_value=auth),
            ),
        ):
            client.get("/auth/saml/login", params={"next": "/dashboard/42"}, follow_redirects=False)

        auth.login.assert_called_once_with(return_to="/dashboard/42")
        assert state_store.consume_auth_state("saml", "ONELOGIN_id_1") == "/dashboard/42"


class TestSamlAcs:
    def _post_acs(self, client, saml_response="ZmFrZQ=="):
        return client.post(
            "/auth/saml/callback",
            data={"SAMLResponse": saml_response},
            follow_redirects=False,
        )

    def test_acs_disabled_returns_403(self, client):
        with patch.object(settings.auth, "saml_enabled", False):
            assert self._post_acs(client).status_code == 403

    def test_acs_without_samlresponse_redirects_to_error(self, client):
        with _configure_saml():
            response = client.post("/auth/saml/callback", data={}, follow_redirects=False)
        assert response.status_code == 303
        assert "/auth?error=saml_failed" in response.headers["location"]

    def test_acs_unknown_in_response_to_redirects_to_error(self, client):
        with (
            _configure_saml(),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.extract_in_response_to",
                return_value="ONELOGIN_unknown",
            ),
        ):
            response = self._post_acs(client)
        assert response.status_code == 303
        assert "/auth?error=saml_failed" in response.headers["location"]

    def test_acs_validation_errors_redirect_to_error(self, client):
        state_store.store_auth_state("saml", "ONELOGIN_id_1", value="/dashboards")
        auth = _mock_auth(errors=["invalid_response"])
        with (
            _configure_saml(),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.extract_in_response_to",
                return_value="ONELOGIN_id_1",
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.init_saml_auth",
                new=AsyncMock(return_value=auth),
            ),
        ):
            response = self._post_acs(client)
        assert response.status_code == 303
        assert "/auth?error=saml_failed" in response.headers["location"]

    def test_acs_success_mints_magic_ticket(self, client):
        state_store.store_auth_state("saml", "ONELOGIN_id_1", value="/dashboard/42")
        auth = _mock_auth(nameid="User@Example.org")

        user = MagicMock()
        user.id = "507f1f77bcf86cd799439011"
        ticket = MagicMock()
        ticket.ticket = "one-shot-secret"

        create_user = AsyncMock(return_value=(user, True))
        sync_user = AsyncMock()
        create_ticket = AsyncMock(return_value=ticket)
        with (
            _configure_saml(),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.extract_in_response_to",
                return_value="ONELOGIN_id_1",
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.init_saml_auth",
                new=AsyncMock(return_value=auth),
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.create_or_get_sso_user",
                new=create_user,
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes._create_magic_link_ticket",
                new=create_ticket,
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.sync_sso_user",
                new=sync_user,
            ),
        ):
            response = self._post_acs(client)

        assert response.status_code == 303
        location = response.headers["location"]
        assert "/auth/magic#ticket=one-shot-secret" in location
        assert "next=/dashboard/42" in location
        # InResponseTo replay protection: process_response pinned to the request id.
        auth.process_response.assert_called_once_with(request_id="ONELOGIN_id_1")
        # Email is lowercased before the user lookup.
        create_user.assert_awaited_once()
        assert create_user.await_args.args[0] == "user@example.org"
        # The assertion's attributes are mirrored into groups/profile for this user.
        sync_user.assert_awaited_once_with(user, auth.get_attributes())

    def test_acs_sync_failure_never_blocks_sign_in(self, client):
        state_store.store_auth_state("saml", "ONELOGIN_id_1", value="/dashboards")
        auth = _mock_auth()
        user = MagicMock()
        user.id = "507f1f77bcf86cd799439011"
        ticket = MagicMock()
        ticket.ticket = "one-shot-secret"
        with (
            _configure_saml(),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.extract_in_response_to",
                return_value="ONELOGIN_id_1",
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.init_saml_auth",
                new=AsyncMock(return_value=auth),
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.create_or_get_sso_user",
                new=AsyncMock(return_value=(user, False)),
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes._create_magic_link_ticket",
                new=AsyncMock(return_value=ticket),
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.sync_sso_user",
                new=AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
        ):
            response = self._post_acs(client)

        assert response.status_code == 303
        assert "/auth/magic#ticket=one-shot-secret" in response.headers["location"]

    def test_acs_replay_rejected(self, client):
        """A second POST with the same InResponseTo must not mint a ticket."""
        state_store.store_auth_state("saml", "ONELOGIN_id_1", value="/dashboards")
        state_store.consume_auth_state("saml", "ONELOGIN_id_1")  # first (legit) use
        with (
            _configure_saml(),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.extract_in_response_to",
                return_value="ONELOGIN_id_1",
            ),
        ):
            response = self._post_acs(client)
        assert response.status_code == 303
        assert "/auth?error=saml_failed" in response.headers["location"]

    def test_acs_registration_disabled_unknown_email(self, client):
        state_store.store_auth_state("saml", "ONELOGIN_id_1", value="/dashboards")
        auth = _mock_auth()
        sync_user = AsyncMock()
        with (
            _configure_saml(),
            patch.object(settings.auth, "registration_disabled", True),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.extract_in_response_to",
                return_value="ONELOGIN_id_1",
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.init_saml_auth",
                new=AsyncMock(return_value=auth),
            ),
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.create_or_get_sso_user",
                new=AsyncMock(return_value=(None, False)),
            ) as create_user,
            patch(
                "depictio.api.v1.endpoints.auth_endpoints.saml_routes.sync_sso_user",
                new=sync_user,
            ),
        ):
            response = self._post_acs(client)

        assert response.status_code == 303
        assert "/auth?error=registration_disabled" in response.headers["location"]
        assert create_user.await_args.kwargs == {"allow_create": False}
        sync_user.assert_not_awaited()


class TestSamlHelpers:
    def test_safe_relay_path(self):
        assert safe_relay_path("/dashboard/42") == "/dashboard/42"
        assert safe_relay_path(None) == "/dashboards"
        assert safe_relay_path("") == "/dashboards"
        assert safe_relay_path("//evil.com") == "/dashboards"
        assert safe_relay_path("https://evil.com") == "/dashboards"

    def test_get_acs_url_strips_trailing_slash(self):
        with patch.object(settings.auth, "saml_sp_base_url", "https://api.example.org/"):
            assert get_acs_url() == "https://api.example.org/depictio/api/v1/auth/saml/callback"

    def test_resolve_email_prefers_configured_attribute(self):
        with patch.object(settings.auth, "saml_attribute_email", "urn:oid:mail"):
            assert (
                resolve_email({"urn:oid:mail": ["User@Example.org"]}, "fallback@x.y")
                == "user@example.org"
            )

    def test_resolve_email_falls_back_to_nameid(self):
        with patch.object(settings.auth, "saml_attribute_email", None):
            assert resolve_email({}, "User@Example.org ") == "user@example.org"
        with patch.object(settings.auth, "saml_attribute_email", "urn:oid:mail"):
            assert resolve_email({"urn:oid:mail": []}, "user@example.org") == "user@example.org"

    def test_resolve_email_none_when_nothing_usable(self):
        with patch.object(settings.auth, "saml_attribute_email", None):
            assert resolve_email({}, None) is None

    def test_extract_in_response_to(self):
        pytest.importorskip("defusedxml")
        import base64

        from depictio.api.v1.endpoints.auth_endpoints.saml_utils import extract_in_response_to

        xml = (
            '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
            'ID="_r1" InResponseTo="ONELOGIN_id_1" Version="2.0"/>'
        )
        encoded = base64.b64encode(xml.encode()).decode()
        assert extract_in_response_to(encoded) == "ONELOGIN_id_1"
        assert extract_in_response_to("not-base64!!") is None


class TestSamlMetadata:
    def test_metadata_disabled_returns_403(self, client):
        with patch.object(settings.auth, "saml_enabled", False):
            assert client.get("/auth/saml/metadata").status_code == 403

    def test_metadata_with_real_library(self, client):
        pytest.importorskip("onelogin")
        # A real (self-signed, throwaway) cert so python3-saml settings validate.
        pytest.importorskip("cryptography")
        from datetime import datetime, timedelta, timezone

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-idp")])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        pem = cert.public_bytes(serialization.Encoding.PEM).decode()

        with _configure_saml(saml_idp_cert=pem):
            response = client.get("/auth/saml/metadata")

        assert response.status_code == 200
        assert "EntityDescriptor" in response.text
        assert "https://api.example.org/depictio" in response.text


class TestInitSamlAuthRequestData:
    """`init_saml_auth` hands python3-saml the request as dicts.

    The route tests above patch `init_saml_auth` out, which is how a list of
    (key, value) pairs went unnoticed: python3-saml checks
    `"SAMLResponse" in post_data`, which is False for a list of pairs, so every
    real IdP POST failed with "SAML Response not found".
    """

    def test_post_and_query_data_are_dicts(self):
        import sys
        import types

        from depictio.api.v1.endpoints.auth_endpoints import saml_utils

        captured: dict = {}

        class _FakeAuth:
            def __init__(self, request_data, settings):
                captured.update(request_data)

        fake_module = types.SimpleNamespace(OneLogin_Saml2_Auth=_FakeAuth)
        app = FastAPI()

        @app.post("/acs")
        async def acs(request: saml_utils.Request):  # type: ignore[name-defined]
            await saml_utils.init_saml_auth(request)
            return {}

        with (
            patch.dict(sys.modules, {"onelogin.saml2.auth": fake_module}),
            patch.object(saml_utils, "get_saml_settings", return_value={}),
        ):
            TestClient(app).post(
                "/acs?x=1", data={"SAMLResponse": "abc", "RelayState": "/dashboards"}
            )

        assert captured["post_data"] == {"SAMLResponse": "abc", "RelayState": "/dashboards"}
        assert captured["get_data"] == {"x": "1"}
