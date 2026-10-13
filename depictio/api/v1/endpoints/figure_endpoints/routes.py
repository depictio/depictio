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


def _authorize_preview_dc(wf_id, dc_id, current_user: User) -> None:
    """Require read permission on the project that owns ``wf_id``/``dc_id``.

    The preview endpoint takes an in-flight ``metadata`` dict straight from the
    client, so unlike ``/dashboards/render_figure`` there is no stored component
    to trust. Resolve the owning project from Mongo, requiring the DC to live
    under the given workflow (so a caller cannot pair a workflow they may read
    with a DC id from a private project), then gate it through the very helper
    the dashboard render endpoints use for viewers — which already allows
    anonymous access only on public projects.

    Raises 404 when the workflow/DC pair resolves to no project (don't leak the
    existence of collections the caller can't see) and 403 when the caller has
    no read access to the project that owns it.
    """
    from bson import ObjectId

    from depictio.api.v1.db import projects_collection
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    try:
        wf_oid = ObjectId(str(wf_id))
        dc_oid = ObjectId(str(dc_id))
    except Exception:
        raise HTTPException(status_code=400, detail="metadata has an invalid wf_id/dc_id.")

    project = projects_collection.find_one(
        {"workflows": {"$elemMatch": {"_id": wf_oid, "data_collections._id": dc_oid}}},
        {"_id": 1},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")
    if not check_project_permission(project["_id"], current_user, "viewer"):
        raise HTTPException(status_code=403, detail="Permission denied.")


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
        from depictio.api.v1.services.figure.definitions import (
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
        from depictio.api.v1.services.figure.definitions import (
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
          "theme": "light" | "dark" (default "light"),
          "dashboard_id": "..." (optional)
        }

    ``dashboard_id``, when supplied, pulls that dashboard's ``brand_theme``
    defaults and ``category_colors`` into the preview so it matches what the
    saved component will render (#397), and its grid sections' figure style.
    ``style`` (optional) overrides the style, as on ``render_figure``.
    """
    metadata = request.get("metadata") or {}
    filters = request.get("filters") or []
    theme = request.get("theme") or "light"
    preview_dashboard_id = request.get("dashboard_id")

    if not metadata or metadata.get("component_type") != "figure":
        raise HTTPException(status_code=400, detail="metadata must be a figure component.")

    wf_id = metadata.get("wf_id")
    dc_id = metadata.get("dc_id")
    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="metadata missing wf_id/dc_id.")

    # Permission gate — before any data is loaded or any user code runs. The
    # caller must have read access to the project that owns this workflow/DC.
    _authorize_preview_dc(wf_id, dc_id, current_user)

    # The DC's Delta location is authoritative in Mongo (resolved by the worker
    # from dc_id). A client-supplied ``dc_config.delta_location`` would let an
    # authorized caller point the read at an arbitrary table, so drop it here at
    # the trust boundary and let the worker look it up.
    dc_config = metadata.get("dc_config")
    if isinstance(dc_config, dict) and "delta_location" in dc_config:
        dc_config = {k: v for k, v in dc_config.items() if k != "delta_location"}
        metadata = {**metadata, "dc_config": dc_config}

    dashboard_doc = None
    category_colors = None
    if preview_dashboard_id:
        from bson import ObjectId

        from depictio.api.v1.db import dashboards_collection
        from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import (
            effective_category_colors,
            family_brand_theme,
        )
        from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
            check_project_permission,
        )
        from depictio.api.v1.services.figure.figure_builder import (
            merge_category_colors,
            merge_dashboard_brand_theme,
        )

        try:
            dashboard_doc = dashboards_collection.find_one(
                {"dashboard_id": ObjectId(str(preview_dashboard_id))}
            )
        except Exception:
            dashboard_doc = None
        # Applying a dashboard's brand theme reads that dashboard — gate it on
        # read permission, the same as fetching the dashboard itself would.
        if dashboard_doc is not None:
            project_id = dashboard_doc.get("project_id")
            if not project_id or not check_project_permission(project_id, current_user, "viewer"):
                raise HTTPException(status_code=403, detail="Permission denied.")
        brand_theme = family_brand_theme(dashboard_doc) if dashboard_doc else None
        category_colors = effective_category_colors(dashboard_doc) if dashboard_doc else None
        if brand_theme or category_colors:
            metadata = {
                **metadata,
                "dict_kwargs": merge_category_colors(
                    category_colors,
                    merge_dashboard_brand_theme(brand_theme, metadata.get("dict_kwargs") or {}),
                ),
            }

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

    from depictio.api.v1.services.figure.style_presets import figure_style_payload

    payload = {
        "metadata": metadata,
        "filter_metadata": filter_metadata,
        "theme": theme,
        # The style the saved figure will take: its own, else its section's on
        # the dashboard it is previewed for.
        "style": figure_style_payload(metadata, dashboard_doc, request.get("style")),
    }
    if category_colors:
        payload["category_colors"] = category_colors
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
