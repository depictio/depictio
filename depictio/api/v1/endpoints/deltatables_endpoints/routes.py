"""
DeltaTables API endpoints for managing data collection delta tables.

Provides CRUD operations for DeltaTableAggregated objects including
upsert, fetch, batch existence checks, and shape queries.
"""

import hashlib
import math
from datetime import datetime

import boto3
import polars as pl
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Response

from depictio.api.v1.celery_dispatch import offload_or_run
from depictio.api.v1.celery_tasks import preview_deltatable as preview_deltatable_task
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import deltatables_collection, projects_collection, users_collection
from depictio.api.v1.endpoints.deltatables_endpoints.utils import precompute_columns_specs
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.s3 import polars_s3_config
from depictio.api.v1.services.card_breakdown import compute_breakdown
from depictio.api.v1.utils import agg_functions
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.deltatables import (
    Aggregation,
    DeltaTableAggregated,
    UpsertDeltaTableAggregated,
)
from depictio.models.models.users import User

deltatables_endpoint_router = APIRouter()


def _delta_identity_hash(delta_table_location: str, storage_options: dict) -> str:
    """Hash the identity of a Delta table from its log, without reading data.

    This replaces a ``df.hash_rows()`` over the fully materialised frame, which
    on a ~14M-row data collection cost a full read plus a numpy round-trip and
    contributed to OOM-killing the worker. The resulting digest is *not* a
    content hash: it covers the table version and the active files (path, size,
    modification time), which change whenever the data does. That is all the
    value is ever used for — it is salted with ``datetime.now()`` by the caller,
    so no two upserts ever produce comparable digests anyway; downstream
    (``RealtimeIndicator``) only tests it for inequality.
    """
    from deltalake import DeltaTable

    dt = DeltaTable(delta_table_location, storage_options=storage_options)
    parts = [str(dt.version())]
    try:
        actions = pl.from_arrow(dt.get_add_actions(flatten=True))
        if not isinstance(actions, pl.DataFrame):
            # A single-column result comes back as a Series; the fallback below
            # handles it rather than this branch guessing at its shape.
            raise TypeError(f"get_add_actions yielded {type(actions).__name__}, not a table")
        wanted = [c for c in ("path", "size_bytes", "modification_time") if c in actions.columns]
        parts += ["|".join(str(v) for v in row) for row in sorted(actions.select(wanted).rows())]
    except Exception as e:
        logger.warning(f"get_add_actions unavailable ({e}); hashing the file list instead.")
        parts += sorted(dt.file_uris())
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _previous_column_types(deltatable_doc: dict | None) -> dict[str, str]:
    """Column name -> type recorded by the latest aggregation, if any.

    Feeding these back into ``precompute_columns_specs`` keeps a re-ingest from
    silently changing the type a saved dashboard component was built against.
    """
    aggregations = (deltatable_doc or {}).get("aggregation") or []
    if not aggregations:
        return {}
    specs = aggregations[-1].get("aggregation_columns_specs") or []
    return {s["name"]: s["type"] for s in specs if s.get("name") and s.get("type")}


def sanitize_for_json(obj):
    """
    Recursively sanitizes data for JSON serialization by replacing NaN and Infinity with None.
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(i) for i in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


@deltatables_endpoint_router.post("/upsert")
async def upsert_deltatable(
    payload: UpsertDeltaTableAggregated,
    current_user: User = Depends(get_current_user),
):
    """
    Upsert a DeltaTableAggregated object.

    Args:
        payload: Delta table configuration and location.
        current_user: Authenticated user making the request.

    Returns:
        Success message on completion.

    Raises:
        HTTPException: If project or data collection not found.
    """
    data_collection_oid = payload.data_collection_id

    project = projects_collection.find_one(
        _owned_or_admin_query(current_user, {"workflows.data_collections._id": data_collection_oid})
    )
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"No projects containing Data Collection id {data_collection_oid} found for the current user.",
        )

    dc_data = None
    for workflow in project.get("workflows", []):
        dc_data = next(
            (
                dc
                for dc in workflow.get("data_collections", [])
                if str(dc["_id"]) == str(data_collection_oid)
            ),
            None,
        )
        if dc_data:
            break

    if not dc_data:
        raise HTTPException(
            status_code=404,
            detail=f"Data collection with ID {data_collection_oid} not found in any project workflow.",
        )

    # Check if this is a MultiQC data collection (stored as parquet, not delta table)
    dc_type = dc_data.get("config", {}).get("type", "")
    is_multiqc = dc_type.lower() == "multiqc"

    query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})

    # For MultiQC, skip delta table validation since it's stored as raw parquet
    if is_multiqc:
        # Create minimal hash for MultiQC without reading the file
        final_hash = hashlib.sha256(
            f"{payload.delta_table_location}{datetime.now()}".encode()
        ).hexdigest()
        results = []  # Column specs not computed for MultiQC (empty list required by Pydantic)
    else:
        # Standard delta table validation and column spec computation. The scan
        # stays lazy: precompute_columns_specs only needs per-column
        # aggregations, and materialising a multi-GB data collection here is
        # what used to get the worker OOM-killed.
        lf = pl.scan_delta(payload.delta_table_location, storage_options=polars_s3_config)
        results = precompute_columns_specs(
            lf, agg_functions, dc_data, previous_types=_previous_column_types(query_dt)
        )

        hash_df = _delta_identity_hash(payload.delta_table_location, polars_s3_config)
        final_hash = hashlib.sha256(
            f"{payload.delta_table_location}{datetime.now()}{hash_df}".encode()
        ).hexdigest()

    if query_dt:
        deltatable = DeltaTableAggregated.from_mongo(query_dt)
        version = (
            1 if not deltatable.aggregation else deltatable.aggregation[-1].aggregation_version + 1
        )
    else:
        deltatable = DeltaTableAggregated(
            data_collection_id=data_collection_oid,
            delta_table_location=str(payload.delta_table_location),
        )
        version = 1

    user = User.from_mongo(users_collection.find_one({"_id": ObjectId(current_user.id)}))  # type: ignore[invalid-argument-type]
    userbase = user.turn_to_userbase()

    deltatable.aggregation.append(
        Aggregation(
            aggregation_time=datetime.now(),
            aggregation_by=userbase,
            aggregation_version=version,
            aggregation_hash=final_hash,
            aggregation_columns_specs=results,
        )
    )

    if payload.deltatable_size_bytes is not None and not is_multiqc:
        projects_collection.update_one(
            {
                "workflows.data_collections._id": data_collection_oid,
                "workflows.data_collections.flexible_metadata": None,
            },
            {"$set": {"workflows.$[workflow].data_collections.$[dc].flexible_metadata": {}}},
            array_filters=[
                {"workflow.data_collections": {"$exists": True}},
                {"dc._id": data_collection_oid},
            ],
        )

        projects_collection.update_one(
            {"workflows.data_collections._id": data_collection_oid},
            {
                "$set": {
                    "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_bytes": payload.deltatable_size_bytes,
                    "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_mb": round(
                        payload.deltatable_size_bytes / (1024 * 1024), 2
                    ),
                    "workflows.$[workflow].data_collections.$[dc].flexible_metadata.deltatable_size_updated": datetime.now().isoformat(),
                }
            },
            array_filters=[
                {"workflow.data_collections": {"$exists": True}},
                {"dc._id": data_collection_oid},
            ],
        )

    if payload.update:
        # First ensure flexible_metadata is not null (MongoDB can't set nested fields on null)
        if payload.deltatable_size_bytes is not None and not is_multiqc:
            deltatables_collection.update_one(
                {"data_collection_id": data_collection_oid, "flexible_metadata": None},
                {"$set": {"flexible_metadata": {}}},
            )

        update_doc = {
            "$set": {
                "delta_table_location": payload.delta_table_location,
                "aggregation": [a.mongo() for a in deltatable.aggregation],
            }
        }
        # Add size to deltatable's flexible_metadata if provided
        if payload.deltatable_size_bytes is not None and not is_multiqc:
            update_doc["$set"]["flexible_metadata.deltatable_size_bytes"] = (
                payload.deltatable_size_bytes
            )
            update_doc["$set"]["flexible_metadata.deltatable_size_mb"] = round(
                payload.deltatable_size_bytes / (1024 * 1024), 2
            )
            update_doc["$set"]["flexible_metadata.deltatable_size_updated"] = (
                datetime.now().isoformat()
            )

        deltatables_collection.update_one(
            {"data_collection_id": data_collection_oid},
            update_doc,
            upsert=True,
        )
    else:
        query_dt = deltatables_collection.find_one({"data_collection_id": data_collection_oid})
        if query_dt:
            raise HTTPException(
                status_code=400,
                detail=f"DeltaTableAggregated with id {data_collection_oid} already exists, use update=True to update it.",
            )
        deltatables_collection.insert_one(deltatable.mongo())

    # The CLI just rewrote the delta — drop every cached DataFrame for this DC
    # so subsequent ``render_*`` calls see fresh rows. Without this the in-process
    # memory cache + Redis cache continue to serve the pre-rewrite DataFrame even
    # after the on-disk delta is gone.
    try:
        from depictio.api.v1.deltatables_utils import invalidate_data_collection_cache

        dropped = invalidate_data_collection_cache(str(data_collection_oid))
        if dropped:
            logger.info(
                f"upsert_deltatable: invalidated {dropped} cached DataFrame(s) for "
                f"dc_id={data_collection_oid}"
            )
    except Exception as e:
        logger.warning(f"upsert_deltatable: cache invalidation failed: {e}")

        # Add size to deltatable's flexible_metadata if provided
        if payload.deltatable_size_bytes is not None and not is_multiqc:
            # First ensure flexible_metadata is not null (MongoDB can't set nested fields on null)
            deltatables_collection.update_one(
                {"data_collection_id": data_collection_oid, "flexible_metadata": None},
                {"$set": {"flexible_metadata": {}}},
            )
            # Now set the nested fields
            deltatables_collection.update_one(
                {"data_collection_id": data_collection_oid},
                {
                    "$set": {
                        "flexible_metadata.deltatable_size_bytes": payload.deltatable_size_bytes,
                        "flexible_metadata.deltatable_size_mb": round(
                            payload.deltatable_size_bytes / (1024 * 1024), 2
                        ),
                        "flexible_metadata.deltatable_size_updated": datetime.now().isoformat(),
                    }
                },
            )

    # Broadcast a real-time event so connected dashboards refresh. The change
    # stream watcher only watches data_collections, not the deltatables
    # collection, so an upsert would otherwise complete silently. Mirrors the
    # test-trigger endpoint's invalidate-then-broadcast pattern.
    await _broadcast_dc_update(str(data_collection_oid))

    return {"message": "DeltaTableAggregated upserted successfully", "result": "success"}


async def _broadcast_dc_update(dc_id: str) -> None:
    """Invalidate the DC cache and broadcast a data-collection-updated event to all subscribers."""
    from datetime import timezone

    from depictio.api.v1.deltatables_utils import invalidate_data_collection_cache
    from depictio.api.v1.endpoints.events_endpoints.routes import _build_event_payload
    from depictio.api.v1.services.events import connection_manager
    from depictio.models.models.realtime import EventMessage, EventSourceType, EventType

    dropped = invalidate_data_collection_cache(dc_id)
    logger.info(f"Upsert {dc_id}: invalidated {dropped} cached DataFrame(s)")

    # Build the same rich payload the test-trigger path produces (row delta vs.
    # the previous delta version, new-id sample, aggregation version/hash/time,
    # live row count) so the RealtimeIndicator journal has something to show.
    # Runs after the upsert recorded a fresh aggregation entry, so the version/
    # hash/time reflect the write that just landed. Best-effort, never raises.
    payload = _build_event_payload(dc_id, operation="upsert")

    event = EventMessage(
        event_type=EventType.DATA_COLLECTION_UPDATED,
        source_type=EventSourceType.MONGODB_CHANGES,
        timestamp=datetime.now(timezone.utc),
        data_collection_id=dc_id,
        payload=payload,
    )

    subscribed = connection_manager.get_all_subscribed_dashboards()
    for dashboard_id in subscribed:
        event_copy = event.model_copy(update={"dashboard_id": dashboard_id})
        await connection_manager.broadcast_to_dashboard(dashboard_id, event_copy)

    logger.info(f"Upsert event broadcast for DC {dc_id} to {len(subscribed)} dashboard(s)")


def _owned_or_admin_query(current_user: User, base: dict) -> dict:
    """Add an owner filter to ``base`` unless the caller is an admin.

    Admins (including the anonymous-admin used in single-user mode) wouldn't
    appear in the project's permissions list, so the explicit-membership
    check would reject them.
    """
    if current_user.is_admin:
        return base
    return {**base, "permissions.owners._id": current_user.id}


def _build_permission_pipeline(data_collection_id: PyObjectId, current_user: User) -> list[dict]:
    """Build MongoDB aggregation pipeline for permission checking.

    Admins (including the anonymous-admin used in single-user mode) skip the
    owner/viewer filter — they wouldn't appear in the project's permissions
    list, so the explicit-membership check would otherwise reject them.
    """
    match_clause: dict = {"workflows.data_collections._id": ObjectId(data_collection_id)}
    if not current_user.is_admin:
        match_clause["$or"] = [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {"permissions.viewers": "*"},
            {"is_public": True},
        ]
    return [
        {"$match": match_clause},
        {"$unwind": "$workflows"},
        {"$unwind": "$workflows.data_collections"},
        {"$match": {"workflows.data_collections._id": ObjectId(data_collection_id)}},
        {"$replaceRoot": {"newRoot": "$workflows.data_collections"}},
    ]


@deltatables_endpoint_router.get("/get/{data_collection_id}")
async def get_deltatable(
    data_collection_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Fetch a DeltaTableAggregated object by data collection ID.

    Args:
        data_collection_id: The data collection identifier.
        current_user: Authenticated or anonymous user.

    Returns:
        DeltaTableAggregated data with ObjectIds converted to strings.

    Raises:
        HTTPException: If data collection not found or access denied.
    """
    pipeline = _build_permission_pipeline(data_collection_id, current_user)
    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    deltatable_cursor = list(
        deltatables_collection.find({"data_collection_id": data_collection_id})
    )
    if not deltatable_cursor:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTableAggregated found for Data Collection ID {data_collection_id}.",
        )

    return convert_objectid_to_str(sanitize_for_json(deltatable_cursor[-1]))


@deltatables_endpoint_router.post("/batch/exists", deprecated=True)
async def batch_check_deltatables_exist(
    data_collection_ids: list[PyObjectId],
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Check existence of multiple deltatables in a single call.

    Deprecated: this batch helper served the old Dash design_draggable()
    flow and has no remaining callers. Scheduled for removal.

    This endpoint eliminates the N+1 query pattern in design_draggable()
    by allowing batch checking of deltatable existence.

    Data collections the caller cannot access are reported identically to
    nonexistent ones (``exists: False``) so the endpoint can't be used as an
    existence oracle or to leak ``delta_table_location`` metadata.

    Args:
        data_collection_ids: List of data collection IDs to check.
        current_user: Current authenticated user.

    Returns:
        Dict mapping data collection ID to existence status and location.
    """
    logger.warning("DEPRECATED endpoint deltatables/batch/exists called; scheduled for removal.")
    # Restrict to the DCs the caller is allowed to see. Build a single
    # permission $match across all requested ids (mirrors the per-id filter in
    # ``_build_permission_pipeline``) so inaccessible DCs never surface.
    object_ids = [ObjectId(dc_id) for dc_id in data_collection_ids]
    accessible_match: dict = {"workflows.data_collections._id": {"$in": object_ids}}
    if not current_user.is_admin:
        accessible_match["$or"] = [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {"permissions.viewers": "*"},
            {"is_public": True},
        ]
    accessible_pipeline = [
        {"$match": accessible_match},
        {"$unwind": "$workflows"},
        {"$unwind": "$workflows.data_collections"},
        {"$match": {"workflows.data_collections._id": {"$in": object_ids}}},
        {"$project": {"_id": "$workflows.data_collections._id"}},
    ]
    accessible_ids = {str(doc["_id"]) for doc in projects_collection.aggregate(accessible_pipeline)}

    deltatable_cursor = deltatables_collection.find(
        {"data_collection_id": {"$in": data_collection_ids}},
        {"data_collection_id": 1, "delta_table_location": 1},
    )

    found_deltatables = {
        str(dt["data_collection_id"]): dt.get("delta_table_location")
        for dt in deltatable_cursor
        if str(dt["data_collection_id"]) in accessible_ids
    }

    return {
        str(dc_id): {
            "exists": str(dc_id) in found_deltatables,
            "delta_table_location": found_deltatables.get(str(dc_id)),
        }
        for dc_id in data_collection_ids
    }


@deltatables_endpoint_router.get("/specs/{data_collection_id}")
async def specs(
    data_collection_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Fetch columns list and specs from data collection.

    Args:
        data_collection_id: The data collection identifier.
        current_user: Authenticated or anonymous user.

    Returns:
        Column specifications from the latest aggregation.

    Raises:
        HTTPException: If data collection not found or access denied.

    Note:
        Currently returns the last aggregation; versioning support planned.
    """
    pipeline = _build_permission_pipeline(data_collection_id, current_user)
    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    deltatable_cursor = list(
        deltatables_collection.find({"data_collection_id": data_collection_id})
    )
    if not deltatable_cursor:
        raise HTTPException(
            status_code=404, detail=f"No DeltaTable found for data collection {data_collection_id}"
        )

    deltatables = sanitize_for_json(deltatable_cursor[0])

    aggregation = deltatables.get("aggregation")
    if not aggregation:
        raise HTTPException(
            status_code=404,
            detail=f"No aggregation data found for data collection {data_collection_id}",
        )

    return convert_objectid_to_str(aggregation[-1]["aggregation_columns_specs"])


@deltatables_endpoint_router.get("/unique_values/{data_collection_id}")
async def get_unique_values(
    data_collection_id: PyObjectId,
    column: str,
    limit: int = 1000,
    filter_expr: str | None = None,
    current_user: str = Depends(get_user_or_anonymous),
):
    """Return the sorted unique values of ``column`` within a data collection.

    Backs the React viewer's MultiSelect options fetch. Mirrors the code path
    Dash uses via ``load_deltatable_lite(..., load_for_options=True)`` so both
    viewers see identical option lists.

    Args:
        data_collection_id: Target data collection.
        column: Column name whose unique values to return.
        limit: Max values to return (default 1000). Prevents unbounded payloads
            on high-cardinality columns; MultiSelect's UX caps at 100 anyway.
        filter_expr: Optional Polars filter expression (string) applied before
            collecting unique values. Validated through the safe-eval pipeline
            in ``depictio.models.components.filter_expr``.
        current_user: Authenticated or anonymous user (permission-checked).

    Returns:
        ``{"column": str, "values": list[str]}`` — strings for MultiSelect UI.

    Raises:
        HTTPException: 404 if DC not found / not accessible, 500 on read error.
    """
    # Find the project that owns this data collection. Doing a full MongoDB
    # permission filter via _build_permission_pipeline rejects the anonymous
    # admin user (no explicit owner entry) — use the same admin-aware
    # check_project_permission as /dashboards/get/{id}.
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    project = projects_collection.find_one(
        {"workflows.data_collections._id": ObjectId(data_collection_id)},
        {"_id": 1},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Data collection not found.")

    if not check_project_permission(project["_id"], current_user, "viewer"):  # type: ignore[arg-type]
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this data collection.",
        )

    # MultiQC DCs have no Delta table — a sample filter bound to one sources its
    # options from the ingested sample list instead, so the MultiQC tab can carry
    # a working sample filter on every route (the metadata / summary_metrics DCs
    # that normally back it may be pruned). Canonical sample IDs are returned;
    # `_resolve_multiqc_sample_filter` expands them to the per-report variant
    # names when the filter is applied.
    # Resolve THIS data collection by _id (a nested positional projection returns
    # the whole workflow's data_collections array, so we must match explicitly —
    # grabbing [0] would misidentify every DC as the workflow's first one).
    dc_cfg = projects_collection.find_one(
        {"workflows.data_collections._id": ObjectId(data_collection_id)},
        {"workflows.data_collections._id": 1, "workflows.data_collections.config.type": 1},
    )
    dc_doc: dict = {}
    for _wf in (dc_cfg or {}).get("workflows", []):
        for _dc in _wf.get("data_collections", []):
            if str(_dc.get("_id")) == str(data_collection_id):
                dc_doc = _dc
                break
        if dc_doc:
            break
    if (dc_doc.get("config", {}).get("type") or "").lower() == "multiqc":
        from depictio.api.v1.db import multiqc_collection

        # multiqc_collection stores one document per report, each carrying only
        # its own report's samples. A multi-report DC therefore has N docs, so a
        # find_one() would surface just one arbitrary report's samples. Union
        # canonical_samples (fallback samples) across ALL report docs so the
        # filter dropdown reflects the aggregate — mirrors the all-docs
        # aggregation in _resolve_multiqc_sample_filter.
        union: set[str] = set()
        for rep in multiqc_collection.find(
            {
                "data_collection_id": {
                    "$in": [ObjectId(str(data_collection_id)), str(data_collection_id)]
                }
            },
            {"metadata.canonical_samples": 1, "metadata.samples": 1},
        ):
            md = rep.get("metadata") or {}
            for v in md.get("canonical_samples") or md.get("samples") or []:
                union.add(str(v))
        values_str = sorted(union)[:limit]
        return {"column": column, "values": values_str}

    deltatables_list = list(deltatables_collection.find({"data_collection_id": data_collection_id}))
    if not deltatables_list:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTable found for Data Collection ID {data_collection_id}.",
        )

    delta_table_location = deltatables_list[-1].get("delta_table_location")
    if not delta_table_location:
        raise HTTPException(
            status_code=404, detail="Delta table location not found in deltatable document."
        )

    # Cached option lists. ``unique()`` has to see every value and Polars can't
    # push ``limit`` through it, so this is a full column scan — repeated on every
    # mount of every MultiSelect, on every dashboard load, for a list that only
    # changes when the data does. The aggregation version salt is part of the key,
    # so an ingest invalidates it for free (same contract as the frame cache).
    from depictio.api.v1.deltatables_utils import _get_aggregation_version

    dc_id_str = str(data_collection_id)
    cache_key = (
        f"unique_values_{dc_id_str}_{column}_{limit}_"
        f"{filter_expr or 'nofilter'}_{_get_aggregation_version(dc_id_str)}"
    )
    try:
        from depictio.api.cache import get_cache

        cached = get_cache().get(cache_key)
        if cached is not None:
            logger.debug(f"unique_values: cache hit for {column} on {dc_id_str}")
            return {"column": column, "values": cached}
    except Exception as exc:  # the cache is an optimisation, never a dependency
        logger.debug(f"unique_values: cache read failed for {cache_key}: {exc}")

    try:
        lazy = pl.scan_delta(delta_table_location, storage_options=polars_s3_config)

        if filter_expr:
            from depictio.models.components.filter_expr import (
                build_filter_expr,
                validate_filter_expr,
            )

            try:
                validate_filter_expr(filter_expr)
                expr = build_filter_expr(filter_expr)
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid filter_expr: {exc}",
                )
            lazy = lazy.filter(expr)

        try:
            df = lazy.select(column).unique().limit(limit).collect()
        except pl.exceptions.ColumnNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"Column '{column}' not found in data collection {data_collection_id}.",
            )

        values = df[column].drop_nulls().to_list()
        # Stable ordering — MultiSelect UX expects sorted strings.
        values_str = sorted({str(v) for v in values})
        try:
            from depictio.api.cache import get_cache

            get_cache().set(cache_key, values_str)
        except Exception as exc:
            logger.debug(f"unique_values: cache write failed for {cache_key}: {exc}")
        return {"column": column, "values": values_str}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching unique values for column {column}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read unique values: {e}")


@deltatables_endpoint_router.get("/breakdown/{data_collection_id}")
async def get_breakdown(
    data_collection_id: PyObjectId,
    column: str,
    breakdown_col: str,
    aggregation: str = "count",
    top_n_count: int = 3,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Top-N breakdown of ``breakdown_col``, for the card builder's live preview.

    Returns the same ``__breakdown__`` payload ``bulk_compute_cards`` attaches to
    a saved card — same helper, same per-group aggregation, same evenness — so
    the preview shows the card's real categories and real distribution instead
    of guessing. The preview used to synthesise ``Bucket 1/2/3`` split evenly at
    33/33/34; the names and the shape were both invented, which made a correct
    builder look broken.

    Computed against the *unfiltered* table: the builder has no interactive
    filter state, and the saved card recomputes under whatever filters the
    dashboard carries.

    Args:
        data_collection_id: Target data collection.
        column: The card's hero column (decides the per-group reduction).
        breakdown_col: Categorical column to group by.
        aggregation: The card's hero aggregation (``count`` / ``nunique`` / ``sum``).
        top_n_count: How many groups to surface, clamped to 1..5 by the helper.
        current_user: Authenticated or anonymous user (permission-checked).

    Returns:
        ``{"column", "total", "top": [{name, count, percent}], "top_share",
        "unique_values", "breakdown_kind", "evenness"}``.

    Raises:
        HTTPException: 404 if the DC / delta table / column is missing, 403 if
        the user may not read it, 500 on a read error.
    """
    pipeline = _build_permission_pipeline(data_collection_id, current_user)
    if not list(projects_collection.aggregate(pipeline)):
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    deltatables_list = list(deltatables_collection.find({"data_collection_id": data_collection_id}))
    if not deltatables_list:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTable found for Data Collection ID {data_collection_id}.",
        )
    delta_table_location = deltatables_list[-1].get("delta_table_location")
    if not delta_table_location:
        raise HTTPException(
            status_code=404, detail="Delta table location not found in deltatable document."
        )

    # The builder re-requests this on every keystroke-ish config change (layout
    # switch, breakdown column, top-N). Salting on the aggregation version means
    # an ingest invalidates it for free, same contract as ``unique_values``.
    from depictio.api.v1.deltatables_utils import _get_aggregation_version

    dc_id_str = str(data_collection_id)
    cache_key = (
        f"breakdown_{dc_id_str}_{column}_{breakdown_col}_{aggregation}_{top_n_count}_"
        f"{_get_aggregation_version(dc_id_str)}"
    )
    try:
        from depictio.api.cache import get_cache

        cached = get_cache().get(cache_key)
        if cached is not None:
            return cached
    except Exception as exc:  # the cache is an optimisation, never a dependency
        logger.debug(f"breakdown: cache read failed for {cache_key}: {exc}")

    try:
        lazy = pl.scan_delta(delta_table_location, storage_options=polars_s3_config)
        # Project before grouping: a breakdown reads two columns, and on a wide
        # collection loading the rest is the whole cost of the request.
        wanted = list(dict.fromkeys([c for c in (breakdown_col, column) if c]))
        available = set(lazy.collect_schema().names())
        missing = [c for c in wanted if c not in available]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Column(s) {missing} not found in data collection {dc_id_str}.",
            )
        payload = compute_breakdown(
            lazy.select(wanted),
            column=column,
            breakdown_col=breakdown_col,
            aggregation=aggregation,
            top_n_count=top_n_count,
        )
        try:
            from depictio.api.cache import get_cache

            get_cache().set(cache_key, payload)
        except Exception as exc:
            logger.debug(f"breakdown: cache write failed for {cache_key}: {exc}")
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing breakdown on {breakdown_col!r} for {dc_id_str}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to compute breakdown: {e}")


@deltatables_endpoint_router.get("/shape/{data_collection_id}")
async def get_shape(
    data_collection_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Get shape information (number of rows and columns) for a data collection.

    Args:
        data_collection_id: The data collection identifier.
        current_user: Authenticated or anonymous user.

    Returns:
        Dictionary with num_rows and num_columns.

    Raises:
        HTTPException: If data collection not found or delta table read fails.
    """
    pipeline = _build_permission_pipeline(data_collection_id, current_user)
    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    deltatables_list = list(deltatables_collection.find({"data_collection_id": data_collection_id}))
    if not deltatables_list:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTable found for Data Collection ID {data_collection_id}.",
        )

    delta_table_location = deltatables_list[-1].get("delta_table_location")
    if not delta_table_location:
        raise HTTPException(
            status_code=404, detail="Delta table location not found in deltatable document."
        )

    try:
        df = pl.scan_delta(delta_table_location, storage_options=polars_s3_config).collect()
        num_rows, num_columns = df.shape
        return {"num_rows": num_rows, "num_columns": num_columns}
    except Exception as e:
        logger.error(f"Error reading delta table shape: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read delta table shape: {e}")


@deltatables_endpoint_router.get("/preview/{data_collection_id}")
async def get_preview(
    response: Response,
    data_collection_id: PyObjectId,
    limit: int = 100,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Return the first `limit` rows + column names for a data collection's
    delta table, for the React stepper data-source preview pane.

    Mirrors what the Dash stepper builds via
    ``load_deltatable_lite(..., limit_rows=100, load_for_preview=True)``.

    Heavy work (Polars scan + collect) runs on Celery when
    `settings.celery.offload_preview` is true (default).
    """
    pipeline = _build_permission_pipeline(data_collection_id, current_user)
    project_result = list(projects_collection.aggregate(pipeline))
    if not project_result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    deltatables_list = list(deltatables_collection.find({"data_collection_id": data_collection_id}))
    if not deltatables_list:
        raise HTTPException(
            status_code=404,
            detail=f"No DeltaTable found for Data Collection ID {data_collection_id}.",
        )

    delta_table_location = deltatables_list[-1].get("delta_table_location")
    if not delta_table_location:
        raise HTTPException(
            status_code=404, detail="Delta table location not found in deltatable document."
        )

    offload = settings.celery.offload_preview
    response.headers["X-Celery-Path"] = "offloaded" if offload else "inline"
    try:
        return await offload_or_run(
            preview_deltatable_task,
            ({"delta_table_location": delta_table_location, "limit": limit},),
            offload=offload,
            label=f"deltatable_preview dc={data_collection_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading delta table preview: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read delta table preview: {e}")


@deltatables_endpoint_router.delete("/delete/{deltatable_id}")
async def delete_deltatable(
    deltatable_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Delete a DeltaTableAggregated and its S3 objects.

    Args:
        deltatable_id: The deltatable identifier to delete.
        current_user: Authenticated user making the request.

    Returns:
        Success message on completion.

    Raises:
        HTTPException: If deltatable not found or S3 deletion fails.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not deltatable_id:
        raise HTTPException(status_code=400, detail="Data Collection ID is required")

    deltatable_oid = ObjectId(deltatable_id)

    deltatable = deltatables_collection.find_one({"_id": deltatable_oid})
    if not deltatable:
        raise HTTPException(
            status_code=404, detail=f"No deltatable with id {deltatable_oid} found."
        )

    data_collection_oid = ObjectId(deltatable["data_collection_id"])
    deltatable_location = deltatable["delta_table_location"].lstrip("/")
    bucket_name = settings.minio.bucket

    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.minio.endpoint,  # type: ignore[possibly-unbound-attribute]
        aws_access_key_id=settings.minio.access_key,  # type: ignore[possibly-unbound-attribute]
        aws_secret_access_key=settings.minio.secret_key,  # type: ignore[possibly-unbound-attribute]
        region_name="us-east-1",
    )

    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=deltatable_location)
        if "Contents" in response:
            objects_to_delete = [{"Key": obj["Key"]} for obj in response["Contents"]]
            s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})
    except ClientError as e:
        logger.error(f"Failed to delete S3 objects: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete S3 objects.")

    if not projects_collection.find_one(
        _owned_or_admin_query(current_user, {"data_collections._id": data_collection_oid})
    ):
        raise HTTPException(
            status_code=404,
            detail=f"No workflows with id {deltatable_oid} found for the current user.",
        )

    deltatables_collection.delete_one({"_id": deltatable_oid})
    return {"message": f"DeltaTableAggregated with id {deltatable_oid} deleted successfully."}
