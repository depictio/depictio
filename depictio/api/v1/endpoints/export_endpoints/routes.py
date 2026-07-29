"""Export a dashboard component for use on an external site.

Three routes:

* ``GET  /export/dashboards/{id}/components`` — manifest: what is exportable and how
* ``GET  /export/dashboards/{id}/components/{cid}`` — the component, as JSON or HTML
* ``POST /export/dashboards/{id}/components/{cid}`` — same, for filter payloads too
  large or awkward to URL-encode

GET is the primary shape because the URL has to work directly as an ``<iframe src>``
and as a plain link.

Auth reuses ``check_project_permission(..., "viewer")`` — the same gate every
``render_*`` endpoint applies — via :func:`get_embed_user`. See that function for why
it does not simply use ``get_user_or_anonymous``.

The whole router is gated on ``settings.fastapi.embed_enabled`` (default off),
because serving embeds relaxes ``X-Frame-Options`` and CSP ``frame-ancestors`` on
this path.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_current_user,
    oauth2_scheme_optional,
)
from depictio.api.v1.services.export.capabilities import (
    ExportFormat,
    formats_for,
    resolve_viz_kind,
    unsupported_reason,
)
from depictio.api.v1.services.export.plotly_export import build_plotly_export
from depictio.api.v1.services.export.resolve import (
    resolve_dashboard,
    resolve_dashboard_component,
)
from depictio.api.v1.services.export.revision import (
    build_etag,
    dashboard_revision,
    etag_matches,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User

export_endpoint_router = APIRouter()

#: Revalidate on every use, but allow a 304. `no-cache` is not `no-store`: the
#: client may keep the copy, it just may not serve it without asking first. That
#: is what makes an embed track the dashboard while still costing ~200 bytes per
#: check. `private` because a figure can be permission-scoped and must not land
#: in a shared proxy cache.
_CACHE_CONTROL = "private, no-cache"


def _require_embed_enabled() -> None:
    if not settings.fastapi.embed_enabled:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "embed_disabled",
                "message": (
                    "Component export is disabled on this instance. Set "
                    "DEPICTIO_FASTAPI_EMBED_ENABLED=true to enable it."
                ),
            },
        )


async def get_embed_user(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> User:
    """Resolve the caller, falling back to the anonymous user in every auth mode.

    ``get_user_or_anonymous`` only falls back to the anonymous identity when the
    instance is in public or single-user mode, and otherwise raises 401 *before*
    any project check runs. That would make embeds unusable on a normal multi-user
    deployment, which is the main case they exist for.

    This is not a new identity or a new token model: it reuses the same anonymous
    user, and every route still calls ``check_project_permission(..., "viewer")``,
    which returns ``project.is_public`` for anonymous callers. The effective
    widening is therefore *public projects only* — private dashboards still require
    a bearer token — and only on this router, only when ``embed_enabled``.
    """
    if token is not None:
        try:
            return await get_current_user(token)
        except HTTPException:
            # An invalid or expired token falls through to anonymous rather than
            # 401ing, so a stale token in an embedding page does not break a
            # public embed that would otherwise work.
            pass

    from depictio.api.v1.endpoints.user_endpoints.routes import UserBeanie

    anonymous = await UserBeanie.find_one({"email": settings.auth.anonymous_user_email})
    if anonymous is None:
        raise HTTPException(
            status_code=401,
            detail=("Anonymous access is unavailable on this instance; supply a bearer token."),
        )
    return anonymous


def _parse_controls(raw: str | None) -> dict:
    """Decode the optional ``controls`` query parameter (a JSON object).

    Intra-viz state that the live renderer keeps in browser state: which case a
    multi-case renderer shows (``{"mode": "roc"}``), a normalisation choice, a
    top-N. Without it an export can only reproduce the persisted default, so a
    component offering three views in the dashboard collapses to one.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"controls must be a JSON object: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="controls must be a JSON object.")
    return parsed


def _parse_filters(raw: str | None) -> list[dict]:
    """Decode the optional ``filters`` query parameter (a JSON array)."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"filters must be a JSON array: {exc}") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="filters must be a JSON array.")
    return parsed


def _html_url(request: Request, dashboard_id: Any, component_id: str, theme: str) -> str:
    """Absolute URL of the HTML form of this component, for the 501 body."""
    return str(
        request.url_for(
            "export_component",
            dashboard_id=str(dashboard_id),
            component_id=component_id,
        ).include_query_params(format="html", theme=theme)
    )


def _embed_cors_headers(request: Request) -> dict[str, str]:
    """CORS headers reflecting an allow-listed embedder's Origin, uncredentialed.

    The global CORS allowlist is empty by default and is credentialed; widening it
    for embeds would be the wrong lever. Embeds are anonymous by design, so no
    ``Access-Control-Allow-Credentials`` is sent and there is no CSRF surface.
    """
    origin = request.headers.get("origin")
    if origin and origin in settings.fastapi.embed_allowed_origins:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {}


def _apply_embed_cors(request: Request, response: Any) -> None:
    for header, value in _embed_cors_headers(request).items():
        response.headers[header] = value


@export_endpoint_router.get("/dashboards/{dashboard_id}/components")
async def list_exportable_components(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_embed_user),
) -> list[dict[str, Any]]:
    """Report every component on a dashboard and which formats it supports.

    Lets a consumer plan an integration without probing each component and
    collecting 422s.
    """
    _require_embed_enabled()
    dashboard_data, _ = resolve_dashboard(dashboard_id, current_user)

    manifest: list[dict[str, Any]] = []
    for component in dashboard_data.get("stored_metadata") or []:
        component_type = component.get("component_type") or ""
        viz_kind = resolve_viz_kind(component.get("viz_kind"))
        supported = formats_for(component_type, viz_kind)
        entry: dict[str, Any] = {
            "component_id": str(component.get("index")),
            "component_type": component_type,
            "viz_kind": viz_kind,
            "title": component.get("title") or "",
            "formats": sorted(f.value for f in supported),
        }
        if ExportFormat.JSON not in supported:
            entry["json_unavailable_reason"] = unsupported_reason(component_type, viz_kind)
        manifest.append(entry)
    return manifest


@export_endpoint_router.get(
    "/dashboards/{dashboard_id}/components/{component_id}",
    name="export_component",
)
async def export_component(
    request: Request,
    dashboard_id: PyObjectId,
    component_id: str,
    format: ExportFormat = Query(
        ExportFormat.JSON, description="`json` for a Plotly spec, `html` for an embed page."
    ),
    theme: str = Query("light", pattern="^(light|dark)$"),
    filters: str | None = Query(
        None, description="URL-encoded JSON array of interactive filter values."
    ),
    controls: str | None = Query(
        None,
        description=(
            'URL-encoded JSON object of intra-viz state, e.g. {"mode": "roc"}. '
            "Selects between the cases a multi-view renderer offers; without it "
            "the export renders the component's persisted default."
        ),
    ),
    expect_version: int | None = Query(
        None,
        description=(
            "Pin the dashboard version this caller was built against. If the "
            "dashboard has moved on, answer 409 rather than silently serving "
            "something different."
        ),
    ),
    current_user: User = Depends(get_embed_user),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> Any:
    """Export one component as a Plotly spec or a self-contained HTML page."""
    _require_embed_enabled()
    return await _export(
        request=request,
        dashboard_id=dashboard_id,
        component_id=component_id,
        export_format=format,
        theme=theme,
        filters=_parse_filters(filters),
        current_user=current_user,
        access_token=access_token,
        expect_version=expect_version,
        controls=_parse_controls(controls),
    )


@export_endpoint_router.post("/dashboards/{dashboard_id}/components/{component_id}")
async def export_component_post(
    request: Request,
    dashboard_id: PyObjectId,
    component_id: str,
    format: ExportFormat = Query(ExportFormat.JSON),
    body: dict = Body(default_factory=dict),
    current_user: User = Depends(get_embed_user),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> Any:
    """Same as the GET, for filter payloads too large to sit in a query string.

    Body: ``{"filters": [...], "theme": "light" | "dark"}``
    """
    _require_embed_enabled()
    theme = body.get("theme") or "light"
    if theme not in ("light", "dark"):
        raise HTTPException(status_code=400, detail="theme must be 'light' or 'dark'.")
    body_controls = body.get("controls") or {}
    if not isinstance(body_controls, dict):
        raise HTTPException(status_code=400, detail="controls must be a JSON object.")
    return await _export(
        request=request,
        dashboard_id=dashboard_id,
        component_id=component_id,
        export_format=format,
        theme=theme,
        filters=body.get("filters") or [],
        current_user=current_user,
        access_token=access_token,
        controls=body_controls,
    )


async def _export(
    *,
    request: Request,
    dashboard_id: PyObjectId,
    component_id: str,
    export_format: ExportFormat,
    theme: str,
    filters: list[dict],
    current_user: User,
    access_token: str | None,
    expect_version: int | None = None,
    controls: dict | None = None,
) -> Any:
    """Shared body of the GET and POST export routes."""
    try:
        return await _export_inner(
            request=request,
            dashboard_id=dashboard_id,
            component_id=component_id,
            export_format=export_format,
            theme=theme,
            filters=filters,
            current_user=current_user,
            access_token=access_token,
            expect_version=expect_version,
            controls=controls,
        )
    except HTTPException as exc:
        # Error bodies here are actionable — they name the supported formats and
        # link to the HTML variant. Without CORS headers a cross-origin caller
        # gets an opaque network failure instead and never sees any of that.
        cors = _embed_cors_headers(request)
        if cors:
            exc.headers = {**(exc.headers or {}), **cors}
        raise


async def _export_inner(
    *,
    request: Request,
    dashboard_id: PyObjectId,
    component_id: str,
    export_format: ExportFormat,
    theme: str,
    filters: list[dict],
    current_user: User,
    access_token: str | None,
    expect_version: int | None = None,
    controls: dict | None = None,
) -> Any:
    dashboard_data, component, _ = resolve_dashboard_component(
        dashboard_id, component_id, current_user
    )

    revision = dashboard_revision(dashboard_data)

    # Pin check first: a caller that asked for a specific version wants to hear
    # about drift, not receive a different figure with a 200.
    if expect_version is not None and revision["dashboard_version"] != expect_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "version_mismatch",
                "message": (
                    f"Dashboard is at version {revision['dashboard_version']}, "
                    f"caller expected {expect_version}. Drop expect_version to take "
                    "the current figure, or re-pin after reviewing the change."
                ),
                "current_version": revision["dashboard_version"],
                "expected_version": expect_version,
                "last_saved_ts": revision["last_saved_ts"],
            },
        )

    etag = build_etag(
        dashboard_doc=dashboard_data,
        component_id=component_id,
        export_format=export_format.value,
        theme=theme,
        filters=filters,
        controls=controls,
    )
    if etag_matches(request.headers.get("if-none-match"), etag):
        # 304 must not carry a body, but must carry the validators — otherwise the
        # client's cached copy has nothing to revalidate against next time.
        from fastapi import Response

        not_modified = Response(status_code=304)
        not_modified.headers["ETag"] = etag
        not_modified.headers["Cache-Control"] = _CACHE_CONTROL
        _apply_embed_cors(request, not_modified)
        return not_modified

    if export_format is ExportFormat.HTML:
        from depictio.api.v1.services.export.embed import render_component_embed

        html, csp = await render_component_embed(
            dashboard_doc=dashboard_data,
            component=component,
            theme=theme,
            filters=filters,
            access_token=access_token,
            current_user=current_user,
        )
        response = HTMLResponse(content=html)
        # Set before the security middleware runs its `setdefault`, so these win.
        # X-Frame-Options is deliberately absent: it has no "allow these origins"
        # value, and CSP frame-ancestors supersedes it. The middleware exempts
        # this path from re-adding it.
        response.headers["Content-Security-Policy"] = csp
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["ETag"] = etag
        _apply_embed_cors(request, response)
        return response

    from fastapi.responses import JSONResponse

    payload = await build_plotly_export(
        dashboard_id=dashboard_id,
        component_id=component_id,
        component=component,
        filters=filters,
        theme=theme,
        access_token=access_token,
        current_user=current_user,
        html_url=_html_url(request, dashboard_id, component_id, theme),
        controls=controls,
    )
    # Provenance travels *inside* the payload as well as in headers: a figure
    # saved to a file keeps no headers, and "which version produced this" is
    # exactly the question you ask months later looking at a committed .json.
    if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
        payload["meta"].update(revision)
        payload["meta"]["etag"] = etag
    logger.info(
        "export: served component=%s format=json type=%s",
        component_id,
        component.get("component_type"),
    )
    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = _CACHE_CONTROL
    response.headers["ETag"] = etag
    _apply_embed_cors(request, response)
    return response
