"""Helpers for SAML SSO (SP-initiated, python3-saml).

Ported from the validated prototype ``dev/dev_fastapi_saml/app.py`` and
parameterized from ``settings.auth.saml_*``. ``onelogin`` imports are lazy so
the optional ``saml`` extra is only required when the feature is enabled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

SAML_ACS_PATH = "/depictio/api/v1/auth/saml/callback"
DEFAULT_RELAY_PATH = "/dashboards"


def saml_configured() -> bool:
    """True when SAML is enabled and every required setting is present."""
    auth = settings.auth
    return bool(
        auth.saml_enabled
        and auth.saml_idp_entity_id
        and auth.saml_idp_sso_url
        and auth.saml_idp_cert
        and auth.saml_sp_entity_id
    )


def read_idp_cert(cert_value: str) -> str:
    """Return the IdP certificate PEM, accepting inline PEM or a file path."""
    if cert_value.lstrip().startswith("-----BEGIN"):
        return cert_value
    return Path(cert_value).read_text()


def get_acs_url() -> str:
    """Public Assertion Consumer Service URL (where the IdP POSTs responses)."""
    base = settings.auth.saml_sp_base_url or settings.fastapi.external_url
    return f"{base.rstrip('/')}{SAML_ACS_PATH}"


def safe_relay_path(candidate: str | None) -> str:
    """Constrain a post-login destination to a same-origin path (anti open-redirect)."""
    if candidate and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return DEFAULT_RELAY_PATH


def get_saml_settings() -> dict[str, Any]:
    """Build the python3-saml settings dict from depictio settings."""
    auth = settings.auth
    import os

    debug = os.getenv("DEPICTIO_DEV_MODE", "false").lower() == "true"
    return {
        "strict": True,
        "debug": debug,
        "sp": {
            "entityId": auth.saml_sp_entity_id,
            "assertionConsumerService": {
                "url": get_acs_url(),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": auth.saml_name_id_format,
            "x509cert": "",
            "privateKey": "",
        },
        "idp": {
            "entityId": auth.saml_idp_entity_id,
            "singleSignOnService": {
                "url": auth.saml_idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": read_idp_cert(auth.saml_idp_cert or ""),
        },
        "security": {
            "authnRequestsSigned": False,
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantAttributeStatement": True,
            "allowSingleLabelDomains": True,
            "nameIdEncrypted": False,
            "requestedAuthnContext": False,
        },
    }


async def init_saml_auth(request: Request) -> Any:
    """Adapt a Starlette request into a ``OneLogin_Saml2_Auth`` instance.

    Honours ``X-Forwarded-Proto``/``X-Forwarded-Host`` so signature-relevant
    URLs match what the browser saw when TLS terminates at nginx/the ingress.
    """
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    url = request.url
    scheme = request.headers.get("x-forwarded-proto", url.scheme)
    host_header = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if host_header:
        host, _, port = host_header.partition(":")
    else:
        host, port = url.hostname or "", str(url.port or "")
    if not port:
        port = "443" if scheme == "https" else "80"

    form_data: list[tuple[str, Any]] = []
    if request.method == "POST":
        form = await request.form()
        form_data = [(k, v) for k, v in form.items()]

    data = {
        "https": "on" if scheme == "https" else "off",
        "http_host": host,
        "server_port": port,
        "script_name": url.path,
        "get_data": [(k, v) for k, v in request.query_params.items()],
        "post_data": form_data,
    }
    logger.debug(f"SAML auth request data: {data}")
    return OneLogin_Saml2_Auth(data, get_saml_settings())


def extract_in_response_to(saml_response_b64: str) -> str | None:
    """Read ``InResponseTo`` from a base64 SAMLResponse without validating it.

    This is only a pre-crypto peek used to look up the pending AuthnRequest in
    the shared state store; the actual signature/condition validation is done
    by ``OneLogin_Saml2_Auth.process_response``.
    """
    import base64

    from defusedxml import ElementTree

    try:
        xml = base64.b64decode(saml_response_b64)
        root = ElementTree.fromstring(xml)
        return root.attrib.get("InResponseTo")
    except Exception as e:
        logger.warning(f"Could not parse SAMLResponse for InResponseTo: {e}")
        return None


def resolve_email(attributes: dict[str, list[str]], nameid: str | None) -> str | None:
    """Resolve the user email from SAML attributes, falling back to the NameID."""
    attr_name = settings.auth.saml_attribute_email
    email: str | None = None
    if attr_name:
        values = attributes.get(attr_name) or []
        email = values[0] if values else None
    if not email:
        email = nameid
    return email.strip().lower() if email else None
