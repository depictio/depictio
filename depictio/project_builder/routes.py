"""The builder's HTTP routes, one factory for both servers.

``build_builder_router(opener)`` declares ``/tree``, ``/suggest``, ``/match``,
``/template`` and ``/metadata``; what differs between the main API and the
standalone server is only how a request's root is opened, so that is the
injected dependency. The main API's opener (``projects_endpoints/builder.py``)
authenticates and confines like the run-folder dialog; the standalone one
serves the single folder it was started on.

Handlers run the sync core off the event loop and answer a
:class:`BuilderRefused` with its ``{detail, code}`` body.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from depictio.cli.cli.utils.data_root import DataRoot
from depictio.project_builder import assemble, infer, match, tree
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.validate import validate_inline_template

BUILDER_PREFIX = "/depictio/api/v1/projects/builder"


class RootSpec(BaseModel):
    """The data root a request reads: a local folder or an ``s3://`` prefix, and
    a private bucket's settings (the run-folder dialog's ``RunStorageIn`` shape)."""

    data_root: str
    storage: dict[str, Any] | None = None
    # Re-list an s3:// prefix instead of reusing the cached listing.
    refresh: bool = False


class RootOpener(Protocol):
    def __call__(self, spec: RootSpec, *, count_files: bool) -> DataRoot: ...


class TreeBody(BaseModel):
    root: RootSpec
    path: str = ""


class SuggestBody(BaseModel):
    root: RootSpec
    path: str
    examples: list[str] = Field(default_factory=list, max_length=50)


class WorkflowShape(BaseModel):
    structure: Literal["flat", "sequencing-runs"] = "flat"
    runs_regex: str | None = None


class MatchBody(BaseModel):
    root: RootSpec
    workflow: WorkflowShape = Field(default_factory=WorkflowShape)
    collection: assemble.DcDraft


class TemplateBody(BaseModel):
    draft: assemble.ProjectDraft
    remote: bool = False


class MetadataBody(BaseModel):
    repo_url: str = Field(max_length=500)


async def run_refusable(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``fn`` off the event loop; a :class:`BuilderRefused` becomes its JSON answer."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except BuilderRefused as exc:
        return JSONResponse(status_code=exc.status, content=exc.body())


def template_for(draft: assemble.ProjectDraft, remote: bool) -> dict[str, Any]:
    """The template a draft becomes, validated as ``from_run`` will validate it."""
    template = assemble.build_template(draft)
    warnings = validate_inline_template(template, remote=remote)
    return {
        "template": template,
        "yaml": assemble.template_yaml(template),
        "template_id": template["template"]["template_id"],
        "warnings": warnings,
    }


def metadata_for(repo_url: str) -> dict[str, Any]:
    from depictio.project_builder.metadata import fetch_workflow_metadata

    try:
        return fetch_workflow_metadata(repo_url)
    except ValueError as exc:
        raise BuilderRefused(400, str(exc), "repo_url_invalid") from exc


def build_builder_router(opener_dependency: Callable[..., RootOpener]) -> APIRouter:
    """The builder routes, opening roots through ``opener_dependency`` (a FastAPI dependency)."""
    router = APIRouter()

    @router.post("/tree")
    async def post_tree(body: TreeBody, opener: RootOpener = Depends(opener_dependency)):
        """One folder level of the data root, folders first; hidden entries left out."""

        def run():
            return tree.list_folder(opener(body.root, count_files=False), body.path)

        return await run_refusable(run)

    @router.post("/suggest")
    async def post_suggest(body: SuggestBody, opener: RootOpener = Depends(opener_dependency)):
        """A first guess (tag, type, scan rule, format, catalog tools) for a picked file."""

        def run():
            return infer.suggest(opener(body.root, count_files=False), body.path, body.examples)

        return await run_refusable(run)

    @router.post("/match")
    async def post_match(body: MatchBody, opener: RootOpener = Depends(opener_dependency)):
        """The files a data collection would ingest, by the scan's own rule, and
        whether their schemas agree."""

        def run():
            root = opener(body.root, count_files=True)
            return match.match_collection(
                root, body.workflow.structure, body.workflow.runs_regex, body.collection
            )

        return await run_refusable(run)

    @router.post("/template")
    async def post_template(body: TemplateBody, _opener: RootOpener = Depends(opener_dependency)):
        """The ad-hoc template a draft becomes, validated; nothing is read or stored."""
        return await run_refusable(template_for, body.draft, body.remote)

    @router.post("/metadata")
    async def post_metadata(body: MetadataBody, _opener: RootOpener = Depends(opener_dependency)):
        """Workflow metadata from a GitHub repository (RO-Crate, nextflow.config, API)."""
        return await run_refusable(metadata_for, body.repo_url)

    return router
