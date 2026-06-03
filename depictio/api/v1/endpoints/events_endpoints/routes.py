"""
WebSocket routes for real-time event notifications.

Provides WebSocket endpoint for dashboard real-time updates with JWT authentication.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from starlette import status

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _async_fetch_user_from_token
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.services.events import connection_manager, event_service
from depictio.models.models.users import User

events_router = APIRouter()


async def _resolve_websocket_user(token: str | None) -> User | None:
    """Decode the WS query-string token into a full ``User`` (or ``None``).

    WebSocket doesn't support Authorization headers, so the JWT arrives as a
    query parameter. Keeping the resolved user object (rather than a flattened
    dict) lets the subscribe path run dashboard/project permission checks.
    """
    if not token:
        return None
    try:
        return await _async_fetch_user_from_token(token)
    except Exception as e:
        logger.debug(f"WebSocket token verification failed: {e}")
        return None


def _user_can_access_dashboard(user: User | None, dashboard_id: str) -> bool:
    """Verify the authenticated user may subscribe to ``dashboard_id``'s events.

    Resolves the dashboard's owning project (minimal local MongoDB query, to
    avoid a ``PyObjectId``-typed cross-module helper that doesn't accept the
    raw ``str`` dashboard id) and reuses
    ``dashboards_endpoints.check_project_permission`` at viewer level. The
    permission helper is imported lazily because ``dashboards_endpoints.routes``
    pulls in a large dependency graph that can create an import cycle at app
    startup. When no user is resolved (public/anonymous mode) only public
    projects are subscribable.
    """
    from bson import ObjectId

    from depictio.api.v1.db import dashboards_collection, projects_collection
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    try:
        dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
        if not dashboard:
            logger.debug(f"WS subscribe denied: dashboard {dashboard_id} not found")
            return False

        project_id = dashboard.get("project_id")
        if not project_id:
            logger.debug(f"WS subscribe denied: dashboard {dashboard_id} has no project_id")
            return False

        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project:
            logger.debug(f"WS subscribe denied: project {project_id} not found")
            return False

        if user is None:
            # Anonymous / public mode: only public projects are subscribable.
            return bool(project.get("is_public", False))

        return check_project_permission(project["_id"], user, required_permission="viewer")
    except Exception as e:
        logger.warning(f"WS subscribe permission check failed for dashboard {dashboard_id}: {e}")
        return False


@events_router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="JWT access token"),
    dashboard_id: str | None = Query(default=None, description="Dashboard ID to subscribe to"),
):
    """
    WebSocket endpoint for real-time event notifications.

    Connect to receive real-time updates when data collections change.
    The server will automatically detect which dashboards are affected
    and send notifications to connected clients.

    Query Parameters:
        token: JWT access token for authentication
        dashboard_id: Dashboard ID to subscribe to for updates

    Message Types Received:
        - connection_established: Sent immediately after connection
        - data_collection_updated: When a DC used by your dashboard changes
        - heartbeat: Periodic keep-alive messages

    Example JavaScript:
        ```javascript
        const ws = new WebSocket(
            `ws://localhost:8058/depictio/api/v1/events/ws?token=${jwt}&dashboard_id=${dashboardId}`
        );
        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.event_type === 'data_collection_updated') {
                // Refresh dashboard component
            }
        };
        ```
    """
    if not settings.events.enabled:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Events disabled")
        return

    # Verify token (optional - allows unauthenticated connections if auth mode allows).
    # TODO(PR2 cookie migration): replace the token-in-query-string scheme with
    # cookie/subprotocol-based WebSocket auth. Query-string tokens leak into proxy
    # access logs and browser history. The full migration (and dropping the `token`
    # query param) is explicitly deferred to PR2.
    user = await _resolve_websocket_user(token)
    user_id = str(user.id) if user else None

    if user is None and not settings.auth.requires_anonymous_user:
        # Require authentication unless single-user / public / unauthenticated mode
        # is enabled (mirrors the HTTP `get_user_or_anonymous` fallback).
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required"
        )
        return

    # Gate the initial query-param subscription: connection_manager.connect()
    # auto-subscribes to `dashboard_id`, so it must pass the same ownership check
    # as message-based subscribes. Drop the auto-subscribe if the user can't access it.
    if dashboard_id and not _user_can_access_dashboard(user, dashboard_id):
        logger.warning(
            f"WS connect: user {user_id} denied auto-subscribe to dashboard {dashboard_id}"
        )
        dashboard_id = None

    # Accept connection and register with connection manager
    client_id = await connection_manager.connect(
        websocket=websocket,
        dashboard_id=dashboard_id,
        user_id=user_id,
    )

    try:
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages from client (ping/pong, subscription changes)
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=settings.events.ws_connection_timeout,
                )
                await handle_client_message(client_id, data, websocket, user)

            except asyncio.TimeoutError:
                # No message received, but connection is still alive
                # The heartbeat loop in EventService handles keep-alive
                continue

    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected normally: {client_id}")
    except Exception as e:
        logger.warning(f"WebSocket error for {client_id}: {e}")
    finally:
        await connection_manager.disconnect(client_id)


async def handle_client_message(
    client_id: str,
    data: dict[str, Any],
    websocket: WebSocket,
    user: User | None,
) -> None:
    """
    Handle incoming messages from WebSocket clients.

    Supports:
        - subscribe: Subscribe to a dashboard (permission-checked)
        - unsubscribe: Unsubscribe from a dashboard
        - ping: Client ping (responds with pong)
    """
    msg_type = data.get("type", "")
    dashboard_id = data.get("dashboard_id")

    if msg_type == "subscribe" and dashboard_id:
        # Verify the authenticated user can access this dashboard before
        # wiring up its event stream. Without this, any connected client could
        # subscribe to (and receive update payloads for) arbitrary dashboards.
        if not _user_can_access_dashboard(user, dashboard_id):
            logger.warning(f"WS subscribe denied: client {client_id} -> dashboard {dashboard_id}")
            await websocket.send_json(
                {
                    "type": "subscribe_denied",
                    "dashboard_id": dashboard_id,
                    "reason": "not_authorized",
                }
            )
            return
        await connection_manager.subscribe_to_dashboard(client_id, dashboard_id)
        await websocket.send_json({"type": "subscribed", "dashboard_id": dashboard_id})

    elif msg_type == "unsubscribe" and dashboard_id:
        await connection_manager.unsubscribe_from_dashboard(client_id, dashboard_id)
        await websocket.send_json({"type": "unsubscribed", "dashboard_id": dashboard_id})

    elif msg_type == "ping":
        await websocket.send_json({"type": "pong"})


@events_router.get("/status")
async def get_events_status(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get the status of the real-time events system. Admin-only — connection
    counts and service internals are operator diagnostics, not tenant data.

    Returns:
        Status information including enabled state, connection counts, etc.
    """
    if not current_user.is_admin:
        logger.warning(f"Non-admin user {current_user.id} denied access to events status")
        raise HTTPException(status_code=403, detail="Current user is not an admin.")
    return {
        "enabled": settings.events.enabled,
        "mongodb_change_streams": settings.events.mongodb_change_streams_enabled,
        "total_connections": connection_manager.get_connection_count(),
        "service_stats": event_service.get_stats(),
    }


def _build_event_payload(dc_id: str, operation: str = "update") -> dict[str, Any]:
    """Assemble a meaningful WS payload for a DC update.

    Pulls the human-readable tag, parent project, latest aggregation entry
    (version, row hash, timestamp), and current delta-table row count from
    MongoDB so the frontend has something useful to show in the journal.
    Best-effort — every field is optional and the function never raises.
    """
    from bson import ObjectId

    from depictio.api.v1.db import deltatables_collection, projects_collection

    payload: dict[str, Any] = {"operation": operation, "dc_id": dc_id}
    try:
        dc_oid = ObjectId(dc_id)
    except Exception:
        return payload

    # Project / DC tags from the embedded structure.
    try:
        project = projects_collection.find_one(
            {"workflows.data_collections._id": dc_oid},
            {"name": 1, "workflows": 1},
        )
        if project:
            payload["project_id"] = str(project.get("_id")) if project.get("_id") else None
            payload["project_name"] = project.get("name")
            for wf in project.get("workflows", []):
                for dc in wf.get("data_collections", []):
                    if dc.get("_id") == dc_oid:
                        payload["data_collection_tag"] = dc.get("data_collection_tag")
                        payload["workflow_tag"] = wf.get("workflow_tag")
                        cfg = dc.get("config", {}) or {}
                        if isinstance(cfg, dict):
                            payload["data_collection_type"] = cfg.get("type")
                        break
    except Exception as e:
        logger.debug(f"_build_event_payload: project lookup failed: {e}")

    # Latest aggregation entry — version + row count + hash.
    delta_location: str | None = None
    try:
        dt = deltatables_collection.find_one({"data_collection_id": dc_oid})
        if dt:
            agg_list = dt.get("aggregation") or []
            if agg_list:
                latest = agg_list[-1]
                payload["aggregation_version"] = latest.get("aggregation_version")
                payload["aggregation_hash"] = latest.get("aggregation_hash")
                ts = latest.get("aggregation_time")
                payload["aggregation_time"] = ts.isoformat() if hasattr(ts, "isoformat") else ts
            fm = dt.get("flexible_metadata") or {}
            if isinstance(fm, dict) and fm.get("deltatable_size_bytes") is not None:
                payload["delta_size_bytes"] = fm.get("deltatable_size_bytes")
            delta_location = dt.get("delta_table_location")
    except Exception as e:
        logger.debug(f"_build_event_payload: deltatable lookup failed: {e}")

    # Live row count — read the delta directly via polars (no API hop). The
    # delta_location came from the same MongoDB record we just queried, so
    # we already know exactly what to scan.
    if delta_location:
        try:
            import polars as pl
            from deltalake import DeltaTable

            from depictio.api.v1.s3 import polars_s3_config

            current_df = pl.scan_delta(delta_location, storage_options=polars_s3_config).collect()
            payload["row_count"] = int(current_df.height)

            # Diff against the previous Delta Lake version to surface what
            # actually changed. Delta versions are commit ids, monotonic per
            # write; for ``mode="overwrite"`` writes the previous commit
            # holds the pre-update snapshot. When this is the very first
            # commit (version=0) there's no diff to compute.
            try:
                dt = DeltaTable(delta_location, storage_options=polars_s3_config)
                current_version = dt.version()
                payload["delta_version"] = int(current_version)
                if current_version > 0:
                    prev_df = pl.scan_delta(
                        delta_location,
                        version=current_version - 1,
                        storage_options=polars_s3_config,
                    ).collect()
                    prev_count = int(prev_df.height)
                    payload["prev_row_count"] = prev_count
                    payload["row_delta"] = int(current_df.height) - prev_count

                    # If we can spot a stable id-ish column, expose a small
                    # sample of new ids — gives the journal something to point
                    # at without dumping the whole new dataset.
                    id_col = _pick_id_column(current_df.columns)
                    if id_col is not None and id_col in prev_df.columns:
                        try:
                            prev_ids = set(prev_df.get_column(id_col).cast(pl.Utf8).to_list())
                            current_ids = current_df.get_column(id_col).cast(pl.Utf8).to_list()
                            new_ids = [v for v in current_ids if v not in prev_ids]
                            if new_ids:
                                payload["id_column"] = id_col
                                payload["new_ids_sample"] = new_ids[:10]
                                payload["new_ids_total"] = len(new_ids)
                        except Exception:
                            pass
            except Exception as diff_err:
                logger.debug(f"_build_event_payload: prev-version diff failed: {diff_err}")
        except Exception as e:
            logger.debug(f"_build_event_payload: row-count scan failed: {e}")

    return payload


def _pick_id_column(columns: list[str]) -> str | None:
    """Pick a likely-unique column to anchor the new-ids diff.

    Preference order: ``index_index`` (common Depictio convention), columns
    ending in ``_id`` / ``id`` / ``index``, then the first column. Returns
    None for an empty schema.
    """
    if not columns:
        return None
    for cand in ("index_index", "id", "ID", "Id"):
        if cand in columns:
            return cand
    for col in columns:
        lower = col.lower()
        if lower.endswith("_id") or lower.endswith("_index") or lower == "index":
            return col
    return columns[0]


@events_router.post("/test-trigger/{dc_id}")
async def test_trigger_event(
    dc_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Manually trigger a ``data_collection_updated`` event — useful for
    verifying WebSocket notifications without standing up MongoDB change
    streams (which require a replica set, not available in dev compose).

    Broadcasts to every dashboard with an active subscription via
    ``connection_manager``. Open the React viewer for the dashboard, then
    POST to this endpoint to see the live-update flow end-to-end.

    Admin-only: this is a test/debug endpoint that broadcasts arbitrary DC
    update events to all connected clients.
    """
    if not current_user.is_admin:
        logger.warning(
            f"Denied test-trigger: non-admin user {current_user.id} ({current_user.email})"
        )
        raise HTTPException(status_code=403, detail="User is not an admin.")

    from datetime import datetime, timezone

    from depictio.api.v1.deltatables_utils import invalidate_data_collection_cache
    from depictio.models.models.realtime import EventMessage, EventSourceType, EventType

    # Invalidate first so the row count we read for the payload reflects the
    # newly-written delta, not the stale cache.
    dropped = invalidate_data_collection_cache(dc_id)
    if dropped:
        logger.info(f"test-trigger {dc_id}: invalidated {dropped} cached DataFrame(s)")

    payload = _build_event_payload(dc_id, operation="update")
    payload["test_trigger"] = True

    event = EventMessage(
        event_type=EventType.DATA_COLLECTION_UPDATED,
        source_type=EventSourceType.MONGODB_CHANGES,
        timestamp=datetime.now(timezone.utc),
        data_collection_id=dc_id,
        payload=payload,
    )

    subscribed = connection_manager.get_all_subscribed_dashboards()
    if not subscribed:
        return {
            "success": False,
            "message": "No connected dashboards to notify",
            "connections": connection_manager.get_connection_count(),
        }

    for dashboard_id in subscribed:
        event_copy = event.model_copy(update={"dashboard_id": dashboard_id})
        await connection_manager.broadcast_to_dashboard(dashboard_id, event_copy)

    logger.info(f"Test event triggered for {len(subscribed)} connected dashboards")
    return {
        "success": True,
        "message": f"Event triggered for {len(subscribed)} connected dashboards",
        "dashboard_ids": list(subscribed),
        "connections": connection_manager.get_connection_count(),
        "payload": payload,
    }
