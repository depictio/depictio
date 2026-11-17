"""A fake OpenID Connect provider for the SSO tests (helpers; fixtures in conftest.py).

``FakeIdP`` answers discovery, JWKS, token and userinfo requests through an
``httpx.MockTransport`` that replaces ``httpx.AsyncClient`` inside
``depictio.api.v1.endpoints.auth_endpoints.oidc``. Nothing leaves the process.
"""

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey

from depictio.api.v1.configs.settings_models import OIDCClaimMapping, OIDCProviderConfig

ISSUER = "https://idp.example.org/realms/example"
CLIENT_ID = "depictio"
CLIENT_SECRET = "s3cret-value"


def make_key(kid: str | None = "k1") -> RSAKey:
    params: dict[str, Any] = {"use": "sig"}
    if kid is not None:
        params["kid"] = kid
    return RSAKey.generate_key(2048, parameters=params)


def make_provider(**overrides: Any) -> OIDCProviderConfig:
    """A fully configured provider for the fake IdP; ``claims`` may be a dict."""
    claims = overrides.pop("claims", {})
    if isinstance(claims, dict):
        claims = OIDCClaimMapping(**claims)
    base: dict[str, Any] = {
        "id": "kc",
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    base.update(overrides)
    return OIDCProviderConfig(claims=claims, **base)


@dataclass
class RecordedRequest:
    method: str
    url: str
    headers: dict[str, str]
    form: dict[str, str]


@dataclass
class FakeIdP:
    issuer: str = ISSUER
    keys: dict[str, RSAKey] = field(default_factory=dict)
    published: list[str] = field(default_factory=list)
    requests: list[RecordedRequest] = field(default_factory=list)
    discovery: dict[str, Any] = field(default_factory=dict)
    #: Callable (form) -> token response body, or None for the default error.
    token_handler: Any = None
    token_status: int = 200
    userinfo: dict[str, Any] | None = None
    userinfo_status: int = 200

    def __post_init__(self) -> None:
        self.add_key("k1")
        self.discovery = {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/protocol/openid-connect/auth",
            "token_endpoint": f"{self.issuer}/protocol/openid-connect/token",
            "jwks_uri": f"{self.issuer}/protocol/openid-connect/certs",
            "userinfo_endpoint": f"{self.issuer}/protocol/openid-connect/userinfo",
        }

    # -- keys ---------------------------------------------------------------

    def add_key(self, kid: str, *, publish: bool = True) -> RSAKey:
        key = make_key(kid)
        self.keys[kid] = key
        if publish:
            self.published.append(kid)
        return key

    @property
    def jwks_uri(self) -> str:
        return self.discovery["jwks_uri"]

    def count(self, url_part: str, method: str = "GET") -> int:
        return sum(1 for r in self.requests if r.method == method and url_part in r.url)

    # -- tokens -------------------------------------------------------------

    def claims(self, **overrides: Any) -> dict[str, Any]:
        now = int(time.time())
        base: dict[str, Any] = {
            "iss": self.issuer,
            "aud": CLIENT_ID,
            "sub": "user-1",
            "exp": now + 300,
            "iat": now,
            "nonce": "nonce-1",
            "email": "jane@example.com",
            "email_verified": True,
        }
        base.update(overrides)
        return {k: v for k, v in base.items() if v != _MISSING}

    def sign(
        self,
        claims: dict[str, Any] | None = None,
        *,
        kid: str | None = "k1",
        alg: str = "RS256",
        key: Any = None,
        **overrides: Any,
    ) -> str:
        payload = claims if claims is not None else self.claims(**overrides)
        header: dict[str, Any] = {"alg": alg}
        if kid is not None:
            header["kid"] = kid
        signing_key = key if key is not None else self.keys[kid or "k1"]
        return jwt.encode(header, payload, signing_key, algorithms=[alg])

    # -- HTTP ---------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        url = str(request.url)
        self.requests.append(RecordedRequest(request.method, url, dict(request.headers), form))
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=self.discovery)
        if url == self.discovery["jwks_uri"]:
            return httpx.Response(
                200,
                json={"keys": [self.keys[k].as_dict(private=False) for k in self.published]},
            )
        if url == self.discovery["token_endpoint"] and request.method == "POST":
            if self.token_handler is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            body = self.token_handler(form)
            return httpx.Response(self.token_status, json=body)
        if url == self.discovery.get("userinfo_endpoint"):
            if self.userinfo is None:
                return httpx.Response(404)
            return httpx.Response(self.userinfo_status, json=self.userinfo)
        return httpx.Response(404, json={"error": "not found"})


_MISSING = "__missing__"


def unsigned_token(claims: dict[str, Any]) -> str:
    def b64(data: dict[str, Any]) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."


def hs256_token(claims: dict[str, Any], secret: str) -> str:
    return jwt.encode({"alg": "HS256"}, claims, OctKey.import_key(secret))


MISSING = _MISSING
