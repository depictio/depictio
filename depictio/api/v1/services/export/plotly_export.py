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

from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.export.bundle import json_safe
from depictio.api.v1.services.export.capabilities import (
    ExportFormat,
    advanced_viz_json_source,
    formats_for,
    resolve_viz_kind,
    unsupported_reason,
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


def _init_data_for(dc_id: Any, dc_config: dict) -> dict[str, dict]:
    """Build the ``init_data`` hint ``load_deltatable_lite`` uses to skip a lookup.

    Falls back to the deltatables collection when the component's stored snapshot
    predates ``delta_location`` being persisted — same fallback as ``render_map``.
    """
    delta_loc = dc_config.get("delta_location")
    if not delta_loc:
        from depictio.api.v1.db import deltatables_collection

        dt = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
        if dt:
            delta_loc = dt.get("delta_table_location")
    if not delta_loc:
        return {}
    return {
        str(dc_id): {
            "delta_location": delta_loc,
            "dc_type": dc_config.get("type") or "table",
            "size_bytes": dc_config.get("size_bytes", 0),
        }
    }


async def _figure_spec(component: dict, filter_metadata: list[dict], theme: str) -> dict[str, Any]:
    """Figure component — reuses the exact Celery task the viewer render uses."""
    from depictio.api.v1.celery_dispatch import offload_or_run, should_offload_render
    from depictio.api.v1.celery_tasks import build_figure_preview as build_figure_preview_task
    from depictio.models.models.base import convert_objectid_to_str

    dc_config = component.get("dc_config") or {}
    mode = component.get("mode", "ui")
    metadata = {
        "wf_id": str(component.get("wf_id")),
        "dc_id": str(component.get("dc_id")),
        "dc_config": convert_objectid_to_str(dc_config),
        "visu_type": component.get("visu_type", "scatter"),
        "dict_kwargs": component.get("dict_kwargs") or {},
        "mode": mode,
        "code_content": component.get("code_content", ""),
        # Selection highlighting is a viewer interaction; an export is a snapshot.
        "selection_enabled": False,
        "selection_column": component.get("selection_column"),
    }
    try:
        size_bytes = int(dc_config.get("size_bytes") or 0)
    except (TypeError, ValueError):
        size_bytes = 0

    result = await offload_or_run(
        build_figure_preview_task,
        ({"metadata": metadata, "filter_metadata": filter_metadata, "theme": theme},),
        offload=should_offload_render(
            force=settings.celery.offload_rendering,
            code_mode=(mode == "code"),
            size_bytes=size_bytes,
            threshold_bytes=settings.celery.offload_size_threshold_bytes,
        ),
        label=f"export_figure dc={component.get('dc_id')}",
    )
    return _normalise_figure(result.get("figure"))


def _map_spec(
    component: dict, filter_metadata: list[dict], theme: str, access_token: str | None
) -> dict[str, Any]:
    """Map component — same call the render_map endpoint makes."""
    import plotly.io as pio

    from depictio.api.v1.deltatables_utils import load_deltatable_lite
    from depictio.api.v1.services.map.render import render_map

    if "mantine_light" not in pio.templates or "mantine_dark" not in pio.templates:
        from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates

        ensure_mantine_templates()

    wf_id = component.get("wf_id")
    dc_id = component.get("dc_id")
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        init_data=_init_data_for(dc_id, component.get("dc_config") or {}),
    )
    fig, _ = render_map(
        df=df,
        trigger_data=component,
        theme=theme,
        existing_metadata=None,
        active_selection_values=None,
        access_token=access_token,
    )
    return _normalise_figure(fig)


def _multiqc_spec(
    dashboard_id: Any,
    component_id: str,
    filters: list[dict],
    theme: str,
    current_user: Any,
) -> dict[str, Any]:
    """MultiQC component — delegates to the render endpoint's own handler.

    The MultiQC path carries cache warm-up, sample resolution and a three-layer
    figure cache (``routes.py:2827``). Calling the handler keeps one implementation
    rather than a second, subtly-different copy; the ``Depends`` defaults in its
    signature are ordinary defaults when it is called directly.

    It can answer 202 while the cache warms — a state an export cannot represent —
    so that becomes a 503 telling the caller to retry or use ``format=html``.
    """
    from fastapi.responses import JSONResponse

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import render_multiqc_endpoint

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


def _celery_advanced_viz_spec(component: dict, filter_metadata: list[dict], kind: str) -> Any:
    """Run an already-server-side advanced-viz compute inline and return its figure.

    ``complex_heatmap`` / ``upset_plot`` / ``sankey`` have Celery tasks that already
    emit ``{"figure": {...}}``; the live viewer reaches them through a
    dispatch+poll pair, which an export cannot use. Running the task body directly
    gives the same result synchronously.
    """
    from depictio.api.v1 import celery_tasks

    task_by_kind = {
        "complex_heatmap": celery_tasks.compute_complex_heatmap,
        "upset_plot": celery_tasks.compute_upset,
        "sankey": celery_tasks.compute_sankey,
    }
    task = task_by_kind[kind]

    config = component.get("config") or {}
    payload = {
        **config,
        "wf_id": str(component.get("wf_id")),
        "dc_id": str(component.get("dc_id")),
        "filter_metadata": filter_metadata,
    }
    result = task.run(payload)
    if not isinstance(result, dict) or "figure" not in result:
        raise HTTPException(
            status_code=500,
            detail=f"{kind} compute returned no figure.",
        )
    return result["figure"]


def _python_advanced_viz_spec(
    component: dict,
    filter_metadata: list[dict],
    kind: str,
    theme: str,
    controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an advanced-viz figure from a registered Python builder.

    ``controls`` is the intra-viz state the live renderer keeps in the browser —
    the ROC/PR/threshold tab, a normalisation mode, a top-N. Without it an export
    can only ever produce the persisted default, so a component that presents
    three cases in the dashboard would be reduced to one on the way out.
    """
    from depictio.api.v1.services.advanced_viz.data import load_tidy_columns
    from depictio.api.v1.services.advanced_viz.figure_registry import build, required_columns

    config = component.get("config") or {}
    columns = required_columns(kind, config)
    tidy = load_tidy_columns(
        wf_id=str(component.get("wf_id")),
        dc_id=str(component.get("dc_id")),
        columns=columns,
        filter_metadata=filter_metadata,
    )
    return build(kind, config=config, rows=tidy["rows"], theme=theme, controls=controls)


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
    supported = formats_for(component_type, viz_kind)

    if ExportFormat.JSON not in supported:
        source = advanced_viz_json_source(viz_kind) if component_type == "advanced_viz" else None
        # A kind whose builder simply hasn't been written yet is a 501 (temporary,
        # and HTML works now); anything else is inherent to the type, so 422.
        temporary = component_type == "advanced_viz" and source == "client_only"
        raise ExportUnsupported(
            status_code=501 if temporary else 422,
            code="kind_not_ported" if temporary else "unsupported_export",
            message=unsupported_reason(component_type, viz_kind) or "Export not supported.",
            component_type=component_type,
            viz_kind=viz_kind,
            supported_formats=sorted(f.value for f in supported),
            html_url=html_url if ExportFormat.HTML in supported else None,
        )

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _build_filter_metadata

    filter_metadata = _build_filter_metadata(filters)

    if component_type == "figure":
        spec = await _figure_spec(component, filter_metadata, theme)
    elif component_type == "map":
        spec = _map_spec(component, filter_metadata, theme, access_token)
    elif component_type == "multiqc":
        spec = _multiqc_spec(dashboard_id, component_id, filters, theme, current_user)
    elif component_type == "advanced_viz":
        source = advanced_viz_json_source(viz_kind)
        if source == "celery":
            spec = _normalise_figure(
                _celery_advanced_viz_spec(component, filter_metadata, str(viz_kind))
            )
        else:
            spec = _python_advanced_viz_spec(
                component, filter_metadata, str(viz_kind), theme, controls
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
