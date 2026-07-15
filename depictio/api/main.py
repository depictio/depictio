"""
Depictio FastAPI Application.

Main application entry point with middleware, routing, and error handling.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.routers import router
from depictio.api.v1.json_response import CustomJSONResponse
from depictio.api.v1.middleware.analytics_middleware import AnalyticsMiddleware
from depictio.api.v1.services.lifespan import lifespan
from depictio.version import get_api_version, get_version


# Custom filter to mask tokens in Uvicorn access logs
class TokenMaskingFilter(logging.Filter):
    """Filter that masks sensitive tokens in log messages."""

    TOKEN_PATTERN = re.compile(r"(token|access_token|refresh_token)=([^&\s\"]+)")

    def filter(self, record: logging.LogRecord) -> bool:
        """Mask tokens in the log message."""
        if hasattr(record, "msg") and record.msg:
            record.msg = self.TOKEN_PATTERN.sub(r"\1=***", str(record.msg))
        if hasattr(record, "args") and record.args:
            masked_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    masked_args.append(self.TOKEN_PATTERN.sub(r"\1=***", arg))
                else:
                    masked_args.append(arg)
            record.args = tuple(masked_args)
        return True


# Apply token masking filter to uvicorn access logger
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.addFilter(TokenMaskingFilter())

# Check if in development mode
dev_mode = os.environ.get("DEPICTIO_DEV_MODE", "false").lower() == "true"


# OpenAPI tag metadata — clarifies which endpoint groups are operator/admin
# surfaces rather than part of the user-facing client API. These groups are not
# called by the React frontend or the CLI; they exist for monitoring, ops
# tooling, and feature-gated subsystems.
_OPENAPI_TAGS: list[dict[str, Any]] = [
    {
        "name": "Celery",
        "description": (
            "Admin/ops: Celery worker health and task stats. Not called by the "
            "frontend or CLI — intended for monitoring/diagnostics."
        ),
    },
    {
        "name": "Monitoring",
        "description": (
            "Admin-only 'Log & Task' monitoring: Celery task history, CLI ingestion "
            "runs, recent application logs, and worker health. Feature-gated by "
            "DEPICTIO_MONITORING_ENABLED; hidden in public/demo mode."
        ),
    },
    {
        "name": "Analytics",
        "description": (
            "Admin/ops: usage analytics. Feature-gated by DEPICTIO_ANALYTICS_ENABLED "
            "and has no frontend client yet (kept pending a product decision)."
        ),
    },
    {
        "name": "Analytics Data",
        "description": (
            "Admin/ops: analytics data maintenance. Feature-gated by DEPICTIO_ANALYTICS_ENABLED."
        ),
    },
    {
        "name": "Real-time Events",
        "description": (
            "WebSocket event stream plus an admin status endpoint. Feature-gated by "
            "DEPICTIO_EVENTS_ENABLED."
        ),
    },
    {
        "name": "Utils",
        "description": (
            "Mixed: public server status/health plus admin-only ops endpoints "
            "(orphaned-S3 cleanup, infrastructure diagnostics, screenshots). The "
            "destructive dev helpers require DEPICTIO_ENABLE_DEV_ENDPOINTS."
        ),
    },
]


# Create FastAPI application
app = FastAPI(
    title="Depictio API",
    version=get_version(),
    debug=dev_mode,
    lifespan=lifespan,
    default_response_class=CustomJSONResponse,
    openapi_tags=_OPENAPI_TAGS,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security-headers middleware
#
# Applied before route handlers so every response (including streamed file
# responses and CORS preflights) carries the same set of conservative
# defaults. The viewer SPA also sets equivalents at the nginx edge — these
# are a defence-in-depth fallback for direct backend-port access.
# ---------------------------------------------------------------------------
_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    # CSP: the React SPA bundle requires its own assets only; ag-grid / Mantine
    # ship CSS-in-JS so 'unsafe-inline' is required for style-src. WebSockets to
    # the same origin are needed for the realtime events stream.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers to every API response."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        # HSTS only meaningful behind TLS; relying on X-Forwarded-Proto from
        # the nginx viewer / ingress to avoid emitting it on plain-HTTP dev.
        if request.headers.get("x-forwarded-proto", "").lower() == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


app.add_middleware(cast(Any, SecurityHeadersMiddleware))

# Compress large JSON payloads (figure/table data can be tens of MB before
# downsampling lands). compresslevel=5 balances CPU vs ratio; minimum_size skips
# tiny responses where framing overhead outweighs the gain.
app.add_middleware(cast(Any, GZipMiddleware), minimum_size=1024, compresslevel=5)


# ---------------------------------------------------------------------------
# CORS — strict allowlist, no wildcard credentials.
#
# Browsers reject ``Access-Control-Allow-Origin: *`` whenever the request is
# credentialed; the previous ``allow_origins=["*"], allow_credentials=True``
# combination was both browser-rejected today and a CSRF amplifier the moment
# anyone "fixed" it by reflecting the Origin header. The allowlist is loaded
# from DEPICTIO_FASTAPI_CORS_ALLOWED_ORIGINS — empty means no cross-origin
# browser traffic, which is the safe default when the viewer SPA is served
# same-origin via nginx.
# ---------------------------------------------------------------------------
_cors_origins: list[str] = list(settings.fastapi.cors_allowed_origins)  # type: ignore[arg-type]
if "*" in _cors_origins and settings.fastapi.cors_allow_credentials:
    raise RuntimeError(
        "DEPICTIO_FASTAPI_CORS_ALLOWED_ORIGINS contains '*' while "
        "DEPICTIO_FASTAPI_CORS_ALLOW_CREDENTIALS is true. Browsers reject this "
        "combination and reflecting Origin opens a CSRF hole — list explicit "
        "origins (e.g. https://app.example.com) instead."
    )

app.add_middleware(
    cast(Any, CORSMiddleware),
    allow_origins=_cors_origins,
    allow_credentials=settings.fastapi.cors_allow_credentials and bool(_cors_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    max_age=600,
)
if not _cors_origins:
    _logger.info(
        "CORS allowlist is empty — cross-origin browser requests are disabled. "
        "Set DEPICTIO_FASTAPI_CORS_ALLOWED_ORIGINS to allow specific origins."
    )

# Add analytics middleware if enabled
if settings.analytics.enabled:
    app.add_middleware(cast(Any, AnalyticsMiddleware), enabled=settings.analytics.enabled)

# Include API router with versioned prefix
api_version = get_api_version()
api_prefix = f"/depictio/api/{api_version}"
app.include_router(router, prefix=api_prefix)


# ---------------------------------------------------------------------------
# React viewer SPA — served at /dashboard/{id} alongside the API.
#
# Built artifact lives at depictio/viewer/dist/ (produced by `npm run build`
# in that directory). FastAPI serves the static bundle and falls back to
# index.html for unknown paths so client-side routing works.
#
# If the bundle isn't built yet, the mount is skipped and a friendly 404 is
# returned. Rebuild with `cd depictio/viewer && npm install && npm run build`.
# ---------------------------------------------------------------------------
_VIEWER_DIST = Path(__file__).resolve().parent.parent / "viewer" / "dist"
_VIEWER_ASSETS = _VIEWER_DIST / "assets"
_VIEWER_INDEX = _VIEWER_DIST / "index.html"

# Dashboard screenshots — written by the auto-screenshot job and served back
# as /static/screenshots/{id}_{light|dark}.png. The path is the canonical
# screenshot output for both the worker (Playwright writes here) and the
# React viewer (reads via this mount).
_SCREENSHOTS_DIR = Path(__file__).resolve().parent / "static" / "screenshots"
_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/screenshots",
    StaticFiles(directory=str(_SCREENSHOTS_DIR)),
    name="dashboard-screenshots",
)

# Workflow logos / icons referenced by the React viewer as ``/assets/images/...``.
# Relocated out of the deleted depictio/dash/assets/ tree.
_STATIC_ASSETS_DIR = Path(__file__).resolve().parent / "static_assets"
if _STATIC_ASSETS_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_STATIC_ASSETS_DIR)),
        name="static-assets",
    )
# Require both index.html and assets/ — `dist/` alone may exist as an empty
# leftover from an interrupted build and would crash StaticFiles at startup.
if _VIEWER_DIST.is_dir() and _VIEWER_ASSETS.is_dir() and _VIEWER_INDEX.is_file():
    # /dashboard/assets/... → static bundle assets
    app.mount(
        "/dashboard/assets",
        StaticFiles(directory=str(_VIEWER_ASSETS)),
        name="viewer-assets",
    )
    # /dashboard/logos/... → SPA public/ assets (logos, etc.). Mounted
    # only when the directory exists so the SPA still serves when public/ is
    # absent (e.g. older build).
    _viewer_logos = _VIEWER_DIST / "logos"
    if _viewer_logos.is_dir():
        app.mount(
            "/dashboard/logos",
            StaticFiles(directory=str(_viewer_logos)),
            name="viewer-logos",
        )

    # index.html must NEVER be cached: it embeds hashed asset filenames
    # (`index-XXX.js`) that change on every rebuild. A cached index.html points
    # at chunks that no longer exist, breaking dynamic imports like
    # `FigureCodeMode-*.js` with "Failed to fetch dynamically imported module".
    # The hashed assets themselves stay default-cacheable since they're
    # content-addressed — only the entry HTML needs to be revalidated.
    _SPA_INDEX_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    def _spa_index() -> FileResponse:
        return FileResponse(_VIEWER_DIST / "index.html", headers=_SPA_INDEX_HEADERS)

    # Favicon must be registered BEFORE the catch-all SPA route, otherwise
    # the path segment matches `{_dashboard_id:path}` and returns index.html.
    _viewer_favicon = _VIEWER_DIST / "favicon.svg"
    if _viewer_favicon.is_file():

        @app.get("/dashboard/favicon.svg")
        async def _serve_viewer_favicon() -> FileResponse:
            return FileResponse(_viewer_favicon, media_type="image/svg+xml")

    @app.get("/dashboard/{_dashboard_id:path}")
    async def _serve_viewer_spa(_dashboard_id: str) -> FileResponse:
        """Serve the React viewer SPA. All sub-paths fall through to index.html
        so React's client-side router handles the dashboard ID segment."""
        return _spa_index()

    @app.get("/dashboard-edit/{_dashboard_id:path}")
    async def _serve_editor_spa(_dashboard_id: str) -> FileResponse:
        """Serve the React editor SPA. Same bundle as the viewer; the SPA's
        boot routing inspects window.location.pathname to render EditorApp.
        Asset paths in index.html still resolve via /dashboard/assets/."""
        return _spa_index()

    # /auth and /auth/google/callback → same React bundle. The SPA's boot
    # routing detects /auth and renders <AuthApp/>. Replaces the Dash /auth
    # page; Dash now redirects users straight here for sign-in.
    @app.get("/auth")
    async def _serve_auth_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/auth/{_auth_path:path}")
    async def _serve_auth_spa(_auth_path: str) -> FileResponse:
        return _spa_index()

    # /dashboards → React management page (replaces the Dash /dashboards
    # listing). Same bundle as the viewer; main.tsx detects the path prefix
    # and renders <DashboardsApp/>. Asset paths in index.html still resolve
    # via /dashboard/assets/ because Vite stamps them with that base.
    @app.get("/dashboards")
    async def _serve_dashboards_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/dashboards/{_path:path}")
    async def _serve_dashboards_spa(_path: str) -> FileResponse:
        return _spa_index()

    # /about and /admin → same React bundle. main.tsx detects the
    # pathname prefix and renders <AboutApp/> or <AdminApp/>. Coexists with
    # the Dash /about and /admin pages until the sidebar is flipped.
    @app.get("/about")
    async def _serve_about_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/about/{_path:path}")
    async def _serve_about_spa(_path: str) -> FileResponse:
        return _spa_index()

    @app.get("/admin")
    async def _serve_admin_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/admin/{_path:path}")
    async def _serve_admin_spa(_path: str) -> FileResponse:
        return _spa_index()

    # /projects → React projects management page (replaces the Dash
    # /projects listing + multi-step create modal + project/{id}/data detail).
    # Same bundle as the viewer; main.tsx detects the path prefix and renders
    # <ProjectsApp/>. Sub-paths (/projects/{id}, /projects/{id}/permissions)
    # all fall through to index.html so the React app can route internally.
    @app.get("/projects")
    async def _serve_projects_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/projects/{_path:path}")
    async def _serve_projects_spa(_path: str) -> FileResponse:
        return _spa_index()

    # /profile and /cli-agents → React-based replacements for the
    # Dash /profile and /cli_configs management pages. Same SPA bundle;
    # main.tsx detects the path prefix and renders <ProfileApp/> or
    # <CliAgentsApp/>. Coexists with the Dash routes during rollout.
    @app.get("/profile")
    async def _serve_profile_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/profile/{_path:path}")
    async def _serve_profile_spa(_path: str) -> FileResponse:
        return _spa_index()

    @app.get("/cli-agents")
    async def _serve_cli_agents_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/cli-agents/{_path:path}")
    async def _serve_cli_agents_spa(_path: str) -> FileResponse:
        return _spa_index()
else:
    logger = logging.getLogger(__name__)
    logger.warning(
        "⚠️  React viewer bundle not built at %s (missing index.html or "
        "assets/) — /dashboard/ and /dashboard-edit/ routes will "
        "404 until `cd depictio/viewer && npm install && npm run build` "
        "is executed.",
        _VIEWER_DIST,
    )


@app.get("/", include_in_schema=False)
async def _redirect_root() -> RedirectResponse:
    """Bare root → React management landing page. The SPA's useCurrentUser
    hook handles the anonymous case by routing to /auth, so this single
    server-side redirect serves both signed-in and signed-out visitors and
    makes the sidebar logo's `href="/"` work as a "go home" affordance."""
    return RedirectResponse("/dashboards", status_code=307)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for monitoring and readiness probes."""
    return {"status": "healthy", "version": get_version()}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: object, exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors with formatted error details."""
    return JSONResponse(status_code=422, content={"detail": [str(error) for error in exc.errors()]})
