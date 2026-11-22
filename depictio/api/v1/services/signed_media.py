"""Short-lived signed query parameters for media an ``<img>`` tag loads.

``/files/serve/image`` and ``/dashboards/logo/{id}`` are mostly loaded through
``<img>`` tags, which cannot send an Authorization header. The authenticated
endpoints that hand those URLs out (the image signing and logo signing
endpoints) append an HMAC ``sig`` + ``exp`` pair over what the URL grants,
keyed with the internal API key like ``services/jbrowse/signing.py``. The
serving routes accept a valid pair instead of a session, so a leaked link
expires and cannot be widened to another file.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from depictio.api.v1.configs.config import settings

#: Lifetime of a signed media URL. Long enough for a dashboard session, short
#: enough that a leaked link dies on its own.
MEDIA_URL_TTL_SECONDS = 60 * 60

#: URL scopes. Part of the HMAC input, so a signature for one kind of URL can
#: never be replayed against another route.
SCOPE_SERVE_IMAGE = "serve-image"
SCOPE_DASHBOARD_LOGO = "dashboard-logo"


def _key(scope: str) -> bytes:
    material = settings.auth.internal_api_key.encode("utf-8")
    return hashlib.sha256(
        b"depictio-signed-media-v1:" + scope.encode("utf-8") + b":" + material
    ).digest()


def sign(scope: str, item: str, exp: int) -> str:
    """HMAC over the signed item and its expiry, for one scope."""
    payload = f"{item}|{exp}".encode("utf-8")
    return hmac.new(_key(scope), payload, hashlib.sha256).hexdigest()[:40]


def signed_query(scope: str, item: str, ttl_seconds: int = MEDIA_URL_TTL_SECONDS) -> str:
    """Query string (without ``?``) granting the item until now + ttl."""
    exp = int(time.time()) + ttl_seconds
    return urlencode({"exp": exp, "sig": sign(scope, item, exp)})


def verify(scope: str, item: str, exp: str | None, sig: str | None) -> bool:
    """True when ``exp``/``sig`` are present, unexpired and correct for ``item``."""
    if not (exp and sig) or not exp.isdigit():
        return False
    if int(exp) < time.time():
        return False
    return hmac.compare_digest(sign(scope, item, int(exp)), sig)


def append_signature(url: str, scope: str, item: str) -> str:
    """``url`` with the scope's ``exp``/``sig`` params added.

    Answers are signed at response time, never stored: the storage keeps the
    unsigned URL, and every GET hands out a fresh expiry.
    """
    if not url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{signed_query(scope, item)}"


def strip_signature(url: str | None) -> str | None:
    """``url`` without any ``exp``/``sig`` params, other params preserved.

    Write paths run this on client-echoed URLs so a short-lived signature from
    a GET response is never persisted into the document.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("exp", "sig")
    ]
    query = urlencode(kept)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
