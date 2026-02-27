"""
API endpoints for rendering dashboard components.

Provides endpoints to render individual dashboard components (figures, cards, tables)
via Celery background tasks, returning Plotly JSON, computed values, or table data.

Endpoints:
    POST /render/{dashboard_id}/components/{component_identifier}
        Render a specific component. Waits up to `timeout` seconds, returns 202 if pending.

    GET /render/tasks/{task_id}
        Poll a pending render task for its result.
"""

from __future__ import annotations

from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.render_models import (
    ComponentRenderRequest,
    ComponentRenderResponse,
    TaskPendingResponse,
    TaskStatusResponse,
)
from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.dash.celery_app import celery_app
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.users import User

render_endpoint_router = APIRouter()

# Component types that support rendering
RENDERABLE_TYPES = {"figure", "card", "table"}


def _resolve_component(
    stored_metadata: list[dict[str, Any]], identifier: str
) -> dict[str, Any] | None:
    """Resolve a component from stored_metadata by UUID index or human-readable tag.

    Args:
        stored_metadata: List of component metadata dicts from the dashboard.
        identifier: Either a UUID string (index) or a tag string.

    Returns:
        The matching component dict, or None if not found.
    """
    for component in stored_metadata:
        if component.get("index") == identifier or component.get("tag") == identifier:
            return component
    return None


@render_endpoint_router.post(
    "/{dashboard_id}/components/{component_identifier}",
    response_model=ComponentRenderResponse,
    responses={
        202: {"model": TaskPendingResponse, "description": "Render in progress, poll for result"},
        400: {"description": "Component type not renderable"},
        404: {"description": "Dashboard or component not found"},
    },
)
async def render_component_endpoint(
    dashboard_id: PyObjectId,
    component_identifier: str,
    request: ComponentRenderRequest | None = None,
    current_user: User = Depends(get_user_or_anonymous),
) -> ComponentRenderResponse | JSONResponse:
    """Render a dashboard component and return its output as JSON.

    Dispatches rendering to a Celery worker and waits up to `timeout` seconds.
    If the task completes in time, returns the rendered result directly.
    Otherwise returns HTTP 202 with a task_id for polling.

    Components are identified by UUID index or human-readable tag.

    Args:
        dashboard_id: The dashboard's ObjectId.
        component_identifier: Component UUID (index) or tag string.
        request: Optional render parameters (theme, filters, timeout).
        current_user: Authenticated user (viewer+ required).

    Returns:
        ComponentRenderResponse on success, or 202 JSONResponse with task_id.

    Raises:
        HTTPException: 404 if dashboard/component not found, 403 if unauthorized,
                       400 if component type is not renderable.
    """
    if request is None:
        request = ComponentRenderRequest()

    # Fetch dashboard
    dashboard_data = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    if not dashboard_data:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )

    # Check project-based permissions
    project_id = dashboard_data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this dashboard."
        )

    # Resolve component by index (UUID) or tag
    stored_metadata: list[dict[str, Any]] = dashboard_data.get("stored_metadata", [])
    component = _resolve_component(stored_metadata, component_identifier)

    if not component:
        raise HTTPException(
            status_code=404,
            detail=f"Component '{component_identifier}' not found in dashboard.",
        )

    component_type = component.get("component_type", "")
    if component_type not in RENDERABLE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Component type '{component_type}' is not renderable. "
                f"Supported types: {', '.join(sorted(RENDERABLE_TYPES))}"
            ),
        )

    # Extract data source IDs
    wf_id = component.get("wf_id")
    dc_id = component.get("dc_id")

    if not wf_id or not dc_id:
        raise HTTPException(
            status_code=400,
            detail="Component is missing workflow or data collection reference (wf_id/dc_id).",
        )

    # Dispatch Celery task — sanitize component dict so ObjectId/datetime/Path
    # values are converted to strings (Celery JSON serializer requires this)
    from depictio.api.v1.tasks.render_tasks import render_component

    serializable_component = convert_objectid_to_str(component)

    task = render_component.delay(
        component_metadata=serializable_component,
        workflow_id=str(wf_id),
        dc_id=str(dc_id),
        theme=request.theme,
        filters=request.filters,
        force_full_data=request.force_full_data,
    )

    logger.info(
        f"Dispatched render task {task.id} for component "
        f"'{component.get('tag', component.get('index'))}' "
        f"(type={component_type}) in dashboard {dashboard_id}"
    )

    # Wait for result up to timeout
    try:
        result = task.get(timeout=request.timeout)
    except Exception:
        # Timeout or other error — return 202 for polling
        return JSONResponse(
            status_code=202,
            content=TaskPendingResponse(
                task_id=task.id,
                message=f"Rendering in progress. Poll GET /render/tasks/{task.id} for result.",
            ).model_dump(),
        )

    # Check for task-level failure
    if result.get("status") == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Render failed: {result.get('error', 'Unknown error')}",
        )

    return ComponentRenderResponse(**result)


@render_endpoint_router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
)
async def get_render_task_status(task_id: str) -> TaskStatusResponse:
    """Poll a pending render task for its status and result.

    Args:
        task_id: The Celery task ID returned from the render endpoint.

    Returns:
        TaskStatusResponse with current status and result if complete.
    """
    async_result = AsyncResult(task_id, app=celery_app)

    if async_result.ready():
        result = async_result.result

        if isinstance(result, dict) and result.get("status") == "failed":
            return TaskStatusResponse(
                status="failed",
                task_id=task_id,
                error=result.get("error", "Unknown error"),
            )

        if isinstance(result, dict) and result.get("status") == "success":
            return TaskStatusResponse(
                status="success",
                task_id=task_id,
                result=ComponentRenderResponse(**result),
            )

        # Unexpected result format
        return TaskStatusResponse(
            status="failed",
            task_id=task_id,
            error="Unexpected task result format",
        )

    if async_result.failed():
        return TaskStatusResponse(
            status="failed",
            task_id=task_id,
            error=str(async_result.result),
        )

    return TaskStatusResponse(
        status="pending",
        task_id=task_id,
    )
