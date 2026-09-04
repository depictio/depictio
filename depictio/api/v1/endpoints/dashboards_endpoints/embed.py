"""Component embeds and figure extraction for ``depictio.notebook``.

* ``POST /dashboards/component_figure/{dashboard}/{component}`` — the
  component as a Plotly figure. Figures the server draws itself and the
  React-rendered kinds alike go through headless extraction on the worker
  (one code path, the real renderer), with a small result cache.
* ``GET /dashboards/component_figure/jobs/{job_id}`` — poll.
* ``POST /dashboards/embed/{dashboard}/{component}`` — an HTML document
  that frames the viewer's ``/embed`` route with the given state, for a
  reader who is logged into the instance.
"""

from __future__ import annotations

import hashlib
import html
import json
import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Response

from depictio.api.celery_app import celery_app
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    dashboards_endpoint_router,
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.api.v1.services.embed.extract import embed_url
from depictio.models.models.analysis_state import ComponentEmbedRequest, ComponentFigureResponse
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User

# Component types that draw a Plotly figure the embed page can hand back.
EXTRACTABLE_TYPES: frozenset[str] = frozenset({"figure", "map", "multiqc", "advanced_viz"})

_RESULT_TTL_S = 600.0
_results: dict[str, tuple[float, dict[str, Any]]] = {}
_jobs: dict[str, str] = {}  # job_id -> cache key


def _require_enabled() -> None:
    if not settings.notebook_export.enabled:
        raise HTTPException(status_code=404, detail="Notebook export is disabled.")


def _load_component(dashboard_id: PyObjectId, component_id: str, current_user: User) -> dict:
    doc = routes.dashboards_collection.find_one(
        {"dashboard_id": dashboard_id}, {"project_id": 1, "stored_metadata": 1}
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")
    if not routes.check_project_permission(doc.get("project_id"), current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")
    for m in doc.get("stored_metadata") or []:
        if str(m.get("index")) == str(component_id):
            return m
    raise HTTPException(status_code=404, detail=f"Component '{component_id}' not found.")


def _cache_key(dashboard_id: Any, component_id: str, state: dict[str, Any], theme: str) -> str:
    blob = json.dumps(
        [str(dashboard_id), str(component_id), state.get("filters"), state.get("groups"), theme],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(blob.encode()).hexdigest()


def _cached(key: str) -> dict[str, Any] | None:
    hit = _results.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.monotonic() - ts > _RESULT_TTL_S:
        _results.pop(key, None)
        return None
    return value


def _remember(key: str, value: dict[str, Any]) -> None:
    _results[key] = (time.monotonic(), value)
    if len(_results) > 512:
        cutoff = time.monotonic() - _RESULT_TTL_S
        for stale in [k for k, (ts, _) in _results.items() if ts < cutoff]:
            _results.pop(stale, None)


@dashboards_endpoint_router.post(
    "/component_figure/{dashboard_id}/{component_id}", response_model=ComponentFigureResponse
)
def component_figure(
    dashboard_id: PyObjectId,
    component_id: str,
    request: ComponentEmbedRequest,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> ComponentFigureResponse:
    """A component as a Plotly figure, extracted from the real renderer."""
    _require_enabled()
    meta = _load_component(dashboard_id, component_id, current_user)
    ctype = str(meta.get("component_type") or "")
    if ctype not in EXTRACTABLE_TYPES:
        return ComponentFigureResponse(
            status="unsupported",
            reason=f"a {ctype} component has no Plotly figure; use .data or .html instead",
        )
    state = request.state.model_dump(mode="json", exclude_none=True) if request.state else {}
    key = _cache_key(dashboard_id, component_id, state, request.theme)
    hit = _cached(key)
    if hit is not None:
        return ComponentFigureResponse(**hit)
    from depictio.api.v1.celery_tasks import extract_component_figure_task

    job = extract_component_figure_task.delay(
        {
            "dashboard_id": str(dashboard_id),
            "component_id": str(component_id),
            "state": state,
            "theme": request.theme,
        }
    )
    _jobs[job.id] = key
    return ComponentFigureResponse(status="pending", job_id=job.id)


@dashboards_endpoint_router.get(
    "/component_figure/jobs/{job_id}", response_model=ComponentFigureResponse
)
def component_figure_job(
    job_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> ComponentFigureResponse:
    _require_enabled()
    from celery.result import AsyncResult

    key = _jobs.get(job_id)
    if key:
        hit = _cached(key)
        if hit is not None:
            return ComponentFigureResponse(**hit)
    result = AsyncResult(job_id, app=celery_app)
    if result.state in ("PENDING", "STARTED", "RETRY", "RECEIVED"):
        return ComponentFigureResponse(status="pending", job_id=job_id)
    if result.state == "FAILURE":
        return ComponentFigureResponse(status="error", job_id=job_id, reason=str(result.result))
    payload = result.result if isinstance(result.result, dict) else {}
    response = ComponentFigureResponse(
        status=payload.get("status") or "error",
        figure=payload.get("figure"),
        job_id=job_id,
        reason=payload.get("reason"),
        source=payload.get("source"),
    )
    if key and response.status == "ready":
        _remember(key, response.model_dump(mode="json"))
    return response


@dashboards_endpoint_router.post("/embed/{dashboard_id}/{component_id}")
def component_embed(
    dashboard_id: PyObjectId,
    component_id: str,
    request: ComponentEmbedRequest,
    current_user: User = Depends(get_user_or_anonymous),
) -> Response:
    """An HTML page framing the live component with the given state.

    The frame loads the viewer's ``/embed`` route with the reader's own
    session, so it renders for anyone who can open the dashboard and shows
    the login page to anyone who cannot.
    """
    _require_enabled()
    meta = _load_component(dashboard_id, component_id, current_user)
    state = request.state.model_dump(mode="json", exclude_none=True) if request.state else {}
    url = embed_url(
        settings.viewer.external_url, str(dashboard_id), component_id, state, request.theme
    )
    title = html.escape(str(meta.get("title") or component_id))
    doc = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>{title}</title>"
        "<style>html,body{margin:0;height:100%}iframe{width:100%;height:100%;border:0}</style>"
        f'</head><body><iframe src="{html.escape(url, quote=True)}" title="{title}"></iframe>'
        "</body></html>"
    )
    return Response(content=doc, media_type="text/html; charset=utf-8")
