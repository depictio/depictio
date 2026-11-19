"""Component embeds and figure extraction for ``depictio.notebook``.

* ``POST /dashboards/component_figure/{dashboard}/{component}`` — the
  component as a Plotly figure. Figures the server draws itself and the
  React-rendered kinds alike go through headless extraction on the worker
  (one code path, the real renderer), with a small result cache. A renderer
  that is not Plotly (SVG, canvas, WebGL, the JBrowse view) comes back as a
  PNG snapshot of the tile instead.
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
from uuid import uuid4

from fastapi import Depends, HTTPException, Response

from depictio.api.celery_app import celery_app
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
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

# Component types the embed page can hand back: as the Plotly figure they draw,
# or, for what is not Plotly, as a PNG snapshot of the tile.
EXTRACTABLE_TYPES: frozenset[str] = frozenset(
    {"figure", "map", "multiqc", "advanced_viz", "jbrowse"}
)
# Of those, the types that never draw Plotly.
SNAPSHOT_TYPES: frozenset[str] = frozenset({"jbrowse"})


def expected_output(meta: dict[str, Any]) -> str:
    """``"image"`` when the tile's renderer is not Plotly, else ``"plotly"``."""
    ctype = str(meta.get("component_type") or "")
    if ctype in SNAPSHOT_TYPES:
        return "image"
    if ctype == "advanced_viz":
        from depictio.api.v1.services.notebook_export.classify import advanced_viz_delivery

        # A tile the document draws natively asks here only as its fallback,
        # which is the renderer's picture.
        if advanced_viz_delivery(meta) in ("snapshot", "native"):
            return "image"
    return "plotly"


_RESULT_TTL_S = 600.0
# Results by cache key, for this process. Only ever served to a caller who
# passed the component's permission check for the same state.
_results: dict[str, tuple[float, dict[str, Any]]] = {}
# An extraction job is bound to its requester in ``notebook_export.jobs``
# (with its cache key), so only they can poll it, and its record expires.
_EXTRACT_KEEP_S = 3600


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


def _cache_key(
    dashboard_id: Any, component_id: str, state: dict[str, Any], theme: str, expect: str = "plotly"
) -> str:
    # Everything the page renders from: filters and groups, but also colour-by,
    # facet and the "other" bucket, which change the figure as much.
    relevant = {k: v for k, v in state.items() if k != "context"}
    blob = json.dumps(
        [str(dashboard_id), str(component_id), relevant, theme, expect],
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


def _server_figure(
    dashboard_id: Any,
    component_id: str,
    meta: dict,
    state: dict[str, Any],
    theme: str,
    current_user: User,
    access_token: str | None,
) -> ComponentFigureResponse | None:
    """The figure from the server's own builder, when it has one for this tile.

    Sixteen kinds (the three Celery computes and the registered Python
    builders, ``export.capabilities.component_json_source``) draw the same
    numbers on the server that the renderer draws in the browser. Building them
    here skips the browser pass and the compute task it would dispatch on the
    worker, which is what starved a report's slots. ``None`` sends the tile to
    the browser instead: a kind without a builder, a tile coloured by groups or
    a column (the builders take no colour-by; the embed page applies it), or a
    build that failed.
    """
    if str(meta.get("component_type") or "") != "advanced_viz":
        return None
    from depictio.api.v1.services.notebook_export.classify import advanced_viz_delivery

    if advanced_viz_delivery(meta) != "server":
        return None
    if ((state.get("color_by") or {}).get("kind") or "none") != "none":
        return None
    # The builders read current data: a pinned state is the renderer's, which
    # honours the pins (the browser pass hands it the whole state).
    if any((state.get("pins") or {}).values()):
        return None
    import asyncio

    from depictio.api.v1.services.export.plotly_export import build_plotly_export

    try:
        spec = asyncio.run(
            build_plotly_export(
                dashboard_id=dashboard_id,
                component_id=str(component_id),
                component=meta,
                filters=list(state.get("filters") or []),
                theme=theme,
                access_token=access_token,
                current_user=current_user,
            )
        )
    except Exception as exc:  # noqa: BLE001 - the browser pass is the fallback
        logger.info(f"component_figure: server build failed for {component_id}, extracting: {exc}")
        return None
    return ComponentFigureResponse(
        status="ready",
        figure={"data": spec.get("data") or [], "layout": spec.get("layout") or {}},
        source="server",
    )


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
    # A renderer that is not Plotly is snapshotted as soon as it reports itself
    # drawn, rather than after a browser pass waiting for a Plotly div it never
    # draws.
    expect = expected_output(meta)
    state = request.state.model_dump(mode="json", exclude_none=True) if request.state else {}
    key = _cache_key(dashboard_id, component_id, state, request.theme, expect)
    hit = _cached(key)
    if hit is not None:
        return ComponentFigureResponse(**hit)
    served = _server_figure(
        dashboard_id, component_id, meta, state, request.theme, current_user, access_token
    )
    if served is not None:
        _remember(key, served.model_dump(mode="json"))
        return served
    from depictio.api.v1.celery_tasks import extract_component_figure_task
    from depictio.api.v1.services.notebook_export import jobs

    # Each pass is a browser for up to three minutes: bounded per user, and
    # run as that user (the worker mints them a token for it), never as the
    # admin.
    user_id = str(getattr(current_user, "id", "") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Extracting a figure needs a user.")
    limits = settings.notebook_export
    jobs.admit(
        user_id,
        jobs.EXTRACT,
        max_active=limits.extract_max_active_per_user,
        max_per_hour=limits.extract_max_per_hour,
        window_s=600,
    )
    job_id = uuid4().hex
    jobs.record(job_id, user_id, jobs.EXTRACT, cache_key=key, keep_s=_EXTRACT_KEEP_S)
    extract_component_figure_task.apply_async(
        args=[
            {
                "dashboard_id": str(dashboard_id),
                "component_id": str(component_id),
                "state": state,
                "theme": request.theme,
                "expect": expect,
                "user_id": user_id,
                "job_id": job_id,
            }
        ],
        task_id=job_id,
    )
    return ComponentFigureResponse(status="pending", job_id=job_id)


@dashboards_endpoint_router.get(
    "/component_figure/jobs/{job_id}", response_model=ComponentFigureResponse
)
def component_figure_job(
    job_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> ComponentFigureResponse:
    _require_enabled()
    from celery.result import AsyncResult

    from depictio.api.v1.services.notebook_export import jobs

    record = jobs.owned(job_id, str(getattr(current_user, "id", "") or ""), jobs.EXTRACT)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No extraction job '{job_id}'.")
    key = str(record.get("cache_key") or "")
    if key:
        hit = _cached(key)
        if hit is not None:
            return ComponentFigureResponse(**hit)
    result = AsyncResult(job_id, app=celery_app)
    if result.state in ("PENDING", "STARTED", "RETRY", "RECEIVED"):
        return ComponentFigureResponse(status="pending", job_id=job_id)
    if result.state == "FAILURE":
        # The exception's text is the worker's (paths, a browser's log).
        return ComponentFigureResponse(
            status="error", job_id=job_id, reason="the extraction failed on the server"
        )
    payload = result.result if isinstance(result.result, dict) else {}
    response = ComponentFigureResponse(
        status=payload.get("status") or "error",
        figure=payload.get("figure"),
        image=payload.get("image"),
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
