"""REST enforcement of token scopes.

``enforce_token_scopes`` is a router-level dependency on the aggregate API
router (``endpoints/routers.py``), so it runs for every API route. It is a
no-op for sessions, legacy tokens and unauthenticated requests. A request
authenticated with a scoped token is fail-closed:

- ``GET`` / ``HEAD`` / ``OPTIONS`` need ``read``, except the routes in
  ``DENIED_READS`` (reads that write, or that leak credentials).
- ``READ_ONLY_POSTS`` need ``read``: render, preview and compute routes that
  only answer a query.
- ``WRITE_SCOPES`` maps each allowed write route to the scope it needs.
- Everything else is refused with 403, including token minting, user and
  group admin, project deletes, backups and thread review.

``EXPLICIT_DENY`` is not consulted at runtime (unmapped already means deny).
It exists so the route-coverage test forces a decision for every new write
route instead of letting it fall through silently.

The gate resolves the Bearer token itself instead of reading the contextvar,
because route-level ``get_current_user`` runs after router-level
dependencies. Keys are ``(method, path template)`` with the API prefix
(``/depictio/api/v1``) stripped.
"""

import re
import weakref

from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import HTTPConnection

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.token_scopes import (
    bearer_token,
    set_current_token,
)
from depictio.models.models.users import TokenBeanie, TokenScope, effective_scopes

RouteKey = tuple[str, str]

READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

# Reads a scoped token may not perform: GETs with side effects, and GETs that
# hand out credentials (other tokens, sessions, storage secrets, backups).
DENIED_READS: frozenset[str] = frozenset(
    {
        "/utils/drop_S3_content",
        "/utils/drop_all_collections",
        # Drives a headless browser in the worker and writes PNGs.
        "/utils/screenshot-react-dual/{dashboard_id}",
        # Launches a browser and runs storage I/O probes.
        "/utils/infrastructure-diagnostics",
        "/auth/list_tokens",
        "/auth/fetch_user/from_token",
        "/auth/fetch_user/from_email",
        "/auth/fetch_user/from_id",
        "/auth/get_anonymous_user_session",
        "/auth/public/get_anonymous_user_session",
        "/auth/get_all_users",
        "/auth/list",
        "/auth/google/login",
        "/auth/google/callback",
        "/projects/{project_id}/storage",
        "/backup/schedule",
        "/backup/list",
        "/backup/download/{backup_id}",
        "/analytics-data/etl/user-summary",
    }
)

# POSTs that only answer a query (render, preview, compute, validate).
READ_ONLY_POSTS: frozenset[RouteKey] = frozenset(
    ("POST", path)
    for path in (
        "/projects/{project_id}/export_template",
        "/workflows/compare_workflow_models",
        "/multiqc/preview",
        "/links/{project_id}/resolve",
        "/deltatables/batch/exists",
        "/deltatables/breakdown/{data_collection_id}",
        "/deltatables/card_metric/{data_collection_id}",
        "/deltatables/preview/{data_collection_id}",
        "/utils/branding/resolve",
        "/dashboards/bulk_component_data/{dashboard_id}",
        "/dashboards/bulk_compute_cards/{dashboard_id}",
        "/dashboards/render_figure/{dashboard_id}/{component_id}",
        "/dashboards/render_table/{dashboard_id}/{component_id}",
        "/dashboards/render_image_paths/{dashboard_id}/{component_id}",
        "/dashboards/render_map/{dashboard_id}/{component_id}",
        "/dashboards/map_data/{dashboard_id}/{component_id}",
        "/dashboards/render_jbrowse/{dashboard_id}/{component_id}",
        "/dashboards/render_multiqc/{dashboard_id}/{component_id}",
        "/dashboards/render_multiqc_general_stats/{dashboard_id}/{component_id}",
        "/dashboards/funnel_values/{dashboard_id}",
        "/dashboards/yaml/validate",
        "/dashboards/json/validate",
        "/figure/preview",
        "/figure/analyze_code",
        "/advanced_viz/data",
        "/advanced_viz/compute_embedding",
        "/advanced_viz/compute_complex_heatmap",
        "/advanced_viz/compute_upset",
        "/advanced_viz/compute_coverage_track",
        "/advanced_viz/compute_sankey",
        "/auth/check_token_validity",
        # Re-mints an access token for the same token document, carrying its
        # scopes, so a refresh can never widen a token.
        "/auth/refresh",
    )
)

WRITE_SCOPES: dict[RouteKey, TokenScope] = {
    # annotate: open a thread, reply to one. Review, publish, edits and
    # deletes stay with humans.
    ("POST", "/comments/threads"): "annotate",
    ("POST", "/comments/threads/{thread_id}/comments"): "annotate",
    # report: LLM analyses and summaries.
    ("POST", "/ai/analyze"): "report",
    ("POST", "/ai/summarize-section"): "report",
    ("POST", "/ai/resolve-filters"): "report",
    # Agent-team runs write threads and a report, each through the tool
    # registry with the run's own scope checks; the dry-run route may spend
    # LLM tokens, so it sits with them.
    ("POST", "/ai/agent-runs"): "report",
    ("POST", "/ai/agent-runs/route"): "report",
    ("POST", "/ai/agent-runs/{run_id}/cancel"): "report",
    # edit_dashboard: dashboard create/edit/import/save and AI generation.
    ("POST", "/dashboards/save/{dashboard_id}"): "edit_dashboard",
    ("POST", "/dashboards/edit/{dashboard_id}"): "edit_dashboard",
    ("PATCH", "/dashboards/appearance/{dashboard_id}"): "edit_dashboard",
    ("PATCH", "/dashboards/tab/{dashboard_id}"): "edit_dashboard",
    ("POST", "/dashboards/tabs/reorder"): "edit_dashboard",
    ("POST", "/dashboards/import/yaml"): "edit_dashboard",
    ("POST", "/dashboards/import/json"): "edit_dashboard",
    ("POST", "/ai/suggest-components"): "edit_dashboard",
    ("POST", "/ai/suggest-figures"): "edit_dashboard",
    ("POST", "/ai/component-from-prompt"): "edit_dashboard",
    ("POST", "/ai/generate-dashboard"): "edit_dashboard",
    (
        "POST",
        "/ai/generated-dashboards/{dashboard_id}/components/{index}/regenerate",
    ): "edit_dashboard",
    (
        "POST",
        "/ai/generated-dashboards/{dashboard_id}/sections/{section}/regenerate",
    ): "edit_dashboard",
    # ingest: project from a run or manifest, data uploads, CLI ingestion.
    ("POST", "/projects/from_run"): "ingest",
    ("POST", "/projects/from_manifest"): "ingest",
    ("POST", "/projects/ingest_manifest"): "ingest",
    ("POST", "/projects/refresh_manifest"): "ingest",
    ("POST", "/runs/upsert_batch"): "ingest",
    ("POST", "/files/upsert_batch"): "ingest",
    ("POST", "/deltatables/upsert"): "ingest",
    ("POST", "/datacollections/create_from_upload"): "ingest",
    ("POST", "/datacollections/create_from_url"): "ingest",
    ("POST", "/datacollections/create_multiqc_from_upload"): "ingest",
    ("POST", "/datacollections/multiqc_uniformity_check"): "ingest",
    ("POST", "/datacollections/{data_collection_id}/append"): "ingest",
    ("POST", "/datacollections/{data_collection_id}/replace"): "ingest",
    ("POST", "/multiqc/reports"): "ingest",
    ("POST", "/multiqc/reports/data-collection/{data_collection_id}/append"): "ingest",
    ("POST", "/multiqc/reports/data-collection/{data_collection_id}/replace"): "ingest",
    ("POST", "/monitoring/ingestion/start"): "ingest",
    ("POST", "/monitoring/ingestion/{run_id}/step"): "ingest",
    ("POST", "/monitoring/ingestion/{run_id}/finish"): "ingest",
}

EXPLICIT_DENY: frozenset[RouteKey] = frozenset(
    {
        # Projects: create/update/delete, permissions, storage, admin.
        ("POST", "/projects/create"),
        ("PUT", "/projects/update"),
        ("DELETE", "/projects/delete"),
        ("PUT", "/projects/{project_id}/storage"),
        ("DELETE", "/projects/{project_id}/storage"),
        ("POST", "/projects/{project_id}/storage/test"),
        ("POST", "/projects/admin/clean_examples"),
        ("POST", "/projects/update_project_permissions"),
        ("POST", "/projects/toggle_public_private/{project_id}"),
        # Workflows, runs, files, deltatables: structural edits and deletes.
        ("POST", "/workflows/create"),
        ("PUT", "/workflows/update"),
        ("DELETE", "/workflows/delete/{workflow_id}"),
        ("DELETE", "/runs/delete/{run_id}"),
        ("DELETE", "/files/delete/{file_id}"),
        ("DELETE", "/deltatables/delete/{deltatable_id}"),
        # Data collections: renames, property edits, deletes.
        ("DELETE", "/datacollections/delete/{workflow_id}/{data_collection_id}"),
        ("PUT", "/datacollections/{data_collection_id}/name"),
        ("PATCH", "/datacollections/{data_collection_id}/dc_specific_properties"),
        ("DELETE", "/datacollections/{data_collection_id}"),
        ("DELETE", "/datacollections/{data_collection_id}/data"),
        # MultiQC report edits and deletes.
        ("PUT", "/multiqc/reports/{report_id}"),
        ("DELETE", "/multiqc/reports/{report_id}"),
        ("DELETE", "/multiqc/reports/data-collection/{data_collection_id}"),
        # DC links.
        ("POST", "/links/{project_id}"),
        ("PUT", "/links/{project_id}/{link_id}"),
        ("DELETE", "/links/{project_id}/{link_id}"),
        # JBrowse config writes.
        ("POST", "/jbrowse/create_trackset/{workflow_id}/{data_collection_id}"),
        ("POST", "/jbrowse/filter_config"),
        ("POST", "/jbrowse/dynamic_mapping_dict"),
        # Instance admin: branding, S3 cleanup, initial data.
        ("PUT", "/utils/branding"),
        ("DELETE", "/utils/branding"),
        ("POST", "/utils/branding/logo/{variant}"),
        ("POST", "/utils/cleanup-orphaned-s3-files"),
        ("POST", "/utils/process_initial_data_collections"),
        # Backups and project migration.
        ("POST", "/backup/create"),
        ("PUT", "/backup/schedule"),
        ("POST", "/backup/validate"),
        ("POST", "/backup/upload"),
        ("POST", "/backup/restore"),
        ("POST", "/migrate/export-project"),
        ("POST", "/migrate/import-project"),
        ("POST", "/migrate/import-project-zip"),
        ("POST", "/cli/validate_cli_config"),
        # Dashboards: permissions sync, logo upload, deletes.
        ("POST", "/dashboards/sync_with_projects"),
        ("POST", "/dashboards/upload_logo/{dashboard_id}"),
        ("DELETE", "/dashboards/delete/{dashboard_id}"),
        ("DELETE", "/dashboards/tab/{dashboard_id}"),
        # Comments: edits, deletes, review and publish stay with humans.
        ("PATCH", "/comments/threads/{thread_id}"),
        ("POST", "/comments/threads/{thread_id}/review"),
        ("DELETE", "/comments/threads/{thread_id}"),
        ("PATCH", "/comments/threads/{thread_id}/comments/{comment_id}"),
        ("DELETE", "/comments/threads/{thread_id}/comments/{comment_id}"),
        # AI: agents never promote or review a generated dashboard.
        ("POST", "/ai/generated-dashboards/{dashboard_id}/promote"),
        ("POST", "/ai/generated-dashboards/{dashboard_id}/review"),
        # Monitoring admin.
        ("POST", "/monitoring/logs/level"),
        # Auth: login, token minting, users, sessions.
        ("POST", "/auth/login"),
        ("POST", "/auth/create_token"),
        ("POST", "/auth/provision_user"),
        ("POST", "/auth/me/magic_link"),
        ("POST", "/auth/magic/exchange"),
        ("POST", "/auth/refresh_token"),
        ("POST", "/auth/create_temporary_user"),
        ("POST", "/auth/cleanup_expired_temporary_users"),
        ("POST", "/auth/public/create_temporary_user"),
        ("POST", "/auth/register"),
        ("POST", "/auth/edit_password"),
        ("POST", "/auth/delete_token"),
        ("POST", "/auth/me/tokens"),
        ("DELETE", "/auth/me/tokens/{token_id}"),
        ("POST", "/auth/purge_expired_tokens"),
        ("POST", "/auth/generate_agent_config"),
        ("DELETE", "/auth/delete/{user_id}"),
        ("POST", "/auth/turn_sysadmin/{user_id}/{is_admin}"),
        # Analytics tracking and admin.
        ("DELETE", "/analytics/sessions/{session_id}"),
        ("POST", "/analytics/cleanup"),
        ("POST", "/analytics/track/pageview"),
        ("POST", "/analytics/admin/consolidate-sessions"),
        ("DELETE", "/analytics/admin/cleanup-anonymous-sessions"),
        ("POST", "/analytics-data/etl/refresh"),
        # Real-time events: test trigger.
        ("POST", "/events/test-trigger/{dc_id}"),
    }
)

_API_PREFIX_RE = re.compile(r"^/depictio/api/v\d+(?=/|$)")


def api_relative_path(path: str) -> str:
    """Strip the ``/depictio/api/vN`` prefix from a full route template."""
    return _API_PREFIX_RE.sub("", path, count=1) or "/"


def required_scope(method: str, path: str) -> TokenScope | None:
    """Scope a scoped token needs for ``method path``; None means refused.

    ``path`` is the route template relative to the API prefix.
    """
    method = method.upper()
    if method in READ_METHODS:
        return None if path in DENIED_READS else "read"
    key = (method, path)
    if key in READ_ONLY_POSTS:
        return "read"
    return WRITE_SCOPES.get(key)


# Full path template per route object, per app. FastAPI >= 0.141 routes
# included routers lazily: ``scope["route"]`` is the route as declared on its
# own router, so its ``.path`` lacks the include prefixes. The effective
# (prefixed) template comes from ``iter_route_contexts``.
_route_paths: "weakref.WeakKeyDictionary[object, dict[int, str]]" = weakref.WeakKeyDictionary()


def _build_route_paths(app: object) -> dict[int, str]:
    paths: dict[int, str] = {}
    routes = getattr(app, "routes", [])
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # older FastAPI: included routes already carry the prefix
        for route in routes:
            if isinstance(route, APIRoute):
                paths[id(route)] = route.path
        return paths
    for ctx in iter_route_contexts(routes):
        if isinstance(ctx.original_route, APIRoute) and ctx.path:
            paths.setdefault(id(ctx.original_route), ctx.path)
    return paths


def route_template(conn: HTTPConnection) -> str | None:
    """Full path template of the matched route, or None if unknown."""
    route = conn.scope.get("route")
    if route is None:
        return None
    app = conn.scope.get("app")
    if app is None:
        return getattr(route, "path", None)
    paths = _route_paths.get(app)
    if paths is None or id(route) not in paths:
        paths = _build_route_paths(app)
        _route_paths[app] = paths
    return paths.get(id(route), getattr(route, "path", None))


async def enforce_token_scopes(conn: HTTPConnection) -> None:
    """Refuse routes outside a scoped token's scopes (router-level dependency)."""
    token = bearer_token(conn.headers)
    if token is None:
        return  # unauthenticated or session cookie: the route's own auth decides
    try:
        token_doc = await TokenBeanie.find_one({"access_token": token})
    except Exception as exc:
        # Fail closed: without the token doc we cannot tell a scoped token
        # from a full-access one.
        logger.error(f"Scope gate could not look up the token: {exc}")
        raise HTTPException(status_code=503, detail="Could not verify token scopes")
    if token_doc is None or token_doc.scopes is None:
        return  # unknown token (route auth rejects it) or legacy full access

    # Expose the scopes before route dependencies run, too.
    set_current_token(token_doc.scopes, token_doc.name, str(token_doc.id))

    if conn.scope.get("type") == "websocket":
        return  # event streams are reads, and read is implied by any scope

    template = route_template(conn)
    method = conn.scope.get("method", "GET")
    scope = required_scope(method, api_relative_path(template)) if template else None
    if scope is None or scope not in effective_scopes(token_doc.scopes):
        logger.info(f"Scoped token {token_doc.id} refused on {method} {template or conn.url.path}")
        raise HTTPException(
            status_code=403,
            detail="This token's scopes do not allow this operation",
        )
