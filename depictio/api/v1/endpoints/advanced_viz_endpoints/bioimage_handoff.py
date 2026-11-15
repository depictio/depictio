"""Hand a bioimage store off to a viewer on another origin (vizarr, Neuroglancer, ...).

Those viewers fetch the store's keys themselves, relative to one URL, with no
way to send our ``Authorization`` header. Two tiers make that possible:

- a store of a **public** project is readable anonymously already: its reads
  carry ``Access-Control-Allow-Origin: *`` (`cors_headers`), never credentialed,
  so a cross-origin page can only ever read what an anonymous visitor could;
- a **private** store gets a short-lived link: a signed token in the URL path
  (`mint`), scoped to one store of one data collection, read-only, revocable
  (`revoke`) until it expires. Off unless ``DEPICTIO_BIOIMAGE_HANDOFF_ENABLED``.

The token is a JWT signed with the instance's own key pair, as access tokens
are, but with its own ``typ``: an access token is never accepted here, and a
hand-off token is never accepted as an access token (those are looked up in
the tokens collection, where a hand-off token is not).

Trade-off, stated in the UI: whoever holds the link reads that one store until
it expires, and access is checked when the link is made, not on every read.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

HANDOFF_TYP = "bioimage_handoff"
_REVOKED_PREFIX = "depictio:bioimage_handoff:revoked:"

#: Headers a cross-origin viewer needs on every read: the size of a ranged
#: read (OME-TIFF, zarr v3 shards) is in ``Content-Range``.
CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
}


def cors_headers(public: bool) -> dict[str, str]:
    """The CORS headers of a read: granted to public stores and token reads only."""
    return dict(CORS_HEADERS) if public else {}


def _redis():
    from depictio.api.v1.services.redis_client import get_shared_redis_client

    return get_shared_redis_client()


def _not_found() -> HTTPException:
    # Same answer whatever is wrong with the link, so it says nothing about
    # which stores exist or whether a token was ever valid.
    return HTTPException(status_code=404, detail="Link not found or expired")


def mint(dc_id: str, store: str, user_id: str | None) -> dict[str, Any]:
    """A signed link token for ``store`` of ``dc_id``, with its expiry."""
    import jwt

    from depictio.api.v1.configs.config import ALGORITHM, PRIVATE_KEY_PATH, settings
    from depictio.api.v1.key_utils import get_private_key

    ttl_s = int(settings.bioimage.handoff_ttl_minutes) * 60
    now = int(time.time())
    claims = {
        "typ": HANDOFF_TYP,
        "dc": dc_id,
        "store": store,
        "sub": user_id,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + ttl_s,
    }
    token = jwt.encode(claims, get_private_key(PRIVATE_KEY_PATH), algorithm=ALGORITHM)
    return {"token": token, "jti": claims["jti"], "expires_at": claims["exp"], "ttl_s": ttl_s}


def _decode(token: str) -> dict[str, Any]:
    import jwt

    from depictio.api.v1.configs.config import ALGORITHM, PUBLIC_KEY_PATH
    from depictio.api.v1.key_utils import get_public_key

    try:
        claims = jwt.decode(
            token,
            get_public_key(PUBLIC_KEY_PATH),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise _not_found() from exc
    if claims.get("typ") != HANDOFF_TYP:
        raise _not_found()
    return claims


def verify(token: str, dc_id: str, store: str) -> dict[str, Any]:
    """The claims of a live token for exactly this store, else a 404.

    Revocation is read from Redis; without Redis a token stays good until it
    expires (revoking then answers 503, so nobody believes a link is dead
    when it is not).
    """
    from depictio.api.v1.configs.config import settings

    if not settings.bioimage.handoff_enabled:
        raise _not_found()
    claims = _decode(token)
    if claims.get("dc") != dc_id or claims.get("store") != store:
        raise _not_found()
    client = _redis()
    if client is not None:
        try:
            if client.exists(_REVOKED_PREFIX + str(claims["jti"])):
                raise _not_found()
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - a Redis blip must not take reads down
            pass
    return claims


def revoke(token: str, dc_id: str) -> dict[str, Any]:
    """Revoke a token of ``dc_id`` until it would have expired anyway."""
    claims = _decode(token)
    if claims.get("dc") != dc_id:
        raise _not_found()
    remaining = int(claims["exp"]) - int(time.time())
    if remaining <= 0:
        return {"revoked": True, "jti": claims["jti"]}
    client = _redis()
    if client is None:
        raise HTTPException(
            status_code=503, detail="Revocation needs Redis; the link stays valid until it expires"
        )
    client.set(_REVOKED_PREFIX + str(claims["jti"]), "1", ex=remaining)
    return {"revoked": True, "jti": claims["jti"]}


_BIOIMAGE_READ_RE = re.compile(r"^/depictio/api/v\d+/advanced_viz/bioimage/[^/]+/")


class BioimagePreflightMiddleware(BaseHTTPMiddleware):
    """Answer the preflight of an uncredentialed bioimage read from any origin.

    A viewer on another origin (vizarr, Neuroglancer, the NGFF validator) reads a
    handed-off store with ``Range`` requests, and a suffix range (``bytes=-n``, a
    zarr v3 shard index) is not CORS-safelisted, so the browser preflights it. A
    preflight grants nothing by itself: whether the page may read the answer is
    decided by the read's own headers, which only public stores and hand-off
    links carry (`cors_headers`). Only GET/HEAD
    preflights asking for ``Range`` alone are answered here; anything else (a
    credentialed request from an allow-listed origin) falls through to the
    global policy.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.method == "OPTIONS" and _BIOIMAGE_READ_RE.match(request.url.path):
            method = request.headers.get("access-control-request-method", "").upper()
            asked = {
                h.strip().lower()
                for h in request.headers.get("access-control-request-headers", "").split(",")
                if h.strip()
            }
            if method in ("GET", "HEAD") and asked <= {"range"}:
                return Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, HEAD",
                        "Access-Control-Allow-Headers": "Range",
                        "Access-Control-Max-Age": "600",
                    },
                )
        return await call_next(request)
