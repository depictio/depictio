"""MongoDB persistence helpers for the monitoring ledger.

Thin CRUD over the ``task_events``, ``ingestion_runs`` and ``app_logs``
collections (handles defined in ``depictio/api/v1/db.py``). Mirrors the
plain-pymongo + dict-document style of ``multiqc_prerender_store``; no Beanie.

``ensure_monitoring_storage()`` is idempotent and called once at API startup to
create the task-events TTL index and the capped app-logs collection.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from pymongo import DESCENDING

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    app_logs_collection,
    cli_agents_collection,
    db,
    ingestion_runs_collection,
    task_events_collection,
)
from depictio.models.models.monitoring import (
    AppLogRecord,
    CliAgent,
    IngestionRun,
    derive_task_kind,
)
from depictio.models.timestamps import utc_now_naive


def ensure_monitoring_storage() -> None:
    """Create the TTL index and capped app-logs collection. Idempotent.

    Never raises — a storage-setup failure must not break API boot; the worst
    case is unbounded growth or a missing capped collection, both recoverable.
    """
    try:
        retention_seconds = max(1, settings.monitoring.retention_days) * 86_400
        task_events_collection.create_index("task_id", unique=True)
        # TTL on created_at: Mongo expires task_events automatically after the
        # configured retention window. Recreated only if the option changed.
        task_events_collection.create_index(
            "created_at", expireAfterSeconds=retention_seconds, name="created_at_ttl"
        )
        ingestion_runs_collection.create_index("run_id", unique=True)
        ingestion_runs_collection.create_index([("started_at", DESCENDING)])
        cli_agents_collection.create_index("agent_id", unique=True)
        # TTL keyed on expires_at rather than a fixed window from creation: an
        # agent refreshes its own expiry on every heartbeat, so a dead one is
        # evicted a few beats after it stops while a healthy one never is.
        cli_agents_collection.create_index("expires_at", expireAfterSeconds=0, name="agent_ttl")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"monitoring: failed to ensure task/ingestion indexes: {exc}")

    try:
        name = settings.mongodb.collections.app_logs_collection
        if name not in db.list_collection_names():
            db.create_collection(
                name,
                capped=True,
                size=max(1, settings.monitoring.app_log_capped_mb) * 1024 * 1024,
            )
            logger.info(f"monitoring: created capped collection '{name}'")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"monitoring: failed to ensure capped app_logs collection: {exc}")


# ── Task events ─────────────────────────────────────────────────────────────


def upsert_task_event(task_id: str, **fields: Any) -> None:
    """Create-or-update the task_events row keyed by ``task_id``.

    ``created_at`` is set only on insert (so the TTL clock starts at first
    sighting); ``updated_at`` is bumped on every call.
    """
    now = datetime.now()
    if "task_name" in fields and "kind" not in fields:
        fields["kind"] = derive_task_kind(fields.get("task_name"))
    set_fields: dict[str, Any] = {**fields, "updated_at": now}
    task_events_collection.update_one(
        {"task_id": task_id},
        {"$set": set_fields, "$setOnInsert": {"task_id": task_id, "created_at": now}},
        upsert=True,
    )


def append_task_logs(task_id: str, lines: list[str]) -> None:
    """Append captured log lines to a task_events row (no-op on empty)."""
    if not lines:
        return
    task_events_collection.update_one(
        {"task_id": task_id},
        {
            "$push": {"logs": {"$each": lines}},
            "$set": {"updated_at": datetime.now()},
            "$setOnInsert": {"task_id": task_id, "created_at": datetime.now()},
        },
        upsert=True,
    )


def query_task_events(
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 100,
    skip: int = 0,
) -> list[dict[str, Any]]:
    """Return task_events newest-first, with optional filters."""
    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    if kind:
        query["kind"] = kind
    if since:
        query["updated_at"] = {"$gte": since}
    cursor = (
        task_events_collection.find(query, {"_id": 0})
        .sort("updated_at", DESCENDING)
        .skip(max(0, skip))
        .limit(max(1, min(limit, 500)))
    )
    return [_serialize(doc) for doc in cursor]


def get_task_event(task_id: str) -> Optional[dict[str, Any]]:
    doc = task_events_collection.find_one({"task_id": task_id}, {"_id": 0})
    return _serialize(doc) if doc else None


# ── Ingestion runs ──────────────────────────────────────────────────────────


def create_ingestion_run(run: IngestionRun) -> None:
    doc = run.model_dump()
    doc["updated_at"] = doc.get("updated_at") or datetime.now()
    ingestion_runs_collection.update_one(
        {"run_id": run.run_id},
        {"$set": doc},
        upsert=True,
    )


def finish_ingestion_run(run_id: str, **fields: Any) -> bool:
    """Patch a run on completion. Returns False if the run_id is unknown."""
    fields.setdefault("finished_at", datetime.now())
    fields.setdefault("updated_at", datetime.now())
    result = ingestion_runs_collection.update_one({"run_id": run_id}, {"$set": fields})
    return result.matched_count > 0


ABANDONED_RUN_ERROR = (
    "No update from the client for over {hours} h: the process most likely exited "
    "without reporting (killed, crashed or lost its connection)."
)


def stale_ingestion_query(cutoff: datetime) -> dict[str, Any]:
    """Mongo filter for ``running`` records with no write since ``cutoff``.

    Records written before ``updated_at`` existed fall back to ``started_at``.
    """
    return {
        "status": "running",
        "$or": [
            {"updated_at": {"$lt": cutoff}},
            {"updated_at": None, "started_at": {"$lt": cutoff}},
        ],
    }


def mark_stale_ingestion_runs(now: Optional[datetime] = None) -> int:
    """Flip stale ``running`` runs to ``abandoned``. Returns how many changed.

    Called on the admin read paths rather than from a background loop: the
    status only matters when someone looks, and sweeping before the query keeps
    the ``status`` filter truthful. ``finished_at`` stays unset, since nobody
    knows when the process actually died. Never raises.
    """
    hours = settings.monitoring.ingestion_stale_after_hours
    if hours <= 0:
        return 0
    now = now or datetime.now()
    try:
        result = ingestion_runs_collection.update_many(
            stale_ingestion_query(now - timedelta(hours=hours)),
            {
                "$set": {
                    "status": "abandoned",
                    "current_step": None,
                    "error": ABANDONED_RUN_ERROR.format(hours=hours),
                }
            },
        )
        return result.modified_count
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"monitoring: stale ingestion sweep failed: {exc}")
        return 0


def upsert_ingestion_step(
    run_id: str,
    *,
    step: dict[str, Any],
    current_step: Optional[str] = None,
    clear_current_step: bool = False,
    counters: Optional[dict[str, int]] = None,
    progress: Optional[dict[str, Any]] = None,
) -> bool:
    """Add-or-update one step of an in-flight run, keyed by step name.

    Applied as a single atomic Mongo operation. The previous implementation read
    the whole ``steps`` array, mutated it in Python and wrote it back, so two
    concurrent step updates for the same run silently lost one of them — which
    goes from theoretical to routine once the CLI reports steps live and scans
    files in parallel.

    ``current_step`` is only written when supplied. It used to be set
    unconditionally, so any caller that omitted it wiped the field to None and
    the UI lost track of what was running. ``clear_current_step`` is the
    explicit way to blank it on completion.

    Every write also bumps ``updated_at``: a live step is the run's heartbeat,
    which is what keeps ``mark_stale_ingestion_runs`` from abandoning a long
    ingestion that is still reporting progress.

    Returns False if the run_id is unknown.
    """
    name = step.get("name")
    top_level: dict[str, Any] = {"updated_at": datetime.now()}
    if clear_current_step:
        top_level["current_step"] = None
    elif current_step is not None:
        top_level["current_step"] = current_step
    if counters:
        top_level["counters"] = counters
    if progress:
        top_level["progress"] = progress

    # Replace the same-named step in place when it exists… The positional `$`
    # targets the element the query matched; names are unique within a run
    # (the append below refuses a duplicate), so that element is the step.
    replace_in_place = (
        {"run_id": run_id, "steps.name": name},
        {"$set": {"steps.$": step, **top_level}},
    )
    if ingestion_runs_collection.update_one(*replace_in_place).matched_count:
        return True

    # …otherwise append it, guarding against the race where another writer
    # inserted the same step between the two operations.
    appended = ingestion_runs_collection.update_one(
        {"run_id": run_id, "steps.name": {"$ne": name}},
        {"$push": {"steps": step}, "$set": top_level},
    )
    if appended.matched_count:
        return True

    # The step appeared in between: retry the in-place path once.
    return ingestion_runs_collection.update_one(*replace_in_place).matched_count > 0


def query_ingestion_runs(
    *,
    instance: Optional[str] = None,
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if instance:
        # An instance is the CLI's `instance_label`, else its hostname: most CLI
        # configs set no label, and the admin pane shows the hostname then.
        query["$or"] = [
            {"cli_instance_label": instance},
            {"cli_instance_label": {"$in": [None, ""]}, "cli_hostname": instance},
        ]
    if status:
        query["status"] = status
    if project_id:
        query["project_id"] = project_id
    cursor = (
        ingestion_runs_collection.find(query, {"_id": 0})
        .sort("started_at", DESCENDING)
        .skip(max(0, skip))
        .limit(max(1, min(limit, 500)))
    )
    return [_serialize(doc) for doc in cursor]


def get_ingestion_run(run_id: str) -> Optional[dict[str, Any]]:
    doc = ingestion_runs_collection.find_one({"run_id": run_id}, {"_id": 0})
    return _serialize(doc) if doc else None


# ── CLI agents ──────────────────────────────────────────────────────────────


def upsert_cli_agent(agent: CliAgent) -> None:
    """Record or refresh a long-running CLI agent's heartbeat."""
    cli_agents_collection.update_one(
        {"agent_id": agent.agent_id},
        {
            # started_at and runs_total belong to the agent's own view of
            # itself; everything else is refreshed on each beat.
            #
            # The run-request fields are server-owned and must survive a beat:
            # they arrive on the agent object as None (the agent has no reason
            # to send them), so including them here would silently cancel a
            # "Run now" that landed between the request and the agent's claim.
            "$set": agent.model_dump(
                exclude={"started_at", "run_requested_at", "run_requested_by"}
            ),
            "$setOnInsert": {"started_at": agent.started_at},
        },
        upsert=True,
    )


def get_cli_agent(agent_id: str) -> Optional[dict[str, Any]]:
    doc = cli_agents_collection.find_one({"agent_id": agent_id}, {"_id": 0})
    return _serialize(doc) if doc else None


def request_cli_agent_run(agent_id: str, *, requested_by: Optional[str] = None) -> bool:
    """Ask an agent to run a cycle at its next command poll.

    A flag rather than a push: the agent lives on someone else's machine, often
    behind a firewall, and the server has no route to it. Returns False when no
    such agent exists — a watcher whose row has expired cannot be asked.
    """
    result = cli_agents_collection.update_one(
        {"agent_id": agent_id},
        {"$set": {"run_requested_at": utc_now_naive(), "run_requested_by": requested_by}},
    )
    return result.matched_count > 0


def claim_cli_agent_run(agent_id: str) -> Optional[dict[str, Any]]:
    """Take a pending run request, clearing it. Returns the request, or None.

    Claim and clear are one atomic step so a request is honoured exactly once:
    read-then-clear would run the cycle twice if two polls overlapped, and clear
    a request the agent never saw if the process died in between.
    """
    return cli_agents_collection.find_one_and_update(
        {"agent_id": agent_id, "run_requested_at": {"$ne": None}},
        {"$set": {"run_requested_at": None, "run_requested_by": None}},
        projection={"_id": 0, "run_requested_at": 1, "run_requested_by": 1},
    )


def query_cli_agents(*, project_id: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if project_id:
        query["project_id"] = project_id
    cursor = (
        cli_agents_collection.find(query, {"_id": 0})
        .sort("heartbeat_at", DESCENDING)
        .limit(max(1, min(limit, 500)))
    )
    return [_serialize(doc) for doc in cursor]


def delete_cli_agent(agent_id: str) -> bool:
    return cli_agents_collection.delete_one({"agent_id": agent_id}).deleted_count > 0


# ── Application logs ────────────────────────────────────────────────────────


def insert_app_log(record: AppLogRecord) -> None:
    app_logs_collection.insert_one(record.model_dump())


def query_app_logs(
    *,
    level: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if level:
        query["level"] = level
    if source:
        query["source"] = source
    # Capped collections preserve insertion order; $natural reverse = newest-first.
    cursor = (
        app_logs_collection.find(query, {"_id": 0})
        .sort("$natural", DESCENDING)
        .limit(max(1, min(limit, 1000)))
    )
    return [_serialize(doc) for doc in cursor]


# ── helpers ─────────────────────────────────────────────────────────────────


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe dict: stringify datetimes so FastAPI can return them directly."""
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def task_event_seconds_ago(seconds: float) -> datetime:
    """Convenience for `since` filters."""
    return datetime.now() - timedelta(seconds=seconds)
