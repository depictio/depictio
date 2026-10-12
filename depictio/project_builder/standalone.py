"""``depictio project-builder <dir>``: the builder on one folder, without a server.

A fresh FastAPI app, never ``depictio.api.main`` (which needs MongoDB, Redis
and S3). It serves the main viewer bundle (``viewer/dist``, shipped in the
wheel) with a ``depictio-mode`` meta tag that tells the SPA to boot straight
into the Project Builder with no sign-in, and the builder routes at the same
paths as the main API, so the SPA's client is the same in both. On top:

- ``GET  /context``: the folder served, where the bundle will be written;
- ``POST /plan``: what the template would ingest (a dry-run ``FromRunReport``);
- ``POST /write``: write the template bundle for ``depictio ingest --template``;
- ``POST /depictio/api/v1/projects/run_file_preview``: the run-folder dialog's
  file preview, for that folder only.

Every request names the folder it reads, and anything but the served one is
refused. The server binds 127.0.0.1 by default and refuses a request whose
``Host`` is not a loopback name (DNS rebinding), unless started on another host.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.cli.cli.utils.file_preview import RunFilePreview, preview_root_file
from depictio.models.local_access import LocalPathRefused
from depictio.project_builder.bundle import default_bundle_dir, write_bundle
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.plan import plan_inline
from depictio.project_builder.roots import standalone_root
from depictio.project_builder.routes import (
    BUILDER_PREFIX,
    RootSpec,
    build_builder_router,
    run_refusable,
)
from depictio.project_builder.validate import validate_inline_template

MODE_META = '<meta name="depictio-mode" content="project-builder">'
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_PORT = 8129


class PlanBody(BaseModel):
    template: dict[str, Any]
    project_name: str | None = None


class WriteBody(BaseModel):
    template: dict[str, Any]
    overwrite: bool = False


class FilePreviewBody(BaseModel):
    data_root: str
    location: str
    storage: dict[str, Any] | None = None
    max_rows: int = Field(default=20, ge=1, le=50)
    infer_types: bool = False


def viewer_index(viewer_dist: Path) -> str:
    """The viewer's ``index.html`` with the builder's mode tag, read once at start."""
    html = (viewer_dist / "index.html").read_text()
    if MODE_META in html:
        return html
    return html.replace("<head>", f"<head>\n    {MODE_META}", 1)


def create_app(
    folder: str | Path,
    *,
    viewer_dist: Path,
    out_dir: Path | None = None,
    allowed_hosts: frozenset[str] | None = LOOPBACK_HOSTS,
) -> FastAPI:
    """The standalone app serving ``folder``. ``allowed_hosts=None`` turns the Host check off."""
    root = standalone_root(folder)
    root_path = Path(root.location)
    bundle_dir = out_dir or default_bundle_dir(root_path, root_path.name)
    index_html = viewer_index(viewer_dist)

    app = FastAPI(
        title="Depictio Project Builder",
        docs_url=f"{BUILDER_PREFIX}/docs",
        openapi_url=f"{BUILDER_PREFIX}/openapi.json",
    )
    app.state.root = root
    app.state.bundle_dir = bundle_dir

    if allowed_hosts is not None:

        @app.middleware("http")
        async def _loopback_only(request: Request, call_next):
            # Parsed from the Host header, brackets of an IPv6 address stripped.
            if (request.url.hostname or "") not in allowed_hosts:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "The Project Builder answers on localhost only.",
                        "code": "non_loopback_host",
                    },
                )
            return await call_next(request)

    def _same_folder(data_root: str) -> LocalDataRoot:
        try:
            asked = Path(data_root).expanduser().resolve()
        except (OSError, RuntimeError):
            asked = None
        if asked != root_path:
            raise BuilderRefused(
                400, f"This Project Builder serves {root_path} only.", "builder_root_other"
            )
        return root

    def standalone_opener():
        def open_root(spec: RootSpec, *, count_files: bool) -> LocalDataRoot:
            return _same_folder(spec.data_root)

        return open_root

    app.include_router(build_builder_router(standalone_opener), prefix=BUILDER_PREFIX)

    extra = APIRouter()

    @extra.get("/context")
    async def get_context() -> dict[str, Any]:
        """The folder this builder serves, and where it writes the template bundle."""
        probe = bundle_dir if bundle_dir.exists() else bundle_dir.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return {
            "mode": "standalone",
            "data_root": str(root_path),
            "out_dir": str(bundle_dir),
            "writable": os.access(probe, os.W_OK),
        }

    @extra.post("/plan")
    async def post_plan(body: PlanBody):
        """What the template would ingest from the folder, as the server's from_run dry run."""

        def run():
            validate_inline_template(body.template, remote=False)
            return plan_inline(body.template, root, project_name=body.project_name)

        return await run_refusable(run)

    @extra.post("/write")
    async def post_write(body: WriteBody):
        """Write the template bundle; 409 ``bundle_exists`` unless ``overwrite``."""

        def run():
            validate_inline_template(body.template, remote=False)
            plan_inline(body.template, root)
            return write_bundle(
                body.template, bundle_dir, data_root=str(root_path), overwrite=body.overwrite
            )

        return await run_refusable(run)

    app.include_router(extra, prefix=BUILDER_PREFIX)

    @app.post("/depictio/api/v1/projects/run_file_preview", response_model=RunFilePreview)
    async def post_run_file_preview(body: FilePreviewBody):
        """The run-folder dialog's file preview, for a file of the served folder."""

        def run():
            served = _same_folder(body.data_root)
            relative = served.relative_of(body.location)
            if relative is None:
                raise BuilderRefused(
                    422, f"'{body.location}' is outside {root_path}.", "location_outside_run"
                )
            try:
                return preview_root_file(
                    served, relative, max_rows=body.max_rows, infer_types=body.infer_types
                )
            except FileNotFoundError as exc:
                raise BuilderRefused(
                    404, f"'{body.location}' is not a file of the folder.", "run_file_missing"
                ) from exc
            except LocalPathRefused as exc:
                raise BuilderRefused(422, exc.detail, exc.code) from exc

        return await run_refusable(run)

    assets = viewer_dist / "assets"
    if assets.is_dir():
        app.mount("/dashboard/assets", StaticFiles(directory=str(assets)), name="viewer-assets")
    logos = viewer_dist / "logos"
    if logos.is_dir():
        app.mount("/dashboard/logos", StaticFiles(directory=str(logos)), name="viewer-logos")
    favicon = viewer_dist / "favicon.svg"

    @app.get("/dashboard/favicon.svg", include_in_schema=False)
    async def get_favicon() -> Response:
        if not favicon.is_file():
            return Response(status_code=404)
        return Response(favicon.read_bytes(), media_type="image/svg+xml")

    @app.get("/", include_in_schema=False)
    async def get_root() -> RedirectResponse:
        return RedirectResponse("/projects/build")

    @app.get("/{_path:path}", include_in_schema=False)
    async def get_spa(_path: str) -> Response:
        if _path.startswith("depictio/api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found."})
        return HTMLResponse(index_html, headers=NO_CACHE)

    return app


def serve(
    folder: str | Path,
    *,
    viewer_dist: Path,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    out_dir: Path | None = None,
    open_browser: bool = True,
) -> None:
    """Run the standalone builder until interrupted."""
    import uvicorn

    allowed = LOOPBACK_HOSTS if host in LOOPBACK_HOSTS else None
    app = create_app(folder, viewer_dist=viewer_dist, out_dir=out_dir, allowed_hosts=allowed)
    if open_browser:
        import threading
        import webbrowser

        url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/projects/build"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
