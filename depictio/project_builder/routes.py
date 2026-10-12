"""The ``/project-builder/*`` authoring API (service-free).

Every endpoint resolves paths against ``request.app.state.project_builder_root`` — the
directory ``depictio project-builder <dir>`` was launched with. No Mongo/Redis/Celery/S3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from depictio.project_builder import export_project as export_project_mod
from depictio.project_builder import preview as preview_mod
from depictio.project_builder import recognize as recognize_mod
from depictio.project_builder import tree as tree_mod
from depictio.project_builder.paths import ProjectBuilderPathError

project_builder_router = APIRouter(prefix="/project-builder", tags=["project-builder"])


def _root(request: Request) -> Path:
    return Path(request.app.state.project_builder_root)


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class PathBody(BaseModel):
    path: str


class RecognizeBody(BaseModel):
    path: str
    examples: list[str] = Field(default_factory=list)


class ScanPreviewBody(BaseModel):
    glob: str
    regex: str | None = None
    max_depth: int | None = None
    ignore: list[str] | None = None
    subroot: str | None = None
    structure: str = "flat"
    runs_regex: str | None = None


class WorkflowMetadataBody(BaseModel):
    repo_url: str


class ExportProjectBody(BaseModel):
    name: str
    workflows: list[dict[str, Any]]


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@project_builder_router.get("/context")
def get_context(request: Request) -> dict[str, Any]:
    """The folder the Project Builder was launched from — used to key client-side
    persistence so a refresh restores work, but a different folder starts fresh."""
    return {"root": str(_root(request))}


@project_builder_router.get("/tree")
def get_tree(request: Request, path: str = "") -> dict[str, Any]:
    try:
        return tree_mod.build_tree(_root(request), path)
    except ProjectBuilderPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@project_builder_router.post("/preview-data")
def post_preview_data(request: Request, body: PathBody) -> dict[str, Any]:
    try:
        return preview_mod.preview_file(_root(request), body.path)
    except ProjectBuilderPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface parse errors to the UI
        raise HTTPException(status_code=422, detail=f"could not read file: {exc}") from exc


@project_builder_router.post("/recognize")
def post_recognize(request: Request, body: RecognizeBody) -> dict[str, Any]:
    try:
        return recognize_mod.recognize(_root(request), body.path, body.examples)
    except ProjectBuilderPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@project_builder_router.post("/scan-preview")
def post_scan_preview(request: Request, body: ScanPreviewBody) -> dict[str, Any]:
    try:
        return recognize_mod.scan_preview(
            _root(request),
            body.glob,
            body.regex,
            body.max_depth,
            body.ignore,
            body.subroot,
            body.structure,
            body.runs_regex,
        )
    except ProjectBuilderPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@project_builder_router.post("/workflow-metadata")
def post_workflow_metadata(body: WorkflowMetadataBody) -> dict[str, Any]:
    from depictio.project_builder import metadata as metadata_mod

    try:
        return metadata_mod.fetch_workflow_metadata(body.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@project_builder_router.post("/export/project")
def post_export_project(request: Request, body: ExportProjectBody) -> dict[str, Any]:
    try:
        return export_project_mod.export_project(_root(request), body.model_dump())
    except ProjectBuilderPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"export failed: {exc}") from exc
