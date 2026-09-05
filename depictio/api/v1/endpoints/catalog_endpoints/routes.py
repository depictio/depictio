"""Catalog compose endpoint — matches ingested DCs against catalog entries.

GET /catalog/project/{project_id}/compose
  Returns recognized catalog modules for a project, grouped by tool. Each
  match includes the dc_id / wf_id so the React builder can jump straight to
  Step 2 with roles pre-filled.
"""

from __future__ import annotations

import logging
import secrets
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from depictio.api.v1.configs.security_headers import csp_with_script_nonce
from depictio.api.v1.db import files_collection, multiqc_collection, projects_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.api.v1.source_links import github_blob_url
from depictio.catalog.payload import (
    CatalogPayloadError,
    advanced_viz_persist_config,
    build_payload,
    json_safe,
    multiqc_module,
)
from depictio.models.components.advanced_viz.catalog import load_catalog_entries
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

catalog_endpoint_router = APIRouter()

# DC types the compose endpoint can recognise. Tables carry the catalog's
# tabular outputs; MultiQC DCs carry every `component: multiqc` section render.
_MATCHABLE_DC_TYPES = {"table", "multiqc"}


def _render_to_dict(render, output) -> dict[str, Any]:
    """Serialise a render's ``renders_as`` declaration for the React builder.

    For advanced_viz renders, also attach the pre-computed ``config`` blob (role
    bindings + data-derived viz-control defaults) so a catalog-added component
    persists exactly what the preview rendered — see ``advanced_viz_persist_config``.
    """
    spec = render.model_dump(exclude_none=True, exclude_defaults=True)
    if render.component == "advanced_viz":
        config = advanced_viz_persist_config(output, render)
        if config is not None:
            spec["config"] = config
    return spec


def _match_dc_to_catalog(
    entries, *, basename: str = "", full_path: str = "", recipe: str | None = None
) -> list[dict[str, Any]]:
    """Return catalog output matches for a DC identified by path and/or recipe.

    Two lanes, and which one an output uses is decided by whether it declares a
    recipe — the catalog's schema-ownership rule (SCHEMA.md): a recipe owns the
    output columns, and such an output must not declare ``columns`` of its own.

    - **No recipe** → the raw file is the bindable frame, recognised by
      ``find.filename`` (fnmatch on the basename) or any of ``find.path_globs()``
      (``path_glob`` plus ``path_glob_alt``, each tried with PurePosixPath.match
      on the full path; ``**`` is a single segment there, which is what the alt
      globs exist for).
    - **Recipe** → only the recipe that produced the DC binds it, compared to the
      output's ``recipe``. ``find`` still says which raw file the recipe eats,
      but the raw DC cannot satisfy renders authored against the recipe's
      schema: ``mosdepth_genome_coverage`` renames chrom/start/coverage to
      chromosome/position/value, so a coverage track offered on the raw
      collection came up "chromosome" not found. Keeping the two apart also
      stops one output being offered twice, once per collection.

    The recipe lane is what recognises *derived* collections. A recipe DC never
    keeps the raw pipeline path the ``find`` patterns describe: it is either
    computed straight into a delta table (no scan block at all) or materialised
    as a canonical seed file. Recipe paths are namespaced per tool and pipeline,
    so equality on them cannot collide the way a bare canonical basename would.
    """
    matches = []
    for entry in entries:
        for output in entry.outputs:
            find = output.find
            if output.recipe is None:
                # Raw lane. The `basename` / `full_path` guards keep a recipe-only
                # lookup, which passes neither, from matching a wildcard `find`
                # pattern on "".
                matched = bool(
                    (basename and find.filename and fnmatch(basename, find.filename))
                    or (
                        full_path
                        and any(PurePosixPath(full_path).match(g) for g in find.path_globs())
                    )
                )
            else:
                # Recipe lane: only the recipe that produced the DC binds it.
                matched = recipe is not None and recipe == output.recipe
            if matched:
                matches.append(
                    {
                        "tool_id": entry.id,
                        "tool_name": entry.name,
                        "output_id": output.id,
                        "name": output.name or output.id,
                        # The producing tool, when the catalog tool aggregates
                        # other tools' output (MultiQC). None everywhere else.
                        "origin_tool": output.origin_tool,
                        "description": output.description or "",
                        # Static provenance, straight off the already-loaded catalog
                        # YAML: it costs nothing here and saves the picker a second
                        # round-trip to show where an offered render comes from.
                        "mode": output.mode,
                        "recipe": output.recipe,
                        "fixture": output.fixture,
                        "nf_core_url": output.nf_core_url or entry.nf_core_url,
                        "biotools_url": output.biotools_url or entry.biotools_url,
                        "find": output.find.model_dump(exclude_none=True),
                        # Where this offer is declared, so the picker can link to
                        # the module definition rather than only describing it.
                        "source_url": github_blob_url(output._source_file),
                        "renders_as": [
                            _render_to_dict(r, output) for r in (output.renders_as or [])
                        ],
                    }
                )
    return matches


def _multiqc_sections(dc_id: str) -> set[str] | None:
    """Modules a MultiQC DC's report can actually render as a `multiqc` component,
    or None if unknown.

    Every MultiQC catalog output keys on the same `multiqc.parquet` path, so path
    matching alone offers all of them (bcftools, ivar, samtools, ...) on a report
    that only ran two. The ingested report already records which modules it holds,
    so use that as the discriminator. `data_collection_id` is stored as a string
    in this collection, not an ObjectId.

    What is stored are MultiQC *anchors*, and a module that ran more than once is
    anchored per run (`samtools_bowtie2`, `samtools_ivar`, `ivar_variants`), while
    a catalog output's `section` names the module itself. `multiqc_module` is the
    normalisation the preview payload already applies to the same anchors, so both
    sides of the catalog agree on what a section means.

    A module that is present but produced no *plot* (a custom-content table like
    `summary_conformance_metrics`, or a `*_software_versions` module) is excluded
    too: the picker (`multiqcConfigForSection` in CatalogTab.tsx) resolves a
    section to `opts.plots[anchor][0]`, and a module with no `plots` entry there
    persists a null `selected_plot` that `render_multiqc` then 400s on at render
    time instead of never being offered. `general_stats` is the one exception —
    it renders through its own stub path and needs no plot.
    """
    doc = multiqc_collection.find_one(
        {"data_collection_id": dc_id}, {"metadata.modules": 1, "metadata.plots": 1}
    )
    if not doc:
        return None
    metadata = doc.get("metadata") or {}
    modules = metadata.get("modules")
    if not isinstance(modules, list) or not modules:
        # An empty list means extraction produced nothing, not that the report is
        # empty. `_parsed_multiqc_report` in dashboards_endpoints treats it the
        # same way: keep every component rather than silently dropping them all.
        return None
    present = {multiqc_module(str(m).lower()) for m in modules}

    # An empty `plots_meta` is not treated as "unknown, trust presence": a
    # module-wide extraction failure in `extract_multiqc_metadata` (one
    # section's plot anchor missing from MultiQC's own report.plot_by_id) can
    # leave `plots` empty on an otherwise-healthy, fully-populated report —
    # confirmed happening intermittently on this exact fixture. Every module
    # in `present` genuinely has no plot to show in that case, so offering
    # them anyway only guarantees a `selected_plot` 400 at render time; the
    # extraction side now recovers per-section instead of zeroing the whole
    # report (see the `multiqc.list_plots()` reimplementation in
    # `multiqc_processor.py`), so this branch should be rare going forward.
    plots_meta = metadata.get("plots") or {}
    plottable = {multiqc_module(str(m).lower()) for m in plots_meta} | {"general_stats"}
    return present & plottable


def _keep_present_multiqc_sections(
    matches: list[dict[str, Any]], sections: set[str] | None
) -> list[dict[str, Any]]:
    """Keep only matches whose section renders both exist in this report and are
    renderable (see `_multiqc_sections`).

    A match is dropped when it declares section renders and none of them is in
    `sections`. Renders without a `section` (plain tables, cards) are never touched.
    """
    if sections is None:
        return matches
    kept = []
    for match in matches:
        declared = {str(r["section"]).lower() for r in match["renders_as"] if r.get("section")}
        if declared and declared.isdisjoint(sections):
            continue
        kept.append(match)
    return kept


def _dc_match_inputs(config: dict[str, Any]) -> tuple[str | None, str, str]:
    """What a stored DC offers the matcher: its recipe, scan mode, scanned file.

    A persisted DC carries every config key, with an explicit ``null`` wherever
    the template omitted the block (``MongoModel.mongo()`` dumps without
    ``exclude_none``), so ``config.get("scan", {})`` still hands back ``None``:
    a recipe DC computed straight into a delta table genuinely has no scan.
    Normalising here keeps that null out of the caller's branching.
    """
    transform = config.get("transform")
    recipe = transform.get("recipe") if isinstance(transform, dict) else None

    scan = config.get("scan")
    if not isinstance(scan, dict):
        return recipe, "", ""
    params = scan.get("scan_parameters")
    filename = params.get("filename") if isinstance(params, dict) else None
    return recipe, str(scan.get("mode") or ""), str(filename or "")


def _add_matches(
    modules_by_tool: dict[str, dict[str, Any]],
    matches: list[dict[str, Any]],
    dc_id: str,
    wf_id: str,
    dc_tag: str,
    dc_type: str,
    seen: set[tuple[str, str, str]],
) -> None:
    for match in matches:
        tool_id = match["tool_id"]
        # A DC can match the same output through more than one signal (path and
        # recipe), and a recursive DC gets one call per ingested file.
        key = (tool_id, match["output_id"], dc_id)
        if key in seen:
            continue
        seen.add(key)
        if tool_id not in modules_by_tool:
            modules_by_tool[tool_id] = {
                "tool_id": tool_id,
                "tool_name": match["tool_name"],
                "matches": [],
            }
        # Everything the matcher emitted except the tool identity, which is
        # already the group this match sits in.
        modules_by_tool[tool_id]["matches"].append(
            {
                **{k: v for k, v in match.items() if k not in ("tool_id", "tool_name")},
                "dc_id": dc_id,
                "wf_id": wf_id,
                "dc_tag": dc_tag,
                # The picker previews the collection's own rows next to the
                # offer, and a MultiQC report has none to show.
                "dc_type": dc_type,
            }
        )


@catalog_endpoint_router.get("/project/{project_id}/compose")
async def compose_project(
    project_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Return recognized catalog modules for a project, grouped by tool_id."""
    try:
        oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    current_user_id = ObjectId(current_user.id)
    permission_query: dict[str, Any] = {
        "_id": oid,
        "$or": [
            {"permissions.owners._id": current_user_id},
            {"permissions.editors._id": current_user_id},
            {"permissions.viewers._id": current_user_id},
            {"is_public": True},
        ],
    }
    if current_user.is_admin:
        permission_query = {"_id": oid}

    project = projects_collection.find_one(permission_query)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        entries = load_catalog_entries()
    except Exception:
        logger.exception("Failed to load catalog entries")
        raise HTTPException(status_code=500, detail="Catalog unavailable")

    modules_by_tool: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str, str]] = set()

    # Collect recursive-scan DC ids for a single bulk files query.
    recursive_dc_ids: list[ObjectId] = []
    dc_meta: dict[str, dict[str, Any]] = {}  # dc_id_str -> {wf_id, dc_tag, dc_type}

    for workflow in project.get("workflows", []):
        wf_id = str(workflow.get("_id", ""))
        for dc in workflow.get("data_collections", []):
            if not isinstance(dc, dict):
                continue
            dc_tag_raw = dc.get("data_collection_tag", "?")
            config = dc.get("config", {})
            if not isinstance(config, dict):
                logger.debug("catalog/compose: DC %s skipped — config not a dict", dc_tag_raw)
                continue
            dc_type = (config.get("type") or "").lower()
            if dc_type not in _MATCHABLE_DC_TYPES:
                logger.debug(
                    "catalog/compose: DC %s skipped — type=%r has no catalog outputs",
                    dc_tag_raw,
                    dc_type,
                )
                continue
            dc_id_str = str(dc.get("_id", ""))
            dc_tag = dc.get("data_collection_tag", dc_id_str)
            recipe, scan_mode, filename = _dc_match_inputs(config)

            # Recipe first: a recipe DC is recognised by what built it, whether or
            # not it was ever scanned (see _match_dc_to_catalog).
            if recipe:
                logger.debug("catalog/compose: DC %s — recipe=%r", dc_tag, recipe)
                _add_matches(
                    modules_by_tool,
                    _match_dc_to_catalog(entries, recipe=recipe),
                    dc_id_str,
                    wf_id,
                    dc_tag,
                    dc_type,
                    seen,
                )

            if scan_mode == "single":
                if not filename:
                    logger.debug("catalog/compose: DC %s — single mode but no filename", dc_tag)
                    continue
                logger.debug("catalog/compose: DC %s — single filename=%r", dc_tag, filename)
                _add_matches(
                    modules_by_tool,
                    _match_dc_to_catalog(entries, basename=Path(filename).name, full_path=filename),
                    dc_id_str,
                    wf_id,
                    dc_tag,
                    dc_type,
                    seen,
                )

            elif scan_mode == "recursive":
                try:
                    dc_oid = ObjectId(dc_id_str)
                    recursive_dc_ids.append(dc_oid)
                    dc_meta[dc_id_str] = {"wf_id": wf_id, "dc_tag": dc_tag, "dc_type": dc_type}
                except Exception:
                    logger.debug("catalog/compose: DC %s — invalid ObjectId, skipping", dc_tag)
            elif not recipe:
                logger.debug(
                    "catalog/compose: DC %s skipped — no recipe and unknown scan mode %r",
                    dc_tag,
                    scan_mode,
                )

    # Bulk-resolve recursive DCs via the files collection (one query).
    multiqc_sections = {
        dc_id: _multiqc_sections(dc_id)
        for dc_id, meta in dc_meta.items()
        if meta["dc_type"] == "multiqc"
    }
    if recursive_dc_ids:
        for file_doc in files_collection.find(
            {"data_collection_id": {"$in": recursive_dc_ids}},
            {"file_location": 1, "filename": 1, "data_collection_id": 1},
        ):
            dc_oid = file_doc.get("data_collection_id")
            dc_id_str = str(dc_oid)
            meta = dc_meta.get(dc_id_str)
            if not meta:
                continue
            file_location = file_doc.get("file_location", "")
            basename = Path(file_location).name if file_location else file_doc.get("filename", "")
            if not basename:
                continue
            logger.debug(
                "catalog/compose: recursive DC %s — file_location=%r", meta["dc_tag"], file_location
            )
            matches = _match_dc_to_catalog(entries, basename=basename, full_path=file_location)
            if dc_id_str in multiqc_sections:
                matches = _keep_present_multiqc_sections(matches, multiqc_sections[dc_id_str])
            _add_matches(
                modules_by_tool,
                matches,
                dc_id=dc_id_str,
                wf_id=meta["wf_id"],
                dc_tag=meta["dc_tag"],
                dc_type=meta["dc_type"],
                seen=seen,
            )

    return {"modules": list(modules_by_tool.values())}


@catalog_endpoint_router.get("/output/{output_id}/preview-payload")
async def preview_output_payload(
    output_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Compute and return the preview payload for a catalog output (from its fixture).

    The payload contains pre-rendered Plotly JSON (figures), card values, table
    schemas, and advanced-viz data — ready for the React preview panel to render
    without any live API calls.
    """
    try:
        entries = load_catalog_entries()
    except Exception:
        logger.exception("Failed to load catalog entries")
        raise HTTPException(status_code=500, detail="Catalog unavailable")

    for entry in entries:
        for output in entry.outputs:
            if output.id == output_id:
                try:
                    # Same normalisation the embedded bundle gets: a plotly trace
                    # built on a pandas frame keeps numpy arrays, which FastAPI's
                    # serialiser refuses outright (500), and NaN, which it emits
                    # as a bare token no browser will parse.
                    return json_safe(build_payload(output, theme="light", tool=entry))
                except CatalogPayloadError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                except Exception:
                    logger.exception("Failed to build preview for output %s", output_id)
                    raise HTTPException(status_code=500, detail="Preview generation failed")

    raise HTTPException(status_code=404, detail=f"Output {output_id!r} not found in catalog")


@catalog_endpoint_router.get("/output/{output_id}/preview-html", response_class=HTMLResponse)
async def preview_output_html(
    output_id: str,
    render_id: str | None = Query(None, description="If given, only this render index is shown"),
    current_user: User = Depends(get_user_or_anonymous),
) -> HTMLResponse:
    """Serve the standalone catalog-preview HTML for an output (uses fixture data).

    The HTML embeds the pre-built catalog-preview bundle with the real
    ComponentRenderer and the pre-computed payload — no live API calls inside.
    Pass ``?render_id=<output_id>-<idx>`` to preview a single component in isolation.
    """
    from depictio.catalog.payload import render_html

    try:
        entries = load_catalog_entries()
    except Exception:
        logger.exception("Failed to load catalog entries")
        raise HTTPException(status_code=500, detail="Catalog unavailable")

    for entry in entries:
        for output in entry.outputs:
            if output.id == output_id:
                try:
                    # The bundle is one giant inline <script type="module">, which
                    # the baseline `script-src 'self'` refuses to execute (the
                    # iframe then renders blank). Stamp a per-response nonce and
                    # allow exactly that nonce, leaving every other directive as
                    # shipped. SecurityHeadersMiddleware uses setdefault, so this
                    # header wins for this response only.
                    nonce = secrets.token_urlsafe(16)
                    html = render_html(
                        output, theme="light", tool=entry, render_id=render_id, nonce=nonce
                    )
                    return HTMLResponse(
                        content=html,
                        headers={"Content-Security-Policy": csp_with_script_nonce(nonce)},
                    )
                except CatalogPayloadError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                except Exception:
                    logger.exception("Failed to render preview HTML for output %s", output_id)
                    raise HTTPException(status_code=500, detail="Preview generation failed")

    raise HTTPException(status_code=404, detail=f"Output {output_id!r} not found in catalog")
