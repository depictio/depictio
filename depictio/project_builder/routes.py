"""The builder's HTTP routes, one factory for both servers.

``build_builder_router(opener)`` declares ``/capabilities``, ``/tree``,
``/suggest``, ``/runs_regex``, ``/runs_overview``, ``/match``, ``/tracks_manifest``,
``/template``, ``/from_template`` (a shipped template, described for editing) and ``/metadata``;
what differs between the main API and the standalone server is how a request's root
is opened, so that is the injected dependency, and what
the instance can do (``capabilities``), which each passes in. The main API's
opener (``projects_endpoints/builder.py``)
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
from depictio.project_builder import (
    assemble,
    capabilities,
    infer,
    match,
    overlay,
    runs,
    tracks,
    tree,
)
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
    # ``sequencing-runs``: the first folder of a path is a run, not a name.
    structure: Literal["flat", "sequencing-runs"] = "flat"
    runs_regex: str | None = Field(default=None, max_length=500)


class WorkflowShape(BaseModel):
    structure: Literal["flat", "sequencing-runs"] = "flat"
    runs_regex: str | None = None


class RunsRegexBody(BaseModel):
    root: RootSpec


class RunsOverviewBody(BaseModel):
    root: RootSpec
    runs_regex: str | None = Field(default=None, max_length=500)


class MatchBody(BaseModel):
    root: RootSpec
    workflow: WorkflowShape = Field(default_factory=WorkflowShape)
    collection: assemble.DcDraft


class TracksManifestBody(BaseModel):
    root: RootSpec
    files: list[str] = Field(min_length=1, max_length=tracks.MAX_MANIFEST_FILES)
    sample_regex: str | None = Field(default=None, max_length=500)


class TemplateBody(BaseModel):
    draft: assemble.ProjectDraft
    remote: bool = False
    # The draft edits a shipped template: its collections are the additions.
    base: overlay.TemplateBase | None = None


class FromTemplateBody(BaseModel):
    """A template shipped with Depictio (``nf-core/viralrecon/3.0.0``, ``.../latest``)."""

    template_id: str = Field(max_length=200)


class MetadataBody(BaseModel):
    repo_url: str = Field(max_length=500)


async def run_refusable(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``fn`` off the event loop; a :class:`BuilderRefused` becomes its JSON answer."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except BuilderRefused as exc:
        return JSONResponse(status_code=exc.status, content=exc.body())


def _has_additions(draft: assemble.ProjectDraft) -> bool:
    return bool(draft.links) or any(w.data_collections for w in draft.workflows)


def template_for(
    draft: assemble.ProjectDraft, remote: bool, base: overlay.TemplateBase | None = None
) -> dict[str, Any]:
    """The template a draft becomes, validated as ``from_run`` will validate it.

    With ``base``, the draft is an edit of a shipped template: ``template`` is
    the draft's own collections and links (None when it adds none), ``yaml``
    the shipped template with every edit applied, and ``removed`` what the
    edits take out, with why.
    """
    if base is not None:
        additions = (
            assemble.build_template(
                draft, remote=remote, link_targets=overlay.link_targets(base.template_id)
            )
            if _has_additions(draft)
            else None
        )
        edits = base.edits(additions)
        raw, path, removed, warnings = overlay.compose(base.template_id, edits, remote=remote)
        resolved_id = str((raw.get("template") or {}).get("template_id") or base.template_id)
        return {
            "template": additions,
            "yaml": overlay.composed_yaml(raw, resolved_id),
            "template_id": resolved_id,
            "warnings": warnings,
            "removed": removed,
        }
    template = assemble.build_template(draft, remote=remote)
    warnings = validate_inline_template(template, remote=remote)
    return {
        "template": template,
        "yaml": assemble.template_yaml(template),
        "template_id": template["template"]["template_id"],
        "warnings": warnings,
        "removed": {},
    }


def metadata_for(repo_url: str) -> dict[str, Any]:
    from depictio.project_builder.metadata import fetch_workflow_metadata

    try:
        return fetch_workflow_metadata(repo_url)
    except ValueError as exc:
        raise BuilderRefused(400, str(exc), "repo_url_invalid") from exc


def build_builder_router(
    opener_dependency: Callable[..., RootOpener],
    *,
    mode: Literal["server", "standalone"] = "server",
    events_enabled: Callable[[], bool | None] = lambda: None,
) -> APIRouter:
    """The builder routes, opening roots through ``opener_dependency`` (a FastAPI dependency).

    ``events_enabled``: whether the instance acts on a project's realtime flag
    (None when it cannot know, as the standalone builder).
    """
    router = APIRouter()

    @router.get("/capabilities")
    async def get_capabilities(_opener: RootOpener = Depends(opener_dependency)):
        """The collection kinds and options this Depictio offers, and the instance
        settings they depend on."""
        return await asyncio.to_thread(capabilities.capabilities, mode, events_enabled())

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
            return infer.suggest(
                opener(body.root, count_files=False),
                body.path,
                body.examples,
                runs=body.structure == "sequencing-runs",
                runs_regex=body.runs_regex,
            )

        return await run_refusable(run)

    @router.post("/runs_regex")
    async def post_runs_regex(body: RunsRegexBody, opener: RootOpener = Depends(opener_dependency)):
        """A runs regex guessed from the data root's first-level folders."""

        def run():
            return runs.suggest_runs_regex(opener(body.root, count_files=False))

        return await run_refusable(run)

    @router.post("/runs_overview")
    async def post_runs_overview(
        body: RunsOverviewBody, opener: RootOpener = Depends(opener_dependency)
    ):
        """The runs a regex takes in, the layout their files share, and the runs that differ."""

        def run():
            return runs.overview(opener(body.root, count_files=True), body.runs_regex)

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

    @router.post("/tracks_manifest")
    async def post_tracks_manifest(
        body: TracksManifestBody, opener: RootOpener = Depends(opener_dependency)
    ):
        """A genome-browser track manifest for picked track files, uris relative to the root."""

        def run():
            return tracks.manifest_for(
                opener(body.root, count_files=False), body.files, body.sample_regex
            )

        return await run_refusable(run)

    @router.post("/template")
    async def post_template(body: TemplateBody, _opener: RootOpener = Depends(opener_dependency)):
        """The ad-hoc template a draft becomes, validated; nothing is read or stored."""
        return await run_refusable(template_for, body.draft, body.remote, body.base)

    @router.post("/from_template")
    async def post_from_template(
        body: FromTemplateBody, _opener: RootOpener = Depends(opener_dependency)
    ):
        """A shipped template as the builder shows it, read-only, to be edited as a
        list of changes (see :mod:`overlay`).

        Only templates shipped with Depictio are read, by id; nothing else on disk is.
        """
        return await run_refusable(overlay.describe_template, body.template_id)

    @router.post("/metadata")
    async def post_metadata(body: MetadataBody, _opener: RootOpener = Depends(opener_dependency)):
        """Workflow metadata from a GitHub repository (RO-Crate, nextflow.config, API)."""
        return await run_refusable(metadata_for, body.repo_url)

    return router
