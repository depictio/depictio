"""Build a portable Plotly spec for one dashboard component.

The output is what an external site needs and nothing else::

    {"data": [...], "layout": {...}, "config": {...}, "meta": {...}}

Two things this deliberately does differently from the ``render_*`` endpoints it
reuses:

* It synthesizes ``config``. The render endpoints return only ``{figure, metadata}``
  and the viewer hardcodes its Plotly config in the renderer components
  (``FigureRenderer.tsx:386``, ``MapRenderer.tsx:190``). An external consumer has no
  such renderer, so the config has to travel with the figure.
* It strips ``layout.uirevision``. That key exists to preserve pan/zoom across
  re-renders inside the viewer; in an exported figure it is meaningless noise.

Every branch delegates to the same builders the live viewer uses — no figure is
constructed here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.export.bundle import json_safe
from depictio.api.v1.services.export.capabilities import (
    ExportFormat,
    component_formats,
    component_json_source,
    component_unsupported_reason,
    resolve_viz_kind,
)


class ExportUnsupported(HTTPException):
    """This component cannot be exported in the requested format.

    Carries a structured body so a consumer can branch on ``code`` and follow
    ``html_url`` instead of parsing prose. Status is 501 when the limitation is
    temporary (a viz kind whose Python builder has not landed yet) and 422 when it
    is inherent to the component type.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        component_type: str,
        viz_kind: str | None = None,
        supported_formats: list[str] | None = None,
        html_url: str | None = None,
    ):
        detail: dict[str, Any] = {
            "code": code,
            "message": message,
            "component_type": component_type,
            "supported_formats": supported_formats or [],
        }
        if viz_kind:
            detail["viz_kind"] = viz_kind
        if html_url:
            detail["html_available"] = True
            detail["html_url"] = html_url
        super().__init__(status_code=status_code, detail=detail)


def plotly_config_for(component_type: str) -> dict[str, Any]:
    """Plotly config matching what the viewer applies to this component type.

    Mirrors ``FigureRenderer.tsx:386`` and ``MapRenderer.tsx:190`` so an embedded
    figure behaves like the one on the dashboard.
    """
    config: dict[str, Any] = {"displaylogo": False, "responsive": True}
    if component_type == "map":
        config["scrollZoom"] = True
    return config


def _normalise_figure(fig: Any) -> dict[str, Any]:
    """Coerce a Plotly figure (object or dict) into a plain ``{data, layout}``."""
    import json

    if hasattr(fig, "to_json"):
        fig_dict = json.loads(fig.to_json())
    elif hasattr(fig, "to_plotly_json"):
        fig_dict = fig.to_plotly_json()
    else:
        fig_dict = fig

    if not isinstance(fig_dict, dict):
        raise HTTPException(status_code=500, detail="Renderer returned a non-figure payload.")

    layout = dict(fig_dict.get("layout") or {})
    # Viewer-only state: preserves pan/zoom across re-renders in the SPA and means
    # nothing to an external consumer.
    layout.pop("uirevision", None)
    return {"data": list(fig_dict.get("data") or []), "layout": layout}


async def _figure_spec(
    dashboard_id: Any,
    component_id: str,
    filters: list[dict],
    theme: str,
    current_user: Any,
    access_token: str | None,
) -> dict[str, Any]:
    """Figure component — the render endpoint the viewer itself calls.

    Calling the handler rather than rebuilding its payload is what keeps an
    exported figure identical to the tile: the figure and section style, the
    family's category colours, the brand theme, the point cap and region
    scoping are all applied there, and each was added after this export first
    shipped. A second copy of that payload would have missed every one.
    """
    from fastapi import Response

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import render_figure_endpoint

    result = await render_figure_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "theme": theme},
        # Absorbs the X-Celery-Path diagnostic header, meaningless to an export.
        response=Response(),
        current_user=current_user,
        access_token=access_token,
    )
    return _normalise_figure(result.get("figure"))


def _map_spec(
    dashboard_id: Any,
    component_id: str,
    filters: list[dict],
    theme: str,
    current_user: Any,
    access_token: str | None,
) -> dict[str, Any]:
    """Map component — the render endpoint the viewer itself calls (category colours included)."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import render_map_endpoint

    result = render_map_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "theme": theme},
        current_user=current_user,
        access_token=access_token,
    )
    return _normalise_figure(result.get("figure"))


def _multiqc_spec(
    dashboard_id: Any,
    component_id: str,
    filters: list[dict],
    theme: str,
    current_user: Any,
    component: dict | None = None,
) -> dict[str, Any]:
    """MultiQC component — delegates to the render endpoint's own handler.

    The MultiQC path carries cache warm-up, sample resolution and a three-layer
    figure cache (``routes.py:2827``). Calling the handler keeps one implementation
    rather than a second, subtly-different copy; the ``Depends`` defaults in its
    signature are ordinary defaults when it is called directly.

    It can answer 202 while the cache warms — a state an export cannot represent —
    so that becomes a 503 telling the caller to retry or use ``format=html``.

    General Statistics is dispatched separately. It is a *table* in MultiQC's
    model, so ``multiqc.get_plot("general_stats", …)`` cannot serve it and the
    plot endpoint answers with a "refresh your browser" stub — advice that makes
    no sense to an external host, which has no Depictio tab to refresh, and
    which arrives as a successful 200 carrying zero traces. The GS payload does
    contain a real figure (the violin summary the in-app renderer draws beside
    the table), so export that instead.
    """
    from fastapi.responses import JSONResponse

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _resolve_selected_keys,
        render_multiqc_endpoint,
    )

    if component is not None and _resolve_selected_keys(component)[3]:
        return _general_stats_spec(dashboard_id, component_id, filters, theme, current_user)

    result = render_multiqc_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "theme": theme},
        current_user=current_user,
    )

    if isinstance(result, JSONResponse):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "multiqc_cache_warming",
                "message": (
                    "MultiQC figures for this data collection are still being prepared. "
                    "Retry shortly, or use format=html, which renders through the "
                    "viewer's own retry loop."
                ),
            },
        )
    return _normalise_figure(result.get("figure"))


def _general_stats_spec(
    dashboard_id: Any,
    component_id: str,
    filters: list[dict],
    theme: str,
    current_user: Any,
) -> dict[str, Any]:
    """Violin summary for a MultiQC General Statistics component.

    GS is primarily a table, and a table is not a Plotly figure, so the honest
    thing to export is the violin the in-app renderer draws alongside it —
    every numeric GS column as one violin, which is exactly the "how do my
    samples compare" question the table answers by eye.

    The paired-end payload carries several read modes; ``mean`` is the one the
    UI opens on, so it is the one an export should reproduce.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        render_multiqc_general_stats_endpoint,
    )

    payload = render_multiqc_general_stats_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "theme": theme},
        current_user=current_user,
    )

    modes = (payload or {}).get("modes") or {}
    mode = modes.get("mean") or next(iter(modes.values()), None)
    figure = (mode or {}).get("violin_figure")
    if not figure or not figure.get("data"):
        raise ExportUnsupported(
            status_code=422,
            code="general_stats_table_only",
            message=(
                "This MultiQC General Statistics component has no numeric columns to "
                "plot, so it exports as a table only. Use format=html to embed it."
            ),
        )
    return _normalise_figure(figure)


def _celery_advanced_viz_spec(
    component: dict, filter_metadata: list[dict], kind: str, access_token: str | None
) -> Any:
    """Run an already-server-side advanced-viz compute inline and return its figure.

    ``complex_heatmap`` / ``upset_plot`` / ``sankey`` have Celery tasks that already
    emit ``{"figure": {...}}``; see ``services/export/compute.py`` for why the
    payload is prepared through the dispatch route's own helpers.
    """
    from depictio.api.v1.services.export.compute import run_compute

    result = run_compute(kind, component, filter_metadata, access_token)
    if not isinstance(result, dict) or "figure" not in result:
        raise HTTPException(
            status_code=500,
            detail=f"{kind} compute returned no figure.",
        )
    return result["figure"]


def _python_advanced_viz_spec(
    component: dict,
    filter_metadata: list[dict],
    current_user: Any,
    access_token: str | None,
    controls: dict[str, Any] | None = None,
    theme: str = "light",
) -> dict[str, Any]:
    """Build an advanced-viz figure from its registered Python builder(s).

    ``controls`` is the intra-viz state the live renderer keeps in the browser —
    the view, a normalisation mode, a top-N. Without it an export can only ever
    produce the persisted default, so a component that presents three cases in
    the dashboard would be reduced to one on the way out.

    The view decides the builder (``services/advanced_viz/views.py``): a
    ``volcano`` on its MA view is drawn by the MA builder, and a ``pr_benchmark``
    on ``both`` by two builders whose traces are overlaid.
    """
    from depictio.api.v1.services.advanced_viz.data import load_tidy_columns
    from depictio.api.v1.services.advanced_viz.figure_registry import build, required_columns
    from depictio.api.v1.services.advanced_viz.views import plan_for

    plan = plan_for(component, controls)
    if plan is None:  # pragma: no cover - guarded by component_formats
        raise HTTPException(status_code=422, detail="Component names no advanced_viz kind.")

    wf_id, dc_id = plan.source or (str(component.get("wf_id")), str(component.get("dc_id")))
    columns = list(
        dict.fromkeys(c for name in plan.builders for c in required_columns(name, plan.config))
    )
    tidy = load_tidy_columns(
        wf_id=wf_id,
        dc_id=dc_id,
        columns=columns,
        filter_metadata=filter_metadata,
        current_user=current_user,
        access_token=access_token,
        viz_kind=plan.kind,
    )

    spec: dict[str, Any] = {"data": [], "layout": {}}
    for position, name in enumerate(plan.builders):
        part = build(
            name,
            config=plan.config,
            rows=tidy["rows"],
            theme=theme,
            controls=plan.controls.get(name, {}),
        )
        spec["data"].extend(part.get("data") or [])
        if position == 0:
            # The first builder owns the axes; an overlay only adds traces.
            spec["layout"] = part.get("layout") or {}
    return spec


def _drawn_view(component: dict, controls: dict[str, Any] | None) -> str | None:
    if component.get("component_type") != "advanced_viz":
        return None
    from depictio.api.v1.services.advanced_viz.views import plan_for

    plan = plan_for(component, controls)
    return plan.view if plan is not None else None


async def build_plotly_export(
    *,
    dashboard_id: Any,
    component_id: str,
    component: dict,
    filters: list[dict],
    theme: str,
    access_token: str | None,
    current_user: Any,
    html_url: str | None = None,
    controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce the portable Plotly spec for one component.

    Raises:
        ExportUnsupported: 422 for a type that is not a Plotly figure at all,
            501 for an advanced-viz kind whose Python builder has not landed.
        HTTPException: 500/503/504 from the underlying render path.
    """
    component_type = component.get("component_type") or ""
    viz_kind = resolve_viz_kind(component.get("viz_kind"))
    supported = component_formats(component, controls)

    if ExportFormat.JSON not in supported:
        source = (
            component_json_source(component, controls) if component_type == "advanced_viz" else None
        )
        # A kind whose builder simply hasn't been written yet is a 501 (temporary,
        # and HTML works now); anything else is inherent to the type, so 422.
        temporary = component_type == "advanced_viz" and source == "client_only"
        raise ExportUnsupported(
            status_code=501 if temporary else 422,
            code="kind_not_ported" if temporary else "unsupported_export",
            message=component_unsupported_reason(component, controls) or "Export not supported.",
            component_type=component_type,
            viz_kind=viz_kind,
            supported_formats=sorted(f.value for f in supported),
            html_url=html_url if ExportFormat.HTML in supported else None,
        )

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _build_filter_metadata

    filter_metadata = _build_filter_metadata(filters)

    if component_type == "figure":
        spec = await _figure_spec(
            dashboard_id, component_id, filters, theme, current_user, access_token
        )
    elif component_type == "map":
        spec = _map_spec(dashboard_id, component_id, filters, theme, current_user, access_token)
    elif component_type == "multiqc":
        spec = _multiqc_spec(dashboard_id, component_id, filters, theme, current_user, component)
    elif component_type == "advanced_viz":
        source = component_json_source(component, controls)
        if source == "celery":
            spec = _normalise_figure(
                _celery_advanced_viz_spec(component, filter_metadata, str(viz_kind), access_token)
            )
        else:
            spec = _python_advanced_viz_spec(
                component, filter_metadata, current_user, access_token, controls, theme
            )
    else:  # pragma: no cover - guarded by the formats_for check above
        raise ExportUnsupported(
            status_code=422,
            code="unsupported_export",
            message=f"No JSON exporter for {component_type!r}.",
            component_type=component_type,
            viz_kind=viz_kind,
            supported_formats=sorted(f.value for f in supported),
        )

    logger.info(
        "export: built plotly spec component=%s type=%s kind=%s traces=%d",
        component_id,
        component_type,
        viz_kind,
        len(spec.get("data") or []),
    )

    return json_safe(
        {
            **spec,
            "config": plotly_config_for(component_type),
            "meta": {
                "dashboard_id": str(dashboard_id),
                "component_id": str(component_id),
                "component_type": component_type,
                "viz_kind": viz_kind,
                # Which of a survivor kind's views was drawn (volcano / ma / qq, ...).
                "view": _drawn_view(component, controls),
                "title": component.get("title") or "",
                "theme": theme,
                "filter_applied": bool(filter_metadata),
                # Echo the intra-viz state so a saved figure records which case
                # it depicts. A ROC and a PR curve from the same component are
                # otherwise indistinguishable once the URL is gone.
                "controls": controls or {},
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    )
