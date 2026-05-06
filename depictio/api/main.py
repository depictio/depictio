"""
Depictio FastAPI Application.

Main application entry point with middleware, routing, and error handling.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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


# Create FastAPI application
app = FastAPI(
    title="Depictio API",
    version=get_version(),
    debug=dev_mode,
    lifespan=lifespan,
    default_response_class=CustomJSONResponse,
)

# Add CORS middleware
# Cast needed due to incomplete FastAPI middleware type stubs
app.add_middleware(
    cast(Any, CORSMiddleware),
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Add analytics middleware if enabled
if settings.analytics.enabled:
    app.add_middleware(cast(Any, AnalyticsMiddleware), enabled=settings.analytics.enabled)

# Include API router with versioned prefix
api_version = get_api_version()
api_prefix = f"/depictio/api/{api_version}"
app.include_router(router, prefix=api_prefix)


# ---------------------------------------------------------------------------
# React viewer SPA — served at /dashboard-beta/{id} alongside the API.
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

# Dashboard screenshots — written by the auto-screenshot job when a dashboard
# is viewed (depictio/dash/layouts/save.py). Same files Dash serves at
# /static/screenshots/{id}_{light|dark}.png; mounting here lets the React
# /dashboards-beta page reuse them without cross-port hops.
_SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "dash" / "static" / "screenshots"
_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/screenshots",
    StaticFiles(directory=str(_SCREENSHOTS_DIR)),
    name="dashboard-screenshots",
)

# Dash workflow logos / icons (used by both viewers). The React viewer
# references them as ``/assets/images/...`` — same path as the Dash app —
# so we mount the same dir on the FastAPI origin to avoid cross-port hops.
# Without this, ``/assets/images/icons/favicon.png`` 404s on port 8055
# (FastAPI) and the dashboard cards lose their workflow logos.
_DASH_ASSETS_DIR = Path(__file__).resolve().parent.parent / "dash" / "assets"
if _DASH_ASSETS_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_DASH_ASSETS_DIR)),
        name="dash-assets",
    )
# Require both index.html and assets/ — `dist/` alone may exist as an empty
# leftover from an interrupted build and would crash StaticFiles at startup.
if _VIEWER_DIST.is_dir() and _VIEWER_ASSETS.is_dir() and _VIEWER_INDEX.is_file():
    # /dashboard-beta/assets/... → static bundle assets
    app.mount(
        "/dashboard-beta/assets",
        StaticFiles(directory=str(_VIEWER_ASSETS)),
        name="viewer-assets",
    )
    # /dashboard-beta/logos/... → SPA public/ assets (logos, etc.). Mounted
    # only when the directory exists so the SPA still serves when public/ is
    # absent (e.g. older build).
    _viewer_logos = _VIEWER_DIST / "logos"
    if _viewer_logos.is_dir():
        app.mount(
            "/dashboard-beta/logos",
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

        @app.get("/dashboard-beta/favicon.svg")
        async def _serve_viewer_favicon() -> FileResponse:
            return FileResponse(_viewer_favicon, media_type="image/svg+xml")

    @app.get("/dashboard-beta/{_dashboard_id:path}")
    async def _serve_viewer_spa(_dashboard_id: str) -> FileResponse:
        """Serve the React viewer SPA. All sub-paths fall through to index.html
        so React's client-side router handles the dashboard ID segment."""
        return _spa_index()

    @app.get("/dashboard-beta-edit/{_dashboard_id:path}")
    async def _serve_editor_spa(_dashboard_id: str) -> FileResponse:
        """Serve the React editor SPA. Same bundle as the viewer; the SPA's
        boot routing inspects window.location.pathname to render EditorApp.
        Asset paths in index.html still resolve via /dashboard-beta/assets/."""
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

    # /dashboards-beta → React management page (replaces the Dash /dashboards
    # listing). Same bundle as the viewer; main.tsx detects the path prefix
    # and renders <DashboardsApp/>. Asset paths in index.html still resolve
    # via /dashboard-beta/assets/ because Vite stamps them with that base.
    @app.get("/dashboards-beta")
    async def _serve_dashboards_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/dashboards-beta/{_path:path}")
    async def _serve_dashboards_spa(_path: str) -> FileResponse:
        return _spa_index()

    # /about-beta and /admin-beta → same React bundle. main.tsx detects the
    # pathname prefix and renders <AboutApp/> or <AdminApp/>. Coexists with
    # the Dash /about and /admin pages until the sidebar is flipped.
    @app.get("/about-beta")
    async def _serve_about_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/about-beta/{_path:path}")
    async def _serve_about_spa(_path: str) -> FileResponse:
        return _spa_index()

    @app.get("/admin-beta")
    async def _serve_admin_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/admin-beta/{_path:path}")
    async def _serve_admin_spa(_path: str) -> FileResponse:
        return _spa_index()

    # /projects-beta → React projects management page (replaces the Dash
    # /projects listing + multi-step create modal + project/{id}/data detail).
    # Same bundle as the viewer; main.tsx detects the path prefix and renders
    # <ProjectsApp/>. Sub-paths (/projects-beta/{id}, /projects-beta/{id}/permissions)
    # all fall through to index.html so the React app can route internally.
    @app.get("/projects-beta")
    async def _serve_projects_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/projects-beta/{_path:path}")
    async def _serve_projects_spa(_path: str) -> FileResponse:
        return _spa_index()

    # /profile-beta and /cli-agents-beta → React-based replacements for the
    # Dash /profile and /cli_configs management pages. Same SPA bundle;
    # main.tsx detects the path prefix and renders <ProfileApp/> or
    # <CliAgentsApp/>. Coexists with the Dash routes during rollout.
    @app.get("/profile-beta")
    async def _serve_profile_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/profile-beta/{_path:path}")
    async def _serve_profile_spa(_path: str) -> FileResponse:
        return _spa_index()

    @app.get("/cli-agents-beta")
    async def _serve_cli_agents_spa_root() -> FileResponse:
        return _spa_index()

    @app.get("/cli-agents-beta/{_path:path}")
    async def _serve_cli_agents_spa(_path: str) -> FileResponse:
        return _spa_index()
else:
    logger = logging.getLogger(__name__)
    logger.warning(
        "⚠️  React viewer bundle not built at %s (missing index.html or "
        "assets/) — /dashboard-beta/ and /dashboard-beta-edit/ routes will "
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
    return RedirectResponse("/dashboards-beta", status_code=307)


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
