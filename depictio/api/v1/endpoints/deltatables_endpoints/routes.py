"""
DeltaTables API endpoints for managing data collection delta tables.

Provides CRUD operations for DeltaTableAggregated objects including
upsert, fetch, batch existence checks, and shape queries.
"""

import asyncio
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
from depictio.api.v1.endpoints.deltatables_endpoints.utils import (
    delta_identity_hash,
    new_aggregation_hash,
    precompute_columns_specs,
    previous_column_types,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.s3 import polars_s3_config
from depictio.api.v1.services.card_breakdown import compute_breakdown
from depictio.api.v1.services.card_metrics import NUMERIC_LAYOUTS, numeric_layout_payload
from depictio.api.v1.utils import agg_functions
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.deltatables import (
    Aggregation,
    DeltaTableAggregated,
    UpsertDeltaTableAggregated,
)
from depictio.models.models.users import User

deltatables_endpoint_router = APIRouter()


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


def _upsert_hash(delta_table_location: str, is_multiqc: bool) -> str:
    """The aggregation hash for this write. Reads the Delta log, never the rows."""
    if is_multiqc:
        # MultiQC is stored as raw parquet, not a Delta table: no log to read.
        return new_aggregation_hash(delta_table_location)
    return new_aggregation_hash(
        delta_table_location, delta_identity_hash(delta_table_location, polars_s3_config)
    )


def _compute_upsert_artifacts(
    delta_table_location: str,
    dc_data: dict,
    is_multiqc: bool,
    previous_types: dict[str, str] | None = None,
) -> tuple[str, list]:
    """Aggregation hash and column specs for a data collection's table.

    The scan stays lazy: ``precompute_columns_specs`` only needs per-column
    aggregations, and materialising a multi-GB data collection here is what
    used to get the worker OOM-killed. It still makes a few passes over the
    table, so it lives outside the request coroutine and is called via
    ``asyncio.to_thread``.
    """
    final_hash = _upsert_hash(delta_table_location, is_multiqc)
    if is_multiqc:
        # Column specs are not computed for MultiQC (empty list required by Pydantic).
        return final_hash, []

    lf = pl.scan_delta(delta_table_location, storage_options=polars_s3_config)
    return final_hash, precompute_columns_specs(
        lf, agg_functions, dc_data, previous_types=previous_types
    )


def _should_offload(requested: bool, is_multiqc: bool) -> bool:
    """Whether to defer the expensive half of an upsert to a Celery task.

    Three conditions, all required. The client asks (``async_mode``), the
    deployment allows it, and the work is actually worth offloading — MultiQC
    collections are stored as parquet with no Delta table to read, so there is
    nothing expensive to defer.

    ``jobs.enabled`` is part of the gate rather than an independent switch: the
    job document *is* the client's only handle on deferred work, so offloading
    without it would hand back a job_id pointing at nothing.
    """
    if not requested or is_multiqc:
        return False
    if not settings.ingestion.async_deltatable_upsert:
        return False
    if not settings.jobs.enabled:
        logger.warning(
            "upsert_deltatable: async_mode requested and ingestion offloading is on, "
            "but jobs are disabled (DEPICTIO_JOBS_ENABLED) — running synchronously."
        )
        return False
    return True


def _dispatch_finalize(
    *,
    dc_id: str,
    delta_table_location: str,
    version: int,
    user_id: str,
    project_id: str | None,
    ingestion_run_id: str | None,
) -> str | None:
    """Create the job record and enqueue its task. Returns the job_id.

    Returns ``None`` if the job could not be created, which the caller must
    treat as "this upsert is now incomplete" — the aggregation entry is already
    stored with ``aggregation_status="pending"`` and nothing else will finish
    it.
    """
    import uuid

    from depictio.api.v1.ingestion_tasks import finalize_deltatable_upsert
    from depictio.api.v1.jobs import store as jobs_store
    from depictio.models.models.jobs import Job

    idempotency_key = jobs_store.build_idempotency_key(
        ingestion_run_id or "-", dc_id, delta_table_location, version, "deltatable.upsert"
    )
    job = Job(
        job_id=uuid.uuid4().hex,
        kind="deltatable.upsert",
        user_id=user_id,
        project_id=project_id,
        data_collection_id=dc_id,
        ingestion_run_id=ingestion_run_id,
        idempotency_key=idempotency_key,
    )
    stored, created = jobs_store.create_job(job)
    if not created:
        # An identical submission is already in flight (CLI retry after a
        # dropped response, or two watchers racing). Hand back the existing
        # job so the client attaches to it instead of queueing a second full
        # table read.
        logger.info(
            f"upsert_deltatable: reusing in-flight job {stored.job_id} for dc={dc_id} v{version}"
        )
        return stored.job_id

    task = finalize_deltatable_upsert.apply_async(
        args=[
            {
                "job_id": stored.job_id,
                "data_collection_id": dc_id,
                "delta_table_location": delta_table_location,
                "aggregation_version": version,
                "ingestion_run_id": ingestion_run_id,
            }
        ],
        queue=settings.celery.ingestion_queue,
    )
    jobs_store.attach_task(stored.job_id, task.id)
    return stored.job_id


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
    previous_types = previous_column_types(query_dt)

    # MultiQC has no Delta table to read, so offloading it would cost a broker
    # round-trip to save nothing: it always runs inline.
    offload = _should_offload(payload.async_mode, is_multiqc)

    if offload:
        # Record the aggregation now with no column specs; a Celery task fills
        # them in. The hash is final already: it only reads the Delta log, so it
        # is cheap enough to compute here, and a provisional value that the task
        # later replaced would read as a data change to anything comparing
        # hashes (comment staleness, cache salts). The version bump below must
        # stay synchronous regardless: it is the salt for every DataFrame cache
        # key (`_generate_cache_keys`), so deferring it would let readers keep
        # serving pre-write data under an unchanged key.
        final_hash = await asyncio.to_thread(_upsert_hash, payload.delta_table_location, is_multiqc)
        results = []
    else:
        # Off the event loop: the column specs scan the whole Delta table. Run
        # inline, that pins the uvicorn worker for the duration, long enough on
        # a large table to blow gunicorn's --timeout and kill the worker
        # outright, which the CLI sees as a dropped connection rather than a
        # clean 504.
        final_hash, results = await asyncio.to_thread(
            _compute_upsert_artifacts,
            payload.delta_table_location,
            dc_data,
            is_multiqc,
            previous_types,
        )

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
            # Delta provenance as reported by the writer. An older CLI sends
            # none of these and they stay None, which is the honest answer for
            # a write whose commit we never observed.
            delta_version=payload.delta_version,
            delta_commit_timestamp=payload.delta_commit_timestamp,
            write_mode=payload.write_mode,
            rows_total=payload.rows_total,
            rows_added=payload.rows_added,
            files_added=payload.files_added,
            aggregation_status="pending" if offload else "complete",
            run_tags=payload.run_tags,
            ingestion_run_id=payload.ingestion_run_id,
            trigger=payload.trigger,
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

    if offload:
        job_id = await asyncio.to_thread(
            _dispatch_finalize,
            dc_id=str(data_collection_oid),
            delta_table_location=str(payload.delta_table_location),
            version=version,
            user_id=str(current_user.id),
            project_id=str(project.get("_id")) if project.get("_id") else None,
            ingestion_run_id=payload.ingestion_run_id,
        )
        if job_id:
            # 200, not 202. The current CLI checks `status_code != 200` and
            # then `result == "error"`; a 202 leaking into any un-updated code
            # path would be read as a failure. 202 is the right code and is
            # documented as a future api_version 2 change — not one to make
            # while old clients are still in the field.
            return {
                "message": "DeltaTableAggregated upserted; finalization offloaded",
                "result": "success",
                "job_id": job_id,
                "aggregation_version": version,
            }
        # Job creation failed, so nothing will ever compute the column specs.
        # Fall through to the synchronous path rather than leave the
        # aggregation stuck at "pending" forever.
        logger.warning(
            "upsert_deltatable: could not create a job — finalizing synchronously instead"
        )
        # The hash recorded above is already final, so only the specs change.
        _, results = await asyncio.to_thread(
            _compute_upsert_artifacts,
            payload.delta_table_location,
            dc_data,
            is_multiqc,
            previous_types,
        )
        deltatables_collection.update_one(
            {"data_collection_id": data_collection_oid},
            {
                "$set": {
                    "aggregation.$[a].aggregation_columns_specs": [
                        r.mongo() if hasattr(r, "mongo") else r for r in results
                    ],
                    "aggregation.$[a].aggregation_status": "complete",
                }
            },
            array_filters=[{"a.aggregation_version": version}],
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
    # Also off the event loop: _build_event_payload reads the table and its
    # previous Delta version to compute the row delta, so it is as heavy as the
    # upsert artifacts it follows.
    payload = await asyncio.to_thread(_build_event_payload, dc_id, "upsert")

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


def _int_metric(metrics: dict, *names: str) -> int | None:
    """The first of ``names`` present in a commit's ``operationMetrics``, as an int.

    Several names per metric because deltalake 0.24 emits snake_case and 1.x
    camelCase.
    """
    for name in names:
        if name in metrics:
            try:
                return int(metrics[name])
            except (TypeError, ValueError):
                return None
    return None


def _read_delta_history(delta_location: str, limit: int) -> list[dict]:
    """Delta commit history for a table. Synchronous; call via to_thread.

    Reads only the last ``limit`` ``_delta_log`` commits — a handful of small
    objects, not the table itself — which is why this stays a plain endpoint
    rather than going through the job protocol.
    """
    from deltalake import DeltaTable

    table = DeltaTable(delta_location, storage_options=polars_s3_config)
    entries = []
    for entry in table.history(limit):
        metrics = entry.get("operationMetrics") or {}
        raw_timestamp = entry.get("timestamp")
        entries.append(
            {
                "version": entry.get("version"),
                "timestamp": (
                    datetime.fromtimestamp(raw_timestamp / 1000).isoformat()
                    if isinstance(raw_timestamp, (int, float))
                    else None
                ),
                "operation": entry.get("operation"),
                "rows_added": _int_metric(metrics, "num_added_rows", "numOutputRows"),
                "files_added": _int_metric(metrics, "num_added_files", "numAddedFiles", "numFiles"),
                "files_removed": _int_metric(metrics, "num_removed_files", "numRemovedFiles"),
                # Custom commit metadata is flattened into the entry by delta-rs.
                "metadata": {
                    key: str(value) for key, value in entry.items() if key.startswith("depictio.")
                },
            }
        )
    return entries


def _caller_is_project_operator(data_collection_id: PyObjectId, current_user: User) -> bool:
    """True when the caller owns or edits the project holding this data collection.

    Delta history names whoever ran each ingestion. Read access is a weaker bar
    than that: ``is_public: True`` admits any authenticated *or* anonymous user,
    so returning emails to everyone who may read the table would turn publishing
    a project into publishing a roster of the people who work on it. Same
    reasoning, and same owners/editors bar, as ``_redact_run`` in the projects
    router.
    """
    if getattr(current_user, "is_admin", False):
        return True
    project = projects_collection.find_one(
        {"workflows.data_collections._id": ObjectId(data_collection_id)},
        {"permissions": 1},
    )
    permissions = (project or {}).get("permissions") or {}
    user_id = str(current_user.id)
    return any(
        str(entry.get("_id")) == user_id
        for group in ("owners", "editors")
        for entry in (permissions.get(group) or [])
    )


@deltatables_endpoint_router.get("/history/{data_collection_id}")
async def get_delta_history(
    data_collection_id: PyObjectId,
    limit: int = 20,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Commit history of a data collection's Delta table, newest first.

    Merges what Delta itself records (version, timestamp, operation, row and
    file counts, plus depictio's own commit metadata) with what Mongo knows
    about each aggregation (who ran it). Degrades to the Mongo-only view when
    the object store is unreachable, so a transient S3 problem shows a partial
    history rather than an error page.

    Who ran an ingestion is shown to owners, editors and admins only — see
    ``_caller_is_project_operator``.
    """
    limit = max(1, min(limit, 200))

    pipeline = _build_permission_pipeline(data_collection_id, current_user)
    if not list(projects_collection.aggregate(pipeline)):
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    show_operator = _caller_is_project_operator(data_collection_id, current_user)

    record = deltatables_collection.find_one({"data_collection_id": data_collection_id})
    if not record:
        raise HTTPException(
            status_code=404, detail=f"No DeltaTable found for data collection {data_collection_id}"
        )

    delta_location = record.get("delta_table_location", "")

    # Mongo side: one entry per aggregation, keyed by the Delta version it wrote
    # when the writer reported one. Older aggregations have no delta_version and
    # simply do not join.
    by_version: dict[int, dict] = {}
    mongo_only: list[dict] = []
    for aggregation in record.get("aggregation", []) or []:
        entry = {
            "aggregation_version": aggregation.get("aggregation_version"),
            "aggregation_time": (
                aggregation["aggregation_time"].isoformat()
                if isinstance(aggregation.get("aggregation_time"), datetime)
                else aggregation.get("aggregation_time")
            ),
            "by_email": (
                (aggregation.get("aggregation_by") or {}).get("email") if show_operator else None
            ),
            "run_id": aggregation.get("ingestion_run_id"),
            "trigger": aggregation.get("trigger"),
            "write_mode": aggregation.get("write_mode"),
            "rows_total": aggregation.get("rows_total"),
        }
        delta_version = aggregation.get("delta_version")
        if delta_version is None:
            mongo_only.append({**entry, "origin": "mongo"})
        else:
            by_version[int(delta_version)] = entry

    degraded = False
    delta_entries: list[dict] = []
    try:
        delta_entries = await asyncio.to_thread(_read_delta_history, delta_location, limit)
    except Exception as exc:  # noqa: BLE001 - a missing object store is not a 500
        logger.warning(f"Delta history unavailable for {delta_location}: {exc}")
        degraded = True

    merged = []
    for entry in delta_entries:
        version = entry.get("version")
        mongo_entry = by_version.pop(int(version), None) if version is not None else None
        if not show_operator:
            # The writer stamps depictio.user_email into the commit metadata, so
            # dropping it from the Mongo side alone would not hide it.
            entry["metadata"] = {
                key: value
                for key, value in (entry.get("metadata") or {}).items()
                if key != "depictio.user_email"
            }
        merged.append(
            {**entry, **(mongo_entry or {}), "origin": "both" if mongo_entry else "delta"}
        )

    # Aggregations whose Delta commit fell outside the requested window, plus
    # anything written before delta_version was recorded.
    merged.extend(mongo_only)
    merged.extend({**entry, "origin": "mongo"} for entry in by_version.values())

    return {
        "delta_table_location": delta_location,
        "current_version": delta_entries[0]["version"] if delta_entries else None,
        "degraded": degraded,
        "versions": merged[:limit],
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
    agg_version = _get_aggregation_version(dc_id_str)
    cache_key = (
        f"unique_values_{dc_id_str}_{column}_{limit}_{filter_expr or 'nofilter'}_{agg_version}"
    )
    # Negative entry: "this DC (at this version) has no such column". Keyed
    # without limit/filter because absence does not depend on them. Without it
    # every probe of a column the DC lacks re-opened the Delta log on S3.
    missing_key = f"unique_values_missing_{dc_id_str}_{column}_{agg_version}"
    column_missing_exc = HTTPException(
        status_code=404,
        detail=f"Column '{column}' not found in data collection {data_collection_id}.",
    )
    try:
        from depictio.api.cache import get_cache

        if get_cache().get(missing_key) is not None:
            logger.debug(f"unique_values: cached miss for {column} on {dc_id_str}")
            raise column_missing_exc
        cached = get_cache().get(cache_key)
        if cached is not None:
            logger.debug(f"unique_values: cache hit for {column} on {dc_id_str}")
            return {"column": column, "values": cached}
    except HTTPException:
        raise
    except Exception as exc:  # the cache is an optimisation, never a dependency
        logger.debug(f"unique_values: cache read failed for {cache_key}: {exc}")

    def _remember_missing() -> None:
        try:
            from depictio.api.cache import get_cache

            get_cache().set(missing_key, True)
        except Exception as exc:
            logger.debug(f"unique_values: cache write failed for {missing_key}: {exc}")

    try:
        lazy = pl.scan_delta(delta_table_location, storage_options=polars_s3_config)
        # Schema comes from the Delta log alone: answer "no such column" before
        # any data scan, and cache it.
        if column not in lazy.collect_schema().names():
            _remember_missing()
            raise column_missing_exc

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
            raise column_missing_exc

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


def _resolve_delta_location(data_collection_id: PyObjectId, current_user: User) -> str:
    """Permission-check ``data_collection_id`` and return its Delta location.

    The shared opening of every read endpoint below: aggregate the permission
    pipeline, find the DC's deltatable document, pull the table location.
    Raises the same 404s those endpoints raised inline.
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
    return delta_table_location


def _breakdown_response(
    data_collection_id: PyObjectId,
    column: str,
    breakdown_col: str,
    aggregation: str,
    top_n_count: int,
    filter_metadata: list[dict],
    current_user: User,
):
    """Shared body of the breakdown GET (unfiltered) and POST (filtered) routes."""
    delta_table_location = _resolve_delta_location(data_collection_id, current_user)

    # The builder re-requests this on every keystroke-ish config change (layout
    # switch, breakdown column, top-N). Salting on the aggregation version means
    # an ingest invalidates it for free, same contract as ``unique_values``.
    # Filtered requests skip the cache entirely: the key doesn't encode filter
    # state, and salting it would fill the cache with transient combinations.
    from depictio.api.v1.deltatables_utils import _get_aggregation_version, apply_filters_to_scan

    dc_id_str = str(data_collection_id)
    cache_key = (
        f"breakdown_{dc_id_str}_{column}_{breakdown_col}_{aggregation}_{top_n_count}_"
        f"{_get_aggregation_version(dc_id_str)}"
    )
    if not filter_metadata:
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
        # collection loading the rest is the whole cost of the request. Filter
        # columns must ride along in the projection or the filters would be
        # applied to a frame that no longer contains them.
        filter_cols = [
            c
            for f in filter_metadata
            if (c := f.get("column_name") or (f.get("metadata") or {}).get("column_name"))
        ]
        wanted = list(dict.fromkeys([c for c in (breakdown_col, column) if c]))
        available = set(lazy.collect_schema().names())
        missing = [c for c in wanted if c not in available]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Column(s) {missing} not found in data collection {dc_id_str}.",
            )
        projected = list(dict.fromkeys(wanted + [c for c in filter_cols if c in available]))
        payload = compute_breakdown(
            apply_filters_to_scan(lazy.select(projected), filter_metadata).select(wanted),
            column=column,
            breakdown_col=breakdown_col,
            aggregation=aggregation,
            top_n_count=top_n_count,
        )
        if not filter_metadata:
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

    Computed against the *unfiltered* table. When the builder carries active
    dashboard filters it uses the POST variant below instead, so the preview
    matches what the saved card will show under those filters.

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
    return _breakdown_response(
        data_collection_id,
        column,
        breakdown_col,
        aggregation,
        top_n_count,
        filter_metadata=[],
        current_user=current_user,
    )


@deltatables_endpoint_router.post("/breakdown/{data_collection_id}")
async def get_breakdown_filtered(
    data_collection_id: PyObjectId,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Filtered flavour of the breakdown preview.

    Body: ``{"column", "breakdown_col", "aggregation", "top_n_count",
    "filters": [InteractiveFilter, ...]}``. Same payload as the GET, computed
    under the dashboard's active filters so the card builder previews the
    distribution the saved card will actually show (#329). Filters whose
    column isn't in this DC are skipped (see ``apply_filters_to_scan``);
    filtered responses bypass the breakdown cache.
    """
    from depictio.api.v1.deltatables_utils import clean_filter_payload
    from depictio.api.v1.region_scope import scope_region_filters

    column = str(request.get("column") or "")
    breakdown_col = str(request.get("breakdown_col") or "")
    if not column or not breakdown_col:
        raise HTTPException(status_code=400, detail="column and breakdown_col are required.")
    return _breakdown_response(
        data_collection_id,
        column,
        breakdown_col,
        str(request.get("aggregation") or "count"),
        int(request.get("top_n_count") or 3),
        # Same region scope as the saved card (``bulk_compute_cards``): a
        # locus navigator's region reaches it only with ``follow_region_filter``.
        filter_metadata=clean_filter_payload(
            scope_region_filters(request.get("filters") or [], "card", request)
        ),
        current_user=current_user,
    )


@deltatables_endpoint_router.post("/card_metric/{data_collection_id}")
async def get_card_metric(
    data_collection_id: PyObjectId,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Payload for a card's numeric / QC secondary layout, for the live preview.

    Runs the same dispatcher ``bulk_compute_cards`` runs for a saved card, so
    the builder shows the values the dashboard will show. POST rather than GET
    because ``attrition`` carries an ordered column list, which does not belong
    in a query string.

    Body: ``{"layout": ..., "column": ..., ...card config fields...}`` — the
    same field names the card metadata uses (``threshold_value``,
    ``threshold_direction``, ``threshold_warn``, ``attrition_cols``,
    ``aggregation``).

    Returns the layout's payload, or ``null`` when the config is incomplete or
    the data cannot support it (a constant column has no histogram). The
    builder then renders no strip rather than a misleading one.

    ``filters`` (optional, ``InteractiveFilter`` list) narrows the frame first,
    so the builder can preview the strip under the dashboard's active filters
    (#329). ``layout: "hero"`` is a preview-only pseudo-layout returning
    ``{"value": <scalar>}`` — the card's hero aggregation computed on the
    (possibly filtered) frame, replacing the static precomputed spec value the
    builder shows when no filters are active.
    """
    from depictio.api.v1.deltatables_utils import apply_filters_to_scan, clean_filter_payload
    from depictio.api.v1.services.card_metrics import hero_value

    layout = str(request.get("layout") or "")
    column = str(request.get("column") or "")
    if (layout not in NUMERIC_LAYOUTS and layout != "hero") or not column:
        raise HTTPException(
            status_code=400,
            detail=f"layout must be 'hero' or one of {NUMERIC_LAYOUTS} and column is required.",
        )

    from depictio.api.v1.region_scope import scope_region_filters

    delta_table_location = _resolve_delta_location(data_collection_id, current_user)
    # Same region scope as the saved card (``bulk_compute_cards``).
    filter_metadata = clean_filter_payload(
        scope_region_filters(request.get("filters") or [], "card", request)
    )

    try:
        lazy = pl.scan_delta(delta_table_location, storage_options=polars_s3_config)
        # Project to the columns this layout reads. ``attrition`` walks a list
        # of stage columns and ``trend`` needs its axis alongside the hero
        # column; the rest read the hero column alone. Filter columns must ride
        # along or the filters would target a frame that no longer has them.
        wanted = [
            column,
            *[str(c) for c in (request.get("attrition_cols") or []) if c],
            *([str(request["trend_col"])] if request.get("trend_col") else []),
        ]
        available = set(lazy.collect_schema().names())
        wanted = list(dict.fromkeys([c for c in wanted if c in available]))
        if not wanted:
            raise HTTPException(
                status_code=404,
                detail=f"Column {column!r} not found in data collection {data_collection_id}.",
            )
        filter_cols = [
            c
            for f in filter_metadata
            if (c := f.get("column_name") or (f.get("metadata") or {}).get("column_name"))
            and c in available
        ]
        projected = list(dict.fromkeys(wanted + filter_cols))
        frame = apply_filters_to_scan(lazy.select(projected), filter_metadata).select(wanted)
        if layout == "hero":
            return {"value": hero_value(frame, column, str(request.get("aggregation") or ""))}
        return numeric_layout_payload(frame, request, column, layout)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing {layout} on {column!r}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to compute {layout}: {e}")


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
    version: int | None = None,
    current_user: User = Depends(get_user_or_anonymous),
):
    """
    Return the first `limit` rows + column names for a data collection's
    delta table, for the React stepper data-source preview pane.

    Mirrors what the Dash stepper builds via
    ``load_deltatable_lite(..., limit_rows=100, load_for_preview=True)``.

    Heavy work (Polars scan + collect) runs on Celery when
    `settings.celery.offload_preview` is true (default).

    ``version`` reads an older Delta commit instead of the current table. Safe
    to expose here specifically because this path scans the table directly
    rather than going through ``load_deltatable_lite``: that function's cache is
    salted with ``aggregation_version`` only, so a historical read served
    through it would be stored under the *live* key and then handed to callers
    who asked for current data. Do not wire time travel into any endpoint that
    reads through the cache without salting the key with the version too.
    """
    delta_table_location = _resolve_delta_location(data_collection_id, current_user)

    offload = settings.celery.offload_preview
    response.headers["X-Celery-Path"] = "offloaded" if offload else "inline"
    try:
        return await offload_or_run(
            preview_deltatable_task,
            (
                {
                    "delta_table_location": delta_table_location,
                    "limit": limit,
                    "version": version,
                },
            ),
            offload=offload,
            label=f"deltatable_preview dc={data_collection_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading delta table preview: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read delta table preview: {e}")


@deltatables_endpoint_router.post("/preview/{data_collection_id}")
async def get_preview_filtered(
    response: Response,
    data_collection_id: PyObjectId,
    request: dict,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Filtered flavour of the preview above, for the component builder.

    Body: ``{"limit": int = 100, "filters": [InteractiveFilter, ...]}``. The
    rows AND ``total_rows`` reflect the filtered frame, so the builder's
    "Showing X of N rows" matches what the dashboard's components show under
    the same filters (#329). Filters whose column isn't in this DC are skipped
    (cross-DC filters can't be link-resolved without dashboard context — see
    ``apply_filters_to_scan``). The GET stays for unfiltered callers.
    """
    from depictio.api.v1.deltatables_utils import clean_filter_payload

    delta_table_location = _resolve_delta_location(data_collection_id, current_user)
    filter_metadata = clean_filter_payload(request.get("filters"))
    limit = int(request.get("limit") or 100)

    offload = settings.celery.offload_preview
    response.headers["X-Celery-Path"] = "offloaded" if offload else "inline"
    try:
        return await offload_or_run(
            preview_deltatable_task,
            (
                {
                    "delta_table_location": delta_table_location,
                    "limit": limit,
                    "filter_metadata": filter_metadata,
                },
            ),
            offload=offload,
            label=f"deltatable_preview dc={data_collection_id} filters={len(filter_metadata)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading filtered delta table preview: {e}")
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
    bucket_name = settings.s3.bucket

    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.s3.endpoint,  # type: ignore[possibly-unbound-attribute]
        aws_access_key_id=settings.s3.access_key,  # type: ignore[possibly-unbound-attribute]
        aws_secret_access_key=settings.s3.secret_key,  # type: ignore[possibly-unbound-attribute]
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
