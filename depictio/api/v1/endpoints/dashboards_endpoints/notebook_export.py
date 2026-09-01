"""Dashboard → notebook: preflight and export endpoints.

Everything that needs Mongo, Delta or link resolution happens here, in
``build_export_plan``; the plan is then handed to the generator, which only
turns it into cells. The helpers come from ``routes`` — the same ones the
funnel endpoint uses — so the stage counts in the notebook are the counts the
funnel view showed, computed by the same code.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import Depends, HTTPException, Response

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    dashboards_endpoint_router,
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    NotebookBuilder,
    StagePlan,
)
from depictio.api.v1.services.notebook_export.ipynb import (
    IpynbExportUnavailable,
    ipynb_available,
    marimo_version,
    to_ipynb,
)
from depictio.api.v1.services.notebook_export.quarto import QuartoFrontMatter, to_quarto_ipynb
from depictio.models.models.analysis_state import (
    AnalysisState,
    NotebookExportRequest,
    NotebookPreflight,
)
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.users import User

STAGE_COMPONENT_TYPES: frozenset[str] = frozenset(
    {"figure", "table", "map", "image", "card", "interactive"}
)

TAB_PROJECTION = {
    k: 1
    for k in (
        "dashboard_id",
        "title",
        "subtitle",
        "tab_order",
        "is_main_tab",
        "main_tab_name",
        "parent_dashboard_id",
        "grid_sections",
        "filter_sections",
        "stored_metadata",
        "project_id",
    )
}


def _require_enabled() -> None:
    if not settings.notebook_export.enabled:
        raise HTTPException(status_code=404, detail="Notebook export is disabled.")


def _order_active_filters(
    filters: list[dict[str, Any]], stage_order: list[str]
) -> list[dict[str, Any]]:
    """The funnel modal's reconcile rule: ranked ones first, the rest in their order."""
    by_index = {str(f.get("index")): f for f in filters}
    ranked: list[dict[str, Any]] = []
    for idx in stage_order:
        f = by_index.pop(str(idx), None)
        if f is not None:
            ranked.append(f)
    for f in filters:
        if by_index.pop(str(f.get("index")), None) is not None:
            ranked.append(f)
    return ranked


def _dc_tags(project: dict[str, Any] | None) -> dict[str, str]:
    tags: dict[str, str] = {}
    for wf in (project or {}).get("workflows") or []:
        for dc in wf.get("data_collections") or []:
            dc_id = str(dc.get("_id") or dc.get("id") or "")
            tag = dc.get("data_collection_tag") or dc.get("tag")
            if dc_id and tag:
                tags[dc_id] = str(tag)
    for dc in (project or {}).get("data_collections") or []:
        dc_id = str(dc.get("_id") or dc.get("id") or "")
        tag = dc.get("data_collection_tag") or dc.get("tag")
        if dc_id and tag:
            tags.setdefault(dc_id, str(tag))
    return tags


def _entry_key(entry: dict[str, Any]) -> str:
    return json.dumps(
        [entry.get("index"), entry.get("column_name"), entry.get("value")],
        sort_keys=True,
        default=str,
    )


def _cleaned_with_index(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for f in filters:
        cleaned = routes._build_filter_metadata([f])
        if not cleaned:
            continue
        entry = dict(cleaned[0])
        entry["index"] = str(f.get("index") or "")
        entry["link"] = entry["index"].startswith("link_")
        out.append(entry)
    return out


def _dtypes_for(family_doc: dict[str, Any], dc_id: str, wf_id: str | None) -> dict | None:
    """The DC's Delta schema, or ``None`` when it cannot be read at export time."""
    if not wf_id:
        return None
    try:
        from depictio.api.v1.deltatables_utils import _get_cached_dtypes, open_deltatable_scan

        scan = open_deltatable_scan(
            workflow_id=ObjectId(str(wf_id)),
            data_collection_id=dc_id,
            init_data=routes._funnel_init_data(family_doc, dc_id),
        )
        if scan is None:
            return None
        dtypes = _get_cached_dtypes(scan, str(dc_id), None)
        return dict(dtypes) if dtypes else None
    except Exception as exc:  # the notebook still works: predicates fall back to string casts
        logger.debug(f"notebook export: schema unavailable for {dc_id}: {exc}")
        return None


def _who(current_user: Any) -> str | None:
    for attr in ("email", "username", "name"):
        value = getattr(current_user, attr, None)
        if value:
            return str(value)
    return None


def build_export_plan(
    dashboard_id: PyObjectId,
    state: AnalysisState,
    current_user: User,
    access_token: str | None,
) -> ExportPlan:
    family_id, raw_tabs = routes._resolve_tab_family(dashboard_id, current_user, TAB_PROJECTION)
    tabs = [convert_objectid_to_str(t) for t in raw_tabs]
    if not tabs:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")
    project_id = tabs[0].get("project_id")
    project_doc = None
    try:
        project_doc = routes.projects_collection.find_one({"_id": ObjectId(str(project_id))})
    except Exception:
        project_doc = None
    project = convert_objectid_to_str(project_doc) if project_doc else None
    dc_tags = _dc_tags(project)

    family_meta: list[dict[str, Any]] = []
    for tab in tabs:
        family_meta.extend(m for m in (tab.get("stored_metadata") or []) if isinstance(m, dict))
    family_doc = {"stored_metadata": family_meta}

    warnings: list[str] = []
    active = [f for f in state.filters_as_payload() if routes._funnel_filter_is_active(f)]
    active = _order_active_filters(active, state.funnel.stage_order)
    if len(active) > routes.FUNNEL_MAX_STAGES:
        warnings.append(
            f"{len(active)} filters were active; only the first {routes.FUNNEL_MAX_STAGES} "
            "become funnel stages (the funnel view has the same limit)."
        )
        active = active[: routes.FUNNEL_MAX_STAGES]

    stage_dc_ids: list[str] = []
    wf_by_dc: dict[str, str | None] = {}
    for m in family_meta:
        if m.get("component_type") not in STAGE_COMPONENT_TYPES:
            continue
        dc_id = str(m.get("dc_id") or "")
        if not dc_id or dc_id in wf_by_dc:
            continue
        if routes._funnel_is_multiqc_dc(family_doc, dc_id):
            continue
        wf_by_dc[dc_id] = str(m.get("wf_id")) if m.get("wf_id") else None
        stage_dc_ids.append(dc_id)

    initial, stage_rows = routes._funnel_stage_counts(
        family_doc, project_id, access_token, active, stage_dc_ids
    )

    dcs: list[DCPlan] = []
    for dc_id in stage_dc_ids:
        dtypes = _dtypes_for(family_doc, dc_id, wf_by_dc.get(dc_id))
        dcs.append(
            DCPlan(
                dc_id=dc_id,
                tag=dc_tags.get(dc_id) or f"dc_{dc_id[-6:]}",
                wf_id=wf_by_dc.get(dc_id),
                dtypes=dtypes,
                initial_rows=initial.get(dc_id),
                n_cols=len(dtypes) if dtypes else None,
            )
        )

    meta_index = {str(m.get("index")): m for m in family_meta}
    stages: list[StagePlan] = []
    previous: dict[str, set[str]] = {dc: set() for dc in stage_dc_ids}
    for k, f in enumerate(active):
        cumulative = active[: k + 1]
        per_dc: dict[str, list[dict[str, Any]]] = {}
        for dc_id in stage_dc_ids:
            try:
                merged = routes._resolve_link_filters_cached(
                    filters=cumulative,
                    target_dc_id=dc_id,
                    project_id=project_id,
                    access_token=access_token,
                    component_type="funnel",
                )
            except Exception as exc:
                warnings.append(
                    f"Cross-collection links could not be resolved for stage {k + 1} on "
                    f"{dc_tags.get(dc_id, dc_id)}: {exc}"
                )
                merged = list(cumulative)
            mine = [g for g in merged if str((g.get("metadata") or {}).get("dc_id") or "") == dc_id]
            entries = _cleaned_with_index(mine)
            fresh = [e for e in entries if _entry_key(e) not in previous[dc_id]]
            previous[dc_id] |= {_entry_key(e) for e in entries}
            per_dc[dc_id] = fresh
        meta = meta_index.get(str(f.get("index") or "")) or {}
        row = stage_rows[k] if k < len(stage_rows) else {}
        stages.append(
            StagePlan(
                index=str(f.get("index") or ""),
                label=str(
                    meta.get("title")
                    or meta.get("column_name")
                    or f.get("column_name")
                    or f.get("index")
                ),
                column=f.get("column_name") or meta.get("column_name"),
                interactive_component_type=f.get("interactive_component_type")
                or meta.get("interactive_component_type"),
                value=f.get("value"),
                source_dc_id=str((f.get("metadata") or {}).get("dc_id") or meta.get("dc_id") or "")
                or None,
                per_dc=per_dc,
                rows_by_dc=dict(row.get("rows_by_dc") or {}),
            )
        )

    api_url = settings.fastapi.external_url
    instance = urlparse(api_url).netloc or api_url
    main = tabs[0]
    return ExportPlan(
        tabs=tabs,
        project=project,
        state=state,
        dcs=dcs,
        stages=stages,
        title=str(main.get("title") or "Dashboard"),
        subtitle=(main.get("subtitle") or None),
        exported_by=_who(current_user),
        exported_at=datetime.now(timezone.utc),
        instance=instance,
        api_url=api_url,
        warnings=warnings,
        marimo_version=marimo_version() or "0.24.0",
    )


@dashboards_endpoint_router.post(
    "/notebook_export/{dashboard_id}/preflight", response_model=NotebookPreflight
)
def notebook_export_preflight(
    dashboard_id: PyObjectId,
    request: NotebookExportRequest,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> NotebookPreflight:
    """What the export will contain: one verdict per tile, stage counts, warnings."""
    _require_enabled()
    plan = build_export_plan(dashboard_id, request.state, current_user, access_token)
    return NotebookBuilder(plan).preflight(ipynb_available=ipynb_available())


@dashboards_endpoint_router.post("/notebook_export/{dashboard_id}")
def notebook_export(
    dashboard_id: PyObjectId,
    request: NotebookExportRequest,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> Response:
    """The dashboard as a notebook: marimo ``.py``, Jupyter ``.ipynb`` or a Quarto-ready ``.ipynb``.

    Nothing runs on the server: the marimo file is generated text, the
    ``.ipynb`` variants come from marimo's converter with outputs excluded.
    """
    _require_enabled()
    plan = build_export_plan(dashboard_id, request.state, current_user, access_token)
    source = NotebookBuilder(plan).build()
    stem = plan.stem
    if request.format == "marimo":
        return Response(
            content=source.encode("utf-8"),
            media_type="text/x-python; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.py"'},
        )
    try:
        ipynb = to_ipynb(source, timeout_s=settings.notebook_export.ipynb_timeout_s, stem=stem)
    except IpynbExportUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    filename = f"{stem}.ipynb"
    if request.format == "quarto":
        ipynb = to_quarto_ipynb(
            ipynb,
            QuartoFrontMatter(
                title=plan.title,
                subtitle=plan.subtitle or f"Exported from Depictio on {plan.exported_at:%Y-%m-%d}",
                author=plan.exported_by,
                date=plan.exported_at.strftime("%Y-%m-%d"),
            ),
        )
        filename = f"{stem}.quarto.ipynb"
    return Response(
        content=ipynb,
        media_type="application/x-ipynb+json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
