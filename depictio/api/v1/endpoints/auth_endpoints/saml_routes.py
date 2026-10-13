"""SAML SSO endpoints (SP-initiated login against e.g. the EMBL Keycloak IdP).

Flow:
1. ``GET /auth/saml/login`` — build an AuthnRequest, remember its ID in the
   shared state store, redirect the browser to the IdP.
2. IdP authenticates the user and POSTs a SAMLResponse to
   ``POST /auth/saml/callback`` (ACS). The response is validated
   (signature, InResponseTo replay check), the email is mapped to a depictio
   user, and the browser is redirected to the viewer's magic-link route with a
   single-use ticket in the URL *fragment* (never query string / server logs).
3. The viewer's existing MagicLinkCallback redeems the ticket for a session.
"""

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.auth_endpoints.saml_utils import (
    extract_in_response_to,
    init_saml_auth,
    resolve_email,
    safe_relay_path,
    saml_configured,
)
from depictio.api.v1.endpoints.auth_endpoints.state_store import (
    consume_auth_state,
    store_auth_state,
)
from depictio.api.v1.endpoints.auth_endpoints.utils import create_or_get_sso_user
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _create_magic_link_ticket,
)

saml_router = APIRouter()


def _require_saml() -> None:
    if not settings.auth.saml_enabled:
        raise HTTPException(status_code=403, detail="SAML SSO is not enabled")
    if not saml_configured():
        raise HTTPException(status_code=500, detail="SAML SSO configuration incomplete")


def _error_redirect(reason: str) -> RedirectResponse:
    """Send the browser back to the login page with a coarse error code.

    Details stay in the server logs — the IdP error internals are not for the
    URL bar, and the ACS must never answer a browser POST with raw JSON.
    """
    viewer = settings.viewer.external_url.rstrip("/")
    return RedirectResponse(f"{viewer}/auth?error={quote(reason)}", status_code=303)


@saml_router.get("/login")
async def saml_login(
    request: Request,
    next: str | None = Query(default=None, description="Same-origin path to land on after login"),
) -> RedirectResponse:
    """Start an SP-initiated SAML login: redirect the browser to the IdP."""
    _require_saml()
    try:
        auth = await init_saml_auth(request)
    except ImportError as e:
        logger.error(
            f"SAML enabled but python3-saml is not installed ({e}); "
            "install the 'saml' extra (pip install 'depictio[saml]')."
        )
        raise HTTPException(status_code=500, detail="SAML support is not installed on the server")

    relay = safe_relay_path(next)
    redirect_url = auth.login(return_to=relay)
    request_id = auth.get_last_request_id()
    # The relay path is stored server-side keyed by the AuthnRequest ID, so the
    # ACS never has to trust the IdP-echoed RelayState.
    store_auth_state("saml", request_id, value=relay)
    logger.info(f"SAML login initiated (request_id={request_id}, relay={relay})")
    return RedirectResponse(redirect_url, status_code=302)


@saml_router.post("/callback")
async def saml_acs(request: Request) -> RedirectResponse:
    """Assertion Consumer Service: validate the IdP response, mint a session ticket."""
    if not settings.auth.saml_enabled:
        raise HTTPException(status_code=403, detail="SAML SSO is not enabled")

    try:
        form = await request.form()
        saml_response = form.get("SAMLResponse")
        if not isinstance(saml_response, str) or not saml_response:
            logger.warning("SAML ACS called without a SAMLResponse")
            return _error_redirect("saml_failed")

        in_response_to = extract_in_response_to(saml_response)
        relay = consume_auth_state("saml", in_response_to or "")
        if relay is None:
            logger.warning(f"SAML ACS with unknown/expired/replayed InResponseTo: {in_response_to}")
            return _error_redirect("saml_failed")

        auth = await init_saml_auth(request)
        auth.process_response(request_id=in_response_to)
        errors = auth.get_errors()
        if errors:
            logger.warning(
                f"SAML response validation failed: {errors} — {auth.get_last_error_reason()}"
            )
            return _error_redirect("saml_failed")

        logger.debug(f"SAML attributes: {auth.get_attributes()}")
        email = resolve_email(auth.get_attributes(), auth.get_nameid())
        if not email:
            logger.warning("SAML response carried no usable email (attributes or NameID)")
            return _error_redirect("saml_failed")

        user, created = await create_or_get_sso_user(
            email, allow_create=not settings.auth.registration_disabled
        )
        if user is None:
            return _error_redirect("registration_disabled")

        # Short expiry: the browser redeems the ticket immediately on landing.
        ticket = await _create_magic_link_ticket(user.id, expiry_minutes=2)  # type: ignore[arg-type]
        viewer = settings.viewer.external_url.rstrip("/")
        logger.info(f"SAML login successful for {email} (created={created})")
        # The ticket rides in the URL fragment: browsers apply fragments on
        # Location headers but never send them to servers/proxies/logs.
        return RedirectResponse(
            f"{viewer}/auth/magic#ticket={ticket.ticket}&next={quote(safe_relay_path(relay))}",
            status_code=303,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in SAML ACS: {e}")
        return _error_redirect("saml_failed")


@saml_router.get("/metadata")
async def saml_metadata() -> Response:
    """Serve the SP metadata XML (import this in the IdP to register the client)."""
    _require_saml()
    try:
        from onelogin.saml2.settings import OneLogin_Saml2_Settings

        from depictio.api.v1.endpoints.auth_endpoints.saml_utils import get_saml_settings

        saml_settings = OneLogin_Saml2_Settings(get_saml_settings(), sp_validation_only=True)
        metadata = saml_settings.get_sp_metadata()
        validation_errors = saml_settings.validate_metadata(metadata)
        if validation_errors:
            logger.error(f"SP metadata validation failed: {validation_errors}")
            raise HTTPException(status_code=500, detail="Invalid SP metadata configuration")
        return Response(content=metadata, media_type="text/xml")
    except ImportError:
        raise HTTPException(status_code=500, detail="SAML support is not installed on the server")
