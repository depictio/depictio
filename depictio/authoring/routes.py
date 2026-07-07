"""The ``/studio/*`` authoring API (service-free).

Every endpoint resolves paths against ``request.app.state.studio_root`` — the
directory ``depictio studio <dir>`` was launched with. No Mongo/Redis/Celery/S3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from depictio.authoring import export_dashboard as export_dashboard_mod
from depictio.authoring import preview as preview_mod
from depictio.authoring import recognize as recognize_mod
from depictio.authoring import render as render_mod
from depictio.authoring import suggest as suggest_mod
from depictio.authoring import tree as tree_mod
from depictio.authoring.export_catalog import CatalogExportNotImplemented, export_catalog
from depictio.authoring.paths import StudioPathError

studio_router = APIRouter(prefix="/studio", tags=["studio"])


def _root(request: Request) -> Path:
    return Path(request.app.state.studio_root)


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class PathBody(BaseModel):
    path: str


class RecognizeBody(BaseModel):
    path: str
    examples: list[str] = Field(default_factory=list)


class SuggestBody(BaseModel):
    schema_: dict[str, str] = Field(alias="schema")
    dc_type: str | None = None
    min_confidence: float = 0.0

    model_config = {"populate_by_name": True}


class RenderBody(BaseModel):
    path: str
    spec: dict[str, Any]
    theme: str = "light"


class ExportDashboardBody(BaseModel):
    name: str
    title: str | None = None
    subtitle: str = ""
    workflow_name: str | None = None
    data_collections: list[dict[str, Any]]
    components: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@studio_router.get("/tree")
def get_tree(request: Request, path: str = "") -> dict[str, Any]:
    try:
        return tree_mod.build_tree(_root(request), path)
    except StudioPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@studio_router.post("/preview-data")
def post_preview_data(request: Request, body: PathBody) -> dict[str, Any]:
    try:
        return preview_mod.preview_file(_root(request), body.path)
    except StudioPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface parse errors to the UI
        raise HTTPException(status_code=422, detail=f"could not read file: {exc}") from exc


@studio_router.post("/recognize")
def post_recognize(request: Request, body: RecognizeBody) -> dict[str, Any]:
    try:
        return recognize_mod.recognize(_root(request), body.path, body.examples)
    except StudioPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@studio_router.post("/suggest")
def post_suggest(body: SuggestBody) -> dict[str, Any]:
    return {
        "suggestions": suggest_mod.suggest_for_schema(
            body.schema_, body.dc_type, body.min_confidence
        )
    }


@studio_router.post("/render")
def post_render(request: Request, body: RenderBody) -> dict[str, Any]:
    from depictio.catalog.payload import CatalogPayloadError

    try:
        return render_mod.render_spec(_root(request), body.path, body.spec, body.theme)
    except StudioPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CatalogPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid viz spec: {exc}") from exc


@studio_router.post("/export/dashboard")
def post_export_dashboard(request: Request, body: ExportDashboardBody) -> dict[str, Any]:
    try:
        return export_dashboard_mod.export_dashboard(_root(request), body.model_dump())
    except StudioPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"export failed: {exc}") from exc


@studio_router.post("/export/catalog")
def post_export_catalog() -> dict[str, Any]:
    try:
        return export_catalog()
    except CatalogExportNotImplemented as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
