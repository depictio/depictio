"""Look up a dashboard component and authorise the caller.

Every ``render_*`` endpoint in ``dashboards_endpoints/routes.py`` opens with the
same six lines: fetch the dashboard, pull ``project_id``, run
``check_project_permission``, then scan ``stored_metadata`` for the matching
``index``. This module is that preamble, factored out so the export routes and
the render routes agree on 404/403 semantics instead of drifting.

The 404/403 preamble itself is ``_viewable_dashboard`` from the dashboards routes,
which the render routes use too, so there stays exactly one implementation.
"""

from typing import Any

from fastapi import HTTPException

from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User


def find_component(stored_metadata: list[dict] | None, component_id: str) -> dict | None:
    """Return the component whose ``index`` matches, or ``None``.

    ``index`` is compared as a string: it is a UUID in freshly built dashboards but
    older seeds and YAML imports can carry other scalar types.
    """
    for component in stored_metadata or []:
        if str(component.get("index")) == str(component_id):
            return component
    return None


def resolve_dashboard_component(
    dashboard_id: PyObjectId,
    component_id: str,
    current_user: User,
    *,
    expected_type: str | None = None,
) -> tuple[dict, dict, Any]:
    """Fetch a dashboard, authorise the user, and return one of its components.

    Args:
        dashboard_id: Dashboard to look in.
        component_id: The component's ``index``.
        current_user: Caller, already resolved by an auth dependency.
        expected_type: When given, the component must have this ``component_type``;
            a mismatch is a 404 rather than a 200 for the wrong thing.

    Returns:
        ``(dashboard_doc, component, project_id)``

    Raises:
        HTTPException: 404 if the dashboard or component is missing, 403 if the
            caller lacks ``viewer`` on the owning project.
    """
    # Imported here rather than at module scope: dashboards_endpoints.routes is a
    # large module that imports a large part of the API, and a top-level import
    # would make this small helper a cycle risk for anything it pulls in.
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _viewable_dashboard

    dashboard_data = _viewable_dashboard(dashboard_id, current_user)
    project_id = dashboard_data.get("project_id")

    component = find_component(dashboard_data.get("stored_metadata"), component_id)
    if component is None:
        raise HTTPException(status_code=404, detail=f"Component '{component_id}' not found.")

    if expected_type is not None and component.get("component_type") != expected_type:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Component '{component_id}' is a "
                f"{component.get('component_type')!r}, not a {expected_type!r}."
            ),
        )

    return dashboard_data, component, project_id


def resolve_dashboard(dashboard_id: PyObjectId, current_user: User) -> tuple[dict, Any]:
    """Fetch a dashboard and authorise the user, without selecting a component.

    Used by the manifest route, which reports on every component at once.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _viewable_dashboard

    dashboard_data = _viewable_dashboard(dashboard_id, current_user)
    return dashboard_data, dashboard_data.get("project_id")
