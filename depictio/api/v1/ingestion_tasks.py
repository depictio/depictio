"""Celery tasks for offloaded ingestion work.

Separate module from ``celery_tasks.py`` so the ingestion worker's task set is
legible at a glance and can be routed to its own queue without pattern-matching
task names.

Two tasks live here:

``finalize_upsert`` finishes what ``POST /deltatables/upsert`` deliberately
left undone: reading the freshly written Delta table to compute its column
specs and content hash. That read is the whole reason the endpoint used to
time out.

``run_project`` runs a whole project ingestion — scan, process, joins — on the
server, for the browser-triggered path. It only works where the API can see the
same filesystem the data sits on, which the endpoint checks before dispatching.
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


def build_server_cli_config(user_id: str):
    """Assemble a CLIConfig that acts as ``user_id`` against this same API.

    Server-side ingestion reuses the CLI's scan/process code unchanged, and that
    code talks to the API over HTTP — so it needs a token. The token is looked
    up here, at execution time, rather than carried in the Celery payload:
    broker messages are persisted and visible to anything with Redis access,
    and a bearer token has no business sitting in a queue.

    Raises when the user has no unexpired token, which is the honest outcome —
    running the ingestion as somebody else (an admin, say) would silently
    escalate whatever the requester could do.
    """
    from datetime import datetime as _datetime

    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.db import tokens_collection, users_collection
    from depictio.models.models.cli import CLIConfig

    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise ValueError(f"User {user_id} no longer exists")

    token = tokens_collection.find_one(
        {"user_id": ObjectId(user_id), "expire_datetime": {"$gt": _datetime.now()}},
        sort=[("expire_datetime", -1)],
    )
    if not token:
        raise ValueError(
            "No unexpired token for the requesting user — sign in again and retry the ingestion"
        )

    return CLIConfig.model_validate(
        {
            "user": {
                "id": str(user["_id"]),
                "email": user["email"],
                "is_admin": user.get("is_admin", False),
                "token": {
                    "user_id": token["user_id"],
                    "access_token": token["access_token"],
                    "refresh_token": token["refresh_token"],
                    "token_type": token.get("token_type", "bearer"),
                    "token_lifetime": token.get("token_lifetime", "short-lived"),
                    "expire_datetime": token["expire_datetime"],
                    "refresh_expire_datetime": token["refresh_expire_datetime"],
                    "name": token.get("name"),
                    "created_at": token.get("created_at"),
                },
            },
            "api_base_url": settings.fastapi.url,
            "s3_storage": settings.minio.model_dump(),
        }
    )


@celery_app.task(
    bind=True,
    name="depictio.ingestion.run_project",
    soft_time_limit=7200,
    time_limit=7500,
    # Deliberately NOT acks_late, unlike finalize_upsert. A redelivered project
    # ingestion would re-walk the filesystem and rewrite every Delta table —
    # expensive, and it would fabricate commits that no user asked for. A worker
    # that dies mid-ingestion instead leaves the job in `running` until its TTL
    # expires, which is visible and harmless.
    acks_late=False,
)
def run_project_ingestion(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Scan, process and join a whole project, server-side.

    Expects::

        {"job_id", "run_id", "project_id", "user_id", "overwrite"}

    This is the same pipeline ``depictio run`` executes, driven from the API
    instead of a workstation — the CLI's scan/process helpers are called
    directly rather than reimplemented, so the two paths cannot drift.

    Records an ``IngestionRun`` with ``trigger="ui"`` as it goes, so a
    browser-triggered ingestion appears in the same ledger and the same panes
    as every other run.
    """
    from depictio.api.v1.db import projects_collection
    from depictio.api.v1.jobs import store as jobs_store
    from depictio.api.v1.monitoring import store as monitoring_store
    from depictio.models.models.monitoring import IngestionRun
    from depictio.models.models.projects import Project, ProjectBeanie

    job_id = payload["job_id"]
    run_id = payload["run_id"]
    project_id = payload["project_id"]
    user_id = payload["user_id"]
    overwrite = bool(payload.get("overwrite", False))

    run_opened = False
    try:
        jobs_store.mark_job_running(job_id, step="prepare", detail="Loading project")

        project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project_doc:
            raise ValueError(f"Project {project_id} no longer exists")
        project = Project.model_validate(ProjectBeanie.from_mongo(project_doc).model_dump())

        cli_config = build_server_cli_config(user_id)

        monitoring_store.create_ingestion_run(
            IngestionRun(
                run_id=run_id,
                source="ui",
                cli_instance_label="Web UI",
                user_id=user_id,
                email=cli_config.user.email,
                project_id=project_id,
                project_name=project.name,
                command="run",
                trigger="ui",
                trigger_reason="Triggered from the project page",
            )
        )
        run_opened = True

        from depictio.cli.cli.utils.helpers import process_project_helper

        # Scan every workflow's data collections in one pass. Scanning DC by DC
        # would skip already-seen runs for every DC after the first — the same
        # trap the reference-dataset processor documents.
        for workflow in project.workflows:
            _step(run_id, "scan", "running", f"Scanning {workflow.name}")
            process_project_helper(
                CLI_config=cli_config,
                project_config=project,
                mode="scan",
                workflow_name=workflow.name,
                data_collection_tag=None,
            )
        _step(run_id, "scan", "success", f"{len(project.workflows)} workflow(s) scanned")

        processed = 0
        failed: list[str] = []
        total_dcs = sum(len(wf.data_collections) for wf in project.workflows)
        for workflow in project.workflows:
            for dc in workflow.data_collections:
                tag = dc.data_collection_tag
                _step(run_id, "process", "running", f"Processing {tag}")
                jobs_store.update_job_progress(
                    job_id,
                    step="process",
                    detail=tag,
                    progress={"current": processed + len(failed), "total": total_dcs},
                )
                try:
                    process_project_helper(
                        CLI_config=cli_config,
                        project_config=project,
                        mode="process",
                        workflow_name=workflow.name,
                        data_collection_tag=tag,
                        command_parameters={"overwrite": overwrite},
                    )
                    processed += 1
                except Exception as exc:  # noqa: BLE001 - one bad DC must not sink the run
                    logger.error(f"run_project: DC {tag} failed: {exc}")
                    failed.append(tag)
        _step(
            run_id,
            "process",
            "failed" if failed and not processed else ("partial" if failed else "success"),
            f"{processed} processed / {len(failed)} failed",
            counters={"data_collections": processed},
        )

        joins_detail = "no joins defined"
        if getattr(project, "joins", None):
            _step(run_id, "joins", "running", "Executing joins")
            from depictio.cli.cli.utils.joins import process_project_joins

            join_result = process_project_joins(
                project=project,
                CLI_config=cli_config,
                join_name=None,
                preview_only=False,
                overwrite=overwrite,
                auto_process_dependencies=True,
            )
            n_ok = len(join_result.get("processed") or [])
            n_err = len(join_result.get("errors") or [])
            joins_detail = f"{n_ok} processed / {n_err} failed"
            _step(run_id, "joins", "success" if not n_err else "partial", joins_detail)
        else:
            _step(run_id, "joins", "skipped", joins_detail)

        status = "failed" if failed and not processed else ("partial" if failed else "success")
        outcome = {
            "project_id": project_id,
            "run_id": run_id,
            "data_collections_processed": processed,
            "data_collections_failed": failed,
            "joins": joins_detail,
        }
        monitoring_store.finish_ingestion_run(
            run_id,
            status=status,
            error=f"{len(failed)} data collection(s) failed: {', '.join(failed)}"
            if failed
            else None,
        )
        jobs_store.finish_job(
            job_id,
            status="success" if status != "failed" else "failed",
            result=outcome,
            error=None if status != "failed" else f"All {len(failed)} data collections failed",
        )
        logger.info(f"run_project: {project_id} finished {status} ({processed} DCs)")
        return outcome

    except Exception as exc:
        logger.exception(f"run_project failed for job {job_id}: {exc}")
        if run_opened:
            try:
                monitoring_store.finish_ingestion_run(run_id, status="failed", error=str(exc))
            except Exception as inner:  # pragma: no cover - defensive
                logger.error(f"run_project: could not close run {run_id}: {inner}")
        try:
            jobs_store.finish_job(job_id, status="failed", error=str(exc))
        except Exception as inner:  # pragma: no cover - defensive
            logger.error(f"run_project: could not record failure for {job_id}: {inner}")
        raise


def _step(run_id: str, name: str, status: str, detail: str | None = None, **extra: Any) -> None:
    """Record one ingestion step, best-effort.

    Monitoring must never be able to fail an ingestion — the same rule the CLI's
    StepReporter follows.
    """
    from depictio.api.v1.monitoring import store as monitoring_store

    try:
        monitoring_store.upsert_ingestion_step(
            run_id,
            step={"name": name, "status": status, "detail": detail, **extra},
            current_step=name if status == "running" else None,
            # A terminal step must blank current_step explicitly, or the UI keeps
            # a spinner on a phase that already ended.
            clear_current_step=status != "running",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"run_project: step {name} not recorded: {exc}")


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
