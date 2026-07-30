"""CORS for the component-export endpoints.

The global CORS allowlist is credentialed and empty by default, and widening it to
admit embedders would be the wrong lever: an embed is deliberately anonymous, so it
needs a *separate*, uncredentialed allowlist. That is
``DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS``.

Simple GETs are answered by the route handlers, which call
:func:`apply_embed_cors` on the way out. A *preflighted* request is different: the
browser sends ``OPTIONS`` first, that never reaches a route handler, and the global
``CORSMiddleware`` rejects it because the embed origin is not on the global list.

A conditional GET is exactly such a request. ``If-None-Match`` is not a
CORS-safelisted header, so revalidating an export — the thing the ETag on every
export response exists for — is preflighted, and would fail for every cross-origin
caller. :func:`preflight_response` is what makes that path work.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from depictio.api.v1.configs.config import settings

#: Request headers an embedder may send. ``If-None-Match`` is the operative one:
#: without it a host page can hold an ETag it is unable to use.
ALLOWED_REQUEST_HEADERS = "If-None-Match, If-Modified-Since, Content-Type, Accept"

#: Response headers JavaScript may read. Cross-origin responses expose only the
#: CORS-safelisted set unless named here, so an unlisted ETag reads back as `null`.
EXPOSED_RESPONSE_HEADERS = "ETag"

#: Preflight cache lifetime. An embed's CORS answer is static, so re-asking on
#: every conditional GET would defeat the point of revalidating cheaply.
MAX_AGE = "600"


def embed_origin(request: Request) -> str | None:
    """The request's Origin if it is allow-listed for embedding, else ``None``."""
    origin = request.headers.get("origin")
    if origin and origin in settings.fastapi.embed_allowed_origins:
        return origin
    return None


def embed_cors_headers(request: Request) -> dict[str, str]:
    """CORS headers reflecting an allow-listed embedder's Origin, uncredentialed.

    No ``Access-Control-Allow-Credentials``: embeds carry no cookies, so there is
    no CSRF surface to protect and nothing to gain from a credentialed grant.
    """
    origin = embed_origin(request)
    if not origin:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Vary": "Origin",
        "Access-Control-Expose-Headers": EXPOSED_RESPONSE_HEADERS,
    }


def apply_embed_cors(request: Request, response: Any) -> None:
    """Attach the embed CORS headers to an outgoing response, if applicable."""
    for header, value in embed_cors_headers(request).items():
        response.headers[header] = value


def preflight_response(request: Request) -> Response | None:
    """Answer an embed preflight, or ``None`` to let normal CORS handling proceed.

    Returning ``None`` rather than a 403 matters: a non-embed ``OPTIONS`` on this
    path should still be judged by the global CORS policy, not pre-empted here.
    """
    if request.method != "OPTIONS":
        return None
    if not request.headers.get("access-control-request-method"):
        return None  # not a preflight, just a plain OPTIONS
    if not embed_origin(request):
        return None

    response = Response(status_code=204)
    apply_embed_cors(request, response)
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = ALLOWED_REQUEST_HEADERS
    response.headers["Access-Control-Max-Age"] = MAX_AGE
    return response
