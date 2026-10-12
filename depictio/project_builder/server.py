"""Standalone uvicorn app for ``depictio project-builder <dir>``.

A *fresh* ``FastAPI()`` — deliberately NOT the API's ``depictio.api.main:app``,
which imports Beanie/Mongo. It serves the Project Builder SPA bundle plus the
``/project-builder/*`` authoring router, both bound to a single root directory. Fully
service-free: nothing here touches Mongo/Redis/Celery/S3.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.cors import CORSMiddleware

from depictio.project_builder.routes import project_builder_router

# The Project Builder SPA is built as one self-contained HTML (like catalog-preview), so
# there is no separate asset dir to mount — see depictio/viewer/vite.project-builder.config.ts.
PROJECT_BUILDER_HTML = (
    Path(__file__).resolve().parent.parent
    / "viewer"
    / "dist-project-builder"
    / "project-builder.html"
)

_MISSING_BUNDLE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Depictio Project Builder</title></head><body style="font-family:system-ui;max-width:40rem;margin:4rem auto">
<h1>Depictio Project Builder</h1>
<p>The Project Builder UI bundle has not been built yet. Run:</p>
<pre style="background:#f4f4f5;padding:1rem;border-radius:.5rem">cd depictio/viewer &amp;&amp; pnpm run build:project-builder</pre>
<p>The authoring API is live at <a href="/project-builder/tree">/project-builder/tree</a>.</p>
</body></html>"""


def _spa_html() -> str:
    if PROJECT_BUILDER_HTML.exists():
        return PROJECT_BUILDER_HTML.read_text()
    return _MISSING_BUNDLE_HTML


def create_app(root: Path) -> FastAPI:
    """Build the Project Builder FastAPI app rooted at ``root``."""
    app = FastAPI(
        title="Depictio Project Builder",
        docs_url="/project-builder/docs",
        openapi_url="/project-builder/openapi.json",
    )
    app.state.project_builder_root = Path(root).resolve()

    # Permissive CORS so the Vite dev server (separate origin) can hit /project-builder.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(project_builder_router)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:  # noqa: D401
        return HTMLResponse(_spa_html())

    # SPA catch-all — any non-/project-builder GET returns the single-file bundle.
    @app.get("/{full_path:path}", response_class=HTMLResponse)
    def spa(full_path: str) -> HTMLResponse:  # noqa: D401
        return HTMLResponse(_spa_html())

    return app


def run_project_builder(
    root: Path,
    host: str = "127.0.0.1",
    port: int = 8129,
    open_browser: bool = True,
) -> None:
    """Launch the Project Builder server (blocking) and optionally open a browser tab."""
    import uvicorn

    root = Path(root).resolve()
    app = create_app(root)

    if open_browser:
        import threading
        import webbrowser

        url = f"http://{host}:{port}/"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
