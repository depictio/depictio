"""Celery tasks for offloaded ingestion work.

Separate module from ``celery_tasks.py`` so the ingestion worker's task set is
legible at a glance and can be routed to its own queue without pattern-matching
task names.

The one task here finishes what ``POST /deltatables/upsert`` deliberately left
undone: reading the freshly written Delta table to compute its column specs and
content hash. That read is the whole reason the endpoint used to time out.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from bson import ObjectId

from depictio.api.celery_app import celery_app
from depictio.api.v1.configs.logging_init import logger


@celery_app.task(
    bind=True,
    name="depictio.deltatable.finalize_upsert",
    soft_time_limit=1800,
    time_limit=2100,
    # acks_late + reject_on_worker_lost means a task whose worker dies is
    # redelivered rather than silently lost. Safe here *only* because every
    # write below is an idempotent patch of one identified aggregation entry —
    # see the array_filters update. Anything that appended instead of patching
    # would corrupt the aggregation history on redelivery.
    acks_late=True,
    reject_on_worker_lost=True,
)
def finalize_deltatable_upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Compute column specs + content hash for an already-recorded aggregation.

    Expects::

        {"job_id", "data_collection_id", "delta_table_location",
         "aggregation_version", "ingestion_run_id"}

    The aggregation entry already exists in Mongo with empty specs and
    ``aggregation_status="pending"``; this fills it in and flips it to
    ``complete``. It never appends — the entry is located by
    ``aggregation_version``, which the endpoint assigned synchronously.
    """
    import polars as pl

    from depictio.api.v1.db import deltatables_collection, projects_collection
    from depictio.api.v1.endpoints.deltatables_endpoints.utils import precompute_columns_specs
    from depictio.api.v1.jobs import store as jobs_store
    from depictio.api.v1.s3 import polars_s3_config
    from depictio.api.v1.utils import agg_functions

    job_id = payload["job_id"]
    dc_id = payload["data_collection_id"]
    location = payload["delta_table_location"]
    version = payload["aggregation_version"]
    dc_oid = ObjectId(dc_id)

    try:
        jobs_store.mark_job_running(job_id, step="read_delta", detail=f"Reading {location}")

        project = projects_collection.find_one({"workflows.data_collections._id": dc_oid})
        dc_data = None
        if project:
            for workflow in project.get("workflows", []):
                dc_data = next(
                    (dc for dc in workflow.get("data_collections", []) if str(dc["_id"]) == dc_id),
                    None,
                )
                if dc_data:
                    break
        if dc_data is None:
            raise ValueError(f"Data collection {dc_id} no longer exists")

        df = pl.read_delta(location, storage_options=polars_s3_config)

        jobs_store.update_job_progress(job_id, step="column_specs", detail="Profiling columns")
        specs = precompute_columns_specs(df, agg_functions, dc_data)

        jobs_store.update_job_progress(job_id, step="hash_rows", detail="Hashing rows")
        hash_bytes = df.hash_rows(seed=0).to_numpy().tobytes()
        hash_df = hashlib.sha256(hash_bytes).hexdigest()
        final_hash = hashlib.sha256(f"{location}{datetime.now()}{hash_df}".encode()).hexdigest()

        # Patch exactly the entry this job owns. Not a whole-array rewrite: a
        # concurrent upsert on the same DC may have appended version+1 while we
        # were reading, and rewriting the array would erase it.
        result = deltatables_collection.update_one(
            {"data_collection_id": dc_oid},
            {
                "$set": {
                    "aggregation.$[a].aggregation_columns_specs": [
                        spec.mongo() if hasattr(spec, "mongo") else spec for spec in specs
                    ],
                    "aggregation.$[a].aggregation_hash": final_hash,
                    "aggregation.$[a].aggregation_status": "complete",
                }
            },
            array_filters=[{"a.aggregation_version": version}],
        )
        if not result.matched_count:
            raise ValueError(
                f"Aggregation v{version} for dc {dc_id} vanished before it could be finalized"
            )

        # Re-invalidate: the endpoint already invalidated once, but anything
        # rendered in the window between then and now cached a DataFrame built
        # against an aggregation with no column specs.
        try:
            from depictio.api.v1.deltatables_utils import invalidate_data_collection_cache

            invalidate_data_collection_cache(dc_id)
        except Exception as exc:
            logger.warning(f"finalize_upsert: cache invalidation failed for {dc_id}: {exc}")

        _publish_dc_update(dc_id)

        outcome = {
            "data_collection_id": dc_id,
            "aggregation_version": version,
            "aggregation_hash": final_hash,
            "columns": len(specs),
            "rows": df.height,
        }
        jobs_store.finish_job(job_id, status="success", result=outcome)
        logger.info(
            f"finalize_upsert: dc={dc_id} v{version} finalized "
            f"({len(specs)} columns, {df.height} rows)"
        )
        return outcome

    except Exception as exc:
        # The Job document is authoritative, so the failure is recorded here
        # rather than left to the task_failure signal — a signal that fires
        # after a worker crash may never run at all.
        logger.exception(f"finalize_upsert failed for job {job_id}: {exc}")
        try:
            jobs_store.finish_job(job_id, status="failed", error=str(exc))
        except Exception as inner:  # pragma: no cover - defensive
            logger.error(f"finalize_upsert: could not record failure for {job_id}: {inner}")
        raise


def _publish_dc_update(dc_id: str) -> None:
    """Notify dashboards that a DC finished aggregating.

    Published to a DC-scoped Redis channel rather than looped over locally
    known dashboards. The subscription registry is per-process, so a worker —
    which holds no WebSockets at all — has nobody to loop over. Publishing lets
    every API worker fan out to its own connections.

    Best-effort by design: a missed refresh notification is a stale panel until
    the next poll, not a failed ingestion.
    """
    try:
        from depictio.api.v1.services.events.publish import publish_dc_update

        publish_dc_update(dc_id, {"reason": "aggregation_finalized"})
    except Exception as exc:
        logger.warning(f"finalize_upsert: DC update publish failed for {dc_id}: {exc}")
