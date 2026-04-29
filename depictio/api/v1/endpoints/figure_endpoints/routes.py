"""
Figure builder helpers — `/figure/preview` and `/figure/analyze_code`.

These wrap the existing render code paths so the React component-creation
stepper can show a live preview and round-trip code↔UI parameters without
having to persist metadata first.

* `preview` accepts the in-flight `metadata` dict (no dashboard lookup) and
  reuses `_create_figure_from_data` / `_process_code_mode_figure` from the
  Dash module — same execution sandbox, same templates, same caching.
* `analyze_code` wraps `analyze_constrained_code` from
  `depictio.dash.modules.figure_component.code_mode` so the UI mode can be
  rebuilt from arbitrary user code on mode switch.
"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Response

from depictio.api.v1.celery_dispatch import offload_or_run
from depictio.api.v1.celery_tasks import (
    analyze_figure_code as analyze_figure_code_task,
)
from depictio.api.v1.celery_tasks import (
    build_figure_preview as build_figure_preview_task,
)
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

figure_endpoint_router = APIRouter()


@figure_endpoint_router.get("/visualizations")
def list_visualizations(
    current_user: User = Depends(get_user_or_anonymous),
):
    """Return the curated list of figure visualizations with display metadata.

    Lightweight payload — name/label/description/icon/group only. The React
    builder uses this to populate the visualization-type dropdown so the TS
    side never falls out of sync with the Python registry. Per-viz parameter
    specs are still fetched lazily via `/figure/parameter-discovery/{viz_type}`.
    """
    try:
        from depictio.dash.modules.figure_component.definitions import (
            get_available_visualizations,
        )
    except Exception as e:
        logger.error(f"figure/visualizations: import failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Visualization registry is unavailable.")

    items = []
    for v in get_available_visualizations():
        group = v.group.value if hasattr(v.group, "value") else str(v.group)
        items.append(
            {
                "name": v.name,
                "label": v.label,
                "description": v.description,
                "icon": v.icon,
                "group": group,
            }
        )
    return items


@figure_endpoint_router.get("/parameter-discovery/{viz_type}")
def parameter_discovery(
    viz_type: str,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Return the full parameter spec for a visualization type.

    Wraps ``depictio.dash.modules.figure_component.definitions.get_visualization_definition``
    and returns the resulting Pydantic ``VisualizationDefinition`` as JSON. The
    React figure builder uses this to render the parameter accordion (Core /
    Common / Specific / Advanced) without duplicating the spec in TS.
    """
    try:
        from depictio.dash.modules.figure_component.definitions import (
            get_visualization_definition,
        )
    except Exception as e:
        logger.error(f"figure/parameter-discovery: import failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Parameter discovery is unavailable.")

    try:
        viz_def = get_visualization_definition(viz_type.lower())
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown visualization type: {viz_type}")
    except Exception as e:
        logger.error(
            f"figure/parameter-discovery: lookup failed for {viz_type}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Parameter discovery failed: {e}")

    return viz_def.model_dump(mode="json")


@figure_endpoint_router.post("/preview")
async def preview_figure(
    response: Response,
    request: dict = Body(...),
    current_user: User = Depends(get_user_or_anonymous),
):
    """Build a figure from the supplied builder metadata and return its JSON.

    Differs from ``/dashboards/render_figure/{id}/{cid}`` in that the metadata
    is supplied directly, not looked up. Suitable for live preview during the
    create / edit flow.

    Heavy work (delta-table load + Plotly build) runs on a Celery worker by
    default — see `settings.celery.offload_preview`. The endpoint awaits the
    task via a non-blocking poll loop so the FastAPI event loop stays free.

    Request body::

        {
          "metadata": { ...full figure stored_metadata shape... },
          "filters": [...] (optional),
          "theme": "light" | "dark" (default "light")
        }
    """
    metadata = request.get("metadata") or {}
    filters = request.get("filters") or []
    theme = request.get("theme") or "light"

    if not metadata or metadata.get("component_type") != "figure":
        raise HTTPException(status_code=400, detail="metadata must be a figure component.")

    wf_id = metadata.get("wf_id")
    dc_id = metadata.get("dc_id")
    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="metadata missing wf_id/dc_id.")

    filter_metadata = [
        {
            "interactive_component_type": f.get("interactive_component_type"),
            "column_name": f.get("column_name"),
            "value": f.get("value"),
        }
        for f in filters
        if f.get("column_name") and f.get("value") not in (None, [], "")
    ]

    offload = settings.celery.offload_preview
    response.headers["X-Celery-Path"] = "offloaded" if offload else "inline"

    payload = {"metadata": metadata, "filter_metadata": filter_metadata, "theme": theme}
    try:
        return await offload_or_run(
            build_figure_preview_task,
            (payload,),
            offload=offload,
            label=f"figure_preview wf={wf_id} dc={dc_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"figure/preview: build failed: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Figure build failed: {e}")


@figure_endpoint_router.post("/analyze_code")
async def analyze_code(
    response: Response,
    request: dict = Body(...),
    current_user: User = Depends(get_user_or_anonymous),
):
    """Validate user-written figure code and extract UI-equivalent params.

    Wraps ``analyze_constrained_code`` from
    ``depictio.dash.modules.figure_component.code_mode``. Used by the React
    builder when toggling code↔UI mode so the UI tab can be re-populated.

    Offloaded to Celery on the same flag as `/preview`.
    """
    code = (request.get("code") or "").strip()
    offload = settings.celery.offload_preview
    response.headers["X-Celery-Path"] = "offloaded" if offload else "inline"
    return await offload_or_run(
        analyze_figure_code_task,
        (code,),
        offload=offload,
        label="figure_analyze_code",
    )
