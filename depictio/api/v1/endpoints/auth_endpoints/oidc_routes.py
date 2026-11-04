"""OpenID Connect SSO endpoints (authorization code flow with PKCE).

Flow, for a provider ``{provider}`` declared in ``settings.auth.oidc_providers``:

1. ``GET /auth/oidc/{provider}/login?next=/path``: mint ``state``, ``nonce``
   and a PKCE verifier, store them server-side with the validated return path
   (``OAuthStateBeanie``), and redirect the browser to the provider.
2. The provider authenticates the user and redirects to the configured
   redirect URI, ``GET /auth/oidc/{provider}/callback?code=&state=``. The state
   is consumed atomically (a replay finds nothing), the code is redeemed with
   the verifier, the ``id_token`` is verified (signature against the provider's
   JWKS, iss, aud, exp, iat, nonce) and the login is provisioned through
   ``sso_sync.provision_sso_login``.
3. The browser is redirected to the viewer's magic-link route with a
   single-use ticket in the URL *fragment* (never sent to servers or logs),
   which the viewer redeems for a session, the same hand-off as every other
   passwordless login.

Errors never reach the browser in detail: it is sent back to ``/auth?error=<code>``
and the reason is logged.
"""

import secrets
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.auth_endpoints import oidc
from depictio.api.v1.endpoints.auth_endpoints.sso_sync import (
    SSOLoginRejected,
    provision_sso_login,
)
from depictio.api.v1.endpoints.auth_endpoints.utils import (
    consume_oauth_state,
    store_oauth_state,
)
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _create_magic_link_ticket,
)

oidc_router = APIRouter()

#: Lifetime of the hand-off ticket: the browser redeems it on landing.
_TICKET_EXPIRY_MINUTES = 2


class OIDCProviderPublic(BaseModel):
    """What the sign-in page needs to draw a provider's button. Nothing secret."""

    id: str
    label: str


def _viewer_base() -> str:
    return settings.viewer.external_url.rstrip("/")


def _error_redirect(code: str) -> RedirectResponse:
    """Back to the sign-in page with a coarse error code (details stay in the logs)."""
    return RedirectResponse(f"{_viewer_base()}/auth?error={quote(code)}", status_code=303)


@oidc_router.get("/providers", response_model=list[OIDCProviderPublic])
async def list_oidc_providers() -> list[OIDCProviderPublic]:
    """Enabled, fully configured providers, in declared order (public)."""
    return [
        OIDCProviderPublic(id=p.id, label=p.display_label)
        for p in settings.auth.enabled_oidc_providers
    ]


@oidc_router.get("/{provider_id}/login")
async def oidc_login(
    provider_id: str,
    next: str | None = Query(default=None, description="Same-origin path to land on after login"),
) -> RedirectResponse:
    """Start a login with ``provider_id``: redirect the browser to the provider."""
    provider = settings.auth.get_oidc_provider(provider_id)
    if provider is None:
        logger.warning(f"OIDC login for unknown or disabled provider {provider_id!r}")
        return _error_redirect("sso_unavailable")

    try:
        metadata = await oidc.get_provider_metadata(provider)
    except oidc.OIDCError as e:
        logger.error(f"OIDC provider '{provider.id}' discovery failed: {e.reason}")
        return _error_redirect("sso_unavailable")

    code_verifier, code_challenge = oidc.new_pkce_pair()
    nonce = secrets.token_urlsafe(32)
    return_to = oidc.safe_return_path(next)
    state = await store_oauth_state(
        provider=provider.id,
        nonce=nonce,
        code_verifier=code_verifier,
        return_to=return_to,
    )
    url = oidc.build_authorization_url(
        provider, metadata, state=state, nonce=nonce, code_challenge=code_challenge
    )
    logger.info(f"OIDC login started with provider '{provider.id}'")
    return RedirectResponse(url, status_code=302)


@oidc_router.get("/{provider_id}/callback")
async def oidc_callback(
    provider_id: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Finish a login: verify what the provider sent and hand off a session ticket."""
    provider = settings.auth.get_oidc_provider(provider_id)
    if provider is None:
        logger.warning(f"OIDC callback for unknown or disabled provider {provider_id!r}")
        return _error_redirect("sso_unavailable")

    # Consume the state first, whatever else the request says, so a callback
    # can never be replayed, not even an error one.
    login = await consume_oauth_state(state or "")

    if error:
        logger.warning(f"OIDC provider '{provider.id}' returned error={error!r}")
        return _error_redirect("sso_cancelled" if error == "access_denied" else "sso_failed")
    if login is None:
        return _error_redirect("sso_failed")
    if not oidc.constant_time_equals(login.provider, provider.id):
        logger.warning(
            f"OIDC state issued for provider {login.provider!r} came back on '{provider.id}'"
        )
        return _error_redirect("sso_failed")
    if not code or not login.nonce or not login.code_verifier:
        logger.warning("OIDC callback without a code, or a state without nonce/verifier")
        return _error_redirect("sso_failed")

    try:
        metadata = await oidc.get_provider_metadata(provider)
        tokens = await oidc.exchange_code(
            provider, metadata, code=code, code_verifier=login.code_verifier
        )
        claims: dict[str, Any] = await oidc.verify_id_token(
            provider, metadata, tokens["id_token"], nonce=login.nonce
        )
        if provider.fetch_userinfo:
            userinfo = await oidc.fetch_userinfo(
                metadata, str(tokens.get("access_token") or ""), expected_sub=str(claims["sub"])
            )
            # The verified id_token wins over userinfo on any claim both carry.
            claims = {**userinfo, **claims}
        user, created = await provision_sso_login(provider, claims)
    except oidc.OIDCError as e:
        logger.warning(f"OIDC login with '{provider.id}' failed: {e.reason}")
        return _error_redirect(e.code)
    except SSOLoginRejected as e:
        logger.warning(f"OIDC login with '{provider.id}' rejected: {e.reason}")
        return _error_redirect(e.code)
    except Exception as e:  # noqa: BLE001 - never a 500 page on a browser redirect
        logger.error(f"Unexpected error in OIDC callback for '{provider.id}': {e}")
        return _error_redirect("sso_failed")

    if user.id is None:
        return _error_redirect("sso_failed")
    ticket = await _create_magic_link_ticket(user.id, expiry_minutes=_TICKET_EXPIRY_MINUTES)
    logger.info(f"OIDC login with '{provider.id}' successful for {user.email} (created={created})")
    return_to = oidc.safe_return_path(login.return_to)
    # The ticket rides in the URL fragment: browsers apply fragments on
    # Location headers but never send them to servers, proxies or logs.
    return RedirectResponse(
        f"{_viewer_base()}/auth/magic#ticket={quote(ticket.ticket)}&next={quote(return_to)}",
        status_code=303,
    )
