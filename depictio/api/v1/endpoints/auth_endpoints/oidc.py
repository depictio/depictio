"""OpenID Connect relying-party helpers: discovery, PKCE, code exchange, ``id_token``.

Everything a login needs besides the HTTP routes (``oidc_routes.py``):

- :func:`get_provider_metadata` reads and caches the provider's discovery
  document, and checks its ``issuer`` against the configured one.
- :class:`JWKSCache` holds each provider's signing keys and fetches them again
  when a token names a key id it does not know (key rotation), at most once
  every ``JWKS_MIN_REFRESH_SECONDS`` per key set.
- :func:`verify_id_token` checks the signature against those keys, and ``iss``,
  ``aud`` (and ``azp`` when there are several audiences), ``exp``, ``iat``,
  ``sub`` and ``nonce``. Signature and claim checks are done by ``joserfc``,
  the JOSE implementation of the Authlib project (``authlib.jose`` is its
  deprecated predecessor).
- :func:`exchange_code` redeems the authorization code with the PKCE verifier
  (challenge computed by Authlib's RFC 7636 implementation).

Only asymmetric signatures are accepted: an ``HS*`` token would be checked
against the client secret, which the provider is not the only one to hold, and
``alg: none`` is never valid.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.configs.settings_models import (
    GOOGLE_OIDC_DISCOVERY_URL as GOOGLE_DISCOVERY_URL,
)
from depictio.api.v1.configs.settings_models import OIDCProviderConfig

#: Path of the callback under the API root; the default redirect URI.
OIDC_CALLBACK_PATH = "/depictio/api/v1/auth/oidc/{provider}/callback"
DEFAULT_RETURN_PATH = "/dashboards"

#: Signature algorithms accepted on an ``id_token``. Asymmetric only.
ALLOWED_ID_TOKEN_ALGS = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
)

#: Clock skew tolerated on ``exp`` / ``iat``, in seconds.
CLOCK_SKEW_SECONDS = 60
#: How long a discovery document is reused before it is read again.
METADATA_TTL_SECONDS = 3600
#: How long a key set is reused when every token names a known key.
JWKS_TTL_SECONDS = 3600
#: Floor between two fetches of one key set, so a stream of tokens naming an
#: unknown key id cannot turn into a stream of requests to the provider.
JWKS_MIN_REFRESH_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 10.0


class OIDCError(Exception):
    """A login that must fail. ``reason`` is logged; the browser only sees a code."""

    def __init__(self, reason: str, code: str = "sso_failed") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def new_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE ``S256`` (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)  # 86 chars, inside the 43..128 range
    return verifier, create_s256_code_challenge(verifier)


def safe_return_path(candidate: str | None) -> str:
    """Constrain a post-login destination to a same-origin path (no open redirect).

    Accepts ``/path?query#fragment`` only. Rejects anything a browser could read
    as another origin: ``//host``, ``/\\host`` (browsers treat ``\\`` as ``/``),
    a scheme, control characters or whitespace.
    """
    if not candidate or len(candidate) > 2048:
        return DEFAULT_RETURN_PATH
    if not candidate.startswith("/") or candidate.startswith("//"):
        return DEFAULT_RETURN_PATH
    if "\\" in candidate or any(ord(c) < 0x21 or ord(c) == 0x7F for c in candidate):
        return DEFAULT_RETURN_PATH
    parts = urlsplit(candidate)
    if parts.scheme or parts.netloc:
        return DEFAULT_RETURN_PATH
    return candidate


def redirect_uri_for(provider: OIDCProviderConfig) -> str:
    """The callback URL sent to the provider: configured, never from the request."""
    if provider.redirect_uri:
        return provider.redirect_uri
    base = settings.fastapi.external_url.rstrip("/")
    return f"{base}{OIDC_CALLBACK_PATH.format(provider=provider.id)}"


def constant_time_equals(a: str | None, b: str | None) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _unverified_header(token: str) -> dict[str, Any]:
    """The JOSE header of a compact JWS, decoded but not trusted."""
    try:
        segment = token.split(".", 1)[0]
        padded = segment + "=" * (-len(segment) % 4)
        header = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception as e:  # noqa: BLE001 - any malformed token is the same failure
        raise OIDCError(f"id_token header is not decodable: {e}") from e
    if not isinstance(header, dict):
        raise OIDCError("id_token header is not a JSON object")
    return header


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


async def _get_json(url: str, *, headers: Mapping[str, str] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.get(url, headers=dict(headers or {}))
    if response.status_code != 200:
        raise OIDCError(f"GET {url} answered {response.status_code}")
    try:
        body = response.json()
    except ValueError as e:
        raise OIDCError(f"GET {url} did not return JSON") from e
    if not isinstance(body, dict):
        raise OIDCError(f"GET {url} did not return a JSON object")
    return body


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@dataclass
class _CachedMetadata:
    metadata: dict[str, Any]
    fetched_at: float


_metadata_cache: dict[str, _CachedMetadata] = {}
_REQUIRED_METADATA = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")


async def get_provider_metadata(
    provider: OIDCProviderConfig, *, force_refresh: bool = False
) -> dict[str, Any]:
    """The provider's discovery document, cached for ``METADATA_TTL_SECONDS``."""
    url = provider.resolved_discovery_url
    if not url:
        raise OIDCError(f"OIDC provider '{provider.id}' has no issuer or discovery_url")

    cached = _metadata_cache.get(url)
    if (
        cached is not None
        and not force_refresh
        and time.monotonic() - cached.fetched_at < METADATA_TTL_SECONDS
    ):
        return cached.metadata

    metadata = await _get_json(url)
    missing = [k for k in _REQUIRED_METADATA if not metadata.get(k)]
    if missing:
        raise OIDCError(f"discovery document {url} lacks {', '.join(missing)}")
    # OIDC Discovery 1.0 §4.3: the issuer in the document must be the one the
    # configuration was read for, or tokens could be accepted from another one.
    if provider.issuer and metadata["issuer"].rstrip("/") != provider.issuer.rstrip("/"):
        raise OIDCError(
            f"discovery document issuer {metadata['issuer']!r} does not match the "
            f"configured issuer {provider.issuer!r}"
        )
    _metadata_cache[url] = _CachedMetadata(metadata=metadata, fetched_at=time.monotonic())
    return metadata


# ---------------------------------------------------------------------------
# JWKS
# ---------------------------------------------------------------------------


@dataclass
class _CachedKeys:
    key_set: KeySet
    kids: set[str]
    fetched_at: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class JWKSCache:
    """Signing keys per ``jwks_uri``, re-fetched on an unknown ``kid``."""

    def __init__(self) -> None:
        self._entries: dict[str, _CachedKeys] = {}

    def clear(self) -> None:
        self._entries.clear()

    async def _fetch(self, jwks_uri: str) -> tuple[KeySet, set[str]]:
        body = await _get_json(jwks_uri)
        keys = body.get("keys")
        if not isinstance(keys, list):
            raise OIDCError(f"JWKS at {jwks_uri} has no 'keys' list")
        # Keep only keys meant for signatures; encryption keys and unknown key
        # types are dropped rather than failing the whole set.
        usable = []
        for key in keys:
            if not isinstance(key, dict) or key.get("use", "sig") != "sig":
                continue
            if key.get("kty") not in ("RSA", "EC", "OKP"):
                continue
            usable.append(key)
        try:
            key_set = KeySet.import_key_set({"keys": usable})
        except (JoseError, ValueError, TypeError) as e:
            raise OIDCError(f"JWKS at {jwks_uri} could not be imported: {e}") from e
        kids = {k["kid"] for k in usable if isinstance(k.get("kid"), str)}
        return key_set, kids

    async def get(self, jwks_uri: str, kid: str | None) -> KeySet:
        """Keys able to verify a token with ``kid``, refreshing once if needed."""
        entry = self._entries.get(jwks_uri)
        now = time.monotonic()
        if entry is not None and now - entry.fetched_at < JWKS_TTL_SECONDS:
            if kid is None or kid in entry.kids:
                return entry.key_set

        lock = entry.lock if entry is not None else asyncio.Lock()
        async with lock:
            entry = self._entries.get(jwks_uri)
            now = time.monotonic()
            fresh_enough = entry is not None and now - entry.fetched_at < JWKS_TTL_SECONDS
            known = entry is not None and (kid is None or kid in entry.kids)
            if fresh_enough and known:
                return entry.key_set  # type: ignore[union-attr]
            # Unknown kid on a recent set: refetch only past the floor, so a
            # token naming a bogus kid cannot hammer the provider.
            if (
                entry is not None
                and fresh_enough
                and now - entry.fetched_at < JWKS_MIN_REFRESH_SECONDS
            ):
                raise OIDCError(f"id_token key id {kid!r} is not in the provider's key set")
            key_set, kids = await self._fetch(jwks_uri)
            self._entries[jwks_uri] = _CachedKeys(
                key_set=key_set, kids=kids, fetched_at=now, lock=lock
            )
            logger.info(f"OIDC: fetched {len(kids)} signing key(s) from {jwks_uri}")
            if kid is not None and kid not in kids:
                raise OIDCError(f"id_token key id {kid!r} is not in the provider's key set")
            return key_set


jwks_cache = JWKSCache()


def clear_caches() -> None:
    """Forget every discovery document and key set (tests, config reloads)."""
    _metadata_cache.clear()
    jwks_cache.clear()


# ---------------------------------------------------------------------------
# Authorization request
# ---------------------------------------------------------------------------


def build_authorization_url(
    provider: OIDCProviderConfig,
    metadata: Mapping[str, Any],
    *,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    """The URL the browser is sent to: authorization code flow with PKCE S256."""
    params: dict[str, str] = dict(provider.authorize_params)
    # The protocol parameters always win over configured extras.
    params.update(
        {
            "response_type": "code",
            "client_id": provider.client_id or "",
            "redirect_uri": redirect_uri_for(provider),
            "scope": " ".join(provider.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    endpoint = str(metadata["authorization_endpoint"])
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode(params)}"


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


async def exchange_code(
    provider: OIDCProviderConfig,
    metadata: Mapping[str, Any],
    *,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Redeem the authorization code. Returns the token response."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri_for(provider),
        "code_verifier": code_verifier,
    }
    auth: httpx.BasicAuth | None = None
    secret = provider.client_secret.get_secret_value() if provider.client_secret else ""
    method = provider.token_endpoint_auth_method
    if method == "client_secret_basic":
        auth = httpx.BasicAuth(provider.client_id or "", secret)
    elif method == "client_secret_post":
        data["client_id"] = provider.client_id or ""
        data["client_secret"] = secret
    else:  # "none": a public client, PKCE is its only proof
        data["client_id"] = provider.client_id or ""

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(
            str(metadata["token_endpoint"]),
            data=data,
            auth=auth,
            headers={"Accept": "application/json"},
        )
    if response.status_code != 200:
        # The body may echo the request; keep it out of anything user-facing.
        raise OIDCError(f"token endpoint answered {response.status_code}: {response.text[:500]}")
    try:
        body = response.json()
    except ValueError as e:
        raise OIDCError("token endpoint did not return JSON") from e
    if not isinstance(body, dict) or not isinstance(body.get("id_token"), str):
        raise OIDCError("token response carries no id_token")
    return body


# ---------------------------------------------------------------------------
# id_token
# ---------------------------------------------------------------------------


async def verify_id_token(
    provider: OIDCProviderConfig,
    metadata: Mapping[str, Any],
    id_token: str,
    *,
    nonce: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify an ``id_token`` and return its claims.

    Checked: signature (provider JWKS, asymmetric algorithms only), ``iss``
    equal to the discovery issuer, ``aud`` containing the client id (and
    ``azp`` equal to it when there are several audiences), ``exp`` in the
    future, ``iat`` present and not in the future, ``sub`` present, ``nonce``
    equal to the one stored for this login. ``CLOCK_SKEW_SECONDS`` of leeway
    on the time checks.
    """
    header = _unverified_header(id_token)
    alg = header.get("alg")
    if alg not in ALLOWED_ID_TOKEN_ALGS:
        raise OIDCError(f"id_token alg {alg!r} is not accepted")
    kid = header.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise OIDCError("id_token kid is not a string")

    key_set = await jwks_cache.get(str(metadata["jwks_uri"]), kid)
    key: Any = key_set
    if kid is None:
        # A provider with a single signing key may omit kid; with several, the
        # token must say which one signed it.
        if len(key_set.keys) != 1:
            raise OIDCError("id_token has no kid and the provider publishes several keys")
        key = key_set.keys[0]
    try:
        token = jwt.decode(id_token, key, algorithms=list(ALLOWED_ID_TOKEN_ALGS))
    except JoseError as e:
        # A rotated key whose id was reused cannot be told apart from a forged
        # signature here; neither is accepted.
        raise OIDCError(f"id_token signature is not valid: {e}") from e
    except (ValueError, TypeError) as e:
        raise OIDCError(f"id_token is malformed: {e}") from e

    claims: dict[str, Any] = dict(token.claims)
    issuer = str(metadata["issuer"])
    client_id = provider.client_id or ""

    registry = JWTClaimsRegistry(
        now=now,
        leeway=CLOCK_SKEW_SECONDS,
        iss={"essential": True, "value": issuer},
        aud={"essential": True, "value": client_id},
        sub={"essential": True},
        exp={"essential": True},
        iat={"essential": True},
    )
    try:
        registry.validate(claims)
    except JoseError as e:
        raise OIDCError(f"id_token claims rejected: {e}") from e

    # Belt and braces: joserfc also refuses an iat in the future.
    current = int(time.time()) if now is None else now
    iat = claims.get("iat")
    if not isinstance(iat, (int, float)) or iat > current + CLOCK_SKEW_SECONDS:
        raise OIDCError("id_token iat is in the future")

    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1:
        # OIDC Core §3.1.3.7: with several audiences the token must say which
        # one it was issued to.
        if not constant_time_equals(claims.get("azp"), client_id):
            raise OIDCError("id_token has several audiences and azp is not this client")
    elif "azp" in claims and not constant_time_equals(claims.get("azp"), client_id):
        raise OIDCError("id_token azp is not this client")

    if not constant_time_equals(claims.get("nonce"), nonce):
        raise OIDCError("id_token nonce does not match this login")

    return claims


async def fetch_userinfo(
    metadata: Mapping[str, Any], access_token: str, *, expected_sub: str
) -> dict[str, Any]:
    """Claims from the userinfo endpoint; ``{}`` when the provider has none.

    The response is only used when its ``sub`` is the ``id_token``'s (OIDC Core
    §5.3.2), so a mixed-up response cannot attach another user's claims.
    """
    endpoint = metadata.get("userinfo_endpoint")
    if not endpoint or not access_token:
        return {}
    try:
        info = await _get_json(str(endpoint), headers={"Authorization": f"Bearer {access_token}"})
    except OIDCError as e:
        # Userinfo only adds claims; the id_token alone is a valid login.
        logger.warning(f"OIDC userinfo request failed, using id_token claims only: {e.reason}")
        return {}
    if not constant_time_equals(info.get("sub"), expected_sub):
        logger.warning("OIDC userinfo sub differs from the id_token sub; ignoring userinfo")
        return {}
    return info


# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

#: Replacement of each removed SAML variable, for the startup error.
LEGACY_SAML_REPLACEMENTS: dict[str, str] = {
    "DEPICTIO_AUTH_SAML_ENABLED": "an entry in DEPICTIO_AUTH_OIDC_PROVIDERS (enabled: true)",
    "DEPICTIO_AUTH_SAML_IDP_ENTITY_ID": "issuer",
    "DEPICTIO_AUTH_SAML_IDP_SSO_URL": "issuer / discovery_url",
    "DEPICTIO_AUTH_SAML_IDP_CERT": "nothing: keys come from the provider's JWKS",
    "DEPICTIO_AUTH_SAML_SP_ENTITY_ID": "client_id (or DEPICTIO_AUTH_OIDC_<ID>_CLIENT_ID)",
    "DEPICTIO_AUTH_SAML_SP_BASE_URL": "redirect_uri",
    "DEPICTIO_AUTH_SAML_NAME_ID_FORMAT": "nothing: the email comes from claims.email",
    "DEPICTIO_AUTH_SAML_ATTRIBUTE_EMAIL": "claims.email",
    "DEPICTIO_AUTH_SAML_ATTRIBUTE_USERNAME": "claims.login",
    "DEPICTIO_AUTH_SAML_LOGIN_LABEL": "label",
    "DEPICTIO_AUTH_SAML_ATTRIBUTE_GROUPS": "claims.groups",
    "DEPICTIO_AUTH_SAML_ATTRIBUTE_TITLE": "claims.title",
    "DEPICTIO_AUTH_SAML_ATTRIBUTE_DISPLAY_NAME": "claims.display_name",
    "DEPICTIO_AUTH_SAML_ATTRIBUTE_LOGIN": "claims.login",
}


def check_legacy_sso_env(environ: Mapping[str, str] | None = None) -> list[str]:
    """Log what the removed SAML and the deprecated Google variables became.

    SAML support is gone: a deployment still setting ``DEPICTIO_AUTH_SAML_*``
    would otherwise lose its sign-in button without a word. Returns the legacy
    variable names found (set, even to an empty value), for tests.
    """
    import os

    env = os.environ if environ is None else environ
    found_saml = sorted(k for k in env if k.upper().startswith("DEPICTIO_AUTH_SAML_"))
    if found_saml:
        lines = [
            f"  {name} -> {LEGACY_SAML_REPLACEMENTS.get(name.upper(), 'see the OIDC documentation')}"
            for name in found_saml
        ]
        logger.error(
            "SAML SSO has been removed and these variables are IGNORED. Declare the identity "
            "provider as an OpenID Connect provider in DEPICTIO_AUTH_OIDC_PROVIDERS (JSON list; "
            "credentials in DEPICTIO_AUTH_OIDC_<ID>_CLIENT_ID / _CLIENT_SECRET):\n"
            + "\n".join(lines)
        )

    found_google = sorted(k for k in env if k.upper().startswith("DEPICTIO_AUTH_GOOGLE_OAUTH_"))
    if found_google and settings.auth.google_oauth_enabled:
        declared = any(p.id == "google" for p in settings.auth.oidc_providers)
        logger.warning(
            "DEPICTIO_AUTH_GOOGLE_OAUTH_* is deprecated and will be removed in a future "
            "release. It is mapped onto an OIDC provider with id 'google'"
            + (
                " (an explicit 'google' provider in DEPICTIO_AUTH_OIDC_PROVIDERS wins)"
                if declared
                else ""
            )
            + ". Declare it in DEPICTIO_AUTH_OIDC_PROVIDERS with discovery_url "
            f"{GOOGLE_DISCOVERY_URL} and DEPICTIO_AUTH_OIDC_GOOGLE_CLIENT_ID / _CLIENT_SECRET."
        )

    for provider in settings.auth.oidc_providers:
        missing = provider.missing_settings()
        if provider.enabled and missing:
            logger.error(
                f"OIDC provider '{provider.id}' is enabled but lacks {', '.join(missing)}; "
                "its sign-in button is hidden until it is configured."
            )
    return found_saml + found_google
